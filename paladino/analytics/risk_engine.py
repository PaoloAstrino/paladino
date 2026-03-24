"""
Risk Scoring Engine - Automated anomaly detection using Graph analytics.
Calculates a risk_score (0.0 to 1.0) for every Company in the graph.
"""

from loguru import logger
from typing import Dict, List
import uuid
from paladino.db import Neo4jConnection

from paladino.analytics.gds_manager import GDSManager
from paladino.analytics.fraud_patterns import FraudPatternLibrary

# Risk scoring weights (sum to 1.0 for normalized scoring)
SINGLE_BIDDER_WEIGHT = 0.4  # High weight: lack of competition is strong risk indicator
CENTRALITY_WEIGHT = 0.3     # Medium weight: market dominance may indicate hub behavior
BUYER_CONCENTRATION_WEIGHT = 0.3  # Medium weight: could indicate favoritism/collusion

# Risk thresholds
HIGH_CENTRALITY_THRESHOLD = 0.5  # PageRank centrality score threshold
MIN_WINS_FOR_ANALYSIS = 2  # Minimum wins to analyze single-bidder ratio
MIN_WINS_FOR_BUYER_ANALYSIS = 3  # Minimum wins to analyze buyer concentration
BUYER_CONCENTRATION_RATIO = 0.8  # Threshold for flagging buyer concentration


