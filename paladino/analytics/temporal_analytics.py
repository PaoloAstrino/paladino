"""
Temporal / Time-Series Analytics
=================================
Analyses procurement patterns over time to identify sudden spikes,
gradual trends, seasonal bias and risk-score evolution.

All methods return ``List[Dict]`` (or ``Dict`` for aggregates) and are
testable without a live database by mocking ``Neo4jConnection.run_query``.

Fallback contract
-----------------
When date data has not been migrated (i.e. ``data_aggiudicazione`` is still
stored as plain strings instead of native Neo4j ``date`` types), queries will
return empty results.  Every public method calls ``_warn_no_dates()`` in that
case to print a Rich panel explaining what to run.

Usage
-----
    from paladino.db import Neo4jConnection
    from paladino.analytics.temporal_analytics import TemporalAnalyzer

    conn = Neo4jConnection()
    ta = TemporalAnalyzer(conn)
    trends = ta.get_tender_volume_trend(quarters=8)
    spikes = ta.detect_sudden_spikes()
    conn.close()
"""

from __future__ import annotations

import statistics

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from paladino.constants import (
    TEMPORAL_DEFAULT_QUARTERS,
    TEMPORAL_MIN_TENDERS_PER_BUCKET,
    TEMPORAL_SEASONAL_YEARS,
    TEMPORAL_SPIKE_THRESHOLD,
)
from paladino.db import Neo4jConnection

_console = Console()

_NO_DATE_GUIDANCE = (
    "[yellow]No native date data found on Tender nodes.[/yellow]\n\n"
    "Dates are currently stored as ISO strings and must be migrated before\n"
    "temporal queries can run.\n\n"
    "Run the one-shot migration:\n"
    "[bold white]  python scripts/migrate_date_types.py[/bold white]\n\n"
    "This is safe and idempotent — it can be run multiple times without\n"
    "duplicating or corrupting data."
)


def _warn_no_dates(query_name: str) -> None:
    """Print a gentle guidance panel when date fields are not yet native types."""
    _console.print(
        Panel(
            _NO_DATE_GUIDANCE,
            title=f"[blue]ℹ  {query_name} — no date data[/blue]",
            border_style="blue",
        )
    )


def _quarter(month: int) -> int:
    """Convert 1-based month to 1-based quarter number."""
    return (month - 1) // 3 + 1


