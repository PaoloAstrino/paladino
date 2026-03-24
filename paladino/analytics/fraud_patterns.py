"""
Fraud Pattern Library
=====================
Ten named, explainable fraud detectors for Italian public procurement data.

Each detector:
  - Runs one or more Cypher queries against the live Neo4j graph
  - Creates a ``FraudPattern`` node for every match found
  - Creates ``FLAGGED_BY`` edges from Company/Tender/Buyer → FraudPattern
  - Returns a list of detection dicts for logging / reporting

Design principles
-----------------
- **Explainability first**: every finding is stored with an ``evidence_summary``
  (JSON) and a human-readable ``description`` so analysts can follow the chain.
- **Single responsibility**: each ``detect_*`` method can be called, tested
  and disabled independently.
- **Graph-native**: patterns are persisted as first-class nodes, not just
  in-memory flags, so they are queryable by the GraphRAG agent.
- **Non-destructive**: detectors never delete or overwrite existing nodes;
  they only create new ``FraudPattern`` nodes and edges.

Usage
-----
    from paladino.db import Neo4jConnection
    from paladino.analytics.fraud_patterns import FraudPatternLibrary

    conn = Neo4jConnection()
    lib = FraudPatternLibrary(conn)
    results = lib.run_all_detectors()
    conn.close()
"""

import json
import uuid
from datetime import UTC, datetime

from loguru import logger

from paladino.constants import (
    BOARD_OVERLAP_MIN_SHARED,
    FRAUD_BID_ROTATION_MIN_OCCURRENCES,
    FRAUD_BID_ROTATION_WINDOW_DAYS,
    FRAUD_COMMUNITY_MIN_TENDERS,
    FRAUD_COMMUNITY_MONOPOLY_RATIO,
    FRAUD_GHOST_BIDDER_MIN_TENDERS,
    FRAUD_NETWORK_CLIQUE_TRIANGLE_THRESHOLD,
    FRAUD_PATTERN_RISK_CONTRIBUTION,
    FRAUD_PNRR_CONCENTRATION_RATIO,
    FRAUD_PNRR_MIN_WINS,
    FRAUD_PRICE_MIN_SECTOR_SAMPLES,
    FRAUD_PRICE_ZSCORE_THRESHOLD,
    FRAUD_SHORT_AWARD_DAYS,
    FRAUD_SPLIT_TENDER_MIN_COUNT,
    FRAUD_SPLIT_TENDER_THRESHOLD_EUR,
    FRAUD_SPLIT_TENDER_WINDOW_DAYS,
    FRAUD_UBO_MAX_DEPTH,
    FRAUD_WINNER_LOSER_PAIR_MIN,
    SUBCONTRACTOR_CONCENTRATION_MAX,
)
from paladino.db import Neo4jConnection


