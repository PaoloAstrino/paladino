"""
Corporate structure loader — write Person nodes and ownership edges to Neo4j.

Three write operations (all idempotent MERGE):
  1. load_persons()        — Person nodes
  2. load_represents()     — REPRESENTS edges (director at company)
  3. load_shareholdings()  — SHAREHOLDER_OF edges + derived SHARES_UBO edges
"""

from __future__ import annotations

import polars as pl
from loguru import logger
from neo4j import Driver
from rich.console import Console
from rich.panel import Panel
from tqdm import tqdm

_console = Console()


class CorporateLoader:
    """
    Load corporate-structure DataFrames into Neo4j.

    All methods are safe to call with empty DataFrames — they return 0
    without touching the database.

    Parameters
    ----------
    driver:
        An open :class:`neo4j.Driver` instance.
    batch_size:
        Number of rows per Cypher UNWIND batch.
    """

    def __init__(self, driver: Driver, batch_size: int = 2_000) -> None:
        self.driver     = driver
        self.batch_size = batch_size

    # ── public methods ───────────────────────────────────────────────────────

    def load_persons(self, df: pl.DataFrame) -> int:
        """
        MERGE Person nodes.

        Creates the node if it does not exist; enriches ``nome`` / ``cognome``
        on subsequent runs without overwriting existing values.
        """
        if df.is_empty():
            return 0

        logger.info(f"Loading {len(df):,} Person nodes…")
        total = 0

        with self.driver.session() as session:
            for batch in self._iter_batches(df):
                result = session.run("""
                    UNWIND $rows AS row
                    MERGE (p:Person {cf: row.cf})
                    ON CREATE SET
                        p.id               = row.id,
                        p.nome             = row.nome,
                        p.cognome          = row.cognome,
                        p.source           = [row.source],
                        p.dataset_version  = row.dataset_version,
                        p.risk_score       = 0.0
                    ON MATCH SET
                        p.nome    = CASE WHEN p.nome    IS NULL THEN row.nome    ELSE p.nome    END,
                        p.cognome = CASE WHEN p.cognome IS NULL THEN row.cognome ELSE p.cognome END,
                        p.source  = apoc.coll.toSet(coalesce(p.source, []) + row.source)
                    RETURN count(p) AS loaded
                """, rows=batch)
                total += result.single()["loaded"]

        logger.info(f"  ↳ {total:,} Person nodes upserted")
        return total

    def load_represents(self, df: pl.DataFrame) -> int:
        """
        MERGE REPRESENTS edges (Person -[:REPRESENTS]-> Company).

        Silently skips rows where the Company CF is not already in the graph.
        A warning is printed at the end if any rows were skipped so the user
        can load company data first.
        """
        if df.is_empty():
            return 0

        logger.info(f"Loading {len(df):,} REPRESENTS edges…")
        total   = 0
        skipped = 0

        with self.driver.session() as session:
            for batch in self._iter_batches(df):
                result = session.run("""
                    UNWIND $rows AS row
                    MATCH (c:Company {cf: row.company_cf})
                    MERGE (p:Person {cf: row.person_cf})
                        ON CREATE SET p.source = [row.source]
                    MERGE (p)-[r:REPRESENTS {ruolo: row.ruolo}]->(c)
                    ON CREATE SET
                        r.data_inizio = row.data_inizio,
                        r.data_fine   = row.data_fine,
                        r.source      = row.source
                    RETURN
                        count(r)                                        AS linked,
                        count(CASE WHEN c IS NULL THEN 1 END)          AS skipped
                """, rows=batch)
                rec      = result.single()
                total   += rec["linked"]
                skipped += rec["skipped"]

        if skipped:
            logger.warning(
                f"  ⚠️  {skipped:,} REPRESENTS rows skipped — Company CF not found in graph.\n"
                "     → Run ANAC or OpenCUP ETL first to populate Company nodes."
            )
        logger.info(f"  ↳ {total:,} REPRESENTS edges upserted")
        return total

    def load_shareholdings(self, df: pl.DataFrame) -> int:
        """
        MERGE SHAREHOLDER_OF edges and derive SHARES_UBO convenience edges.

        Step A: MERGE SHAREHOLDER_OF on every row.
        Step B: For each pair of companies that share a common ultimate owner
                (same Person at depth ≤ 2), write a SHARES_UBO edge between
                them.  This powers the existing ``detect_ubo_conflict()``
                detector without expensive path queries at analysis time.
        """
        if df.is_empty():
            return 0

        logger.info(f"Loading {len(df):,} SHAREHOLDER_OF edges…")
        total   = 0
        skipped = 0

        with self.driver.session() as session:
            # ── Step A: SHAREHOLDER_OF ───────────────────────────────────────
            for batch in self._iter_batches(df):
                result = session.run("""
                    UNWIND $rows AS row
                    MATCH (target:Company {cf: row.company_cf})
                    // The shareholder can be a Person OR another Company
                    MERGE (src  {cf: row.source_cf})
                    MERGE (src)-[r:SHAREHOLDER_OF {data_rilevazione: row.data_rilevazione}]->(target)
                    ON CREATE SET
                        r.quota  = row.quota,
                        r.source = row.source
                    ON MATCH SET
                        r.quota  = row.quota
                    RETURN
                        count(r)                                            AS linked,
                        count(CASE WHEN target IS NULL THEN 1 END)         AS skipped
                """, rows=batch)
                rec      = result.single()
                total   += rec["linked"]
                skipped += rec["skipped"]

            # ── Step B: derive SHARES_UBO between Companies ──────────────────
            logger.info("  Computing SHARES_UBO convenience edges from SHAREHOLDER_OF chains…")
            ubo_result = session.run("""
                // Find all pairs of companies that share a common Person owner
                // at depth 1 or 2 (direct or via an intermediate holding).
                MATCH (p:Person)-[:SHAREHOLDER_OF*1..2]->(c1:Company)
                MATCH (p)-[:SHAREHOLDER_OF*1..2]->(c2:Company)
                WHERE id(c1) < id(c2)
                MERGE (c1)-[u:SHARES_UBO]->(c2)
                ON CREATE SET
                    u.cf_persona = p.cf,
                    u.ruolo      = 'derived_shareholder',
                    u.percentuale = null
                RETURN count(u) AS ubo_edges
            """)
            ubo_edges = ubo_result.single()["ubo_edges"]
            logger.info(f"  ↳ {ubo_edges:,} SHARES_UBO edges derived")

        if skipped:
            logger.warning(
                f"  ⚠️  {skipped:,} SHAREHOLDER_OF rows skipped — Company CF not in graph.\n"
                "     → Run ANAC ETL first, then re-run the corporate loader."
            )

        logger.info(f"  ↳ {total:,} SHAREHOLDER_OF edges upserted")
        return total

    # ── utilities ────────────────────────────────────────────────────────────

    def _iter_batches(self, df: pl.DataFrame):
        """Yield list[dict] batches for Cypher UNWIND."""
        for start in range(0, len(df), self.batch_size):
            yield df[start : start + self.batch_size].to_dicts()

    def load_all(
        self,
        persons_df:      pl.DataFrame,
        represents_df:   pl.DataFrame,
        shareholding_df: pl.DataFrame,
    ) -> dict[str, int]:
        """
        Convenience method: run all three loaders in the correct order and
        return a summary dict.

        Order matters:
          persons first → so REPRESENTS edges can reference them
          represents second → board-member links
          shareholdings last → derives SHARES_UBO after all persons exist
        """
        persons_loaded      = self.load_persons(persons_df)
        represents_loaded   = self.load_represents(represents_df)
        shareholdings_loaded = self.load_shareholdings(shareholding_df)

        summary = {
            "persons":      persons_loaded,
            "represents":   represents_loaded,
            "shareholdings": shareholdings_loaded,
        }

        _console.print(Panel(
            "\n".join(
                f"  [cyan]{k:20s}[/cyan]  [bold green]{v:>8,}[/bold green]  rows loaded"
                for k, v in summary.items()
            ),
            title="[bold]Corporate ETL — Load Complete[/bold]",
            border_style="green",
            expand=False,
        ))

        return summary
