"""
Enhanced shell-company detection for the Paladino Knowledge Graph.

This module replaces the simple three-factor heuristic in
``OwnershipGraphAnalyzer.score_shell_companies()`` with a weighted
multi-factor model that combines seven independent risk signals.

Scoring formula
───────────────────────────────────────────────────────────────────
    shell_score = (
        0.30 * legacy_score          # existing: tender-wins + employees + depth
      + 0.15 * vat_anomaly_score     # wins contracts but VAT registration is missing/expired
      + 0.15 * dormancy_score        # no financial filings for ≥ 2 years
      + 0.15 * board_conc_score      # director sits on ≥ 20 boards simultaneously
      + 0.10 * supplier_only_score   # company only appears as sub-contractor, never prime
      + 0.10 * address_flag_score    # shares address / mailbox with other shell suspects
      + 0.05 * depth_bonus           # extra penalty for obscure holding chains > 5 hops
    )

    flag threshold: shell_score > 0.50  →  HIGH_RISK
    alert threshold: shell_score > 0.35 →  MEDIUM_RISK

All Neo4j queries are read-only (no writes).  Optionally the caller can ask
``store_results=True`` to persist a ``ShellRiskScore`` node for each company.

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.analytics.shell_company_detector import ShellCompanyDetector

    detector = ShellCompanyDetector(driver)
    results  = detector.score_all(limit=200, store_results=True)
    top10    = detector.get_high_risk(results, threshold=0.50)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from paladino.constants import (
    SHELL_COMPANY_TENDER_WIN_MIN,
    SHELL_COMPANY_EMPLOYEE_THRESHOLD,
    OWNERSHIP_CHAIN_MAX_DEPTH,
    SHELL_VAT_ANOMALY_WEIGHT,
    SHELL_DORMANCY_YEARS,
    SHELL_BOARD_CONCENTRATION_MAX,
    SHELL_SCORE_FLAG_THRESHOLD,
    SHELL_SCORE_ALERT_THRESHOLD,
)


# ─────────────────────────────────────────────────────────────────────────────
# Data-classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ShellRiskScore:
    """
    Risk decomposition for one company.

    Attributes
    ----------
    company_id:   CF (Codice Fiscale) of the company.
    company_name: Display name.
    shell_score:  Final weighted score  [0.0 … 1.0].
    risk_tier:    "HIGH_RISK" | "MEDIUM_RISK" | "LOW_RISK".
    factors:      Dict of factor_name → raw_value used in scoring.
    weights:      Dict of factor_name → weight applied.
    component_scores: Dict of factor_name → weighted contribution.
    """
    company_id:       str
    company_name:     str
    shell_score:      float
    risk_tier:        str
    factors:          Dict[str, Any]   = field(default_factory=dict)
    weights:          Dict[str, float] = field(default_factory=dict)
    component_scores: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "company_id":       self.company_id,
            "company_name":     self.company_name,
            "shell_score":      round(self.shell_score, 4),
            "risk_tier":        self.risk_tier,
            "factors":          self.factors,
            "weights":          self.weights,
            "component_scores": {k: round(v, 4) for k, v in self.component_scores.items()},
        }


# ─────────────────────────────────────────────────────────────────────────────
# Detector
# ─────────────────────────────────────────────────────────────────────────────

class ShellCompanyDetector:
    """
    Multi-factor shell company risk scorer.

    Parameters
    ----------
    driver:
        Active ``neo4j.Driver`` instance.
    """

    # Scoring weights (must sum to 1.0)
    _WEIGHTS: Dict[str, float] = {
        "legacy":        0.30,  # tender_wins + employees + ownership_depth
        "vat_anomaly":   0.15,  # VAT registration gap
        "dormancy":      0.15,  # no financial filings
        "board_conc":    0.15,  # director on many boards
        "supplier_only": 0.10,  # always sub, never prime
        "address_flag":  0.10,  # shared mailbox / no address
        "depth_bonus":   0.05,  # extra: deep holding chain
    }

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    # ── public API ───────────────────────────────────────────────────────────

    def score_all(
        self,
        limit:         int  = 500,
        store_results: bool = False,
    ) -> List[ShellRiskScore]:
        """
        Score every Company node in the graph and return results sorted by
        ``shell_score`` descending.

        Parameters
        ----------
        limit:
            Maximum number of companies to score (most-active first).
        store_results:
            When True, upsert a ``ShellRiskScore`` node for each result.
        """
        logger.info(f"[shell] Scoring up to {limit:,} companies…")
        raw_scores = self._query_raw_metrics(limit)

        results: List[ShellRiskScore] = []
        for row in raw_scores:
            score = self._compute_score(row)
            results.append(score)

        results.sort(key=lambda s: s.shell_score, reverse=True)
        logger.info(f"[shell] Scored {len(results):,} companies")

        if store_results:
            self._persist_scores(results)

        return results

    def score_single(self, company_id: str) -> Optional[ShellRiskScore]:
        """Score a single company by its CF."""
        rows = self._query_raw_metrics(limit=1, company_id=company_id)
        if not rows:
            return None
        return self._compute_score(rows[0])

    def get_high_risk(
        self,
        results: List[ShellRiskScore],
        threshold: float = SHELL_SCORE_FLAG_THRESHOLD,
    ) -> List[ShellRiskScore]:
        """Filter results to those above *threshold*."""
        return [r for r in results if r.shell_score >= threshold]

    def get_medium_risk(
        self,
        results: List[ShellRiskScore],
        low_threshold:  float = SHELL_SCORE_ALERT_THRESHOLD,
        high_threshold: float = SHELL_SCORE_FLAG_THRESHOLD,
    ) -> List[ShellRiskScore]:
        """Filter results in the medium-risk band."""
        return [r for r in results if low_threshold <= r.shell_score < high_threshold]

    # ── raw metric query ─────────────────────────────────────────────────────

    def _query_raw_metrics(
        self,
        limit: int,
        company_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all metrics needed for scoring in a single multi-pattern Cypher query.

        Columns returned per company:
          cf, name, tender_wins, has_employees, max_employees,
          chain_depth, vat_active, last_filing_year,
          director_board_count, sub_only, address_shared
        """
        where = "WHERE c.cf = $cf" if company_id else ""
        params: Dict[str, Any] = {"limit": limit}
        if company_id:
            params["cf"] = company_id

        query = f"""
        MATCH (c:Company)
        {where}

        // --- tender wins ---
        OPTIONAL MATCH (c)-[:AWARDED]->(t:Tender)
        WITH c, count(t) AS tender_wins

        // --- max employees ---
        OPTIONAL MATCH (c)-[:EMPLOYS]->(e:EmployeeRecord)
        WITH c, tender_wins, max(coalesce(e.count, 0)) AS max_employees

        // --- ownership chain depth ---
        OPTIONAL MATCH path = (c)-[:SHAREHOLDER_OF|SHARES_UBO*1..{OWNERSHIP_CHAIN_MAX_DEPTH}]->(root)
          WHERE NOT (root)-[:SHAREHOLDER_OF|SHARES_UBO]->()
        WITH c, tender_wins, max_employees,
             coalesce(max(length(path)), 0) AS chain_depth

        // --- VAT status (stored as property) ---
        WITH c, tender_wins, max_employees, chain_depth,
             coalesce(c.vat_active, true) AS vat_active,
             coalesce(c.last_financial_year, 0) AS last_filing_year

        // --- board concentration: max boards any director of c sits on ---
        OPTIONAL MATCH (p:Person)-[:REPRESENTS]->(c)
        OPTIONAL MATCH (p)-[:REPRESENTS]->(other:Company)
        WITH c, tender_wins, max_employees, chain_depth, vat_active, last_filing_year,
             coalesce(max(count(distinct other)), 0) AS director_board_count

        // --- supplier_only: never appears as prime contractor ---
        OPTIONAL MATCH (c)-[:SUBCONTRACTS_TO]->()
        WITH c, tender_wins, max_employees, chain_depth, vat_active, last_filing_year,
             director_board_count,
             (tender_wins = 0 AND count(*) > 0) AS sub_only

        // --- address shared with another company ---
        OPTIONAL MATCH (other2:Company)
          WHERE other2 <> c
            AND c.registered_address IS NOT NULL
            AND c.registered_address = other2.registered_address
        RETURN
            c.cf             AS cf,
            c.name           AS name,
            tender_wins,
            max_employees,
            chain_depth,
            vat_active,
            last_filing_year,
            director_board_count,
            sub_only,
            count(distinct other2) AS address_shared_count
        ORDER BY tender_wins DESC
        LIMIT $limit
        """

        try:
            with self._driver.session() as session:
                result = session.run(query, params)
                return [dict(r) for r in result]
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[shell] Raw metric query failed: {exc}")
            return []

    # ── scoring engine ────────────────────────────────────────────────────────

    def _compute_score(self, row: Dict[str, Any]) -> ShellRiskScore:
        """Apply the weighted formula to one row of raw metrics."""
        import datetime

        tender_wins     = int(row.get("tender_wins") or 0)
        max_employees   = int(row.get("max_employees") or 0)
        chain_depth     = int(row.get("chain_depth") or 0)
        vat_active      = bool(row.get("vat_active", True))
        last_filing     = int(row.get("last_filing_year") or 0)
        board_count     = int(row.get("director_board_count") or 0)
        sub_only        = bool(row.get("sub_only", False))
        address_shared  = int(row.get("address_shared_count") or 0)

        current_year = datetime.datetime.now().year

        # 1. Legacy score (matches existing OwnershipGraphAnalyzer.score_shell_companies)
        win_factor   = min(tender_wins / max(SHELL_COMPANY_TENDER_WIN_MIN, 1), 1.0)
        emp_factor   = 1.0 - min(max_employees / max(SHELL_COMPANY_EMPLOYEE_THRESHOLD, 1), 1.0)
        depth_factor = min(chain_depth / max(OWNERSHIP_CHAIN_MAX_DEPTH, 1), 1.0)
        legacy_score = (win_factor + emp_factor + depth_factor) / 3.0

        # 2. VAT anomaly: wins contracts but VAT inactive
        vat_anomaly_score = 0.0
        if tender_wins >= SHELL_COMPANY_TENDER_WIN_MIN and not vat_active:
            vat_anomaly_score = 1.0
        elif tender_wins > 0 and not vat_active:
            vat_anomaly_score = 0.5

        # 3. Dormancy: no filings for ≥ SHELL_DORMANCY_YEARS
        dormancy_score = 0.0
        if last_filing > 0:
            years_silent = current_year - last_filing
            if years_silent >= SHELL_DORMANCY_YEARS:
                dormancy_score = min(years_silent / (SHELL_DORMANCY_YEARS * 2), 1.0)

        # 4. Board concentration: director on too many boards
        board_conc_score = 0.0
        if board_count >= SHELL_BOARD_CONCENTRATION_MAX:
            board_conc_score = min(board_count / (SHELL_BOARD_CONCENTRATION_MAX * 2), 1.0)
        elif board_count > SHELL_BOARD_CONCENTRATION_MAX // 2:
            board_conc_score = 0.4

        # 5. Supplier-only: only ever appears as sub-contractor, never prime
        supplier_only_score = 1.0 if sub_only else 0.0

        # 6. Address flag
        address_flag_score = min(address_shared / 3.0, 1.0) if address_shared > 0 else 0.0

        # 7. Depth bonus: extra weight for deep chains
        depth_bonus = min(chain_depth / 8.0, 1.0) if chain_depth > 5 else 0.0

        # Weighted sum
        w = self._WEIGHTS
        components = {
            "legacy":        w["legacy"]        * legacy_score,
            "vat_anomaly":   w["vat_anomaly"]   * vat_anomaly_score,
            "dormancy":      w["dormancy"]       * dormancy_score,
            "board_conc":    w["board_conc"]     * board_conc_score,
            "supplier_only": w["supplier_only"]  * supplier_only_score,
            "address_flag":  w["address_flag"]   * address_flag_score,
            "depth_bonus":   w["depth_bonus"]    * depth_bonus,
        }
        total = sum(components.values())

        # Risk tier classification
        if total >= SHELL_SCORE_FLAG_THRESHOLD:
            tier = "HIGH_RISK"
        elif total >= SHELL_SCORE_ALERT_THRESHOLD:
            tier = "MEDIUM_RISK"
        else:
            tier = "LOW_RISK"

        return ShellRiskScore(
            company_id=str(row.get("cf") or ""),
            company_name=str(row.get("name") or ""),
            shell_score=total,
            risk_tier=tier,
            factors={
                "tender_wins":    tender_wins,
                "max_employees":  max_employees,
                "chain_depth":    chain_depth,
                "vat_active":     vat_active,
                "last_filing":    last_filing,
                "board_count":    board_count,
                "sub_only":       sub_only,
                "address_shared": address_shared,
            },
            weights=dict(w),
            component_scores=components,
        )

    # ── optional persistence ──────────────────────────────────────────────────

    def _persist_scores(self, results: List[ShellRiskScore]) -> None:
        """
        Upsert a ``ShellRiskScore`` node for each result and connect it to
        the Company node via ``HAS_SHELL_SCORE``.
        """
        logger.info(f"[shell] Persisting {len(results):,} shell risk scores…")
        query = """
        UNWIND $rows AS row
        MATCH (c:Company {cf: row.company_id})
        MERGE (s:ShellRiskScore {company_id: row.company_id})
        SET s.shell_score  = row.shell_score,
            s.risk_tier    = row.risk_tier,
            s.computed_at  = datetime(),
            s.factors      = row.factors_json,
            s.components   = row.components_json
        MERGE (c)-[:HAS_SHELL_SCORE]->(s)
        """
        import json as _json
        rows = [
            {
                "company_id":     r.company_id,
                "shell_score":    round(r.shell_score, 4),
                "risk_tier":      r.risk_tier,
                "factors_json":   _json.dumps(r.factors),
                "components_json": _json.dumps(
                    {k: round(v, 4) for k, v in r.component_scores.items()}
                ),
            }
            for r in results
        ]
        try:
            with self._driver.session() as session:
                session.run(query, {"rows": rows})
            logger.info("[shell] Shell risk scores persisted to graph")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[shell] Failed to persist shell scores: {exc}")
