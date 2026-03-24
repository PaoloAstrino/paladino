"""
Recommendation Engine — Feature 4.4.

Suggests "what to look at next" for an investigator who has just examined a
company, using four complementary graph-native strategies:

  content       — feature similarity (ATECO sector, region, risk score proximity,
                  anomaly-flag overlap)
  community     — Louvain community neighbours (co-cluster members)
  anomaly       — Jaccard similarity on anomaly_flags arrays
  sector_trending — top-risk companies in the same 2-digit ATECO sector

All strategies are pure Cypher queries against the existing graph — no
external ML libraries required.

Example output (JSON)
──────────────────────────────────────────────────────────────────────────────
{
  "source_company_id":   "cf-12345",
  "source_company_name": "COSTRUZIONI ROSSI SRL",
  "source_risk_score":   0.73,
  "source_risk_tier":    "HIGH",
  "recommendations": [
    {
      "company_id":       "cf-67890",
      "company_name":     "EDIL BIANCHI SPA",
      "cf":               "67890123456",
      "risk_score":       0.69,
      "similarity_score": 0.81,
      "reason":           "Same Louvain community (#5); same ATECO sector (41); similar risk score (delta 0.04).",
      "strategies":       ["community", "content"],
      "shared_features":  ["community:5", "ATECO:41", "risk_delta<0.10"]
    },
    ...
  ],
  "strategies_used": ["content", "community", "anomaly", "sector_trending"],
  "generated_at":    "2026-02-24T12:00:00+00:00"
}

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.analytics.recommendation_engine import RecommendationEngine

    engine = RecommendationEngine(conn)
    result = engine.recommend("12345678901")
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
# Risk-tier helper (mirrors anomaly_explainer)
# ─────────────────────────────────────────────────────────────────────────────

_TIER_HIGH   = 0.70
_TIER_MEDIUM = 0.40


def _risk_tier(score: float) -> str:
    if score >= _TIER_HIGH:
        return "HIGH"
    if score >= _TIER_MEDIUM:
        return "MEDIUM"
    return "LOW"


# ─────────────────────────────────────────────────────────────────────────────
# Similarity scoring constants
# ─────────────────────────────────────────────────────────────────────────────

_WEIGHT_SAME_ATECO   = 0.30   # same 2-digit sector prefix
_WEIGHT_SAME_REGION  = 0.25   # same Italian region
_WEIGHT_RISK_CLOSE   = 0.20   # |risk_delta| < RISK_DELTA_THRESHOLD
_WEIGHT_FLAG_JACCARD = 0.25   # anomaly_flags Jaccard similarity
RISK_DELTA_THRESHOLD = 0.15   # risk scores within this band are "similar"
COMMUNITY_DEFAULT_SCORE = 0.85  # similarity score assigned to community neighbours


# ─────────────────────────────────────────────────────────────────────────────
# Data-classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Recommendation:
    """A single company recommendation with explanation."""
    company_id:       str
    company_name:     str
    cf:               str
    risk_score:       float
    similarity_score: float          # 0.0 – 1.0
    reason:           str
    strategies:       List[str]      # which strategies produced this recommendation
    shared_features:  List[str]      # human-readable feature overlap

    def as_dict(self) -> Dict[str, Any]:
        return {
            "company_id":       self.company_id,
            "company_name":     self.company_name,
            "cf":               self.cf,
            "risk_score":       round(self.risk_score, 4),
            "similarity_score": round(self.similarity_score, 4),
            "reason":           self.reason,
            "strategies":       self.strategies,
            "shared_features":  self.shared_features,
        }


@dataclass
class RecommendationResult:
    """Full recommendation result for a source company."""
    source_company_id:   str
    source_company_name: str
    source_risk_score:   float
    source_risk_tier:    str
    recommendations:     List[Recommendation]
    strategies_used:     List[str]
    generated_at:        str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_company_id":   self.source_company_id,
            "source_company_name": self.source_company_name,
            "source_risk_score":   round(self.source_risk_score, 4),
            "source_risk_tier":    self.source_risk_tier,
            "recommendations":     [r.as_dict() for r in self.recommendations],
            "strategies_used":     self.strategies_used,
            "generated_at":        self.generated_at,
        }

    def render(self, fmt: str = "json") -> str:
        """Render to 'json', 'md', or 'text'."""
        if fmt == "json":
            return json.dumps(self.as_dict(), ensure_ascii=False, indent=2)
        if fmt == "md":
            return _render_markdown(self)
        if fmt == "text":
            return _render_text(self)
        raise ValueError(f"Unknown format {fmt!r}. Choose 'json', 'md', or 'text'.")


# ─────────────────────────────────────────────────────────────────────────────
# Renderers
# ─────────────────────────────────────────────────────────────────────────────

def _render_markdown(r: RecommendationResult) -> str:
    tier_badge = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(r.source_risk_tier, "")
    lines: List[str] = [
        f"# Recommendations for {r.source_company_name}",
        "",
        f"**Source risk score:** {r.source_risk_score:.2f} {tier_badge} {r.source_risk_tier}  ",
        f"**Strategies applied:** {', '.join(r.strategies_used)}  ",
        f"**Generated:** {r.generated_at}",
        "",
        f"---",
        "",
        f"## {len(r.recommendations)} Recommended Companies",
        "",
    ]
    for i, rec in enumerate(r.recommendations, 1):
        tier_b = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(_risk_tier(rec.risk_score), "")
        lines += [
            f"### {i}. {rec.company_name}",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| CF | `{rec.cf}` |",
            f"| Risk Score | {rec.risk_score:.2f} {tier_b} {_risk_tier(rec.risk_score)} |",
            f"| Similarity | {rec.similarity_score:.0%} |",
            f"| Strategies | {', '.join(rec.strategies)} |",
            "",
            f"**Why:** {rec.reason}",
            "",
            f"**Shared features:** {', '.join(rec.shared_features) if rec.shared_features else 'n/a'}",
            "",
        ]
    return "\n".join(lines)


def _render_text(r: RecommendationResult) -> str:
    lines: List[str] = [
        f"Recommendations for {r.source_company_name} "
        f"(risk {r.source_risk_score:.2f} / {r.source_risk_tier}):",
        "",
    ]
    for i, rec in enumerate(r.recommendations, 1):
        lines.append(
            f"  {i}. {rec.company_name} — risk {rec.risk_score:.2f}, "
            f"similarity {rec.similarity_score:.0%}. {rec.reason}"
        )
    lines.append(f"\nGenerated: {r.generated_at}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Jaccard utility
# ─────────────────────────────────────────────────────────────────────────────

def _jaccard(a: List[str], b: List[str]) -> float:
    """Jaccard similarity between two lists treated as sets."""
    sa, sb = set(a or []), set(b or [])
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _ateco2(ateco: Optional[str]) -> Optional[str]:
    """Return the 2-digit ATECO prefix, or None."""
    if not ateco or len(ateco) < 2:
        return None
    return ateco[:2]


# ─────────────────────────────────────────────────────────────────────────────
# Main engine
# ─────────────────────────────────────────────────────────────────────────────

class RecommendationEngine:
    """
    Graph-native recommendation engine using four complementary strategies.

    Parameters
    ----------
    conn:
        Active :class:`~paladino.db.Neo4jConnection` instance.
    """

    _VALID_STRATEGIES = frozenset({"content", "community", "anomaly", "sector_trending"})

    def __init__(self, conn: Neo4jConnection) -> None:
        self.conn = conn

    # ── public API ────────────────────────────────────────────────────────────

    def recommend(
        self,
        company_id: str,
        strategies: Optional[List[str]] = None,
        limit: int = 10,
        min_similarity: float = 0.0,
    ) -> RecommendationResult:
        """
        Generate recommendations for *company_id*.

        Parameters
        ----------
        company_id:
            Company node ``id`` or ``cf`` (Codice Fiscale).
        strategies:
            Subset of ``["content", "community", "anomaly", "sector_trending"]``.
            Defaults to all four.
        limit:
            Maximum number of recommendations to return (after deduplication).
        min_similarity:
            Discard candidates with similarity_score < this threshold.

        Returns
        -------
        RecommendationResult
        """
        strategies = strategies or list(self._VALID_STRATEGIES)
        unknown = set(strategies) - self._VALID_STRATEGIES
        if unknown:
            raise ValueError(
                f"Unknown strategy/strategies: {sorted(unknown)}. "
                f"Valid options: {sorted(self._VALID_STRATEGIES)}"
            )

        source = self._get_company_info(company_id)
        if source is None:
            raise KeyError(f"Company {company_id!r} not found in graph.")

        logger.info(
            f"[Recommend] Generating for {source['company_name']!r} "
            f"(id={source['company_id']}) — strategies: {strategies}"
        )

        # Collect raw candidates from each strategy
        all_recs: Dict[str, Recommendation] = {}  # keyed by company_id

        if "content" in strategies:
            for rec in self._content_based(source):
                _merge(all_recs, rec, "content")

        if "community" in strategies:
            for rec in self._community_based(source):
                _merge(all_recs, rec, "community")

        if "anomaly" in strategies:
            for rec in self._anomaly_based(source):
                _merge(all_recs, rec, "anomaly")

        if "sector_trending" in strategies:
            for rec in self._sector_trending(source):
                _merge(all_recs, rec, "sector_trending")

        # Filter out the source company itself, apply min_similarity, sort, trim
        filtered = [
            r for r in all_recs.values()
            if r.company_id != source["company_id"]
            and r.similarity_score >= min_similarity
        ]
        filtered.sort(key=lambda r: r.similarity_score, reverse=True)
        final = filtered[:limit]

        return RecommendationResult(
            source_company_id=source["company_id"],
            source_company_name=source["company_name"],
            source_risk_score=source["risk_score"],
            source_risk_tier=_risk_tier(source["risk_score"]),
            recommendations=final,
            strategies_used=sorted(strategies),
        )

    # ── strategy: content-based ───────────────────────────────────────────────

    def _content_based(self, source: Dict[str, Any]) -> List[Recommendation]:
        """
        Compute feature-overlap similarity for candidate companies.

        Scoring weights
        ---------------
        same ATECO prefix (2 digits) : 0.30
        same regione                 : 0.25
        risk score within ±0.15      : 0.20
        anomaly_flags Jaccard        : 0.25
        """
        rows = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.id <> $source_id
              AND c.cf <> $source_id
              AND c.id IS NOT NULL
            RETURN c.id               AS company_id,
                   c.nome_normalizzato AS company_name,
                   c.cf               AS cf,
                   coalesce(c.risk_score, 0.0)      AS risk_score,
                   c.ateco            AS ateco,
                   c.regione          AS regione,
                   c.anomaly_flags    AS anomaly_flags
            LIMIT 2000
            """,
            {"source_id": source["company_id"]},
        )

        src_ateco  = _ateco2(source.get("ateco"))
        src_region = source.get("regione")
        src_risk   = source.get("risk_score", 0.0)
        src_flags  = source.get("anomaly_flags") or []

        results: List[Recommendation] = []
        for row in rows:
            score = 0.0
            shared: List[str] = []

            cand_ateco = _ateco2(row.get("ateco"))
            if src_ateco and cand_ateco and src_ateco == cand_ateco:
                score += _WEIGHT_SAME_ATECO
                shared.append(f"ATECO:{src_ateco}")

            cand_region = row.get("regione")
            if src_region and cand_region and src_region == cand_region:
                score += _WEIGHT_SAME_REGION
                shared.append(f"regione:{src_region}")

            cand_risk = float(row.get("risk_score") or 0.0)
            if abs(cand_risk - src_risk) < RISK_DELTA_THRESHOLD:
                score += _WEIGHT_RISK_CLOSE
                shared.append(f"risk_delta<{RISK_DELTA_THRESHOLD}")

            cand_flags = list(row.get("anomaly_flags") or [])
            jac = _jaccard(src_flags, cand_flags)
            score += jac * _WEIGHT_FLAG_JACCARD
            if jac > 0:
                shared.append(f"flags_jaccard:{jac:.2f}")

            if score <= 0:
                continue

            reason_parts: List[str] = []
            if f"ATECO:{src_ateco}" in shared:
                reason_parts.append(f"same ATECO sector ({src_ateco})")
            if f"regione:{src_region}" in shared:
                reason_parts.append(f"same region ({src_region})")
            if f"risk_delta<{RISK_DELTA_THRESHOLD}" in shared:
                reason_parts.append(
                    f"similar risk score (delta {abs(cand_risk - src_risk):.2f})"
                )
            if jac > 0:
                reason_parts.append(f"overlapping anomaly flags (Jaccard {jac:.2f})")

            results.append(
                Recommendation(
                    company_id=row["company_id"],
                    company_name=row.get("company_name") or row.get("cf") or row["company_id"],
                    cf=row.get("cf") or "",
                    risk_score=cand_risk,
                    similarity_score=min(score, 1.0),
                    reason="; ".join(reason_parts) + ".",
                    strategies=["content"],
                    shared_features=shared,
                )
            )

        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results[:50]  # keep top-50 from this strategy before merging

    # ── strategy: community-based ─────────────────────────────────────────────

    def _community_based(self, source: Dict[str, Any]) -> List[Recommendation]:
        """
        Return companies in the same Louvain community (``community_id`` property).
        """
        community_id = source.get("community_id")
        if community_id is None:
            logger.debug("[Recommend] community_based: source has no community_id, skipping.")
            return []

        rows = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.community_id = $cid
              AND c.id <> $source_id
            RETURN c.id               AS company_id,
                   c.nome_normalizzato AS company_name,
                   c.cf               AS cf,
                   coalesce(c.risk_score, 0.0) AS risk_score
            ORDER BY c.risk_score DESC
            LIMIT 30
            """,
            {"cid": community_id, "source_id": source["company_id"]},
        )

        results: List[Recommendation] = []
        for row in rows:
            results.append(
                Recommendation(
                    company_id=row["company_id"],
                    company_name=row.get("company_name") or row.get("cf") or row["company_id"],
                    cf=row.get("cf") or "",
                    risk_score=float(row.get("risk_score") or 0.0),
                    similarity_score=COMMUNITY_DEFAULT_SCORE,
                    reason=f"Same Louvain community (#{community_id}).",
                    strategies=["community"],
                    shared_features=[f"community:{community_id}"],
                )
            )
        return results

    # ── strategy: anomaly-profile ─────────────────────────────────────────────

    def _anomaly_based(self, source: Dict[str, Any]) -> List[Recommendation]:
        """
        Find companies with similar anomaly-flag profiles using Jaccard similarity.
        Only considers companies that share at least one anomaly flag with the source.
        """
        src_flags = list(source.get("anomaly_flags") or [])
        if not src_flags:
            logger.debug("[Recommend] anomaly_based: source has no anomaly_flags, skipping.")
            return []

        # Retrieve candidates that have at least one matching flag
        rows = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.id <> $source_id
              AND any(flag IN $flags WHERE flag IN coalesce(c.anomaly_flags, []))
            RETURN c.id               AS company_id,
                   c.nome_normalizzato AS company_name,
                   c.cf               AS cf,
                   coalesce(c.risk_score, 0.0) AS risk_score,
                   coalesce(c.anomaly_flags, []) AS anomaly_flags
            LIMIT 200
            """,
            {"source_id": source["company_id"], "flags": src_flags},
        )

        results: List[Recommendation] = []
        for row in rows:
            cand_flags  = list(row.get("anomaly_flags") or [])
            jac         = _jaccard(src_flags, cand_flags)
            shared_flags = list(set(src_flags) & set(cand_flags))
            results.append(
                Recommendation(
                    company_id=row["company_id"],
                    company_name=row.get("company_name") or row.get("cf") or row["company_id"],
                    cf=row.get("cf") or "",
                    risk_score=float(row.get("risk_score") or 0.0),
                    similarity_score=jac,
                    reason=(
                        f"Shares anomaly flags [{', '.join(shared_flags)}] "
                        f"(Jaccard {jac:.2f})."
                    ),
                    strategies=["anomaly"],
                    shared_features=[f"flag:{f}" for f in shared_flags],
                )
            )

        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results[:30]

    # ── strategy: sector trending ─────────────────────────────────────────────

    def _sector_trending(self, source: Dict[str, Any]) -> List[Recommendation]:
        """
        Return the highest-risk companies in the same 2-digit ATECO sector,
        ordered by risk_score descending (sector-level risk hotspots).
        """
        src_ateco2 = _ateco2(source.get("ateco"))
        if not src_ateco2:
            logger.debug("[Recommend] sector_trending: source has no ATECO, skipping.")
            return []

        rows = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.ateco STARTS WITH $ateco2
              AND c.id <> $source_id
              AND c.risk_score IS NOT NULL
              AND c.risk_score > 0
            RETURN c.id               AS company_id,
                   c.nome_normalizzato AS company_name,
                   c.cf               AS cf,
                   c.risk_score       AS risk_score,
                   c.ateco            AS ateco
            ORDER BY c.risk_score DESC
            LIMIT 20
            """,
            {"ateco2": src_ateco2, "source_id": source["company_id"]},
        )

        results: List[Recommendation] = []
        for row in rows:
            score = float(row.get("risk_score") or 0.0)
            results.append(
                Recommendation(
                    company_id=row["company_id"],
                    company_name=row.get("company_name") or row.get("cf") or row["company_id"],
                    cf=row.get("cf") or "",
                    risk_score=score,
                    similarity_score=round(score, 4),   # trending = ranked by own risk
                    reason=(
                        f"Trending risk in sector ATECO {row.get('ateco') or src_ateco2} "
                        f"(risk score {score:.2f})."
                    ),
                    strategies=["sector_trending"],
                    shared_features=[f"ATECO:{src_ateco2}"],
                )
            )
        return results

    # ── helper: fetch source company ─────────────────────────────────────────

    def _get_company_info(self, company_id: str) -> Optional[Dict[str, Any]]:
        rows = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.id = $cid OR c.cf = $cid
            RETURN c.id               AS company_id,
                   c.cf               AS cf,
                   c.nome_normalizzato AS company_name,
                   coalesce(c.risk_score, 0.0)   AS risk_score,
                   c.anomaly_flags    AS anomaly_flags,
                   c.community_id     AS community_id,
                   c.ateco            AS ateco,
                   c.regione          AS regione
            LIMIT 1
            """,
            {"cid": company_id},
        )
        return dict(rows[0]) if rows else None


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication helper
# ─────────────────────────────────────────────────────────────────────────────

