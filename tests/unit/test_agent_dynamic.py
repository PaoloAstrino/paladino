from unittest.mock import MagicMock

import pytest

from paladino.app.graphrag_agent import GraphRAGAgent


@pytest.fixture
def mock_driver():
    return MagicMock()


@pytest.fixture
def agent(mock_driver):
    metadata = "Company {cf, nome_normalizzato}, Tender {cig, importo}"
    agent = GraphRAGAgent(mock_driver, schema_metadata=metadata)
    agent.llm = MagicMock()
    return agent


def test_natural_language_query_template_match(agent):
    # Mock LLM to return a template match
    agent.llm.classify_intent.return_value = {
        "template_name": "pnrr_projects",
        "params": {"limit": 5},
    }

    # Mock the query method
    agent.query = MagicMock(return_value=[{"p.cup": "123"}])

    result = agent.natural_language_query("Show me PNRR")

    assert result["method"] == "template"
    assert result["template"] == "pnrr_projects"
    agent.query.assert_called_once()


def test_natural_language_query_dynamic_fallback(agent):
    # Mock LLM to return NO template match
    agent.llm.classify_intent.return_value = {"template_name": None}

    # Mock LLM to return a generated Cypher query
    generated_cypher = "MATCH (c:Company) RETURN c LIMIT 1"
    agent.llm.generate_cypher.return_value = generated_cypher

    # Mock driver session and run
    mock_session = agent.driver.session.return_value.__enter__.return_value
    mock_session.run.return_value = [{"c.nome": "Test Co"}]

    result = agent.natural_language_query("How many companies?")

    assert result["method"] == "dynamic_cypher"
    assert result["cypher"] == generated_cypher
    assert result["count"] == 1
