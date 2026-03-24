import pytest
from unittest.mock import Mock, patch
from paladino.app.graphrag_agent import GraphRAGAgent

def test_agent_self_correction_loop():
    """Verify that the agent attempts to fix a broken Cypher query."""
    mock_llm = Mock()
    mock_templates = Mock()
    mock_templates.list_templates.return_value = []
    
    # Correct instantiation: __init__ only takes (driver, schema_metadata)
    agent = GraphRAGAgent(driver=Mock(), schema_metadata="Node Company { cf, nome_normalizzato }")
    # Manually inject mocks
    agent.llm = mock_llm
    agent.templates = mock_templates
    
    # 1. First attempt returns a broken query (using non-existent 'tax_id')
    mock_llm.classify_intent.return_value = {"template_name": None}
    mock_llm.generate_cypher.return_value = "MATCH (c:Company) RETURN c.tax_id"
    
    # 2. Second attempt (the fix) returns a valid query
    mock_llm.fix_cypher.return_value = "MATCH (c:Company) RETURN c.cf"
    
    # Mock execution failure for first, success for second
    with patch.object(agent, 'execute_custom_cypher') as mock_exec:
        # First call raises error, second returns results
        mock_exec.side_effect = [Exception("Property tax_id not found"), [{"cf": "123"}]]
        
        result = agent.natural_language_query("Show companies")
        
        assert result["method"] == "dynamic_cypher"
        assert result["attempts"] == 2
        assert result["results"] == [{"cf": "123"}]
        assert mock_llm.fix_cypher.called
