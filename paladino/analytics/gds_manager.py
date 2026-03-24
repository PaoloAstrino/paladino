"""
GDS Manager - Native Neo4j Graph Data Science Integration.
Handles in-memory graph projections and high-performance algorithms.
"""

from loguru import logger
from paladino.db import Neo4jConnection

class GDSManager:
    """
    Manages Neo4j GDS projections and algorithm execution.
    """
    
    def __init__(self, conn: Neo4jConnection, graph_name: str = "paladino-analytics"):
        self.conn = conn
        self.graph_name = graph_name

    def project_graph(self):
        """Create an in-memory projection of the procurement network."""
        logger.info(f"Creating GDS projection: {self.graph_name}")
        
        # Drop existing if any
        self.drop_graph()
        
        query = """
        CALL gds.graph.project(
            $graph_name,
            ['Company', 'Buyer', 'Tender'],
            {
                WINS: { orientation: 'UNDIRECTED' },
                ISSUES: { orientation: 'UNDIRECTED' }
            }
        )
        """
        self.conn.run_query(query, {"graph_name": self.graph_name})
        logger.success("Graph projected into memory.")

    def run_pagerank(self):
        """Calculate PageRank to find influential entities in the network."""
        logger.info("Running PageRank centrality algorithm...")
        query = """
        CALL gds.pageRank.write($graph_name, {
            writeProperty: 'centrality_score',
            maxIterations: 20,
            dampingFactor: 0.85
        })
        """
        res = self.conn.run_query(query, {"graph_name": self.graph_name})
        logger.success("PageRank scores written to database.")
        return res

    def run_louvain(self):
        """Run Louvain community detection to find clusters/cartels."""
        logger.info("Running Louvain community detection...")
        query = """
        CALL gds.louvain.write($graph_name, {
            writeProperty: 'community_id'
        })
        """
        res = self.conn.run_query(query, {"graph_name": self.graph_name})
        logger.success("Community IDs written to database.")
        return res

    def run_betweenness_centrality(self):
        """
        Calculate betweenness centrality to find bridge nodes in the network.

        High betweenness companies sit on many shortest paths between other
        entities - a structural indicator of intermediary / broker behaviour.
        Writes `betweenness_score` to Company and Buyer nodes.
        """
        logger.info("Running Betweenness Centrality algorithm...")
        query = """
        CALL gds.betweenness.write($graph_name, {
            writeProperty: 'betweenness_score'
        })
        """
        res = self.conn.run_query(query, {"graph_name": self.graph_name})
        logger.success("Betweenness scores written to database.")
        return res

    def run_triangle_count(self):
        """
        Count triangles for each node to detect dense collusion sub-graphs.

        A high triangle count on a Company node means it participates in many
        closed triads (A wins tender → B issues tender → A supplies B → repeat),
        a structural fingerprint of bid-rigging rings.
        Writes `triangle_count` to Company and Buyer nodes.
        """
        logger.info("Running Triangle Count algorithm...")
        query = """
        CALL gds.triangleCount.write($graph_name, {
            writeProperty: 'triangle_count'
        })
        """
        res = self.conn.run_query(query, {"graph_name": self.graph_name})
        logger.success("Triangle counts written to database.")
        return res

    def run_weakly_connected_components(self):
        """
        Find Weakly Connected Components to isolate shells and orphan networks.

        Companies in very small WCC (size 1-2) that still win tenders are
        potential ghost / shell companies with no real supply chain.
        Writes `wcc_id` to Company and Buyer nodes.
        """
        logger.info("Running Weakly Connected Components algorithm...")
        query = """
        CALL gds.wcc.write($graph_name, {
            writeProperty: 'wcc_id'
        })
        """
        res = self.conn.run_query(query, {"graph_name": self.graph_name})
        logger.success("WCC component IDs written to database.")
        return res

    # ── Supply chain & ownership graph algorithms ────────────────────────────

    def project_supply_chain_graph(self) -> bool:
        """
        Project the supply-chain sub-graph (Company nodes + SUBCONTRACTS_TO /
        SUPPLIES_TO edges) into GDS memory.

        Returns True if the projection contains at least one relationship and
        False (with a helpful hint) when no supply-chain data has been loaded.
        """
        proj_name = self.graph_name + "-supply"
        self._drop_named(proj_name)

        result = self.conn.run_query(
            """
            CALL gds.graph.project(
                $proj,
                'Company',
                {
                    SUBCONTRACTS_TO: { orientation: 'NATURAL' },
                    SUPPLIES_TO:     { orientation: 'NATURAL' }
                }
            )
            YIELD relationshipCount
            RETURN relationshipCount
            """,
            {"proj": proj_name},
        )
        rel_count = result[0]["relationshipCount"] if result else 0

        if rel_count == 0:
            logger.warning(
                "Supply-chain projection has 0 relationships — "
                "SUBCONTRACTS_TO / SUPPLIES_TO data may not be loaded yet.\n"
                "  → Run: python scripts/run_supply_chain_etl.py --step subcontractors"
            )
            self._drop_named(proj_name)
            return False

        logger.info(f"Supply-chain projection: {rel_count:,} edges")
        return True

    def run_supply_chain_scc(self) -> int:
        """
        Strongly-Connected-Components on the supply-chain graph.

        A strongly connected component with size > 1 is a cycle
        (A subcontracts B subcontracts C ... subcontracts A) — the structural
        fingerprint of carousel fraud.

        Writes ``supply_scc_id`` and ``supply_scc_size`` to Company nodes.
        Returns the number of companies written to.
        """
        logger.info("Running SCC on supply-chain graph…")
        proj_name = self.graph_name + "-supply"

        if not self.project_supply_chain_graph():
            return 0   # No data — skip silently, warning already logged

        try:
            result = self.conn.run_query(
                """
                CALL gds.scc.write($proj, {
                    writeProperty: 'supply_scc_id'
                })
                YIELD componentCount, nodePropertiesWritten
                RETURN componentCount, nodePropertiesWritten
                """,
                {"proj": proj_name},
            )
            written = result[0]["nodePropertiesWritten"] if result else 0

            # Tag each company with its SCC size (needed by carousel detector)
            self.conn.run_query(
                """
                MATCH (c:Company)
                WHERE c.supply_scc_id IS NOT NULL
                WITH c.supply_scc_id AS scc_id, collect(c) AS members
                FOREACH (m IN members | SET m.supply_scc_size = size(members))
                """
            )
            logger.success(f"SCC written to {written:,} Company nodes.")
            return written
        finally:
            self._drop_named(proj_name)

    def project_ownership_graph(self) -> bool:
        """
        Project the ownership sub-graph (Person + Company nodes,
        SHAREHOLDER_OF + REPRESENTS edges) into GDS memory.

        Returns True if at least one edge exists.
        """
        proj_name = self.graph_name + "-ownership"
        self._drop_named(proj_name)

        result = self.conn.run_query(
            """
            CALL gds.graph.project(
                $proj,
                ['Person', 'Company'],
                {
                    SHAREHOLDER_OF: { orientation: 'NATURAL' },
                    REPRESENTS:     { orientation: 'NATURAL' }
                }
            )
            YIELD relationshipCount
            RETURN relationshipCount
            """,
            {"proj": proj_name},
        )
        rel_count = result[0]["relationshipCount"] if result else 0

        if rel_count == 0:
            logger.warning(
                "Ownership projection has 0 relationships — "
                "SHAREHOLDER_OF / REPRESENTS data may not be loaded yet.\n"
                "  → Drop CSV files into data/corporate/raw/ and run the Supply Chain ETL."
            )
            self._drop_named(proj_name)
            return False

        logger.info(f"Ownership projection: {rel_count:,} edges")
        return True

    def run_ownership_pagerank(self) -> int:
        """
        PageRank on the ownership graph to score corporate *control influence*.

        A high ``ownership_influence`` score means the entity (Person or Company)
        controls many subsidiaries or sits at the top of a deep ownership chain.
        These are the entities to scrutinise first when investigating shell companies.

        Writes ``ownership_influence`` to Person and Company nodes.
        Returns the number of nodes written to.
        """
        logger.info("Running PageRank on ownership graph…")
        proj_name = self.graph_name + "-ownership"

        if not self.project_ownership_graph():
            return 0   # No data — skip silently

        try:
            result = self.conn.run_query(
                """
                CALL gds.pageRank.write($proj, {
                    writeProperty:  'ownership_influence',
                    maxIterations:  20,
                    dampingFactor:  0.85
                })
                YIELD nodePropertiesWritten
                RETURN nodePropertiesWritten
                """,
                {"proj": proj_name},
            )
            written = result[0]["nodePropertiesWritten"] if result else 0
            logger.success(f"Ownership PageRank written to {written:,} nodes.")
            return written
        finally:
            self._drop_named(proj_name)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _drop_named(self, proj_name: str) -> None:
        """Drop a named projection if it exists (swallows errors)."""
        try:
            exists = self.conn.run_query(
                "CALL gds.graph.exists($n) YIELD exists",
                {"n": proj_name},
            )
            if exists and exists[0]["exists"]:
                self.conn.run_query("CALL gds.graph.drop($n)", {"n": proj_name})
        except Exception:  # noqa: BLE001
            pass

    def drop_graph(self):
        """Remove the primary procurement projection from memory."""
        self._drop_named(self.graph_name)
        logger.info(f"Dropped existing graph: {self.graph_name}")

    def run_full_analytics_suite(self):
        """Execute the complete GDS pipeline.

        Runs (in order):
          Procurement network (Company + Buyer + Tender):
            1. PageRank           → centrality_score
            2. Louvain            → community_id
            3. Betweenness        → betweenness_score
            4. Triangle Count     → triangle_count
            5. WCC                → wcc_id

          Supply-chain network (Company only, SUBCONTRACTS_TO / SUPPLIES_TO):
            6. SCC                → supply_scc_id, supply_scc_size
               (skipped gracefully if no supply-chain data loaded yet)

          Ownership network (Person + Company, SHAREHOLDER_OF / REPRESENTS):
            7. PageRank           → ownership_influence
               (skipped gracefully if no corporate structure data loaded yet)

        The procurement projection is created fresh and dropped regardless of
        errors so the in-memory graph does not leak between runs.
        Supply-chain and ownership projections are managed internally by their
        own methods.
        """
        try:
            self.project_graph()
            self.run_pagerank()
            self.run_louvain()
            self.run_betweenness_centrality()
            self.run_triangle_count()
            self.run_weakly_connected_components()
            logger.success("Procurement GDS algorithms completed.")
        except Exception as e:
            logger.error(f"Procurement GDS pipeline failed: {e}. "
                         "Ensure the GDS library is installed in Neo4j.")
        finally:
            self.drop_graph()

        # These two are independent projections — run unconditionally
        self.run_supply_chain_scc()
        self.run_ownership_pagerank()

        logger.success("Full GDS Analytics Suite completed.")