class RiskEngine:
    """
    Analyzes graph patterns to identify suspicious procurement activity.
    
    Risk scoring methodology:
    - Single-bidder ratio: Companies with high % of single-bidder wins (weight: 0.4)
    - Market dominance: High PageRank centrality (weight: 0.3)
    - Buyer concentration: Dependency on few buyers (weight: 0.3)
    """

    def __init__(self, conn: Neo4jConnection):
        self.conn = conn
        self.gds = GDSManager(conn)

    def run_global_analysis(self):
        """
        Calculate and persist risk scores for all companies in the graph.

        Risk scoring methodology:
        - Single-bidder ratio: Companies with high % of single-bidder wins (weight: 0.4)
        - Market dominance: High PageRank centrality (weight: 0.3)
        - Buyer concentration: Dependency on few buyers (weight: 0.3)
        """
        logger.info("Starting global risk analysis (Native GDS + Heuristics)...")

        # 1. Run Native GDS Algorithms
        # This populates c.centrality_score and c.community_id
        self.gds.run_full_analytics_suite()

        # 2. Reset high-level risk scores
        self.conn.run_query("MATCH (c:Company) SET c.risk_score = 0.0, c.anomaly_flags = []")

        # 3. Flag Single-Bidder wins (Weight: SINGLE_BIDDER_WEIGHT)
        logger.info("Analyzing competition levels...")
        self.conn.run_query("""
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WITH c, count(t) as total_wins,
                 sum(case when t.single_bidder = true then 1 else 0 end) as single_bidder_wins
            WHERE total_wins > $min_wins
            WITH c, (toFloat(single_bidder_wins) / total_wins) as ratio
            SET c.risk_score = c.risk_score + (ratio * $weight),
                c.anomaly_flags = coalesce(c.anomaly_flags, []) + ["high_single_bidder_ratio"]
        """, {
            "min_wins": MIN_WINS_FOR_ANALYSIS,
            "weight": SINGLE_BIDDER_WEIGHT
        })

        # 4. Flag Centrality / Market Dominance (Weight: CENTRALITY_WEIGHT)
        # High PageRank + low diversity of buyers = suspicious hub
        logger.info("Analyzing market dominance via PageRank...")
        self.conn.run_query("""
            MATCH (c:Company)
            WHERE c.centrality_score > $threshold
            SET c.risk_score = c.risk_score + $weight,
                c.anomaly_flags = coalesce(c.anomaly_flags, []) + ["market_dominance_high"]
        """, {
            "threshold": HIGH_CENTRALITY_THRESHOLD,
            "weight": CENTRALITY_WEIGHT
        })

        # 5. Flag Buyer Concentration (Weight: BUYER_CONCENTRATION_WEIGHT)
        logger.info("Analyzing buyer concentration...")
        self.conn.run_query("""
            MATCH (c:Company)-[:WINS]->(t:Tender)<-[:ISSUES]-(b:Buyer)
            WITH c, b, count(t) as wins_with_buyer
            MATCH (c)-[:WINS]->(total_t:Tender)
            WITH c, b, wins_with_buyer, count(total_t) as total_wins
            WHERE total_wins > $min_wins
              AND (toFloat(wins_with_buyer) / total_wins) > $ratio_threshold
            SET c.risk_score = c.risk_score + $weight,
                c.anomaly_flags = coalesce(c.anomaly_flags, []) + ["high_buyer_concentration"]
        """, {
            "min_wins": MIN_WINS_FOR_BUYER_ANALYSIS,
            "ratio_threshold": BUYER_CONCENTRATION_RATIO,
            "weight": BUYER_CONCENTRATION_WEIGHT
        })

        # 6. Normalize Scores (ensure max is 1.0)
        self.conn.run_query("""
            MATCH (c:Company)
            WHERE c.risk_score > 1.0
            SET c.risk_score = 1.0
        """)

        # 7. Run Fraud Pattern Library (10 named detectors)
        # Detectors add incremental delta to risk_score and create FraudPattern nodes.
        logger.info("Running Fraud Pattern Library (10 detectors)...")
        fraud_lib = FraudPatternLibrary(self.conn)
        fraud_results = fraud_lib.run_all_detectors()

        # Log summary
        total_findings = sum(len(v) for v in fraud_results.values())
        logger.success(f"Fraud Pattern Library: {total_findings} finding(s) across "
                       f"{len(fraud_results)} detector(s).")

        # Final normalisation after fraud deltas
        self.conn.run_query("""
            MATCH (c:Company)
            WHERE c.risk_score > 1.0
            SET c.risk_score = 1.0
        """)

        # 8. Persist risk snapshots as Version nodes for temporal tracking
        logger.info("Saving risk score snapshots for temporal history...")
        self.save_all_risk_snapshots()

        logger.success("Global risk analysis complete (heuristics + fraud patterns).")

    def get_high_risk_entities(self, limit: int = 10) -> List[Dict]:
        """Retrieve companies with the highest risk scores."""
        query = """
            MATCH (c:Company)
            WHERE c.risk_score > 0.1
            RETURN c.nome_normalizzato as company, 
                   c.cf as cf,
                   c.risk_score as score,
                   c.anomaly_flags as flags
            ORDER BY c.risk_score DESC
            LIMIT $limit
        """
        return self.conn.run_query(query, {"limit": limit})

    def save_risk_snapshot(self, company_id: str, score: float) -> None:
        """
        Persist a risk-score snapshot for a single company as a ``Version`` node
        linked via ``HAS_VERSION``.

        This enables ``TemporalAnalyzer.get_risk_score_history()`` to reconstruct
        the score trajectory over time.

        Parameters
        ----------
        company_id :
            The ``id`` property of the Company node (not ``cf``).
        score :
            The risk score to record (0.0 – 1.0).
        """
        snap_id = str(uuid.uuid4())
        self.conn.run_query(
            """
            MATCH (c:Company {id: $company_id})
            CREATE (v:Version {
                id:            $snap_id,
                entityId:      $company_id,
                risk_score:    $score,
                change_date:   datetime(),
                snapshot_type: 'risk_score'
            })
            CREATE (c)-[:HAS_VERSION]->(v)
            """,
            {"company_id": company_id, "snap_id": snap_id, "score": score},
        )

    def save_all_risk_snapshots(self) -> int:
        """
        Bulk-snapshot all companies whose ``risk_score > 0.0``.

        Fetches company IDs + scores in one query, then saves each via
        ``save_risk_snapshot()``.

        Returns the number of snapshots written.
        """
        rows = self.conn.run_query(
            """
            MATCH (c:Company)
            WHERE c.risk_score > 0.0
            RETURN c.id AS company_id, c.risk_score AS score
            """
        )
        if not isinstance(rows, list):
            rows = []
        count = 0
        for row in rows:
            try:
                self.save_risk_snapshot(row["company_id"], row["score"])
                count += 1
            except Exception as exc:
                logger.debug(f"[risk] snapshot skipped for {row['company_id']}: {exc}")
        logger.info(f"[risk] Saved {count} risk snapshots.")
        return count
