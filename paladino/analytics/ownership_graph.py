"""
Supply Chain & Ownership Graph analyser.

Queries the graph for ownership chains, supply chains, board overlaps,
carousel paths, and shell-company candidates.

All methods degrade gracefully when the relevant nodes/edges have not yet
been loaded (they return empty results and print an informative hint).
"""

from __future__ import annotations

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from paladino.constants import (
    BOARD_OVERLAP_MIN_SHARED,
    CAROUSEL_MAX_CYCLE_LENGTH,
    CAROUSEL_MIN_CYCLE_LENGTH,
    OWNERSHIP_CHAIN_MAX_DEPTH,
    SHELL_COMPANY_EMPLOYEE_THRESHOLD,
    SHELL_COMPANY_TENDER_WIN_MIN,
    SUPPLY_CHAIN_MAX_DEPTH,
)
from paladino.db import Neo4jConnection

_console = Console()

# ── Hint shown when required data is absent ──────────────────────────────────

_MISSING_DATA_HINT = """\
[yellow]No data found for this query.  Possible reasons:[/yellow]

  1. [bold]PNRR subcontractor data not loaded[/bold]
     Run: [cyan]paladino maintenance → Run Supply Chain ETL 🔗[/cyan]
     Or:  [cyan]python scripts/run_supply_chain_etl.py --step subcontractors[/cyan]

  2. [bold]Board / shareholder data not loaded[/bold]
     Drop CSV files into  [cyan]data/corporate/raw/[/cyan]  then re-run the ETL.
     See: [cyan]paladino/etl/corporate/download.py[/cyan]  for required column names.

  3. [bold]ANAC tenders not loaded yet[/bold]  (needed for WINS relationships)
     Run: [cyan]paladino maintenance → Run ANAC ETL Pipeline[/cyan]
"""


