"""
Unit tests for Confidence Propagation Engine.
"""

import pytest
from unittest.mock import MagicMock
from paladino.analytics.confidence_engine import ConfidencePropagator

class MockNeo4jConn:
    def __init__(self):
        self.queries = []
        self.results = []
    
    def run_query(self, query, params=None):
        self.queries.append(query)
        return self.results.pop(0) if self.results else [{"updates": 0, "total": 0, "count": 0}]

def test_propagator_initialization():
    conn = MockNeo4jConn()
    conn.results = [[{"count": 10}]] # Result for initialize
    
    propagator = ConfidencePropagator(conn)
    propagator.initialize_derived_scores()
    
    assert "SET n.derived_confidence = coalesce(n.confidence, 1.0)" in conn.queries[0]

def test_propagator_sweep_logic():
    conn = MockNeo4jConn()
    # Results for 3 passes: 5 updates, 2 updates, 0 updates (convergence)
    conn.results = [
        [{"updates": 5}], 
        [{"updates": 2}], 
        [{"updates": 0}]
    ]
    
    propagator = ConfidencePropagator(conn)
    propagator.run_propagation_sweep(max_passes=5)
    
    # Should have run 3 queries (last one returned 0 updates)
    assert len(conn.queries) == 3
    assert "min(m.derived_confidence * r.confidence)" in conn.queries[0]

def test_confidence_stats():
    conn = MockNeo4jConn()
    mock_stats = {
        "total": 100,
        "average": 0.85,
        "high_trust": 80,
        "low_trust": 5
    }
    conn.results = [[mock_stats]]
    
    propagator = ConfidencePropagator(conn)
    stats = propagator.get_confidence_stats()
    
    assert stats["total"] == 100
    assert stats["average"] == 0.85
    assert "MATCH (n)" in conn.queries[0]
    assert "n.derived_confidence" in conn.queries[0]
