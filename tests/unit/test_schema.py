"""
Unit tests for Neo4j schema management.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path
from paladino.schema_manager import SchemaManager


@pytest.fixture
def schema_dir(tmp_path):
    d = tmp_path / "schema"
    d.mkdir()
    (d / "constraints.cypher").write_text("CREATE CONSTRAINT;")
    (d / "indexes.cypher").write_text("CREATE INDEX;")
    return d


def test_schema_directory_exists():
    # Schema directory is at project root, not inside paladino package
    schema_path = Path.cwd() / "schema"
    assert schema_path.exists(), f"Schema directory not found at {schema_path}"


def test_schema_initialization(mock_driver, schema_dir):
    manager = SchemaManager(mock_driver, schema_dir)
    manager.initialize_schema()
    assert mock_driver.session.called


def test_constraints_created(mock_driver, schema_dir):
    manager = SchemaManager(mock_driver, schema_dir)
    constraints = manager.list_constraints()
    assert len(constraints) > 0


def test_indexes_created(mock_driver, schema_dir):
    manager = SchemaManager(mock_driver, schema_dir)
    indexes = manager.list_indexes()
    assert len(indexes) > 0

def test_validate_schema(mock_driver, schema_dir):
    manager = SchemaManager(mock_driver, schema_dir)
    # Stateful Mock returns counts > 0 for SHOW CONSTRAINTS/INDEXES
    assert manager.validate_schema() is True
