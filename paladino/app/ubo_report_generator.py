"""
UBO (Ultimate Beneficial Owner) Report Generator.

Assembles corporate-structure data, ownership chains, and fraud-pattern
results into a human-readable or machine-readable report for a single company.

Supported output formats:
  • json   — structured dict (default, API-friendly)
  • md     — Markdown document
  • csv    — flat CSV rows (one row per UBO)

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.app.ubo_report_generator import UBOReportGenerator
    from paladino.db import Neo4jConnection

    conn = Neo4jConnection()
    gen  = UBOReportGenerator(conn)

    report = gen.generate("12345678901", format="json")
    print(report)

    # Markdown report
    md = gen.generate("12345678901", format="md")
    Path("ubo_report.md").write_text(md)
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from paladino.analytics.ownership_graph import OwnershipGraphAnalyzer
from paladino.analytics.shell_company_detector import ShellCompanyDetector
from paladino.db import Neo4jConnection


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_SUPPORTED_FORMATS = {"json", "md", "csv"}


# ─────────────────────────────────────────────────────────────────────────────
# Generator
# ─────────────────────────────────────────────────────────────────────────────

class UBOReportGenerator:
    """
    Generate UBO (Ultimate Beneficial Owner) reports for Italian companies.

    Parameters
    ----------
    conn:
        Active :class:`~paladino.db.Neo4jConnection`.
    """

    def __init__(self, conn: Neo4jConnection) -> None:
        self.conn = conn
        self._ownership_analyzer = OwnershipGraphAnalyzer(conn)
        self._shell_detector     = ShellCompanyDetector(conn.driver)

    # ── public API ───────────────────────────────────────────────────────────

    def generate(
        self,
        company_id: str,
        format:     str = "json",
    ) -> str:
        """
        Generate a UBO report for *company_id*.

        Parameters
        ----------
        company_id:
            Codice Fiscale (CF) of the target company.
        format:
            One of ``"json"``, ``"md"``, ``"csv"``.

        Returns
        -------
        str — serialised report in the requested format.

        Raises
        ------
        ValueError if format is not supported.
        KeyError if the company is not found in the graph.
        """
        if format not in _SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format {format!r}. Choose one of: {sorted(_SUPPORTED_FORMATS)}"
            )

        logger.info(f"[ubo_report] Generating {format.upper()} report for {company_id}")
        data = self._collect_data(company_id)

        if format == "json":
            return json.dumps(data, ensure_ascii=False, indent=2, default=str)
        if format == "md":
            return self._render_markdown(data)
        if format == "csv":
            return self._render_csv(data)

        raise ValueError(f"Unhandled format: {format}")  # unreachable

    # ── data collection ───────────────────────────────────────────────────────

    def _collect_data(self, company_id: str) -> Dict[str, Any]:
        """
        Pull all data needed for the report from the graph.

        Sections assembled:
          - company_info
          - ownership_chain  (all ancestors up to OWNERSHIP_CHAIN_MAX_DEPTH)
          - ubos             (terminal nodes — the actual beneficial owners)
          - corporate_family (sibling companies under same UBO)
          - shell_risk       (multi-factor shell score)
          - fraud_patterns   (any FraudPattern nodes linked to this company)
          - directors        (REPRESENTS edges)
          - supply_chain     (downstream SUBCONTRACTS_TO / SUPPLIES_TO)
        """
        company_info = self._get_company_info(company_id)

        ownership_chain = self._ownership_analyzer.get_ownership_chain(company_id)
        ubos            = self._extract_ubos(ownership_chain)
        corporate_family = self._ownership_analyzer.get_corporate_family(company_id)
        shell_risk      = self._get_shell_risk(company_id)
        fraud_patterns  = self._get_fraud_patterns(company_id)
        directors       = self._get_directors(company_id)
        supply_chain    = self._ownership_analyzer.get_supply_chain(company_id)

        return {
            "generated_at":   datetime.now(timezone.utc).isoformat(),
            "company_id":     company_id,
            "company_info":   company_info,
            "ownership_chain": ownership_chain,
            "ubos":           ubos,
            "corporate_family": corporate_family,
            "shell_risk":     shell_risk,
            "fraud_patterns": fraud_patterns,
            "directors":      directors,
            "supply_chain":   supply_chain,
        }

    def _get_company_info(self, company_id: str) -> Dict[str, Any]:
        rows = self.conn.run_query(
            """
            MATCH (c:Company {cf: $cf})
            RETURN c.cf            AS cf,
                   c.name          AS name,
                   c.ateco         AS ateco,
                   c.comune        AS comune,
                   c.regione       AS regione,
                   c.vat_active    AS vat_active,
                   c.risk_score    AS risk_score,
                   c.registered_address AS address
            LIMIT 1
            """,
            {"cf": company_id},
        )
        if not rows:
            raise KeyError(f"Company {company_id!r} not found in graph")
        return dict(rows[0])

    def _extract_ubos(self, ownership_chain: List[Dict]) -> List[Dict]:
        """
        Filter the ownership chain to terminal nodes (the actual UBOs).

        A UBO is any node in the chain that has no further upstream owner
        in the returned chain.  Following the EU AML Directive: any entity
        owning ≥ 25% is a reportable beneficial owner.
        """
        if not ownership_chain:
            return []

        # Nodes that appear as targets of ownership edges are intermediaries;
        # nodes that only appear as sources are the UBOs.
        has_owner: set[str] = set()
        all_nodes: dict[str, dict] = {}
        for entry in ownership_chain:
            owner_id = entry.get("owner_id") or entry.get("from_id")
            target_id = entry.get("target_id") or entry.get("to_id") or entry.get("company_id")
            if owner_id:
                all_nodes[owner_id] = entry
            if target_id:
                has_owner.add(target_id)

        # UBOs = nodes with no owner in this chain
        return [
            {"ubo_id": nid, **info}
            for nid, info in all_nodes.items()
            if nid not in has_owner
        ]

    def _get_shell_risk(self, company_id: str) -> Optional[Dict]:
        result = self._shell_detector.score_single(company_id)
        return result.as_dict() if result else None

    def _get_fraud_patterns(self, company_id: str) -> List[Dict]:
        rows = self.conn.run_query(
            """
            MATCH (c:Company {cf: $cf})-[:FLAGGED_BY]->(f:FraudPattern)
            RETURN f.pattern_name AS pattern_name,
                   f.severity     AS severity,
                   f.confidence   AS confidence,
                   f.description  AS description,
                   f.created_at   AS created_at
            ORDER BY f.confidence DESC
            """,
            {"cf": company_id},
        )
        return [dict(r) for r in (rows or [])]

    def _get_directors(self, company_id: str) -> List[Dict]:
        rows = self.conn.run_query(
            """
            MATCH (p:Person)-[r:REPRESENTS]->(c:Company {cf: $cf})
            RETURN p.cf      AS person_cf,
                   p.name    AS name,
                   r.role    AS role,
                   r.start   AS start_date,
                   r.end     AS end_date
            ORDER BY r.role
            """,
            {"cf": company_id},
        )
        return [dict(r) for r in (rows or [])]

    # ── renderers ─────────────────────────────────────────────────────────────

    def _render_markdown(self, data: Dict[str, Any]) -> str:
        info    = data.get("company_info") or {}
        name    = info.get("name") or data["company_id"]
        risk    = data.get("shell_risk") or {}
        ubos    = data.get("ubos") or []
        dirs    = data.get("directors") or []
        frauds  = data.get("fraud_patterns") or []
        family  = data.get("corporate_family") or []
        supply  = data.get("supply_chain") or []

        lines: list[str] = [
            f"# UBO Report — {name}",
            f"",
            f"**Generated:** {data['generated_at']}  ",
            f"**Company CF:** `{data['company_id']}`  ",
            f"**ATECO:** {info.get('ateco', 'N/A')}  ",
            f"**Address:** {info.get('address', 'N/A')}  ",
            f"**VAT Active:** {info.get('vat_active', 'Unknown')}  ",
            f"",
            f"---",
            f"",
            f"## Shell Risk Score",
            f"",
        ]

        if risk:
            score = risk.get("shell_score", 0)
            tier  = risk.get("risk_tier", "N/A")
            tier_badge = {"HIGH_RISK": "🔴", "MEDIUM_RISK": "🟡", "LOW_RISK": "🟢"}.get(tier, "⚪")
            lines += [
                f"**Score:** {score:.2%}  ",
                f"**Risk Tier:** {tier_badge} {tier}  ",
                f"",
                f"| Factor | Contribution |",
                f"|--------|-------------|",
            ]
            for factor, contrib in (risk.get("component_scores") or {}).items():
                lines.append(f"| {factor} | {contrib:.4f} |")
        else:
            lines.append("_No shell risk data available._")

        lines += ["", "---", "", "## Ultimate Beneficial Owners (UBOs)", ""]
        if ubos:
            for ubo in ubos:
                lines.append(f"- **{ubo.get('ubo_id', '?')}** — {ubo}")
        else:
            lines.append("_No UBOs identified in the ownership chain._")

        lines += ["", "---", "", "## Board of Directors", ""]
        if dirs:
            lines += [
                "| Name | CF | Role | From | To |",
                "|------|----|------|------|----|",
            ]
            for d in dirs:
                lines.append(
                    f"| {d.get('name','')} | {d.get('person_cf','')} | "
                    f"{d.get('role','')} | {d.get('start_date','')} | {d.get('end_date','')} |"
                )
        else:
            lines.append("_No director data available._")

        lines += ["", "---", "", "## Fraud Pattern Alerts", ""]
        if frauds:
            for f in frauds:
                sev = f.get("severity", "?").upper()
                lines.append(
                    f"- **[{sev}]** `{f.get('pattern_name')}` "
                    f"(confidence {f.get('confidence', 0):.0%}): {f.get('description', '')}"
                )
        else:
            lines.append("_No fraud patterns detected for this company._")

        lines += ["", "---", "", "## Corporate Family", ""]
        if family:
            for member in family[:20]:
                lines.append(f"- {member}")
        else:
            lines.append("_No corporate family data available._")

        lines += ["", "---", "", "## Supply Chain", ""]
        if supply:
            for node in supply[:20]:
                lines.append(f"- {node}")
        else:
            lines.append("_No supply chain data available._")

        return "\n".join(lines)

    def _render_csv(self, data: Dict[str, Any]) -> str:
        """
        Flat CSV with one row per UBO (or director if no UBOs).
        Columns: report_date, company_id, company_name, ubo_id,
                 shell_score, risk_tier, fraud_count.
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "report_date", "company_id", "company_name",
            "ubo_id", "shell_score", "risk_tier", "fraud_count",
        ])

        info    = data.get("company_info") or {}
        ubos    = data.get("ubos") or [{}]
        risk    = data.get("shell_risk") or {}
        frauds  = data.get ("fraud_patterns") or []

        for ubo in ubos:
            writer.writerow([
                data["generated_at"],
                data["company_id"],
                info.get("name", ""),
                ubo.get("ubo_id", ""),
                risk.get("shell_score", ""),
                risk.get("risk_tier", ""),
                len(frauds),
            ])

        return output.getvalue()