class TemporalAnalyzer:
    """
    Trend and spike analysis over the procurement knowledge graph.

    All methods accept an optional ``company_id`` (the ``id`` property on a
    ``Company`` node) to scope results to a single entity; when omitted the
    analysis covers the entire graph.
    """

    def __init__(self, conn: Neo4jConnection) -> None:
        self.conn = conn

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Tender volume trend (count + value per quarter)
    # ──────────────────────────────────────────────────────────────────────────

    def get_tender_volume_trend(
        self,
        company_id: str | None = None,
        quarters: int = TEMPORAL_DEFAULT_QUARTERS,
    ) -> list[dict]:
        """
        Return quarterly tender activity: count, total value, average value.

        Each result dict has:
          year, quarter, tender_count, total_value, avg_value[, company_id]

        Parameters
        ----------
        company_id :
            Scope to a specific winner.  ``None`` = all companies.
        quarters :
            How many past quarters to include (counting from today).
        """
        logger.debug(f"[temporal] tender_volume_trend: company={company_id} q={quarters}")

        if company_id:
            query = """
                MATCH (c:Company {id: $company_id})-[:WINS]->(t:Tender)
                WHERE t.data_aggiudicazione IS NOT NULL
                  AND t.data_aggiudicazione >= date() - duration({months: $months})
                WITH c.id                              AS company_id,
                     t.data_aggiudicazione.year        AS year,
                     ((t.data_aggiudicazione.month-1)/3 + 1) AS quarter,
                     t.importo                         AS importo
                WITH company_id, year, quarter,
                     count(*)           AS tender_count,
                     sum(importo)       AS total_value,
                     avg(importo)       AS avg_value
                WHERE tender_count >= $min_bucket
                RETURN company_id, year, quarter, tender_count,
                       total_value, avg_value
                ORDER BY year ASC, quarter ASC
            """
            results = self.conn.run_query(
                query,
                {
                    "company_id": company_id,
                    "months": quarters * 3,
                    "min_bucket": TEMPORAL_MIN_TENDERS_PER_BUCKET,
                },
            )
        else:
            query = """
                MATCH ()-[:WINS]->(t:Tender)
                WHERE t.data_aggiudicazione IS NOT NULL
                  AND t.data_aggiudicazione >= date() - duration({months: $months})
                WITH t.data_aggiudicazione.year        AS year,
                     ((t.data_aggiudicazione.month-1)/3 + 1) AS quarter,
                     t.importo                         AS importo
                WITH year, quarter,
                     count(*)           AS tender_count,
                     sum(importo)       AS total_value,
                     avg(importo)       AS avg_value
                WHERE tender_count >= $min_bucket
                RETURN year, quarter, tender_count, total_value, avg_value
                ORDER BY year ASC, quarter ASC
            """
            results = self.conn.run_query(
                query,
                {
                    "months": quarters * 3,
                    "min_bucket": TEMPORAL_MIN_TENDERS_PER_BUCKET,
                },
            )

        if not results:
            _warn_no_dates("Tender volume trend")
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Single-bidder ratio trend
    # ──────────────────────────────────────────────────────────────────────────

    def get_single_bidder_trend(
        self,
        company_id: str | None = None,
        quarters: int = TEMPORAL_DEFAULT_QUARTERS,
    ) -> list[dict]:
        """
        Return quarterly single-bidder ratio (fraction of unopposed wins).

        Each result dict has:
          year, quarter, total_wins, single_bidder_wins, single_bidder_ratio

        A rising ratio over time suggests a company is increasingly exploiting
        non-competitive procurement — a core fraud indicator.
        """
        logger.debug(f"[temporal] single_bidder_trend: company={company_id} q={quarters}")

        company_filter = "AND c.id = $company_id" if company_id else ""
        params: dict = {"months": quarters * 3}
        if company_id:
            params["company_id"] = company_id

        results = self.conn.run_query(
            f"""
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({{months: $months}})
              {company_filter}
            WITH c.id                                   AS company_id,
                 c.nome_normalizzato                    AS company_name,
                 t.data_aggiudicazione.year             AS year,
                 ((t.data_aggiudicazione.month-1)/3+1)  AS quarter,
                 t.single_bidder                        AS is_single
            WITH company_id, company_name, year, quarter,
                 count(*)                               AS total_wins,
                 sum(CASE WHEN is_single = true THEN 1 ELSE 0 END)
                                                        AS single_bidder_wins
            WITH company_id, company_name, year, quarter, total_wins, single_bidder_wins,
                 toFloat(single_bidder_wins) / total_wins AS single_bidder_ratio
            WHERE total_wins >= {TEMPORAL_MIN_TENDERS_PER_BUCKET}
            RETURN company_id, company_name, year, quarter,
                   total_wins, single_bidder_wins,
                   round(single_bidder_ratio * 1000) / 1000.0 AS single_bidder_ratio
            ORDER BY company_id, year ASC, quarter ASC
            """,
            params,
        )

        if not results:
            _warn_no_dates("Single-bidder ratio trend")
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Buyer-concentration trend (HHI per quarter)
    # ──────────────────────────────────────────────────────────────────────────

    def get_buyer_concentration_trend(
        self,
        company_id: str,
        quarters: int = TEMPORAL_DEFAULT_QUARTERS,
    ) -> list[dict]:
        """
        Quarterly Herfindahl-Hirschman Index (HHI) of buyer concentration for
        a given company winner.

        HHI = Σ(share_i²) where share_i = fraction of wins from buyer i.
        HHI → 1.0  means the company gets almost all work from a single buyer.
        HHI < 0.25 means healthy diversity.

        Each result dict has:
          year, quarter, buyer_count, hhi
        """
        logger.debug(f"[temporal] buyer_concentration_trend: company={company_id} q={quarters}")

        results = self.conn.run_query(
            """
            MATCH (c:Company {id: $company_id})-[:WINS]->(t:Tender)<-[:ISSUES]-(b:Buyer)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
            WITH c,
                 t.data_aggiudicazione.year            AS year,
                 ((t.data_aggiudicazione.month-1)/3+1) AS quarter,
                 b.id                                  AS buyer_id,
                 count(t)                              AS buyer_wins
            WITH year, quarter,
                 buyer_id, buyer_wins,
                 sum(buyer_wins) OVER (PARTITION BY year, quarter) AS quarter_total
            WITH year, quarter,
                 count(DISTINCT buyer_id)              AS buyer_count,
                 sum(toFloat(buyer_wins) * buyer_wins / (quarter_total * quarter_total)) AS hhi
            WHERE buyer_count >= 1
            RETURN year, quarter, buyer_count,
                   round(hhi * 1000) / 1000.0 AS hhi
            ORDER BY year ASC, quarter ASC
            """,
            {"company_id": company_id, "months": quarters * 3},
        )

        # Fallback: simpler query without window functions for older Neo4j
        if not results:
            results = self.conn.run_query(
                """
                MATCH (c:Company {id: $company_id})-[:WINS]->(t:Tender)<-[:ISSUES]-(b:Buyer)
                WHERE t.data_aggiudicazione IS NOT NULL
                  AND t.data_aggiudicazione >= date() - duration({months: $months})
                WITH t.data_aggiudicazione.year            AS year,
                     ((t.data_aggiudicazione.month-1)/3+1) AS quarter,
                     b.id                                   AS buyer_id,
                     count(t)                               AS buyer_wins
                WITH year, quarter,
                     collect({buyer: buyer_id, wins: buyer_wins}) AS pairs,
                     sum(buyer_wins)                               AS total
                WITH year, quarter,
                     size(pairs)                                   AS buyer_count,
                     reduce(h=0.0, p IN pairs |
                         h + toFloat(p.wins)*p.wins / (total*total)
                     )                                             AS hhi
                RETURN year, quarter, buyer_count,
                       round(hhi*1000)/1000.0 AS hhi
                ORDER BY year ASC, quarter ASC
                """,
                {"company_id": company_id, "months": quarters * 3},
            )

        if not results:
            _warn_no_dates("Buyer concentration trend")
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Sector spending volatility
    # ──────────────────────────────────────────────────────────────────────────

    def get_sector_spending_volatility(
        self,
        ateco_prefix: str,
        quarters: int = TEMPORAL_DEFAULT_QUARTERS,
    ) -> list[dict]:
        """
        Quarterly total spending + standard deviation for all companies whose
        ATECO code starts with ``ateco_prefix``.

        A high standard deviation signals boom-and-bust patterns within a
        sector — possible indicator of concentrated project pushes.

        Each result dict has:
          ateco_prefix, year, quarter, company_count, total_value, stddev_value
        """
        logger.debug(f"[temporal] sector_spending: ateco={ateco_prefix} q={quarters}")

        results = self.conn.run_query(
            """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE c.ateco STARTS WITH $ateco_prefix
              AND t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
              AND t.importo IS NOT NULL
            WITH t.data_aggiudicazione.year             AS year,
                 ((t.data_aggiudicazione.month-1)/3+1)  AS quarter,
                 c.id                                   AS company_id,
                 t.importo                              AS importo
            WITH year, quarter, company_id,
                 sum(importo) AS company_quarterly_spend
            WITH year, quarter,
                 count(DISTINCT company_id)                 AS company_count,
                 sum(company_quarterly_spend)               AS total_value,
                 stDev(company_quarterly_spend)             AS stddev_value
            WHERE company_count >= 1
            RETURN $ateco_prefix AS ateco_prefix,
                   year, quarter, company_count,
                   total_value,
                   round(stddev_value * 100) / 100.0 AS stddev_value
            ORDER BY year ASC, quarter ASC
            """,
            {"ateco_prefix": ateco_prefix, "months": quarters * 3},
        )

        if not results:
            _warn_no_dates("Sector spending volatility")
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Spike detection
    # ──────────────────────────────────────────────────────────────────────────

    def detect_sudden_spikes(
        self,
        metric: str = "tender_count",
        threshold: float = TEMPORAL_SPIKE_THRESHOLD,
        quarters: int = TEMPORAL_DEFAULT_QUARTERS,
        limit: int = 30,
    ) -> list[dict]:
        """
        Identify companies whose most recent quarter's activity exceeds
        ``threshold`` × the rolling mean of all prior quarters in the window.

        Parameters
        ----------
        metric :
            ``"tender_count"`` or ``"total_value"``
        threshold :
            Multiplier above which the latest quarter is flagged as a spike.
        quarters :
            How many past quarters to examine.
        limit :
            Maximum companies to return, ranked by spike ratio.

        Each result dict has:
          company_id, company_name, latest_year, latest_quarter,
          latest_value, prior_mean, spike_ratio
        """
        logger.debug(f"[temporal] detect_spikes: metric={metric} threshold={threshold}")

        if metric not in ("tender_count", "total_value"):
            raise ValueError(f"metric must be 'tender_count' or 'total_value', got {metric!r}")

        # Pull per-company quarterly volume
        raw = self.conn.run_query(
            """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
            WITH c.id                                   AS company_id,
                 c.nome_normalizzato                    AS company_name,
                 t.data_aggiudicazione.year             AS year,
                 ((t.data_aggiudicazione.month-1)/3+1)  AS quarter,
                 t.importo                              AS importo
            WITH company_id, company_name, year, quarter,
                 count(*)      AS tender_count,
                 sum(importo)  AS total_value
            RETURN company_id, company_name, year, quarter, tender_count, total_value
            ORDER BY company_id, year ASC, quarter ASC
            """,
            {"months": quarters * 3},
        )

        if not raw:
            _warn_no_dates("Spike detection")
            return []

        # Group in Python
        from collections import defaultdict

        by_company: dict[str, list[dict]] = defaultdict(list)
        for row in raw:
            by_company[row["company_id"]].append(row)

        spikes: list[dict] = []
        for company_id, rows in by_company.items():
            if len(rows) < 2:
                continue  # need at least one prior quarter to compare

            values = [r[metric] or 0.0 for r in rows]
            latest = values[-1]
            prior = values[:-1]
            prior_mean = statistics.mean(prior)

            if prior_mean == 0:
                continue

            ratio = latest / prior_mean
            if ratio >= threshold:
                last_row = rows[-1]
                spikes.append(
                    {
                        "company_id": company_id,
                        "company_name": last_row["company_name"],
                        "latest_year": last_row["year"],
                        "latest_quarter": last_row["quarter"],
                        "latest_value": round(latest, 2),
                        "prior_mean": round(prior_mean, 2),
                        "spike_ratio": round(ratio, 3),
                        "metric": metric,
                    }
                )

        spikes.sort(key=lambda x: x["spike_ratio"], reverse=True)
        return spikes[:limit]

    # ──────────────────────────────────────────────────────────────────────────
    # 6. Seasonal patterns
    # ──────────────────────────────────────────────────────────────────────────

    def get_seasonal_patterns(
        self,
        years: int = TEMPORAL_SEASONAL_YEARS,
    ) -> list[dict]:
        """
        Aggregate tender count and total value by calendar month across all
        years in the window to reveal seasonal procurement bias.

        Tenders clustered in December (end of budget year) or just before
        elections are a known red flag in Italian public procurement.

        Each result dict has:
          month (1-12), month_name, tender_count, total_value,
          avg_per_year (tender_count / years)
        """
        logger.debug(f"[temporal] seasonal_patterns: years={years}")

        _MONTH_NAMES = [
            "",
            "Gennaio",
            "Febbraio",
            "Marzo",
            "Aprile",
            "Maggio",
            "Giugno",
            "Luglio",
            "Agosto",
            "Settembre",
            "Ottobre",
            "Novembre",
            "Dicembre",
        ]

        results = self.conn.run_query(
            """
            MATCH ()-[:WINS]->(t:Tender)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({years: $years})
            WITH t.data_aggiudicazione.month AS month,
                 count(*)                    AS tender_count,
                 sum(t.importo)              AS total_value
            RETURN month, tender_count, total_value
            ORDER BY month ASC
            """,
            {"years": years},
        )

        if not results:
            _warn_no_dates("Seasonal patterns")
            return []

        return [
            {
                "month": row["month"],
                "month_name": _MONTH_NAMES[row["month"]],
                "tender_count": row["tender_count"],
                "total_value": row["total_value"],
                "avg_per_year": round(row["tender_count"] / years, 1),
            }
            for row in results
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # 7. Risk score history
    # ──────────────────────────────────────────────────────────────────────────

    def get_risk_score_history(
        self,
        company_id: str,
        snapshots: int = 8,
    ) -> list[dict]:
        """
        Return the most recent risk-score snapshots for a company, ordered
        newest-first.

        Snapshots are ``Version`` nodes linked via ``HAS_VERSION`` and populated
        by ``RiskEngine.save_risk_snapshot()``.

        Each result dict has:
          company_id, risk_score, change_date, anomaly_flags
        """
        logger.debug(f"[temporal] risk_score_history: company={company_id}")

        results = self.conn.run_query(
            """
            MATCH (c:Company {id: $company_id})-[:HAS_VERSION]->(v:Version)
            WHERE v.risk_score IS NOT NULL
            RETURN c.id            AS company_id,
                   v.risk_score    AS risk_score,
                   v.change_date   AS change_date,
                   v.anomaly_flags AS anomaly_flags
            ORDER BY v.change_date DESC
            LIMIT $snapshots
            """,
            {"company_id": company_id, "snapshots": snapshots},
        )

        if not results:
            logger.debug(
                f"[temporal] No risk snapshots for company={company_id}. "
                "Run RiskEngine.save_risk_snapshot() after each analysis cycle."
            )
        return results