def _warn_empty(query_name: str, reason: str | None = None) -> None:
    hint = f"[dim]({reason})[/dim]\n\n" + _MISSING_DATA_HINT if reason else _MISSING_DATA_HINT
    _console.print(
        Panel(
            hint,
            title=f"[bold yellow]ℹ️  {query_name} — no results[/bold yellow]",
            border_style="yellow",
            expand=False,
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main analyser class
# ─────────────────────────────────────────────────────────────────────────────


class OwnershipGraphAnalyzer:
    """
    Query the corporate-structure layer of the Paladino knowledge graph.

    All public methods return plain Python dicts / lists so they can be
    called from the fraud detectors, Oracle, CLI, and GraphRAG agent.

    Parameters
    ----------
    conn : Neo4jConnection
        Active DB connection.  The analyser does not own its lifecycle.
    """

    def __init__(self, conn: Neo4jConnection) -> None:
        self.conn = conn

    # ── 1. Ownership chain ───────────────────────────────────────────────────

    def get_ownership_chain(
        self,
        company_id: str,
        max_depth: int = OWNERSHIP_CHAIN_MAX_DEPTH,
    ) -> list[dict]:
        """
        Return all owners (Person or Company) reachable via SHAREHOLDER_OF / SHARES_UBO
        from a given company, up to *max_depth* hops.

        Each result dict has:
          company_id, owner_id, owner_type, owner_name, quota, depth
        """
        logger.debug(f"[ownership] chain for {company_id}, depth {max_depth}")
        results = self.conn.run_query(
            f"""
            MATCH path = (owner)-[:SHAREHOLDER_OF|SHARES_UBO*1..{max_depth}]->(c {{id: $company_id}})
            WITH owner, c, length(path) AS depth,
                 last(relationships(path)).quota AS quota
            RETURN
                c.id            AS company_id,
                owner.id        AS owner_id,
                labels(owner)[0]AS owner_type,
                coalesce(owner.nome_normalizzato, owner.cognome + ' ' + owner.nome, owner.cf)
                                AS owner_name,
                quota           AS quota,
                depth           AS depth
            ORDER BY depth, quota DESC
            LIMIT 500
            """,
            {"company_id": company_id},
        )
        if not results:
            _warn_empty(
                "Ownership chain",
                f"No SHAREHOLDER_OF data found for company id={company_id}",
            )
        return results

    # ── 2. Supply chain ──────────────────────────────────────────────────────

    def get_supply_chain(
        self,
        company_id: str,
        max_depth: int = SUPPLY_CHAIN_MAX_DEPTH,
        direction: str = "downstream",
    ) -> list[dict]:
        """
        Return the supply / subcontract chain radiating from a company.

        Parameters
        ----------
        direction : "downstream" (who this company subcontracts to)
                  | "upstream"   (who subcontracts *this* company)
        """
        logger.debug(f"[supply_chain] {direction} chain for {company_id}")

        if direction == "downstream":
            pattern = (
                f"(root {{id: $company_id}})-[:SUBCONTRACTS_TO|SUPPLIES_TO*1..{max_depth}]->(node)"
            )
        else:
            pattern = (
                f"(node)-[:SUBCONTRACTS_TO|SUPPLIES_TO*1..{max_depth}]->(root {{id: $company_id}})"
            )

        results = self.conn.run_query(
            f"""
            MATCH path = {pattern}
            WITH root, node, length(path) AS depth,
                 [r IN relationships(path) | type(r)] AS rel_types,
                 last(relationships(path)).cig AS cig
            RETURN
                root.id                 AS root_id,
                root.nome_normalizzato  AS root_name,
                node.id                 AS node_id,
                node.nome_normalizzato  AS node_name,
                depth                   AS depth,
                rel_types               AS relationship_path,
                cig                     AS last_cig
            ORDER BY depth, node_name
            LIMIT 1000
            """,
            {"company_id": company_id},
        )
        if not results:
            _warn_empty(
                "Supply chain",
                f"No SUBCONTRACTS_TO / SUPPLIES_TO data found for company id={company_id}. "
                "Run the PNRR Supply Chain ETL first.",
            )
        return results

    # ── 3. Board overlaps ────────────────────────────────────────────────────

    def find_board_overlaps(
        self,
        min_shared: int = BOARD_OVERLAP_MIN_SHARED,
        limit: int = 50,
    ) -> list[dict]:
        """
        Find company pairs that share ≥ *min_shared* board members.

        Dict keys: company1_id, company1_name, company2_id, company2_name,
                   shared_person_count, shared_persons (list of names)
        """
        logger.debug(f"[board_overlap] min_shared={min_shared}")
        results = self.conn.run_query(
            """
            MATCH (p:Person)-[:REPRESENTS]->(c1:Company)
            MATCH (p)-[:REPRESENTS]->(c2:Company)
            WHERE id(c1) < id(c2)
            WITH c1, c2, collect(DISTINCT coalesce(p.cognome + ' ' + p.nome, p.cf)) AS persons
            WHERE size(persons) >= $min_shared
            RETURN
                c1.id                  AS company1_id,
                c1.nome_normalizzato   AS company1_name,
                c2.id                  AS company2_id,
                c2.nome_normalizzato   AS company2_name,
                size(persons)          AS shared_person_count,
                persons                AS shared_persons
            ORDER BY shared_person_count DESC
            LIMIT $limit
            """,
            {"min_shared": min_shared, "limit": limit},
        )
        if not results:
            _warn_empty(
                "Board overlaps",
                "No REPRESENTS relationships found. Load corporate director data first.",
            )
        return results

    # ── 4. Carousel paths (supply-chain cycles) ──────────────────────────────

    def detect_carousel_paths(
        self,
        min_len: int = CAROUSEL_MIN_CYCLE_LENGTH,
        max_len: int = CAROUSEL_MAX_CYCLE_LENGTH,
        limit: int = 20,
    ) -> list[dict]:
        """
        Detect cycles in the SUBCONTRACTS_TO / SUPPLIES_TO graph (carousel fraud).

        A carousel is a path A→B→…→A where money circulates between connected
        companies to inflate invoices or launder public funds.

        Returns list of dicts:
          cycle_ids, cycle_names, cycle_length, cigs (tenders involved)
        """
        logger.debug(f"[carousel] searching cycles len {min_len}..{max_len}")

        # We use the scc_id property written by GDS SCC (run_supply_chain_scc).
        # When SCC has not been run yet, fall back to a direct path query
        # (slower but works without GDS).
        scc_results = self._detect_via_scc(limit)
        if scc_results:
            return scc_results

        logger.info("[carousel] SCC IDs not found, falling back to path query…")
        return self._detect_via_paths(min_len, max_len, limit)

    def _detect_via_scc(self, limit: int) -> list[dict]:
        """Fast carousel detection when GDS SCC IDs are available."""
        return self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.supply_scc_id IS NOT NULL AND c.supply_scc_size > 1
            WITH c.supply_scc_id AS scc_id, collect(c) AS members
            WHERE size(members) >= 2
            WITH scc_id, members,
                 [m IN members | m.id]               AS cycle_ids,
                 [m IN members | m.nome_normalizzato] AS cycle_names
            // gather the CIGs that connect this cycle
            OPTIONAL MATCH (m1:Company)-[r:SUBCONTRACTS_TO]->(m2:Company)
            WHERE m1.supply_scc_id = scc_id AND m2.supply_scc_id = scc_id
            RETURN
                scc_id,
                cycle_ids,
                cycle_names,
                size(members)       AS cycle_length,
                collect(r.cig)      AS cigs
            ORDER BY cycle_length DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )

    def _detect_via_paths(self, min_len: int, max_len: int, limit: int) -> list[dict]:
        """Slower fallback: direct variable-length path cycle query."""
        results = self.conn.run_query(
            f"""
            MATCH path = (start:Company)-[:SUBCONTRACTS_TO*{min_len}..{max_len}]->(start)
            WITH path, start,
                 [n IN nodes(path) | n.id]               AS cycle_ids,
                 [n IN nodes(path) | n.nome_normalizzato] AS cycle_names,
                 [r IN relationships(path) | r.cig]      AS cigs
            WHERE size(apoc.coll.toSet(cycle_ids)) = length(path)
            RETURN
                null            AS scc_id,
                cycle_ids,
                cycle_names,
                length(path)    AS cycle_length,
                cigs
            ORDER BY cycle_length
            LIMIT $limit
            """,
            {"limit": limit},
        )
        if not results:
            _warn_empty(
                "Carousel paths",
                "No cycles detected. Either data is not loaded or supply chains are clean.",
            )
        return results

    # ── 5. Shell company scoring ─────────────────────────────────────────────

    def score_shell_companies(
        self,
        min_tender_wins: int = SHELL_COMPANY_TENDER_WIN_MIN,
        max_employees: int = SHELL_COMPANY_EMPLOYEE_THRESHOLD,
        limit: int = 50,
    ) -> list[dict]:
        """
        Score companies as potential shells.

        A shell indicator combines:
          - High tender-win count (active bidder)
          - Very low or unknown employee count
          - Deep ownership chain (many layers of holding companies)
          - Low risk score (not already flagged) — so we find NEW suspects

        Returns list of dicts:
          company_id, company_name, tender_wins, employee_count,
          ownership_depth, shell_score (0.0–1.0)
        """
        logger.debug("[shell_scoring] running")
        results = self.conn.run_query(
            """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WITH c, count(t) AS tender_wins
            WHERE tender_wins >= $min_tender_wins

            // Ownership depth (0 if no SHAREHOLDER_OF)
            OPTIONAL MATCH depth_path = (owner)-[:SHAREHOLDER_OF*1..10]->(c)
            WITH c, tender_wins,
                 coalesce(max(length(depth_path)), 0) AS ownership_depth

            // Employee count (may not exist)
            WITH c, tender_wins, ownership_depth,
                 coalesce(c.num_dipendenti, c.employees, -1) AS employee_count

            // Shell score: normalise each factor to 0-1 and average
            WITH c, tender_wins, ownership_depth, employee_count,
                 toFloat(tender_wins) / 100.0                                  AS win_factor,
                 CASE WHEN employee_count < 0    THEN 0.5
                      WHEN employee_count <= $max_emp THEN 1.0
                      ELSE 0.0 END                                             AS emp_factor,
                 CASE WHEN ownership_depth >= 3  THEN 1.0
                      WHEN ownership_depth >= 1  THEN 0.5
                      ELSE 0.0 END                                             AS depth_factor
            WITH c, tender_wins, ownership_depth, employee_count,
                 round((win_factor + emp_factor + depth_factor) / 3.0, 3)     AS shell_score
            WHERE shell_score > 0.3
            RETURN
                c.id                 AS company_id,
                c.nome_normalizzato  AS company_name,
                tender_wins,
                employee_count,
                ownership_depth,
                shell_score
            ORDER BY shell_score DESC
            LIMIT $limit
            """,
            {
                "min_tender_wins": min_tender_wins,
                "max_emp": max_employees,
                "limit": limit,
            },
        )
        if not results:
            _warn_empty(
                "Shell company scoring",
                f"No companies with ≥{min_tender_wins} tender wins found.",
            )
        return results

    # ── 5b. Enhanced shell scoring (multi-factor, Feature 3.2) ──────────────────

    def score_shell_companies_enhanced(
        self,
        limit: int = 200,
        store_results: bool = False,
    ) -> list[dict]:
        """
        Multi-factor shell company scoring using :class:`ShellCompanyDetector`.

        Extends the legacy 3-factor heuristic with four additional signals:
          - VAT registration anomaly
          - Financial-filing dormancy
          - Board overconcentration
          - Supplier-only participation pattern
          - Shared address flag
          - Deep holding-chain bonus

        Parameters
        ----------
        limit:
            How many companies to score.
        store_results:
            When True, upsert ``ShellRiskScore`` nodes in the graph.

        Returns
        -------
        List of dicts compatible with the legacy ``score_shell_companies()``
        output plus extra fields:  risk_tier, component_scores, factors.
        """
        from paladino.analytics.shell_company_detector import ShellCompanyDetector

        logger.debug("[shell_scoring_enhanced] running")
        detector = ShellCompanyDetector(self.conn.driver)
        results = detector.score_all(limit=limit, store_results=store_results)

        # Convert to the standard list-of-dicts format used by callers
        return [
            {
                "company_id": r.company_id,
                "company_name": r.company_name,
                "shell_score": round(r.shell_score, 4),
                "risk_tier": r.risk_tier,
                "tender_wins": r.factors.get("tender_wins", 0),
                "employee_count": r.factors.get("max_employees", -1),
                "ownership_depth": r.factors.get("chain_depth", 0),
                "component_scores": r.component_scores,
                "factors": r.factors,
            }
            for r in results
        ]

    # ── 6. Corporate family (all companies under same ultimate owner) ─────────

    def get_corporate_family(
        self,
        company_id: str,
        max_depth: int = OWNERSHIP_CHAIN_MAX_DEPTH,
    ) -> dict:
        """
        Return all companies under the same ultimate beneficial owner as the
        given company.

        Useful for showing analysts the full corporate family before deciding
        whether to flag related bids as collusive.
        """
        logger.debug(f"[corporate_family] for {company_id}")
        siblings = self.conn.run_query(
            f"""
            // Find the UBO(s) of the given company
            MATCH (ubo)-[:SHAREHOLDER_OF*1..{max_depth}]->(root {{id: $company_id}})
            WHERE NOT (ubo)-[:SHAREHOLDER_OF]->()  // top-level owner
               OR labels(ubo) = ['Person']

            // Find all other companies owned by those UBOs
            MATCH (ubo)-[:SHAREHOLDER_OF*1..{max_depth}]->(sibling:Company)
            WHERE sibling.id <> $company_id
            RETURN
                ubo.id                   AS ubo_id,
                coalesce(ubo.cognome + ' ' + ubo.nome, ubo.nome_normalizzato, ubo.cf)
                                         AS ubo_name,
                labels(ubo)[0]           AS ubo_type,
                sibling.id               AS sibling_id,
                sibling.nome_normalizzato AS sibling_name,
                sibling.risk_score        AS risk_score
            ORDER BY ubo_name, sibling_name
            LIMIT 200
            """,
            {"company_id": company_id},
        )
        if not siblings:
            _warn_empty(
                "Corporate family",
                f"No ownership data for company id={company_id}.",
            )
            return {"company_id": company_id, "ubos": [], "siblings": []}

        # Re-shape into a nested structure
        ubos: dict[str, dict] = {}
        for row in siblings:
            uid = row["ubo_id"]
            if uid not in ubos:
                ubos[uid] = {
                    "ubo_id": uid,
                    "ubo_name": row["ubo_name"],
                    "ubo_type": row["ubo_type"],
                    "siblings": [],
                }
            ubos[uid]["siblings"].append(
                {
                    "id": row["sibling_id"],
                    "name": row["sibling_name"],
                    "risk_score": row["risk_score"],
                }
            )

        return {
            "company_id": company_id,
            "ubos": list(ubos.values()),
            "siblings": [s for u in ubos.values() for s in u["siblings"]],
        }
