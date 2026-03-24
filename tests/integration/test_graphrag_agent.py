"""
Integration tests for GraphRAG agent.
Tests require a running Neo4j instance with data loaded.
"""

from pathlib import Path

import pytest

from paladino.app.graphrag_agent import GraphRAGAgent
from paladino.db import get_driver
from paladino.schema_manager import SchemaManager


@pytest.fixture(scope="module")
def driver():
    """Provide a Neo4j driver for tests."""
    driver = get_driver()
    yield driver
    driver.close()


@pytest.fixture(scope="module")
def graphrag_agent(driver):
    """Provide a GraphRAG agent instance."""
    schema_dir = Path(__file__).parent.parent.parent / "schema"
    schema_manager = SchemaManager(driver, schema_dir)
    schema_metadata = schema_manager.get_schema_metadata()
    return GraphRAGAgent(driver, schema_metadata=schema_metadata)


class TestGraphRAGAgentIntegration:
    """Integration tests for GraphRAG agent with live database."""

    def test_query_top_vendors(self, graphrag_agent):
        """Test querying top vendors."""
        results = graphrag_agent.query("top_vendors", {}, limit=5)

        assert isinstance(results, list)
        assert len(results) <= 5

        if len(results) > 0:
            # Verify result structure
            first_result = results[0]
            assert "company" in first_result
            assert "tender_count" in first_result
            assert "total_value" in first_result

            # Verify ordering (descending by tender_count)
            if len(results) > 1:
                assert results[0]["tender_count"] >= results[1]["tender_count"]

    def test_query_top_centrality_companies(self, graphrag_agent):
        """Test querying companies by centrality score."""
        results = graphrag_agent.query("top_centrality_companies", {}, limit=5)

        assert isinstance(results, list)

        if len(results) > 0:
            # Verify result structure
            first_result = results[0]
            assert "company" in first_result
            assert "influence_score" in first_result
            assert "community" in first_result

            # Verify centrality scores exist
            assert first_result["influence_score"] is not None

            # Verify ordering (descending by influence_score)
            if len(results) > 1:
                assert results[0]["influence_score"] >= results[1]["influence_score"]

    def test_query_project_funding_analysis(self, graphrag_agent):
        """Test project funding analysis query."""
        results = graphrag_agent.query("project_funding_analysis", {}, limit=10)

        assert isinstance(results, list)

        if len(results) > 0:
            # Verify result structure
            first_result = results[0]
            assert "funding_source" in first_result
            assert "project_count" in first_result
            assert "total_funding" in first_result

            # Verify counts are positive
            assert first_result["project_count"] > 0

    def test_query_pnrr_projects(self, graphrag_agent):
        """Test PNRR projects query."""
        results = graphrag_agent.query("pnrr_projects", {}, limit=5)

        assert isinstance(results, list)

        if len(results) > 0:
            # Verify result structure
            first_result = results[0]
            assert "cup" in first_result or "titolo" in first_result

    def test_query_with_custom_limit(self, graphrag_agent):
        """Test that custom limit parameter works."""
        results_5 = graphrag_agent.query("top_vendors", {}, limit=5)
        results_10 = graphrag_agent.query("top_vendors", {}, limit=10)

        assert len(results_5) <= 5
        assert len(results_10) <= 10

        # If we have enough data, 10 should return more than 5
        if len(results_10) == 10:
            assert len(results_10) > len(results_5)

    def test_execute_custom_cypher(self, graphrag_agent):
        """Test executing custom Cypher queries."""
        cypher = "MATCH (c:Company) RETURN count(c) as company_count"
        results = graphrag_agent.execute_custom_cypher(cypher)

        assert isinstance(results, list)
        assert len(results) == 1
        assert "company_count" in results[0]
        assert results[0]["company_count"] > 0

    def test_execute_custom_cypher_with_params(self, graphrag_agent):
        """Test executing custom Cypher with parameters."""
        cypher = "MATCH (c:Company) RETURN count(c) as count LIMIT $limit"
        results = graphrag_agent.execute_custom_cypher(cypher, {"limit": 1})

        assert isinstance(results, list)
        assert len(results) == 1

    def test_query_nonexistent_template(self, graphrag_agent):
        """Test querying with a non-existent template."""
        results = graphrag_agent.query("nonexistent_template", {})

        assert isinstance(results, list)
        assert len(results) == 0

    def test_regional_spending_query(self, graphrag_agent):
        """Test regional spending analysis."""
        results = graphrag_agent.query("regional_spending", {})

        assert isinstance(results, list)

        if len(results) > 0:
            # Verify result structure
            first_result = results[0]
            assert "regione" in first_result
            assert "total_tenders" in first_result
            assert "total_importo" in first_result

    def test_database_connectivity(self, driver):
        """Test that database connection is working."""
        with driver.session() as session:
            result = session.run("RETURN 1 as test")
            record = result.single()
            assert record["test"] == 1

    def test_graph_has_data(self, driver):
        """Test that the graph contains expected data."""
        with driver.session() as session:
            # Check for companies
            result = session.run("MATCH (c:Company) RETURN count(c) as count")
            company_count = result.single()["count"]
            assert company_count > 0, "Database should contain Company nodes"

            # Check for tenders
            result = session.run("MATCH (t:Tender) RETURN count(t) as count")
            tender_count = result.single()["count"]
            assert tender_count > 0, "Database should contain Tender nodes"

            # Check for projects
            result = session.run("MATCH (p:Project) RETURN count(p) as count")
            project_count = result.single()["count"]
            assert project_count > 0, "Database should contain Project nodes"
