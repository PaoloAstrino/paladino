import pytest
from unittest.mock import MagicMock, ANY
from paladino.db import Neo4jConnection

def test_execute_batch_checkpointing():
    """Verify that execute_batch skips already processed batches."""
    conn = Neo4jConnection()

    # Setup MagicMocks for context managers
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    conn.connect = MagicMock(return_value=mock_driver)
    # Mock _claim_batch: first batch already processed (False), second batch claimed (True)
    conn._claim_batch = MagicMock(side_effect=[False, True])
    conn.mark_batch_completed = MagicMock()
    conn.run_query = MagicMock()

    data = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
    query = "MERGE (n:Node {id: row.id})"

    # Run with batch_size=2 (total 2 batches)
    conn.execute_batch(query, data, batch_size=2)

    # Assertions
    assert conn._claim_batch.call_count == 2
    assert conn.mark_batch_completed.call_count == 1
    assert mock_session.run.call_count == 1