class FraudPatternLibrary:
    """
    Collection of 10 graph-pattern fraud detectors for public procurement.

    Detected patterns (FRAUD_PATTERN_NAMES):
      bid_rotation         – same group of companies winning alternately
      ghost_bidding        – companies that only lose, providing false cover
      split_tendering      – buyer splits large contract below threshold
      short_award_window   – tender awarded suspiciously fast
      price_manipulation   – tender value far above sector median
      ubo_conflict         – winner and buyer share a beneficial owner
      winner_loser_ring    – recurring (winner, loser) pairs across tenders
      pnrr_concentration   – one company monopolises EU-funded tenders
      community_monopoly   – one entity dominates a Louvain community
      network_clique       – dense triangle mesh signals collusion ring
    """

    SEVERITY_ORDER = ["low", "medium", "high", "critical"]

    def __init__(self, conn: Neo4jConnection):
        self.conn = conn
        self.run_id: str = str(uuid.uuid4())
        self._run_started_at: datetime = datetime.now(UTC)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    def _create_fraud_pattern_node(
        self,
        pattern_name: str,
        severity: str,
        description: str,
        evidence: dict,
        affected_entity_ids: list[str] | None = None,
    ) -> str:
        """
        Persist a FraudPattern node in Neo4j and return its ID.

        Parameters
        ----------
        pattern_name : str
            One of the canonical keys from FRAUD_PATTERN_NAMES.
        severity : str
            "low" | "medium" | "high" | "critical"
        description : str
            Human-readable explanation of the pattern.
        evidence : dict
            Key metrics / entity references that justify the flag.
        affected_entity_ids : list[str], optional
            IDs of nodes that will be connected via FLAGGED_BY.

        Returns
        -------
        str : UUID of the new FraudPattern node.
        """
        pattern_id = str(uuid.uuid4())
        self.conn.run_query(
            """
            CREATE (f:FraudPattern {
                id:                   $id,
                pattern_name:         $pattern_name,
                severity:             $severity,
                description:          $description,
                evidence_summary:     $evidence_summary,
                detected_at:          $detected_at,
                run_id:               $run_id,
                affected_entity_ids:  $affected_entity_ids
            })
            """,
            {
                "id": pattern_id,
                "pattern_name": pattern_name,
                "severity": severity,
                "description": description,
                "evidence_summary": json.dumps(evidence, default=str),
                "detected_at": self._now_iso(),
                "run_id": self.run_id,
                "affected_entity_ids": affected_entity_ids or [],
            },
        )
        return pattern_id

    def _link_entity_to_pattern(
        self,
        entity_id: str,
        entity_label: str,
        pattern_id: str,
        score: float,
        evidence_snippet: dict,
    ) -> None:
        """
        Create a FLAGGED_BY edge from an entity node to a FraudPattern node.

        Parameters
        ----------
        entity_id : str
            The ``id`` property of the entity (Company/Tender/Buyer).
        entity_label : str
            Neo4j label: "Company", "Tender", or "Buyer".
        pattern_id : str
            UUID of the FraudPattern node.
        score : float
            0.0-1.0 severity contribution for this specific entity.
        evidence_snippet : dict
            Entity-specific evidence (metrics, counterpart IDs, etc.).
        """
        self.conn.run_query(
            f"""
            MATCH (e:{entity_label} {{id: $entity_id}})
            MATCH (f:FraudPattern {{id: $pattern_id}})
            CREATE (e)-[:FLAGGED_BY {{
                detected_at: $detected_at,
                score:       $score,
                evidence:    $evidence
            }}]->(f)
            """,
            {
                "entity_id": entity_id,
                "pattern_id": pattern_id,
                "detected_at": self._now_iso(),
                "score": min(1.0, max(0.0, score)),
                "evidence": json.dumps(evidence_snippet, default=str),
            },
        )

    def _bump_entity_risk_score(self, entity_id: str, entity_label: str, severity: str) -> None:
        """
        Increment a Company or Buyer risk_score by the fraud severity contribution.
        Caps score at 1.0 and appends the pattern name to anomaly_flags.
        """
        delta = FRAUD_PATTERN_RISK_CONTRIBUTION.get(severity, 0.0)
        self.conn.run_query(
            f"""
            MATCH (e:{entity_label} {{id: $entity_id}})
            SET e.risk_score = CASE
                    WHEN coalesce(e.risk_score, 0.0) + $delta > 1.0 THEN 1.0
                    ELSE coalesce(e.risk_score, 0.0) + $delta
                END,
                e.anomaly_flags = coalesce(e.anomaly_flags, []) + [$pattern]
            """,
            {"entity_id": entity_id, "delta": delta, "pattern": "fraud_library_flag"},
        )

    # ------------------------------------------------------------------
    # 1. Bid Rotation
    # ------------------------------------------------------------------

    def detect_bid_rotation(self) -> list[dict]:
        """
        Flag buyers where a small recurring group of companies take turns winning.

        Signal: same set of companies (≥3) win tenders from the same buyer at
        least ``FRAUD_BID_ROTATION_MIN_OCCURRENCES`` times each within a rolling
        year.  Rotation is captured by comparing winner sets across successive
        awards.
        """
        logger.info("[ Fraud ] Running: Bid Rotation detector...")
        detections: list[dict] = []

        results = self.conn.run_query(
            """
            MATCH (b:Buyer)-[:ISSUES]->(t:Tender)<-[:WINS]-(c:Company)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({days: $window_days})
            WITH b, c,
                 count(t) AS wins,
                 collect(t.id)[..5] AS sample_tenders
            WHERE wins >= $min_occurrences
            WITH b,
                 collect({company_id: c.id, company_name: c.nome_normalizzato, wins: wins,
                          sample_tenders: sample_tenders}) AS rotation_group,
                 sum(wins) AS total_wins
            WHERE size(rotation_group) >= 2
            RETURN b.id            AS buyer_id,
                   b.nome          AS buyer_name,
                   rotation_group,
                   total_wins
            ORDER BY total_wins DESC
            LIMIT 50
            """,
            {
                "min_occurrences": FRAUD_BID_ROTATION_MIN_OCCURRENCES,
                "window_days": FRAUD_BID_ROTATION_WINDOW_DAYS,
            },
        )

        for row in results:
            evidence = {
                "buyer_id": row["buyer_id"],
                "buyer_name": row["buyer_name"],
                "rotation_group": row["rotation_group"],
                "total_wins": row["total_wins"],
            }
            affected_ids = [r["company_id"] for r in row["rotation_group"]]

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="bid_rotation",
                severity="high",
                description=(
                    f"Buyer '{row['buyer_name']}' shows bid rotation: {len(row['rotation_group'])} "
                    f"companies repeatedly alternate winning tenders "
                    f"({FRAUD_BID_ROTATION_MIN_OCCURRENCES}+ wins each, {row['total_wins']} total)."
                ),
                evidence=evidence,
                affected_entity_ids=affected_ids,
            )

            for company_rec in row["rotation_group"]:
                self._link_entity_to_pattern(
                    entity_id=company_rec["company_id"],
                    entity_label="Company",
                    pattern_id=pattern_id,
                    score=0.7,
                    evidence_snippet={"wins": company_rec["wins"], "buyer_id": row["buyer_id"]},
                )
                self._bump_entity_risk_score(company_rec["company_id"], "Company", "high")

            detections.append(
                {
                    "pattern": "bid_rotation",
                    "buyer": row["buyer_name"],
                    "companies": len(affected_ids),
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Bid Rotation: {len(detections)} buyer(s) flagged.")
        return detections

    # ------------------------------------------------------------------
    # 2. Ghost Bidding
    # ------------------------------------------------------------------

    def detect_ghost_bidding(self) -> list[dict]:
        """
        Flag companies that appear as participants many times but NEVER win.

        These "ghost bidders" provide artificial competition to make
        single-bidder tenders look contested.  We approximate participation
        by looking at tenders where the same buyer repeatedly selects a
        different company while our ghost is structurally close (same community).
        """
        logger.info("[ Fraud ] Running: Ghost Bidding detector...")
        detections: list[dict] = []

        # A ghost bidder: company in many tenders' communities that never wins
        results = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE NOT (c)-[:WINS]->(:Tender)
              AND c.community_id IS NOT NULL
            WITH c
            MATCH (winner:Company)-[:WINS]->(t:Tender)
            WHERE winner.community_id = c.community_id
            WITH c,
                 count(DISTINCT t) AS community_tenders,
                 collect(DISTINCT winner.id)[..5] AS winner_samples
            WHERE community_tenders >= $min_tenders
            RETURN c.id            AS ghost_id,
                   c.nome_normalizzato AS ghost_name,
                   c.community_id  AS community,
                   community_tenders,
                   winner_samples
            ORDER BY community_tenders DESC
            LIMIT 30
            """,
            {"min_tenders": FRAUD_GHOST_BIDDER_MIN_TENDERS},
        )

        for row in results:
            evidence = {
                "ghost_company_id": row["ghost_id"],
                "ghost_company_name": row["ghost_name"],
                "community_id": row["community"],
                "community_tenders": row["community_tenders"],
                "co_community_winners": row["winner_samples"],
            }

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="ghost_bidding",
                severity="medium",
                description=(
                    f"'{row['ghost_name']}' belongs to a procurement community "
                    f"with {row['community_tenders']} tender(s) but has ZERO wins. "
                    "May be acting as a cover bidder."
                ),
                evidence=evidence,
                affected_entity_ids=[row["ghost_id"]],
            )

            self._link_entity_to_pattern(
                entity_id=row["ghost_id"],
                entity_label="Company",
                pattern_id=pattern_id,
                score=0.5,
                evidence_snippet={"community_tenders": row["community_tenders"]},
            )
            self._bump_entity_risk_score(row["ghost_id"], "Company", "medium")

            detections.append(
                {
                    "pattern": "ghost_bidding",
                    "company": row["ghost_name"],
                    "community_tenders": row["community_tenders"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Ghost Bidding: {len(detections)} company/ies flagged.")
        return detections

    # ------------------------------------------------------------------
    # 3. Split Tendering (Frazionamento)
    # ------------------------------------------------------------------

    def detect_split_tendering(self) -> list[dict]:
        """
        Flag buyers that issue many low-value tenders to the same company close
        in time, effectively splitting a larger contract to stay below the EU
        procurement notification threshold (default: €40,000).
        """
        logger.info("[ Fraud ] Running: Split Tendering (Frazionamento) detector...")
        detections: list[dict] = []

        results = self.conn.run_query(
            """
            MATCH (b:Buyer)-[:ISSUES]->(t:Tender)<-[:WINS]-(c:Company)
            WHERE t.importo IS NOT NULL
              AND t.importo < $threshold
              AND t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({days: $window_days})
            WITH b, c,
                 count(t)           AS tender_count,
                 sum(t.importo)     AS total_value,
                 collect(t.id)[..5] AS sample_tenders
            WHERE tender_count >= $min_count
            RETURN b.id        AS buyer_id,
                   b.nome      AS buyer_name,
                   c.id        AS company_id,
                   c.nome_normalizzato AS company_name,
                   tender_count,
                   total_value,
                   sample_tenders
            ORDER BY tender_count DESC
            LIMIT 50
            """,
            {
                "threshold": FRAUD_SPLIT_TENDER_THRESHOLD_EUR,
                "min_count": FRAUD_SPLIT_TENDER_MIN_COUNT,
                "window_days": FRAUD_SPLIT_TENDER_WINDOW_DAYS,
            },
        )

        for row in results:
            evidence = {
                "buyer_id": row["buyer_id"],
                "buyer_name": row["buyer_name"],
                "company_id": row["company_id"],
                "company_name": row["company_name"],
                "tender_count": row["tender_count"],
                "total_value": row["total_value"],
                "threshold_eur": FRAUD_SPLIT_TENDER_THRESHOLD_EUR,
                "sample_cigs": row["sample_tenders"],
            }

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="split_tendering",
                severity="high",
                description=(
                    f"Buyer '{row['buyer_name']}' issued {row['tender_count']} tenders "
                    f"(each <€{FRAUD_SPLIT_TENDER_THRESHOLD_EUR:,.0f}) to '{row['company_name']}', "
                    f"totalling €{row['total_value']:,.2f}. Possible contract splitting."
                ),
                evidence=evidence,
                affected_entity_ids=[row["buyer_id"], row["company_id"]],
            )

            for entity_id, label in [(row["buyer_id"], "Buyer"), (row["company_id"], "Company")]:
                self._link_entity_to_pattern(
                    entity_id=entity_id,
                    entity_label=label,
                    pattern_id=pattern_id,
                    score=0.75,
                    evidence_snippet={
                        "tender_count": row["tender_count"],
                        "total_value": row["total_value"],
                    },
                )
            self._bump_entity_risk_score(row["company_id"], "Company", "high")

            detections.append(
                {
                    "pattern": "split_tendering",
                    "buyer": row["buyer_name"],
                    "company": row["company_name"],
                    "count": row["tender_count"],
                    "total": row["total_value"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Split Tendering: {len(detections)} pair(s) flagged.")
        return detections

    # ------------------------------------------------------------------
    # 4. Short Award Window
    # ------------------------------------------------------------------

    def detect_short_award_window(self) -> list[dict]:
        """
        Flag tenders where the award was issued suspiciously quickly after
        publication (fewer than ``FRAUD_SHORT_AWARD_DAYS`` days).

        Extremely short award windows suggest the winner was predetermined
        and the tender was published only as a formality.
        """
        logger.info("[ Fraud ] Running: Short Award Window detector...")
        detections: list[dict] = []

        results = self.conn.run_query(
            """
            MATCH (c:Company)-[:WINS]->(t:Tender)<-[:ISSUES]-(b:Buyer)
            WHERE t.data_apertura IS NOT NULL
              AND t.data_aggiudicazione IS NOT NULL
              AND duration.between(t.data_apertura, t.data_aggiudicazione).days < $max_days
              AND duration.between(t.data_apertura, t.data_aggiudicazione).days >= 0
            RETURN t.id              AS tender_id,
                   t.cig             AS cig,
                   t.oggetto         AS oggetto,
                   t.importo         AS importo,
                   c.id              AS company_id,
                   c.nome_normalizzato AS company_name,
                   b.id              AS buyer_id,
                   b.nome            AS buyer_name,
                   duration.between(t.data_apertura, t.data_aggiudicazione).days AS award_days
            ORDER BY award_days ASC
            LIMIT 100
            """,
            {"max_days": FRAUD_SHORT_AWARD_DAYS},
        )

        for row in results:
            evidence = {
                "tender_id": row["tender_id"],
                "cig": row["cig"],
                "importo_eur": row["importo"],
                "award_days": row["award_days"],
                "company": row["company_name"],
                "buyer": row["buyer_name"],
            }
            severity = "critical" if row["award_days"] <= 1 else "high"

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="short_award_window",
                severity=severity,
                description=(
                    f"Tender '{row['cig']}' (€{row['importo']:,.2f}) was awarded "
                    f"only {row['award_days']} day(s) after publication. "
                    f"Winner: '{row['company_name']}'. Buyer: '{row['buyer_name']}'."
                ),
                evidence=evidence,
                affected_entity_ids=[row["tender_id"], row["company_id"]],
            )

            for entity_id, label in [
                (row["tender_id"], "Tender"),
                (row["company_id"], "Company"),
            ]:
                self._link_entity_to_pattern(
                    entity_id=entity_id,
                    entity_label=label,
                    pattern_id=pattern_id,
                    score=0.8 if severity == "critical" else 0.6,
                    evidence_snippet={"award_days": row["award_days"]},
                )

            self._bump_entity_risk_score(row["company_id"], "Company", severity)

            # Mark tender itself
            self.conn.run_query(
                """
                MATCH (t:Tender {id: $tid})
                SET t.red_flags = coalesce(t.red_flags, []) + ['short_award_window']
                """,
                {"tid": row["tender_id"]},
            )

            detections.append(
                {
                    "pattern": "short_award_window",
                    "cig": row["cig"],
                    "days": row["award_days"],
                    "company": row["company_name"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Short Award Window: {len(detections)} tender(s) flagged.")
        return detections

    # ------------------------------------------------------------------
    # 5. Price Manipulation
    # ------------------------------------------------------------------

    def detect_price_manipulation(self) -> list[dict]:
        """
        Flag tenders whose awarded value is significantly above the median for
        the same ATECO sector, suggesting inflated pricing.

        Uses a simple z-score computed inside Cypher.  Requires at least
        ``FRAUD_PRICE_MIN_SECTOR_SAMPLES`` tenders in the same sector.
        """
        logger.info("[ Fraud ] Running: Price Manipulation (z-score) detector...")
        detections: list[dict] = []

        results = self.conn.run_query(
            """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE c.ateco IS NOT NULL AND t.importo IS NOT NULL
            WITH c.ateco AS sector,
                 collect({tender_id: t.id, cig: t.cig, importo: t.importo,
                          company_id: c.id, company_name: c.nome_normalizzato}) AS tenders
            WHERE size(tenders) >= $min_samples
            WITH sector, tenders,
                 reduce(s = 0.0, x IN tenders | s + x.importo) / size(tenders) AS mean_val
            WITH sector, tenders, mean_val,
                 sqrt(reduce(s = 0.0, x IN tenders |
                      s + (x.importo - mean_val)^2) / size(tenders)) AS std_val
            WHERE std_val > 0
            UNWIND tenders AS t
            WITH sector, t, mean_val, std_val,
                 (t.importo - mean_val) / std_val AS z_score
            WHERE z_score > $z_threshold
            RETURN sector,
                   t.tender_id    AS tender_id,
                   t.cig          AS cig,
                   t.importo      AS importo,
                   t.company_id   AS company_id,
                   t.company_name AS company_name,
                   mean_val,
                   std_val,
                   z_score
            ORDER BY z_score DESC
            LIMIT 50
            """,
            {
                "min_samples": FRAUD_PRICE_MIN_SECTOR_SAMPLES,
                "z_threshold": FRAUD_PRICE_ZSCORE_THRESHOLD,
            },
        )

        for row in results:
            evidence = {
                "sector": row["sector"],
                "cig": row["cig"],
                "importo_eur": row["importo"],
                "sector_mean": round(row["mean_val"], 2),
                "sector_std": round(row["std_val"], 2),
                "z_score": round(row["z_score"], 3),
                "company": row["company_name"],
            }
            severity = "critical" if row["z_score"] > 4.0 else "high"

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="price_manipulation",
                severity=severity,
                description=(
                    f"Tender '{row['cig']}' value €{row['importo']:,.2f} "
                    f"is {row['z_score']:.1f}σ above the sector '{row['sector']}' median "
                    f"(€{row['mean_val']:,.2f}). Possible inflated pricing."
                ),
                evidence=evidence,
                affected_entity_ids=[row["tender_id"], row["company_id"]],
            )

            for entity_id, label in [
                (row["tender_id"], "Tender"),
                (row["company_id"], "Company"),
            ]:
                self._link_entity_to_pattern(
                    entity_id=entity_id,
                    entity_label=label,
                    pattern_id=pattern_id,
                    score=min(1.0, row["z_score"] / 5.0),
                    evidence_snippet={"z_score": round(row["z_score"], 3)},
                )

            self._bump_entity_risk_score(row["company_id"], "Company", severity)
            self.conn.run_query(
                "MATCH (t:Tender {id: $tid}) SET t.red_flags = coalesce(t.red_flags, []) + ['price_manipulation']",
                {"tid": row["tender_id"]},
            )

            detections.append(
                {
                    "pattern": "price_manipulation",
                    "cig": row["cig"],
                    "z_score": round(row["z_score"], 2),
                    "sector": row["sector"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Price Manipulation: {len(detections)} tender(s) flagged.")
        return detections

    # ------------------------------------------------------------------
    # 6. UBO / Ownership Conflict
    # ------------------------------------------------------------------

    def detect_ubo_conflict(self) -> list[dict]:
        """
        Flag tenders where winner and issuing buyer share a beneficial owner
        (up to ``FRAUD_UBO_MAX_DEPTH`` ownership levels deep).

        Self-awarded contracts or family/corporate ties between buyer and winner
        are a critical integrity red flag.
        """
        logger.info("[ Fraud ] Running: UBO Conflict detector...")
        detections: list[dict] = []

        results = self.conn.run_query(
            f"""
            MATCH (winner:Company)-[:WINS]->(t:Tender)<-[:ISSUES]-(b:Buyer)
            MATCH (winner)-[:SHARES_UBO*1..{FRAUD_UBO_MAX_DEPTH}]->(shared:Company)
            WHERE shared.cf = b.cf OR shared.piva = b.cf
            RETURN winner.id            AS company_id,
                   winner.nome_normalizzato AS company_name,
                   b.id                 AS buyer_id,
                   b.nome               AS buyer_name,
                   shared.id            AS shared_entity_id,
                   shared.nome_normalizzato AS shared_name,
                   t.id                 AS tender_id,
                   t.cig                AS cig,
                   t.importo            AS importo
            LIMIT 50
            """
        )

        for row in results:
            evidence = {
                "company": row["company_name"],
                "buyer": row["buyer_name"],
                "shared_entity": row["shared_name"],
                "cig": row["cig"],
                "importo_eur": row["importo"],
            }

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="ubo_conflict",
                severity="critical",
                description=(
                    f"Winner '{row['company_name']}' and buyer '{row['buyer_name']}' "
                    f"share a beneficial owner ('{row['shared_name']}') on tender '{row['cig']}' "
                    f"(€{row['importo']:,.2f}). Possible self-award."
                ),
                evidence=evidence,
                affected_entity_ids=[row["company_id"], row["buyer_id"], row["tender_id"]],
            )

            for entity_id, label in [
                (row["company_id"], "Company"),
                (row["tender_id"], "Tender"),
            ]:
                self._link_entity_to_pattern(
                    entity_id=entity_id,
                    entity_label=label,
                    pattern_id=pattern_id,
                    score=1.0,
                    evidence_snippet={"shared_entity": row["shared_name"]},
                )

            self._bump_entity_risk_score(row["company_id"], "Company", "critical")

            detections.append(
                {
                    "pattern": "ubo_conflict",
                    "company": row["company_name"],
                    "buyer": row["buyer_name"],
                    "cig": row["cig"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] UBO Conflict: {len(detections)} case(s) flagged.")
        return detections

    # ------------------------------------------------------------------
    # 7. Winner-Loser Collusion Ring
    # ------------------------------------------------------------------

    def detect_winner_loser_ring(self) -> list[dict]:
        """
        Flag recurring (winner, loser-community-peer) pairs across tenders of
        the same buyer.

        A collusion ring is indicated when the same small group of companies
        repeatedly appear together in the same buyer's tenders with one company
        always winning and the others always absent from winners.
        """
        logger.info("[ Fraud ] Running: Winner-Loser Ring detector...")
        detections: list[dict] = []

        results = self.conn.run_query(
            """
            MATCH (winner:Company)-[:WINS]->(t:Tender)<-[:ISSUES]-(b:Buyer)
            MATCH (peer:Company)
            WHERE peer.community_id = winner.community_id
              AND peer.id <> winner.id
              AND NOT (peer)-[:WINS]->(t)
            WITH winner, peer, b,
                 count(DISTINCT t) AS co_appearances
            WHERE co_appearances >= $min_pairs
            RETURN winner.id            AS winner_id,
                   winner.nome_normalizzato AS winner_name,
                   peer.id              AS peer_id,
                   peer.nome_normalizzato AS peer_name,
                   b.id                 AS buyer_id,
                   b.nome               AS buyer_name,
                   co_appearances
            ORDER BY co_appearances DESC
            LIMIT 30
            """,
            {"min_pairs": FRAUD_WINNER_LOSER_PAIR_MIN},
        )

        for row in results:
            evidence = {
                "winner": row["winner_name"],
                "loser_peer": row["peer_name"],
                "buyer": row["buyer_name"],
                "co_appearances": row["co_appearances"],
            }

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="winner_loser_ring",
                severity="high",
                description=(
                    f"'{row['winner_name']}' and '{row['peer_name']}' are in the same procurement "
                    f"community and appeared together in {row['co_appearances']} tender(s) of "
                    f"'{row['buyer_name']}' where '{row['winner_name']}' always won. "
                    "Possible collusion ring."
                ),
                evidence=evidence,
                affected_entity_ids=[row["winner_id"], row["peer_id"]],
            )

            for entity_id in [row["winner_id"], row["peer_id"]]:
                self._link_entity_to_pattern(
                    entity_id=entity_id,
                    entity_label="Company",
                    pattern_id=pattern_id,
                    score=0.7,
                    evidence_snippet={"co_appearances": row["co_appearances"]},
                )
                self._bump_entity_risk_score(entity_id, "Company", "high")

            detections.append(
                {
                    "pattern": "winner_loser_ring",
                    "winner": row["winner_name"],
                    "peer": row["peer_name"],
                    "appearances": row["co_appearances"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Winner-Loser Ring: {len(detections)} pair(s) flagged.")
        return detections

    # ------------------------------------------------------------------
    # 8. PNRR Fund Concentration
    # ------------------------------------------------------------------

    def detect_pnrr_concentration(self) -> list[dict]:
        """
        Flag companies that win a disproportionately large share of EU-funded
        (PNRR, FESR, FSE) tenders relative to all companies in their region.

        EU-funded procurement is higher-value and more closely scrutinised;
        concentration signals potential favouritism or collusion with PA.
        """
        logger.info("[ Fraud ] Running: PNRR Concentration detector...")
        detections: list[dict] = []

        results = self.conn.run_query(
            """
            // Count PNRR-linked tender wins per company
            MATCH (c:Company)-[:WINS]->(t:Tender)-[:PART_OF_PROJECT]->(p:Project)
                  -[:FUNDED_BY]->(f:FundingSource)
            WHERE f.tipo IN ['PNRR', 'FESR', 'FSE']
            WITH c,
                 count(DISTINCT t) AS pnrr_wins,
                 sum(t.importo)     AS pnrr_value,
                 c.regione          AS region
            WHERE pnrr_wins >= $min_wins

            // Get total PNRR wins in the same region
            MATCH (all:Company)-[:WINS]->(rt:Tender)-[:PART_OF_PROJECT]->(rp:Project)
                  -[:FUNDED_BY]->(rf:FundingSource)
            WHERE rf.tipo IN ['PNRR', 'FESR', 'FSE']
              AND all.regione = region
            WITH c, pnrr_wins, pnrr_value, region,
                 count(DISTINCT rt) AS regional_pnrr_total
            WHERE regional_pnrr_total > 0
            WITH c, pnrr_wins, pnrr_value, region, regional_pnrr_total,
                 toFloat(pnrr_wins) / regional_pnrr_total AS concentration_ratio
            WHERE concentration_ratio >= $min_ratio

            RETURN c.id              AS company_id,
                   c.nome_normalizzato AS company_name,
                   region,
                   pnrr_wins,
                   pnrr_value,
                   regional_pnrr_total,
                   concentration_ratio
            ORDER BY concentration_ratio DESC
            LIMIT 30
            """,
            {
                "min_wins": FRAUD_PNRR_MIN_WINS,
                "min_ratio": FRAUD_PNRR_CONCENTRATION_RATIO,
            },
        )

        for row in results:
            evidence = {
                "company": row["company_name"],
                "region": row["region"],
                "pnrr_wins": row["pnrr_wins"],
                "pnrr_value_eur": row["pnrr_value"],
                "regional_total": row["regional_pnrr_total"],
                "concentration_ratio": round(row["concentration_ratio"], 3),
            }
            severity = "critical" if row["concentration_ratio"] >= 0.8 else "high"

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="pnrr_concentration",
                severity=severity,
                description=(
                    f"'{row['company_name']}' holds {row['concentration_ratio'] * 100:.1f}% "
                    f"of EU-funded (PNRR/FESR/FSE) tender wins in region '{row['region']}' "
                    f"({row['pnrr_wins']} wins, €{row['pnrr_value']:,.2f})."
                ),
                evidence=evidence,
                affected_entity_ids=[row["company_id"]],
            )

            self._link_entity_to_pattern(
                entity_id=row["company_id"],
                entity_label="Company",
                pattern_id=pattern_id,
                score=min(1.0, row["concentration_ratio"]),
                evidence_snippet={
                    "pnrr_wins": row["pnrr_wins"],
                    "concentration_ratio": round(row["concentration_ratio"], 3),
                },
            )
            self._bump_entity_risk_score(row["company_id"], "Company", severity)

            detections.append(
                {
                    "pattern": "pnrr_concentration",
                    "company": row["company_name"],
                    "ratio": round(row["concentration_ratio"], 2),
                    "region": row["region"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] PNRR Concentration: {len(detections)} company/ies flagged.")
        return detections

    # ------------------------------------------------------------------
    # 9. Community Monopoly
    # ------------------------------------------------------------------

    def detect_community_monopoly(self) -> list[dict]:
        """
        Flag Louvain communities where a single company controls an
        outsized share of total tender spend.

        Near-monopoly within a community (≥70% of community value)
        indicates barrier-to-entry behaviour or market carving.
        """
        logger.info("[ Fraud ] Running: Community Monopoly detector...")
        detections: list[dict] = []

        results = self.conn.run_query(
            """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE c.community_id IS NOT NULL AND t.importo IS NOT NULL
            WITH c.community_id AS community,
                 c,
                 count(t)       AS wins,
                 sum(t.importo) AS company_value
            WITH community,
                 collect({company_id: c.id, company_name: c.nome_normalizzato,
                          wins: wins, value: company_value}) AS members,
                 sum(company_value) AS community_total
            WHERE community_total > 0 AND size(members) >= 2
            UNWIND members AS m
            WITH community, m, community_total,
                 toFloat(m.value) / community_total AS share
            WHERE share >= $monopoly_ratio
              AND m.wins >= $min_tenders
            RETURN community,
                   m.company_id   AS company_id,
                   m.company_name AS company_name,
                   m.wins         AS wins,
                   m.value        AS company_value,
                   community_total,
                   share
            ORDER BY share DESC
            LIMIT 20
            """,
            {
                "monopoly_ratio": FRAUD_COMMUNITY_MONOPOLY_RATIO,
                "min_tenders": FRAUD_COMMUNITY_MIN_TENDERS,
            },
        )

        for row in results:
            evidence = {
                "community_id": row["community"],
                "company": row["company_name"],
                "company_wins": row["wins"],
                "company_value": row["company_value"],
                "community_total": row["community_total"],
                "share": round(row["share"], 3),
            }

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="community_monopoly",
                severity="high",
                description=(
                    f"'{row['company_name']}' controls {row['share'] * 100:.1f}% of spend in "
                    f"Louvain community #{row['community']} "
                    f"(€{row['company_value']:,.2f} of €{row['community_total']:,.2f} total)."
                ),
                evidence=evidence,
                affected_entity_ids=[row["company_id"]],
            )

            self._link_entity_to_pattern(
                entity_id=row["company_id"],
                entity_label="Company",
                pattern_id=pattern_id,
                score=min(1.0, row["share"]),
                evidence_snippet={"share": round(row["share"], 3), "wins": row["wins"]},
            )
            self._bump_entity_risk_score(row["company_id"], "Company", "high")

            detections.append(
                {
                    "pattern": "community_monopoly",
                    "company": row["company_name"],
                    "community": row["community"],
                    "share": round(row["share"], 2),
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Community Monopoly: {len(detections)} case(s) flagged.")
        return detections

    # ------------------------------------------------------------------
    # 10. Dense Collusion Network (Triangle Count)
    # ------------------------------------------------------------------

    def detect_network_clique(self) -> list[dict]:
        """
        Flag companies whose GDS triangle count suggests participation in a
        dense collusion sub-graph.

        High triangle count means a company is part of many closed triads in
        the procurement network (Company ↔ Buyer ↔ Company ↔ Tender ↔ …),
        a structural fingerprint of organised bid-rigging.
        Requires GDS to have already written ``triangle_count``.
        """
        logger.info("[ Fraud ] Running: Dense Collusion Network (Triangle) detector...")
        detections: list[dict] = []

        results = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.triangle_count IS NOT NULL
              AND c.triangle_count >= $threshold
            RETURN c.id              AS company_id,
                   c.nome_normalizzato AS company_name,
                   c.triangle_count  AS triangles,
                   c.community_id    AS community,
                   c.risk_score      AS current_risk
            ORDER BY c.triangle_count DESC
            LIMIT 30
            """,
            {"threshold": FRAUD_NETWORK_CLIQUE_TRIANGLE_THRESHOLD},
        )

        for row in results:
            evidence = {
                "company": row["company_name"],
                "triangle_count": row["triangles"],
                "community_id": row["community"],
                "current_risk": row["current_risk"],
            }

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="network_clique",
                severity="high",
                description=(
                    f"'{row['company_name']}' participates in {row['triangles']} triangle(s) "
                    "in the procurement network graph. Dense triadic closure is a structural "
                    "indicator of organised bid-rigging."
                ),
                evidence=evidence,
                affected_entity_ids=[row["company_id"]],
            )

            self._link_entity_to_pattern(
                entity_id=row["company_id"],
                entity_label="Company",
                pattern_id=pattern_id,
                score=min(1.0, row["triangles"] / 20.0),
                evidence_snippet={"triangle_count": row["triangles"]},
            )
            self._bump_entity_risk_score(row["company_id"], "Company", "high")

            detections.append(
                {
                    "pattern": "network_clique",
                    "company": row["company_name"],
                    "triangles": row["triangles"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Network Clique: {len(detections)} company/ies flagged.")
        return detections

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    # 11. Carousel Fraud (supply-chain cycles)
    # ------------------------------------------------------------------

    def detect_carousel_fraud(self) -> list[dict]:
        """
        Flag supply-chain cycles: A subcontracts B which subcontracts C … which
        subcontracts A.  Money flows in a circle, inflating invoices and
        laundering public funds.

        Detection strategy
        ------------------
        1. Prefer pre-computed ``supply_scc_id`` / ``supply_scc_size`` written by
           GDS SCC (fast, O(n+e)).
        2. Fallback to a variable-length path cycle query (slower, no GDS needed).

        If no SUBCONTRACTS_TO data exists at all, returns [] with a console hint.

        Severity: critical
        """
        logger.info("[ Fraud ] Running: Carousel Fraud detector…")

        # ── Check whether supply-chain data exists ──────────────────────────
        check = self.conn.run_query("MATCH ()-[r:SUBCONTRACTS_TO]->() RETURN count(r) AS n LIMIT 1")
        if not check or check[0]["n"] == 0:
            logger.warning(
                "[ Fraud ] No SUBCONTRACTS_TO edges found — carousel detector skipped.\n"
                "  → Run: python scripts/run_supply_chain_etl.py --step subcontractors"
            )
            return []

        # ── Try SCC first ───────────────────────────────────────────────────
        results = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.supply_scc_id IS NOT NULL AND c.supply_scc_size > 1
            WITH c.supply_scc_id AS scc_id, collect(c) AS members
            OPTIONAL MATCH (m1:Company)-[r:SUBCONTRACTS_TO]->(m2:Company)
            WHERE m1.supply_scc_id = scc_id AND m2.supply_scc_id = scc_id
            WITH scc_id, members,
                 [m IN members | m.id]               AS cycle_ids,
                 [m IN members | m.nome_normalizzato] AS cycle_names,
                 collect(r.cig)                       AS cigs
            WHERE size(cycle_ids) >= 3
            RETURN scc_id, cycle_ids, cycle_names, size(members) AS cycle_length, cigs
            ORDER BY cycle_length DESC
            LIMIT 20
            """
        )

        # ── Fallback to path query ──────────────────────────────────────────
        if not results:
            results = self.conn.run_query(
                """
                MATCH path = (start:Company)-[:SUBCONTRACTS_TO*3..6]->(start)
                WITH start,
                     [n IN nodes(path) | n.id]               AS cycle_ids,
                     [n IN nodes(path) | n.nome_normalizzato] AS cycle_names,
                     [r IN relationships(path) | r.cig]      AS cigs,
                     length(path)                             AS cycle_length
                WHERE size(apoc.coll.toSet(cycle_ids[0..-1])) = cycle_length
                RETURN null AS scc_id, cycle_ids, cycle_names, cycle_length, cigs
                ORDER BY cycle_length
                LIMIT 20
                """
            )

        detections: list[dict] = []
        for row in results:
            evidence = {
                "scc_id": row.get("scc_id"),
                "cycle_ids": row["cycle_ids"],
                "cycle_names": row["cycle_names"],
                "cycle_length": row["cycle_length"],
                "cigs": row["cigs"],
            }
            pattern_id = self._create_fraud_pattern_node(
                pattern_name="carousel_fraud",
                severity="critical",
                description=(
                    f"Supply-chain cycle of length {row['cycle_length']} detected "
                    f"involving companies: {', '.join(row['cycle_names'][:4])}. "
                    "Public funds may be circulating between connected entities "
                    "via subcontracting to inflate invoices."
                ),
                evidence=evidence,
                affected_entity_ids=row["cycle_ids"],
            )
            for cid in row["cycle_ids"]:
                self._link_entity_to_pattern(cid, "Company", pattern_id, 0.95, evidence)
                self._bump_entity_risk_score(cid, "Company", "critical")

            detections.append(
                {
                    "pattern": "carousel_fraud",
                    "cycle_length": row["cycle_length"],
                    "cycle_names": row["cycle_names"],
                    "cigs": row["cigs"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Carousel fraud: {len(detections)} cycle(s) found")
        return detections

    # ------------------------------------------------------------------
    # 12. Board Overlap Collusion
    # ------------------------------------------------------------------

    def detect_board_overlap_collusion(self) -> list[dict]:
        """
        Flag company pairs that share ≥ BOARD_OVERLAP_MIN_SHARED board members
        AND have both won tenders from the same buyer.

        Shared directors across competing firms is a classic collusion indicator:
        the firms appear independent but are coordinated by the same people.

        If no REPRESENTS edges exist, returns [] with a console hint rather than
        failing.

        Severity: high
        """
        logger.info("[ Fraud ] Running: Board Overlap Collusion detector…")

        check = self.conn.run_query("MATCH ()-[r:REPRESENTS]->() RETURN count(r) AS n LIMIT 1")
        if not check or check[0]["n"] == 0:
            logger.warning(
                "[ Fraud ] No REPRESENTS edges found — board overlap detector skipped.\n"
                "  → Drop director CSV files into data/corporate/raw/ and run:\n"
                "    python scripts/run_supply_chain_etl.py --step corporate"
            )
            return []

        results = self.conn.run_query(
            """
            // Pairs of companies that share board members
            MATCH (p:Person)-[:REPRESENTS]->(c1:Company)
            MATCH (p)-[:REPRESENTS]->(c2:Company)
            WHERE id(c1) < id(c2)
            WITH c1, c2, collect(DISTINCT p) AS shared_persons
            WHERE size(shared_persons) >= $min_shared

            // Both companies must have won at least one tender from the same buyer
            MATCH (c1)-[:WINS]->(t1:Tender)<-[:ISSUES]-(b:Buyer)
            MATCH (c2)-[:WINS]->(t2:Tender)<-[:ISSUES]-(b)

            RETURN
                c1.id                  AS company1_id,
                c1.nome_normalizzato   AS company1_name,
                c2.id                  AS company2_id,
                c2.nome_normalizzato   AS company2_name,
                b.id                   AS buyer_id,
                b.nome                 AS buyer_name,
                size(shared_persons)   AS shared_count,
                [p IN shared_persons | coalesce(p.cognome + ' ' + p.nome, p.cf)]
                                       AS shared_names
            ORDER BY shared_count DESC
            LIMIT 50
            """,
            {"min_shared": BOARD_OVERLAP_MIN_SHARED},
        )

        detections: list[dict] = []
        for row in results:
            evidence = {
                "company1": row["company1_name"],
                "company2": row["company2_name"],
                "buyer": row["buyer_name"],
                "shared_count": row["shared_count"],
                "shared_persons": row["shared_names"],
            }
            pattern_id = self._create_fraud_pattern_node(
                pattern_name="board_overlap_collusion",
                severity="high",
                description=(
                    f"'{row['company1_name']}' and '{row['company2_name']}' share "
                    f"{row['shared_count']} board member(s) and have both won tenders "
                    f"from buyer '{row['buyer_name']}'. "
                    "Shared leadership between competing bidders indicates coordinated bidding."
                ),
                evidence=evidence,
                affected_entity_ids=[row["company1_id"], row["company2_id"]],
            )
            for cid in [row["company1_id"], row["company2_id"]]:
                self._link_entity_to_pattern(cid, "Company", pattern_id, 0.75, evidence)
                self._bump_entity_risk_score(cid, "Company", "high")

            detections.append(
                {
                    "pattern": "board_overlap_collusion",
                    "company1": row["company1_name"],
                    "company2": row["company2_name"],
                    "buyer": row["buyer_name"],
                    "shared_count": row["shared_count"],
                    "shared_persons": row["shared_names"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Board overlap collusion: {len(detections)} pair(s) found")
        return detections

    # ------------------------------------------------------------------
    # 13. Subcontractor Concentration
    # ------------------------------------------------------------------

    def detect_subcontractor_concentration(self) -> list[dict]:
        """
        Flag winners that route the vast majority of their PNRR subcontracts
        to a single company (concentration ratio > SUBCONTRACTOR_CONCENTRATION_MAX).

        This pattern occurs when a prime contractor exists primarily to act as a
        pass-through, directing most of the public money to a connected entity
        while taking a fee — a form of kickback laundering.

        If no SUBCONTRACTS_TO edges exist, returns [] with a console hint.

        Severity: high
        """
        logger.info("[ Fraud ] Running: Subcontractor Concentration detector…")

        check = self.conn.run_query("MATCH ()-[r:SUBCONTRACTS_TO]->() RETURN count(r) AS n LIMIT 1")
        if not check or check[0]["n"] == 0:
            logger.warning(
                "[ Fraud ] No SUBCONTRACTS_TO edges found — subcontractor concentration "
                "detector skipped.\n"
                "  → Run: python scripts/run_supply_chain_etl.py --step subcontractors"
            )
            return []

        results = self.conn.run_query(
            """
            MATCH (winner:Company)-[r:SUBCONTRACTS_TO]->(sub:Company)
            WITH winner,
                 sub,
                 count(r)         AS pair_count,
                 collect(r.cig)   AS cigs
            WITH winner,
                 sub, pair_count, cigs,
                 sum(pair_count) OVER (PARTITION BY winner) AS total_winner_subs
            WITH winner, sub, pair_count, cigs,
                 toFloat(pair_count) / total_winner_subs AS concentration_ratio
            WHERE concentration_ratio >= $threshold AND pair_count >= 3
            RETURN
                winner.id                 AS winner_id,
                winner.nome_normalizzato  AS winner_name,
                sub.id                    AS sub_id,
                sub.nome_normalizzato     AS sub_name,
                pair_count,
                concentration_ratio,
                cigs
            ORDER BY concentration_ratio DESC
            LIMIT 30
            """,
            {"threshold": SUBCONTRACTOR_CONCENTRATION_MAX},
        )

        # Fallback without window functions (older Neo4j / less elegant)
        if not results:
            results = self.conn.run_query(
                """
                MATCH (winner:Company)-[r:SUBCONTRACTS_TO]->(sub:Company)
                WITH winner, count(DISTINCT sub.id) AS distinct_subs,
                             collect({sub: sub, cig: r.cig}) AS all_subs
                WHERE distinct_subs >= 1
                UNWIND all_subs AS entry
                WITH winner, entry.sub AS sub,
                     count(*) AS pair_count,
                     collect(entry.cig) AS cigs,
                     size(all_subs) AS total_winner_subs
                WITH winner, sub, pair_count, cigs, total_winner_subs,
                     toFloat(pair_count) / total_winner_subs AS concentration_ratio
                WHERE concentration_ratio >= $threshold AND pair_count >= 3
                RETURN
                    winner.id                AS winner_id,
                    winner.nome_normalizzato AS winner_name,
                    sub.id                   AS sub_id,
                    sub.nome_normalizzato     AS sub_name,
                    pair_count,
                    concentration_ratio,
                    cigs
                ORDER BY concentration_ratio DESC
                LIMIT 30
                """,
                {"threshold": SUBCONTRACTOR_CONCENTRATION_MAX},
            )

        detections: list[dict] = []
        for row in results:
            evidence = {
                "winner": row["winner_name"],
                "sub": row["sub_name"],
                "pair_count": row["pair_count"],
                "concentration_ratio": round(row["concentration_ratio"], 3),
                "cigs": row["cigs"][:10],
            }
            pattern_id = self._create_fraud_pattern_node(
                pattern_name="subcontractor_concentration",
                severity="high",
                description=(
                    f"'{row['winner_name']}' routes {row['concentration_ratio']:.0%} of its "
                    f"subcontracts ({row['pair_count']} tenders) to a single company "
                    f"'{row['sub_name']}'. This pass-through pattern is a kickback indicator."
                ),
                evidence=evidence,
                affected_entity_ids=[row["winner_id"], row["sub_id"]],
            )
            for cid in [row["winner_id"], row["sub_id"]]:
                self._link_entity_to_pattern(cid, "Company", pattern_id, 0.80, evidence)
                self._bump_entity_risk_score(cid, "Company", "high")

            detections.append(
                {
                    "pattern": "subcontractor_concentration",
                    "winner": row["winner_name"],
                    "sub": row["sub_name"],
                    "pair_count": row["pair_count"],
                    "concentration_ratio": row["concentration_ratio"],
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Subcontractor concentration: {len(detections)} finding(s)")
        return detections

    # ------------------------------------------------------------------
    # Shell Company Network detector
    # ------------------------------------------------------------------

    def detect_shell_company_network(
        self,
        flag_threshold: float | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """
        Identify clusters of HIGH_RISK shell companies that share directors,
        addresses, or UBO chains — indicators of a coordinated shell network.

        Uses the multi-factor ``ShellCompanyDetector`` to score companies, then
        groups HIGH_RISK results by shared director (REPRESENTS) or shared
        registered address into "network clusters".

        Each cluster with ≥ 2 HIGH_RISK members creates one FraudPattern node
        of type ``shell_company_network``.

        Parameters
        ----------
        flag_threshold:
            Shell score above which a company is flagged HIGH_RISK.  Defaults
            to ``SHELL_SCORE_FLAG_THRESHOLD`` from constants.
        limit:
            Maximum number of companies to score.

        Returns
        -------
        List of detection dicts, one per cluster.
        """
        from paladino.analytics.shell_company_detector import ShellCompanyDetector
        from paladino.constants import SHELL_SCORE_FLAG_THRESHOLD

        threshold = flag_threshold if flag_threshold is not None else SHELL_SCORE_FLAG_THRESHOLD
        detector = ShellCompanyDetector(self.conn.driver)
        all_scores = detector.score_all(limit=limit, store_results=True)
        high_risk = detector.get_high_risk(all_scores, threshold=threshold)

        if not high_risk:
            logger.info("[ Fraud ] Shell company network: no HIGH_RISK companies found")
            return []

        # Build clusters: query shared directors/addresses among high-risk CFs
        high_risk_cfs = [r.company_id for r in high_risk]
        cluster_query = """
        UNWIND $cfs AS cf
        MATCH (c:Company {cf: cf})

        // cluster by shared director
        OPTIONAL MATCH (p:Person)-[:REPRESENTS]->(c)
        OPTIONAL MATCH (p)-[:REPRESENTS]->(sibling:Company)
          WHERE sibling.cf IN $cfs AND sibling.cf <> cf

        // cluster by shared address
        OPTIONAL MATCH (addr_sib:Company)
          WHERE addr_sib.cf IN $cfs
            AND addr_sib.cf <> cf
            AND c.registered_address IS NOT NULL
            AND c.registered_address = addr_sib.registered_address

        WITH cf, c.name AS name,
             collect(distinct sibling.cf) + collect(distinct addr_sib.cf) AS linked_cfs
        RETURN cf, name, [x IN linked_cfs WHERE x IS NOT NULL] AS linked_cfs
        """
        rows = self.conn.run_query(cluster_query, {"cfs": high_risk_cfs})

        # Build undirected cluster groups via union-find
        parent: dict[str, str] = {r["cf"]: r["cf"] for r in rows}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for row in rows:
            for linked in row["linked_cfs"]:
                if linked in parent:
                    union(row["cf"], linked)

        # Group by root
        groups: dict[str, list[str]] = {}
        for cf in parent:
            root = find(cf)
            groups.setdefault(root, []).append(cf)

        # Look up score objects by CF
        score_map = {s.company_id: s for s in high_risk}
        name_map = {r["cf"]: r["name"] for r in rows}

        detections: list[dict] = []
        for root, cf_list in groups.items():
            if len(cf_list) < 2:
                continue  # singleton — not a "network"

            max_score = max(score_map[cf].shell_score for cf in cf_list if cf in score_map)
            severity = "critical" if max_score >= 0.75 else "high"

            names = [name_map.get(cf, cf) for cf in cf_list]
            evidence = (
                f"Shell company network detected: {len(cf_list)} HIGH_RISK companies share "
                f"directors or registered addresses. "
                f"Members: {', '.join(names[:5])}{'…' if len(names) > 5 else ''}. "
                f"Max shell score: {max_score:.2f}."
            )

            pattern_id = self._create_fraud_pattern_node(
                pattern_name="shell_company_network",
                severity=severity,
                confidence=min(max_score + 0.1, 1.0),
                description=evidence,
                evidence=evidence,
                affected_entity_ids=cf_list,
            )

            for cf in cf_list:
                self._link_entity_to_pattern(
                    cf,
                    "Company",
                    pattern_id,
                    score_map[cf].shell_score if cf in score_map else 0.5,
                    evidence,
                )
                self._bump_entity_risk_score(cf, "Company", severity)

            detections.append(
                {
                    "pattern": "shell_company_network",
                    "cluster_cfs": cf_list,
                    "cluster_names": names,
                    "size": len(cf_list),
                    "max_score": round(max_score, 4),
                    "severity": severity,
                    "pattern_id": pattern_id,
                }
            )

        logger.info(f"[ Fraud ] Shell company network: {len(detections)} cluster(s) detected")
        return detections

    # ------------------------------------------------------------------

    def run_all_detectors(self) -> dict[str, list[dict]]:
        """
        Run all 13 detectors in sequence and return a summary dict.

        Returns
        -------
        dict mapping detector name → list of detection dicts.

        Each individual detector handles its own exceptions so that a failure
        in one detector does not block the rest.  Supply-chain detectors
        (carousel_fraud, board_overlap_collusion, subcontractor_concentration)
        return an empty list when the required data is not yet loaded rather
        than raising exceptions.
        """
        logger.info(f"=== FraudPatternLibrary run started | run_id={self.run_id} ===")

        detectors = [
            ("bid_rotation", self.detect_bid_rotation),
            ("ghost_bidding", self.detect_ghost_bidding),
            ("split_tendering", self.detect_split_tendering),
            ("short_award_window", self.detect_short_award_window),
            ("price_manipulation", self.detect_price_manipulation),
            ("ubo_conflict", self.detect_ubo_conflict),
            ("winner_loser_ring", self.detect_winner_loser_ring),
            ("pnrr_concentration", self.detect_pnrr_concentration),
            ("community_monopoly", self.detect_community_monopoly),
            ("network_clique", self.detect_network_clique),
            # Supply-chain detectors (require SUBCONTRACTS_TO / REPRESENTS data)
            ("carousel_fraud", self.detect_carousel_fraud),
            ("board_overlap_collusion", self.detect_board_overlap_collusion),
            ("subcontractor_concentration", self.detect_subcontractor_concentration),
            # Enhanced shell company detection (multi-factor, Phase 3.2)
            ("shell_company_network", self.detect_shell_company_network),
        ]

        results: dict[str, list[dict]] = {}
        total_detections = 0

        for name, detector in detectors:
            try:
                found = detector()
                results[name] = found
                total_detections += len(found)
            except Exception as exc:
                logger.error(f"[ Fraud ] Detector '{name}' failed: {exc}")
                results[name] = []

        elapsed = (datetime.now(UTC) - self._run_started_at).total_seconds()
        logger.success(
            f"=== FraudPatternLibrary run complete | "
            f"{total_detections} pattern(s) detected across {len(detectors)} detectors "
            f"| elapsed={elapsed:.1f}s ==="
        )
        return results

    def get_summary_stats(self) -> dict:
        """
        Return aggregate statistics for all FraudPattern nodes in the graph.

        Useful for the Oracle and CLI stats display.
        """
        rows = self.conn.run_query(
            """
            MATCH (f:FraudPattern)
            RETURN f.pattern_name AS pattern,
                   f.severity     AS severity,
                   count(f)       AS occurrences
            ORDER BY occurrences DESC
            """
        )
        total = sum(r["occurrences"] for r in rows) if rows else 0
        return {"total": total, "by_pattern": rows}