def _merge(
    registry: Dict[str, Recommendation],
    incoming: Recommendation,
    strategy: str,
) -> None:
    """
    Merge *incoming* into *registry* (keyed by company_id).

    - If the company is new: add it.
    - If already present: keep the higher similarity_score, union the
      strategy list and shared_features, and combine reasons.
    """
    key = incoming.company_id

    if key not in registry:
        # Clone to avoid mutating the original strategy list
        registry[key] = Recommendation(
            company_id=incoming.company_id,
            company_name=incoming.company_name,
            cf=incoming.cf,
            risk_score=incoming.risk_score,
            similarity_score=incoming.similarity_score,
            reason=incoming.reason,
            strategies=list(incoming.strategies),
            shared_features=list(incoming.shared_features),
        )
        return

    existing = registry[key]
    # Keep the best similarity score
    existing.similarity_score = max(existing.similarity_score, incoming.similarity_score)
    # Accumulate strategy labels
    if strategy not in existing.strategies:
        existing.strategies.append(strategy)
    # Accumulate shared features (deduplicated)
    for feat in incoming.shared_features:
        if feat not in existing.shared_features:
            existing.shared_features.append(feat)
    # Combine reasons if they differ
    if incoming.reason not in existing.reason:
        existing.reason = existing.reason.rstrip(".") + "; " + incoming.reason
