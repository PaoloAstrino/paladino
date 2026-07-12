"""
Integration tests for GraphRAG agent.
"""

import pytest
from paladino.app.graphrag_agent import CypherQueryTemplates, GraphRAGAgent


def test_query_templates_list():
    """Test that all templates are listed."""
    templates = CypherQueryTemplates.list_templates()

    assert "pnrr_projects" in templates
    # Template was renamed from high_risk_companies to companies_with_high_risk
    assert "companies_with_high_risk" in templates
    assert "companies_by_region" in templates
    assert len(templates) >= 5


def test_query_template_retrieval():
    """Test retrieving a specific template."""
    template = CypherQueryTemplates.get_template("pnrr_projects")

    assert template is not None
    assert "MATCH" in template
    assert "PNRR" in template


def test_graphrag_agent_execute_template(clean_neo4j):
    """Test executing a template query against Neo4j."""
    agent = GraphRAGAgent(clean_neo4j)

    # Create test data
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (c:Company {
                nome_normalizzato: 'TEST COMPANY',
                risk_score: 0.8,
                anomaly_flags: ['high_single_bidder_rate'],
                total_tenders: 10,
                source: 'TEST'
            })
        """)

    # Execute template (use correct template name)
    results = agent.query("companies_with_high_risk", {"min_risk": 0.5}, limit=10)

    assert len(results) == 1
    assert results[0]["nome_normalizzato"] == "TEST COMPANY"
    assert results[0]["risk_score"] == 0.8


@pytest.mark.skip(reason="Requires running Neo4j instance")
def test_graphrag_agent_natural_language_with_llm(clean_neo4j, mock_ollama):
    """Test natural language query with LLM integration."""
    agent = GraphRAGAgent(clean_neo4j)

    # Mock LLM to return correct template name
    mock_ollama.return_value.json.return_value = {
        "message": {
            "content": '{"template_name": "companies_with_high_risk", "params": {"min_risk": 0.5}}'
        }
    }

    # Create test data
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (c:Company {
                nome_normalizzato: 'RISKY COMPANY',
                risk_score: 0.9,
                anomaly_flags: ['buyer_concentration'],
                total_tenders: 5,
                source: 'TEST'
            })
        """)

    # Execute natural language query
    result = agent.natural_language_query("Show me high risk companies")

    assert result["template"] == "companies_with_high_risk"
    assert len(result["results"]) == 1
    assert result["results"][0]["nome_normalizzato"] == "RISKY COMPANY"


def test_graphrag_agent_invalid_template(clean_neo4j):
    """Test handling of invalid template name."""
    agent = GraphRAGAgent(clean_neo4j)

    results = agent.query("nonexistent_template", {})

    assert len(results) == 0
