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

    # ──────────────────────────────────────────────────────────────────────────
    # 8. Risk trend analysis
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_risk_tier(score: float) -> str:
        """Classify risk score into tier."""
        if score >= 0.7:
            return "high"
        elif score >= 0.4:
            return "medium"
        else:
            return "low"

    def get_risk_trend_analysis(
        self,
        company_id: str,
        snapshots: int = 8,
    ) -> dict:
        """
        Calculate trend metrics for a company's risk score evolution.

        Parameters
        ----------
        company_id :
            The ``id`` property of the Company node.
        snapshots :
            Number of snapshots to analyze (default: 8).

        Returns
        -------
        dict
            Trend analysis with:
            - company_id, company_name
            - current_score, current_tier
            - previous_score, previous_tier
            - delta, delta_percent, direction
            - volatility (std dev), max_score, min_score
            - tier_crossed, significant_increase
            - snapshots_count, period_start, period_end
        """
        logger.debug(f"[temporal] risk_trend_analysis: company={company_id}")

        # Get history (ordered newest first)
        history = self.get_risk_score_history(company_id, snapshots)

        if not history:
            return {
                "company_id": company_id,
                "company_name": None,
                "current_score": None,
                "current_tier": None,
                "previous_score": None,
                "previous_tier": None,
                "delta": 0.0,
                "delta_percent": None,
                "direction": "stable",
                "volatility": 0.0,
                "max_score": None,
                "min_score": None,
                "tier_crossed": False,
                "significant_increase": False,
                "snapshots_count": 0,
                "period_start": None,
                "period_end": None,
            }

        # Get company name
        company_name = None
        name_result = self.conn.run_query(
            "MATCH (c:Company {id: $company_id}) RETURN c.nome_normalizzato AS name",
            {"company_id": company_id},
        )
        if name_result:
            company_name = name_result[0].get("name")

        # Reverse to chronological order for analysis
        scores_chronological = [h["risk_score"] for h in reversed(history)]
        scores = [h["risk_score"] for h in history]  # newest first

        current_score = scores[0]
        current_tier = self._get_risk_tier(current_score)

        previous_score = scores[1] if len(scores) > 1 else None
        previous_tier = self._get_risk_tier(previous_score) if previous_score is not None else None

        # Calculate delta (current - previous, where previous is oldest in window)
        oldest_score = scores_chronological[0]
        delta = current_score - oldest_score

        # Delta percent
        delta_percent = None
        if oldest_score is not None and oldest_score > 0:
            delta_percent = round((delta / oldest_score) * 100, 2)

        # Direction
        if delta > 0.05:
            direction = "increasing"
        elif delta < -0.05:
            direction = "decreasing"
        else:
            direction = "stable"

        # Volatility (standard deviation)
        volatility = 0.0
        if len(scores_chronological) > 1:
            volatility = round(statistics.stdev(scores_chronological), 4)

        # Range
        max_score = max(scores)
        min_score = min(scores)

        # Tier crossed?
        tier_crossed = False
        if previous_tier is not None and current_tier != previous_tier:
            tier_crossed = True

        # Significant increase (delta > 0.3)
        significant_increase = delta > 0.3

        # Period dates
        period_end = history[0].get("change_date") if history else None
        period_start = history[-1].get("change_date") if len(history) > 1 else None

        return {
            "company_id": company_id,
            "company_name": company_name,
            "current_score": current_score,
            "current_tier": current_tier,
            "previous_score": oldest_score,
            "previous_tier": self._get_risk_tier(oldest_score),
            "delta": round(delta, 4),
            "delta_percent": delta_percent,
            "direction": direction,
            "volatility": volatility,
            "max_score": max_score,
            "min_score": min_score,
            "tier_crossed": tier_crossed,
            "significant_increase": significant_increase,
            "snapshots_count": len(history),
            "period_start": period_start,
            "period_end": period_end,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 9. Risk distribution over time
    # ──────────────────────────────────────────────────────────────────────────

    def get_risk_distribution_over_time(
        self,
        quarters: int = 8,
    ) -> list[dict]:
        """
        Get global risk score distribution by quarter.

        Aggregates Version nodes by quarter and calculates distribution
        across risk tiers (high, medium, low).

        Parameters
        ----------
        quarters :
            Number of past quarters to include.

        Returns
        -------
        list[dict]
            Risk distribution per quarter with:
            - period, year, quarter
            - high_risk_count, medium_risk_count, low_risk_count
            - total_companies, avg_risk_score, median_risk_score
            - stddev_risk_score (if available)
            - high_risk_percent, medium_risk_percent, low_risk_percent
        """
        logger.debug(f"[temporal] risk_distribution_over_time: quarters={quarters}")

        results = self.conn.run_query(
            """
            MATCH (c:Company)-[:HAS_VERSION]->(v:Version)
            WHERE v.risk_score IS NOT NULL
              AND v.change_date >= datetime() - duration({months: $months})
            WITH c.id AS company_id,
                 v.risk_score AS risk_score,
                 v.change_date.year AS year,
                 ((v.change_date.month - 1) / 3 + 1) AS quarter
            // Get latest snapshot per company per quarter
            WITH company_id, year, quarter, risk_score
            ORDER BY company_id, year, quarter, risk_score DESC
            WITH company_id, year, quarter, head(collect(risk_score)) AS risk_score
            // Aggregate by quarter
            WITH year, quarter, collect(risk_score) AS scores
            WITH year, quarter,
                 size([s IN scores WHERE s >= 0.7]) AS high_count,
                 size([s IN scores WHERE s >= 0.4 AND s < 0.7]) AS medium_count,
                 size([s IN scores WHERE s < 0.4]) AS low_count,
                 size(scores) AS total,
                 avg(toFloat(scores)) AS avg_score,
                 scores AS sorted_scores
            WITH year, quarter,
                 high_count, medium_count, low_count, total,
                 avg_score,
                 sorted_scores[toInt(size(sorted_scores)/2)] AS median_score,
                 CASE WHEN size(sorted_scores) > 1
                      THEN sqrt(reduce(sum = 0.0, s IN sorted_scores |
                           sum + (s - avg_score)^2
                      ) / (size(sorted_scores) - 1))
                      ELSE null END AS stddev_score
            WHERE total > 0
            RETURN toString(year) + '-Q' + toString(quarter) AS period,
                   year, quarter,
                   high_count AS high_risk_count,
                   medium_count AS medium_risk_count,
                   low_count AS low_risk_count,
                   total AS total_companies,
                   round(avg_score * 1000) / 1000.0 AS avg_risk_score,
                   round(median_score * 1000) / 1000.0 AS median_risk_score,
                   CASE WHEN stddev_score IS NOT NULL
                        THEN round(stddev_score * 1000) / 1000.0
                        ELSE null END AS stddev_risk_score,
                   round(toFloat(high_count) / total * 100, 2) AS high_risk_percent,
                   round(toFloat(medium_count) / total * 100, 2) AS medium_risk_percent,
                   round(toFloat(low_count) / total * 100, 2) AS low_risk_percent
            ORDER BY year ASC, quarter ASC
            """,
            {"months": quarters * 3},
        )

        if not results:
            logger.debug("[temporal] No risk distribution data found")
            return []

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # 10. Companies with risk changes
    # ──────────────────────────────────────────────────────────────────────────

    def get_companies_with_risk_changes(
        self,
        limit: int = 20,
        min_delta: float = 0.1,
    ) -> dict:
        """
        Find companies with the biggest risk score changes between snapshots.

        Compares the two most recent snapshots for each company to identify
        significant increases and decreases.

        Parameters
        ----------
        limit :
            Maximum companies to return for each category.
        min_delta :
            Minimum absolute delta to include (default: 0.1).

        Returns
        -------
        dict
            Contains:
            - increases: Companies with biggest risk increases
            - decreases: Companies with biggest risk decreases
            - critical_alerts: Companies with delta > 0.3
            - tier_crossings: Companies that crossed tier boundaries
        """
        logger.debug(f"[temporal] risk_changes: limit={limit} min_delta={min_delta}")

        # Get latest two snapshots per company
        results = self.conn.run_query(
            """
            MATCH (c:Company)-[:HAS_VERSION]->(v:Version)
            WHERE v.risk_score IS NOT NULL
            WITH c, v
            ORDER BY v.change_date DESC
            WITH c, collect(v) AS versions
            WHERE size(versions) >= 2
            WITH c,
                 versions[0].risk_score AS new_score,
                 versions[1].risk_score AS old_score,
                 versions[0].change_date AS new_date,
                 versions[1].change_date AS old_date
            WHERE abs(new_score - old_score) >= $min_delta
            RETURN c.id AS company_id,
                   c.nome_normalizzato AS company_name,
                   c.regione AS region,
                   c.ateco AS ateco,
                   old_score,
                   new_score,
                   (new_score - old_score) AS delta,
                   CASE WHEN old_score >= 0.7 THEN 'high'
                        WHEN old_score >= 0.4 THEN 'medium'
                        ELSE 'low' END AS old_tier,
                   CASE WHEN new_score >= 0.7 THEN 'high'
                        WHEN new_score >= 0.4 THEN 'medium'
                        ELSE 'low' END AS new_tier
            ORDER BY delta DESC
            """,
            {"min_delta": min_delta},
        )

        if not results:
            logger.debug("[temporal] No significant risk changes found")
            return {
                "increases": [],
                "decreases": [],
                "critical_alerts": [],
                "tier_crossings": [],
            }

        increases = []
        decreases = []
        critical_alerts = []
        tier_crossings = []

        for row in results:
            item = {
                "company_id": row["company_id"],
                "company_name": row["company_name"],
                "region": row.get("region"),
                "ateco": row.get("ateco"),
                "old_score": row["old_score"],
                "new_score": row["new_score"],
                "delta": round(row["delta"], 4),
                "old_tier": row["old_tier"],
                "new_tier": row["new_tier"],
                "tier_crossed": row["old_tier"] != row["new_tier"],
                "change_type": "increase" if row["delta"] > 0 else "decrease",
                "severity": "critical" if abs(row["delta"]) > 0.3 else "moderate",
            }

            if row["delta"] > 0:
                increases.append(item)
                if row["delta"] > 0.3:
                    critical_alerts.append(item)
            else:
                decreases.append(item)

            if item["tier_crossed"]:
                tier_crossings.append(item)

        # Sort decreases by delta ascending (most negative first)
        decreases.sort(key=lambda x: x["delta"])
        # Sort increases by delta descending (most positive first)
        increases.sort(key=lambda x: x["delta"], reverse=True)

        return {
            "increases": increases[:limit],
            "decreases": decreases[:limit],
            "critical_alerts": critical_alerts[:limit],
            "tier_crossings": tier_crossings[:limit],
        }

    def get_diff(self, entity_id: str, date_a: str, date_b: str) -> dict:
        """
        Compare the properties and relationships of an entity between two dates.
        Returns a structured delta including structural changes.
        """
        from paladino.app.temporal_rewriter import apply_temporal_filter

        logger.info(f"Computing structural diff for {entity_id} between {date_a} and {date_b}")
        
        # 1. Get Node Properties for both dates
        prop_query = "MATCH (n {id: $id}) RETURN properties(n) as props"
        query_a = apply_temporal_filter(prop_query, date_a)
        query_b = apply_temporal_filter(prop_query, date_b)

        res_a = self.conn.run_query(query_a, {"id": entity_id, "as_of": date_a})
        res_b = self.conn.run_query(query_b, {"id": entity_id, "as_of": date_b})

        props_a = res_a[0]["props"] if res_a else {}
        props_b = res_b[0]["props"] if res_b else {}

        # 2. Get Structural State (Relationships) for both dates
        rel_query = """
        MATCH (n {id: $id})-[r]-(m)
        RETURN type(r) as type, id(m) as target_id, properties(r) as props
        """
        rel_query_a = apply_temporal_filter(rel_query, date_a)
        rel_query_b = apply_temporal_filter(rel_query, date_b)

        rels_a_raw = self.conn.run_query(rel_query_a, {"id": entity_id, "as_of": date_a})
        rels_b_raw = self.conn.run_query(rel_query_b, {"id": entity_id, "as_of": date_b})

        # Convert to membership signatures: {(type, target_id): props}
        def _get_sig_map(raw_rels):
            return {(r['type'], r['target_id']): r['props'] for r in raw_rels}

        sig_map_a = _get_sig_map(rels_a_raw)
        sig_map_b = _get_sig_map(rels_b_raw)

        # ── comparison logic (Properties) ─────────────────────────────────────
        added_props = {}
        removed_props = {}
        changed_props = {}
        internal_keys = {"valid_from", "valid_to", "updated_at", "lastUpdated", "retrievalDate"}

        all_prop_keys = set(props_a.keys()) | set(props_b.keys())
        for key in all_prop_keys:
            if key in internal_keys: continue
            val_a, val_b = props_a.get(key), props_b.get(key)
            if key not in props_a: added_props[key] = val_b
            elif key not in props_b: removed_props[key] = val_a
            elif val_a != val_b: changed_props[key] = {"old": val_a, "new": val_b}

        # ── comparison logic (Relationships) ──────────────────────────────────
        added_links = []
        removed_links = []
        changed_links = []

        all_sigs = set(sig_map_a.keys()) | set(sig_map_b.keys())
        for sig in all_sigs:
            type_name, target_id = sig
            p_a, p_b = sig_map_a.get(sig), sig_map_b.get(sig)

            if sig not in sig_map_a:
                added_links.append({"type": type_name, "target_id": target_id, "props": p_b})
            elif sig not in sig_map_b:
                removed_links.append({"type": type_name, "target_id": target_id, "props": p_a})
            elif p_a != p_b:
                # Compare relationship properties
                diff_p = {}
                all_p_keys = set(p_a.keys()) | set(p_b.keys())
                for pk in all_p_keys:
                    if pk in internal_keys: continue
                    va, vb = p_a.get(pk), p_b.get(pk)
                    if va != vb: diff_p[pk] = {"old": va, "new": vb}
                if diff_p:
                    changed_links.append({"type": type_name, "target_id": target_id, "changes": diff_p})

        return {
            "entity_id": entity_id,
            "date_a": date_a,
            "date_b": date_b,
            "diff": {
                "added": added_props,
                "removed": removed_props,
                "changed": changed_props,
                "added_links": added_links,
                "removed_links": removed_links,
                "changed_links": changed_links
            },
            "has_changes": bool(added_props or removed_props or changed_props or added_links or removed_links or changed_links)
        }
