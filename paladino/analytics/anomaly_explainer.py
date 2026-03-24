"""
Anomaly Explanation Engine — Feature 4.2.

Translates a company's numeric risk score into a plain-language explanation
that names *why* the score is high, cites the raw evidence values, and traces
every claim back to a source node in the graph.

Output format (JSON, Markdown, plain text)
──────────────────────────────────────────────────────────────────────────────
Example JSON:
{
  "company_id":  "12345678901",
  "company_name": "COSTRUZIONI ROSSI SRL",
  "risk_score":  0.73,
  "risk_tier":   "HIGH",
  "summary":     "This company scored 0.73 because: (1) 68% single-bidder wins,
                  (2) PageRank = 0.58 (market dominance), (3) 90% buyer concentration.",
  "factors": [
    {
      "factor":       "single_bidder_ratio",
      "label":        "Single-bidder win rate",
      "value":        0.68,
      "weight":       0.40,
      "contribution": 0.272,
      "sentence":     "Won 68% of its 15 tenders without competition (single-bidder).",
      "sources":      ["Tender:T001", "Tender:T002", ...]
    },
    ...
  ],
  "fraud_patterns": [
    {
      "pattern_name": "bid_rotation",
      "severity":     "high",
      "confidence":   0.85,
      "description":  "...",
      "pattern_id":   "uuid..."
    }
  ],
  "shell_risk": { ... },          // from ShellCompanyDetector if available
  "trend":   "WORSENING",         // WORSENING | STABLE | IMPROVING
  "risk_history": [...],          // last 5 snapshots
  "evidence_chain": [
    { "claim": "...", "source_label": "Tender", "source_id": "T001", "url": null }
  ],
  "generated_at": "2026-02-24T12:00:00+00:00"
}

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.analytics.anomaly_explainer import AnomalyExplainer

    explainer = AnomalyExplainer(conn)
    result = explainer.explain("12345678901")
    print(result.summary)
    print(result.render("md"))
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from paladino.db import Neo4jConnection


# ─────────────────────────────────────────────────────────────────────────────
# Risk-tier thresholds
# ─────────────────────────────────────────────────────────────────────────────

_TIER_HIGH     = 0.70
_TIER_MEDIUM   = 0.40
_TIER_LOW      = 0.0


def _risk_tier(score: float) -> str:
    if score >= _TIER_HIGH:
        return "HIGH"
    if score >= _TIER_MEDIUM:
        return "MEDIUM"
    return "LOW"


# ─────────────────────────────────────────────────────────────────────────────
# Data-classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FactorExplanation:
    """One scoring signal contributing to the overall risk score."""
    factor:       str          # machine key, e.g. "single_bidder_ratio"
    label:        str          # human label, e.g. "Single-bidder win rate"
    value:        float        # raw measured value
    weight:       float        # relative weight in the scoring formula
    contribution: float        # weight × normalised_value
    sentence:     str          # 1-sentence plain-English narrative
    sources:      List[str] = field(default_factory=list)  # ["Tender:T001", …]


@dataclass
class EvidenceLink:
    """A single citation linking a claim to a source graph node."""
    claim:        str
    source_label: str          # Neo4j label: "Tender", "Buyer", "FraudPattern"
    source_id:    str
    source_name:  Optional[str] = None
    url:          Optional[str] = None


@dataclass
class ExplanationResult:
    """
    Complete explanation for one company.

    All fields are plain Python (no Neo4j types) so the object is directly
    JSON-serialisable.
    """
    company_id:     str
    company_name:   str
    risk_score:     float
    risk_tier:      str
    summary:        str
    factors:        List[FactorExplanation]        = field(default_factory=list)
    fraud_patterns: List[Dict[str, Any]]           = field(default_factory=list)
    shell_risk:     Optional[Dict[str, Any]]       = None
    trend:          str                            = "STABLE"   # WORSENING|STABLE|IMPROVING
    risk_history:   List[Dict[str, Any]]           = field(default_factory=list)
    evidence_chain: List[EvidenceLink]             = field(default_factory=list)
    generated_at:   str                            = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── serialisation ──────────────────────────────────────────────────────

    def as_dict(self) -> Dict[str, Any]:
        return {
            "company_id":     self.company_id,
            "company_name":   self.company_name,
            "risk_score":     round(self.risk_score, 4),
            "risk_tier":      self.risk_tier,
            "summary":        self.summary,
            "factors": [
                {
                    "factor":       f.factor,
                    "label":        f.label,
                    "value":        round(f.value, 4),
                    "weight":       f.weight,
                    "contribution": round(f.contribution, 4),
                    "sentence":     f.sentence,
                    "sources":      f.sources,
                }
                for f in self.factors
            ],
            "fraud_patterns": self.fraud_patterns,
            "shell_risk":     self.shell_risk,
            "trend":          self.trend,
            "risk_history":   self.risk_history,
            "evidence_chain": [
                {
                    "claim":        e.claim,
                    "source_label": e.source_label,
                    "source_id":    e.source_id,
                    "source_name":  e.source_name,
                    "url":          e.url,
                }
                for e in self.evidence_chain
            ],
            "generated_at":   self.generated_at,
        }

    def render(self, format: str = "json") -> str:
        """Render this explanation as json | md | text."""
        if format == "json":
            return json.dumps(self.as_dict(), ensure_ascii=False, indent=2, default=str)
        if format == "md":
            return _render_markdown(self)
        if format == "text":
            return _render_text(self)
        raise ValueError(f"Unsupported format {format!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Main explainer
# ─────────────────────────────────────────────────────────────────────────────

class AnomalyExplainer:
    """
    Explain *why* a company has its current risk score.

    Queries the graph for all contributing signals, formats them into
    human-readable sentences, and returns an :class:`ExplanationResult`.

    Parameters
    ----------
    conn:
        Active :class:`~paladino.db.Neo4jConnection`.
    include_shell_risk:
        When True (default), call :class:`ShellCompanyDetector` for the
        multi-factor shell score component.
    """

    def __init__(
        self,
        conn: Neo4jConnection,
        include_shell_risk: bool = True,
    ) -> None:
        self.conn = conn
        self.include_shell_risk = include_shell_risk

    # ── public API ───────────────────────────────────────────────────────────

    def explain(self, company_id: str) -> ExplanationResult:
        """
        Generate a full explanation for *company_id*.

        Parameters
        ----------
        company_id:
            ``id`` property (or ``cf`` — the method tries both) of the Company node.

        Raises
        ------
        KeyError if the company is not found in the graph.
        """
        logger.info(f"[explain] Generating explanation for {company_id}")

        info = self._get_company_info(company_id)
        if not info:
            raise KeyError(f"Company {company_id!r} not found in graph")

        # Resolve actual id (may have been passed cf)
        resolved_id = info.get("company_id") or company_id
        risk_score  = float(info.get("risk_score") or 0.0)
        name        = info.get("company_name") or company_id

        # Collect all signals
        factors         = self._explain_risk_factors(resolved_id, risk_score)
        fraud_patterns  = self._get_fraud_patterns(resolved_id)
        shell_risk      = self._get_shell_risk(resolved_id) if self.include_shell_risk else None
        risk_history    = self._get_risk_history(resolved_id)
        trend           = self._compute_trend(risk_history, risk_score)
        evidence_chain  = self._build_evidence_chain(
            resolved_id, factors, fraud_patterns
        )
        summary = self._generate_summary(name, risk_score, factors, fraud_patterns)

        return ExplanationResult(
            company_id=company_id,
            company_name=name,
            risk_score=risk_score,
            risk_tier=_risk_tier(risk_score),
            summary=summary,
            factors=factors,
            fraud_patterns=fraud_patterns,
            shell_risk=shell_risk,
            trend=trend,
            risk_history=risk_history,
            evidence_chain=evidence_chain,
        )

    # ── company info ─────────────────────────────────────────────────────────

    def _get_company_info(self, company_id: str) -> Optional[Dict[str, Any]]:
        rows = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.id = $cid OR c.cf = $cid
            RETURN c.id                  AS company_id,
                   c.cf                  AS cf,
                   c.nome_normalizzato   AS company_name,
                   c.risk_score         AS risk_score,
                   c.anomaly_flags      AS anomaly_flags,
                   c.centrality_score   AS centrality_score,
                   c.community_id       AS community_id
            LIMIT 1
            """,
            {"cid": company_id},
        )
        return dict(rows[0]) if rows else None

    # ── risk factor breakdown ─────────────────────────────────────────────────

    def _explain_risk_factors(
        self,
        company_id: str,
        risk_score: float,
    ) -> List[FactorExplanation]:
        """
        Reconstruct the three scoring signals from RiskEngine and compute
        their individual contributions to the overall score.
        """
        factors: List[FactorExplanation] = []

        # 1. Single-bidder ratio
        sbr = self._query_single_bidder(company_id)
        if sbr is not None:
            ratio    = sbr["ratio"]
            total    = sbr["total_wins"]
            sb_wins  = sbr["single_bidder_wins"]
            contrib  = round(ratio * 0.40, 4)
            sentence = (
                f"Won {ratio:.0%} of its {total} tender(s) without competition "
                f"({sb_wins} single-bidder award{'s' if sb_wins != 1 else ''})."
                if ratio > 0
                else f"All {total} tender win(s) had at least one competing bidder."
            )
            factors.append(FactorExplanation(
                factor="single_bidder_ratio",
                label="Single-bidder win rate",
                value=ratio,
                weight=0.40,
                contribution=contrib,
                sentence=sentence,
                sources=[f"Tender:{tid}" for tid in sbr.get("sample_tender_ids", [])],
            ))

        # 2. Market dominance (PageRank centrality)
        centrality = self._query_centrality(company_id)
        if centrality is not None:
            raw      = centrality["centrality_score"]
            contrib  = round(raw * 0.30, 4)
            sentence = (
                f"PageRank centrality = {raw:.2f} "
                f"({'above' if raw >= 0.50 else 'below'} the 0.50 market-dominance threshold). "
                + ("Indicates a hub-like position in the procurement network." if raw >= 0.50
                   else "No unusual centrality detected.")
            )
            factors.append(FactorExplanation(
                factor="market_dominance",
                label="Market dominance (PageRank)",
                value=raw,
                weight=0.30,
                contribution=contrib,
                sentence=sentence,
            ))

        # 3. Buyer concentration
        bc = self._query_buyer_concentration(company_id)
        if bc is not None:
            ratio    = bc["concentration_ratio"]
            buyer    = bc.get("top_buyer_name") or "unknown buyer"
            contrib  = round(min(ratio, 1.0) * 0.30, 4)
            sentence = (
                f"{ratio:.0%} of wins came from a single buyer ({buyer}). "
                + ("Suggests dependency or preferential treatment." if ratio >= 0.80
                   else "Buyer concentration within normal range.")
            )
            factors.append(FactorExplanation(
                factor="buyer_concentration",
                label="Buyer concentration",
                value=ratio,
                weight=0.30,
                contribution=contrib,
                sentence=sentence,
                sources=[f"Buyer:{bc.get('top_buyer_id')}"] if bc.get("top_buyer_id") else [],
            ))

        # Sort by contribution descending (most impactful first)
        factors.sort(key=lambda f: f.contribution, reverse=True)
        return factors

    # ── graph queries for each factor ─────────────────────────────────────────

    def _query_single_bidder(self, company_id: str) -> Optional[Dict[str, Any]]:
        rows = self.conn.run_query(
            """
            MATCH (c:Company {id: $cid})-[:WINS]->(t:Tender)
            WITH c,
                 count(t)                                                       AS total_wins,
                 sum(CASE WHEN t.single_bidder = true THEN 1 ELSE 0 END)        AS sb_wins,
                 collect(CASE WHEN t.single_bidder = true THEN t.id END)[..5]   AS sample_ids
            WHERE total_wins > 0
            RETURN total_wins,
                   sb_wins                                                       AS single_bidder_wins,
                   toFloat(sb_wins) / total_wins                                AS ratio,
                   [x IN sample_ids WHERE x IS NOT NULL]                        AS sample_tender_ids
            """,
            {"cid": company_id},
        )
        return dict(rows[0]) if rows else None

    def _query_centrality(self, company_id: str) -> Optional[Dict[str, Any]]:
        rows = self.conn.run_query(
            """
            MATCH (c:Company {id: $cid})
            RETURN coalesce(c.centrality_score, 0.0) AS centrality_score
            """,
            {"cid": company_id},
        )
        return dict(rows[0]) if rows else None

    def _query_buyer_concentration(self, company_id: str) -> Optional[Dict[str, Any]]:
        rows = self.conn.run_query(
            """
            MATCH (c:Company {id: $cid})-[:WINS]->(t:Tender)<-[:ISSUES]-(b:Buyer)
            WITH c, b, count(t) AS wins_with_buyer
            MATCH (c)-[:WINS]->(total_t:Tender)
            WITH b, wins_with_buyer, count(total_t) AS total_wins
            WHERE total_wins > 0
            WITH b, wins_with_buyer, total_wins,
                 toFloat(wins_with_buyer) / total_wins AS ratio
            ORDER BY ratio DESC
            LIMIT 1
            RETURN ratio                   AS concentration_ratio,
                   b.id                    AS top_buyer_id,
                   b.nome_normalizzato     AS top_buyer_name
            """,
            {"cid": company_id},
        )
        return dict(rows[0]) if rows else None

    # ── fraud patterns ────────────────────────────────────────────────────────

    def _get_fraud_patterns(self, company_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.run_query(
            """
            MATCH (c:Company {id: $cid})-[r:FLAGGED_BY]->(f:FraudPattern)
            RETURN f.id              AS pattern_id,
                   f.pattern_name   AS pattern_name,
                   f.severity       AS severity,
                   f.confidence     AS confidence,
                   f.description    AS description,
                   f.created_at     AS created_at,
                   r.score          AS entity_score,
                   r.evidence       AS evidence_json
            ORDER BY f.confidence DESC
            """,
            {"cid": company_id},
        )
        return [dict(r) for r in (rows or [])]

    # ── shell risk ────────────────────────────────────────────────────────────

    def _get_shell_risk(self, company_id: str) -> Optional[Dict[str, Any]]:
        """
        Try the cached ShellRiskScore node first; fall back to live scoring.
        """
        # Check for cached score
        rows = self.conn.run_query(
            """
            MATCH (c:Company {id: $cid})-[:HAS_SHELL_SCORE]->(s:ShellRiskScore)
            RETURN s.shell_score   AS shell_score,
                   s.risk_tier     AS risk_tier,
                   s.components    AS components_json,
                   s.computed_at   AS computed_at
            LIMIT 1
            """,
            {"cid": company_id},
        )
        if rows:
            r = dict(rows[0])
            try:
                r["components"] = json.loads(r.get("components_json") or "{}")
            except (ValueError, TypeError):
                r["components"] = {}
            return r

        # Fall back to live computation
        try:
            from paladino.analytics.shell_company_detector import ShellCompanyDetector
            detector = ShellCompanyDetector(self.conn.driver)
            result   = detector.score_single(company_id)
            if result:
                return result.as_dict()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[explain] Shell risk fallback failed: {exc}")
        return None

    # ── risk history & trend ──────────────────────────────────────────────────

    def _get_risk_history(self, company_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.run_query(
            """
            MATCH (c:Company {id: $cid})-[:HAS_VERSION]->(v:Version)
            WHERE v.risk_score IS NOT NULL
            RETURN v.risk_score    AS risk_score,
                   v.change_date   AS change_date,
                   v.anomaly_flags AS anomaly_flags
            ORDER BY v.change_date DESC
            LIMIT 6
            """,
            {"cid": company_id},
        )
        return [dict(r) for r in (rows or [])]

    def _compute_trend(
        self,
        history: List[Dict[str, Any]],
        current_score: float,
    ) -> str:
        """
        Classify trend as WORSENING, STABLE, or IMPROVING.

        Requires at least 2 historical snapshots (newest-first).
        """
        if len(history) < 2:
            return "STABLE"

        # history[0] is the most recent snapshot *before* now
        previous_score = float(history[0].get("risk_score") or 0.0)
        delta = current_score - previous_score

        if delta > 0.05:
            return "WORSENING"
        if delta < -0.05:
            return "IMPROVING"
        return "STABLE"

    # ── evidence citation chain ────────────────────────────────────────────────

    def _build_evidence_chain(
        self,
        company_id: str,
        factors:        List[FactorExplanation],
        fraud_patterns: List[Dict[str, Any]],
    ) -> List[EvidenceLink]:
        """
        Build a list of evidence links tracing each claim to a graph node.
        """
        chain: List[EvidenceLink] = []

        for f in factors:
            for src in f.sources:
                parts = src.split(":", 1)
                label = parts[0] if len(parts) == 2 else "Unknown"
                sid   = parts[1] if len(parts) == 2 else src
                chain.append(EvidenceLink(
                    claim=f.sentence,
                    source_label=label,
                    source_id=sid,
                ))

        for fp in fraud_patterns:
            chain.append(EvidenceLink(
                claim=fp.get("description") or fp.get("pattern_name") or "Fraud pattern",
                source_label="FraudPattern",
                source_id=fp.get("pattern_id") or "",
                source_name=fp.get("pattern_name"),
            ))

        return chain

    # ── summary sentence ──────────────────────────────────────────────────────

    def _generate_summary(
        self,
        name:           str,
        risk_score:     float,
        factors:        List[FactorExplanation],
        fraud_patterns: List[Dict[str, Any]],
    ) -> str:
        """
        Auto-generate the headline summary sentence.

        Example: "This company scored 0.73 because: (1) 68% single-bidder wins,
                  (2) PageRank = 0.58, (3) 90% buyer concentration."
        """
        if not factors and not fraud_patterns:
            return (
                f"{name} has a risk score of {risk_score:.2f}. "
                "No specific contributing factors were identified."
            )

        parts: List[str] = []
        for i, f in enumerate(factors[:3], start=1):
            if f.factor == "single_bidder_ratio":
                parts.append(f"({i}) {f.value:.0%} single-bidder wins")
            elif f.factor == "market_dominance":
                parts.append(f"({i}) PageRank = {f.value:.2f}")
            elif f.factor == "buyer_concentration":
                parts.append(f"({i}) {f.value:.0%} buyer concentration")
            else:
                parts.append(f"({i}) {f.label} = {f.value:.2f}")

        if fraud_patterns and len(parts) < 3:
            pat_names = [p.get("pattern_name", "unknown") for p in fraud_patterns[:2]]
            parts.append(f"({len(parts)+1}) fraud patterns: {', '.join(pat_names)}")

        if parts:
            return (
                f"This company scored {risk_score:.2f} because: "
                + ", ".join(parts) + "."
            )
        return f"{name} has a risk score of {risk_score:.2f}."


# ─────────────────────────────────────────────────────────────────────────────
# Markdown and text renderers
# ─────────────────────────────────────────────────────────────────────────────

def _render_markdown(r: ExplanationResult) -> str:
    tier_badge = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(r.risk_tier, "⚪")
    trend_icon = {"WORSENING": "📈", "IMPROVING": "📉", "STABLE": "➡️"}.get(r.trend, "➡️")

    lines = [
        f"# Anomaly Explanation — {r.company_name}",
        "",
        f"**Generated:** {r.generated_at}  ",
        f"**Company ID:** `{r.company_id}`  ",
        f"**Risk Score:** {tier_badge} **{r.risk_score:.2f}** ({r.risk_tier})  ",
        f"**Trend:** {trend_icon} {r.trend}  ",
        "",
        f"> {r.summary}",
        "",
        "---",
        "",
        "## Scoring Factors",
        "",
    ]

    if r.factors:
        lines += [
            "| Factor | Value | Weight | Contribution |",
            "|--------|-------|--------|-------------|",
        ]
        for f in r.factors:
            bar = "█" * int(f.contribution * 20)
            lines.append(
                f"| **{f.label}** | {f.value:.2%} | {f.weight:.0%} | "
                f"{f.contribution:.3f} {bar} |"
            )
        lines.append("")
        for f in r.factors:
            lines += [f"**{f.label}:** {f.sentence}", ""]
    else:
        lines.append("_No scoring factor data available._")

    lines += ["---", "", "## Fraud Pattern Alerts", ""]
    if r.fraud_patterns:
        for fp in r.fraud_patterns:
            sev   = (fp.get("severity") or "?").upper()
            icons = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "⚪"}
            icon  = icons.get(sev, "⚪")
            lines.append(
                f"- {icon} **[{sev}]** `{fp.get('pattern_name')}` "
                f"(confidence {float(fp.get('confidence') or 0):.0%})"
            )
            if fp.get("description"):
                lines.append(f"  > {fp['description']}")
    else:
        lines.append("_No fraud patterns detected._")

    if r.shell_risk:
        sr = r.shell_risk
        lines += [
            "", "---", "", "## Shell Company Risk", "",
            f"**Shell Score:** {float(sr.get('shell_score') or 0):.2%}  ",
            f"**Tier:** {sr.get('risk_tier', 'N/A')}  ",
        ]

    if r.risk_history:
        lines += ["", "---", "", "## Risk Score History", "",
                  "| Date | Score | Flags |",
                  "|------|-------|-------|"]
        for snap in r.risk_history:
            lines.append(
                f"| {snap.get('change_date','')} | "
                f"{float(snap.get('risk_score') or 0):.2f} | "
                f"{snap.get('anomaly_flags','')} |"
            )

    if r.evidence_chain:
        lines += ["", "---", "", "## Evidence Citation Chain", ""]
        for i, ev in enumerate(r.evidence_chain, start=1):
            src = f"{ev.source_label}:{ev.source_id}"
            if ev.source_name:
                src += f" ({ev.source_name})"
            lines.append(f"{i}. **[{src}]** — {ev.claim}")

    return "\n".join(lines)


def _render_text(r: ExplanationResult) -> str:
    lines = [
        f"ANOMALY EXPLANATION — {r.company_name}",
        f"Risk Score: {r.risk_score:.2f} [{r.risk_tier}]  Trend: {r.trend}",
        "",
        r.summary,
        "",
        "FACTORS:",
    ]
    for f in r.factors:
        lines.append(f"  [{f.label}]  value={f.value:.2%}  weight={f.weight:.0%}  "
                     f"contribution={f.contribution:.3f}")
        lines.append(f"  → {f.sentence}")
    if r.fraud_patterns:
        lines += ["", "FRAUD PATTERNS:"]
        for fp in r.fraud_patterns:
            lines.append(f"  [{fp.get('severity','?').upper()}] {fp.get('pattern_name')} — "
                         f"{fp.get('description','')[:100]}")
    if r.shell_risk:
        lines += ["", f"SHELL RISK: {float(r.shell_risk.get('shell_score') or 0):.2%} "
                      f"[{r.shell_risk.get('risk_tier','?')}]"]
    return "\n".join(lines)
