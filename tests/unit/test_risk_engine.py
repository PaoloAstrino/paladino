import pytest
from unittest.mock import Mock, ANY
from paladino.analytics.risk_engine import RiskEngine

def test_risk_engine_queries():
    """Verify that the risk engine executes expected Cypher queries."""
    mock_conn = Mock()
    engine = RiskEngine(mock_conn)
    
    # Mock GDS Manager to avoid needing real GDS in tests
    engine.gds = Mock()
    
    engine.run_global_analysis()
    
    # Verify that native GDS suite was called
    assert engine.gds.run_full_analytics_suite.called
    
    # Verify that reset query was called
    assert mock_conn.run_query.called
    
    # Check that at least 4 queries were run (reset, competition, concentration, normalize)
    assert mock_conn.run_query.call_count >= 4
    
    # Verify the normalization logic is present in one of the queries
    queries = [call.args[0] for call in mock_conn.run_query.call_args_list]
    assert any("SET c.risk_score = 1.0" in q for q in queries)

def test_get_high_risk_entities():
    mock_conn = Mock()
    mock_conn.run_query.return_value = [{"company": "Rossi SRL", "score": 0.9}]
    
    engine = RiskEngine(mock_conn)
    results = engine.get_high_risk_entities(limit=5)
    
    assert len(results) == 1
    assert results[0]["score"] == 0.9
    mock_conn.run_query.assert_called_with(ANY, {"limit": 5})
