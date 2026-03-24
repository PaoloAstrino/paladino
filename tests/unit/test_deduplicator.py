from unittest.mock import Mock

import pytest

from paladino.db import Neo4jConnection
from paladino.etl.deduplicator import EntityDeduplicator
from paladino.llm_manager import LLMManager


@pytest.fixture
def mock_neo4j_driver():
    mock_driver = Mock(spec=Neo4jConnection)
    mock_driver.run_query.return_value = []
    return mock_driver


@pytest.fixture
def mock_llm_manager():
    mock_llm = Mock(spec=LLMManager)
    return mock_llm


@pytest.fixture
def deduplicator(mock_neo4j_driver, mock_llm_manager):
    return EntityDeduplicator(mock_neo4j_driver, mock_llm_manager, fuzzy_threshold=0.7)


def test_block_entities_company(deduplicator):
    """Test multi-pass blocking logic."""
    companies = [
        {"id": 1, "nome_originale": "ABC SRL", "nome_normalizzato": "ABC", "cod_istat": "123"},
        {"id": 2, "nome_originale": "ABC SPA", "nome_normalizzato": "ABC", "cod_istat": "123"},
        {"id": 3, "nome_originale": "XYZ SRL", "nome_normalizzato": "XYZ", "cod_istat": "456"},
        {"id": 4, "nome_originale": "ACME Ltd", "nome_normalizzato": "ACME", "cod_istat": "789"},
    ]

    blocked = deduplicator.block_entities("Company", companies)

    # multi-pass creates blocks for PHON, GEO, and CF if present
    assert len(blocked) >= 3
    # Check that geo-block exists
    assert any(k.startswith("GEO_123") for k in blocked.keys())


def test_weighted_scoring(deduplicator):
    """Test the new weighted scoring system."""
    e1 = {"id": 1, "nome_normalizzato": "ACME CORP", "cod_istat": "123"}
    e2 = {"id": 2, "nome_normalizzato": "ACME CORP", "cod_istat": "123"}

    # 1.0 because names match (0.7) + geo match (0.3)
    score = deduplicator.calculate_match_score(e1, e2, "Company")
    assert score == 1.0

    # CF match is absolute 1.0
    e3 = {"id": 3, "cf": "MATCH"}
    e4 = {"id": 4, "cf": "MATCH"}
    assert deduplicator.calculate_match_score(e3, e4, "Company") == 1.0


def test_deduplicate_entities_tiered_policy(deduplicator):
    """Test tiered merge policy."""
    companies = [
        {"id": 1, "nome_normalizzato": "ABC COMPANY", "cod_istat": "123", "cf": "CF1"},
        {"id": 2, "nome_normalizzato": "ABC COMPANY", "cod_istat": "123", "cf": "CF1"},
    ]

    merges = deduplicator.deduplicate_entities("Company", companies)

    assert len(merges) == 1
    assert merges[0][2] == "exact_cf_match"


def test_llm_disambiguate_pair_yes(deduplicator):
    # LLM Mock returns YES
    deduplicator.llm_manager.chat.return_value = "YES"
    entity1 = {"id": 1, "nome_normalizzato": "Company A"}
    entity2 = {"id": 2, "nome_normalizzato": "Company A S.r.l."}

    result = deduplicator._llm_disambiguate_pair(entity1, entity2, "Company")
    assert result is True


def test_merge_nodes_and_relationships(deduplicator):
    deduplicator.driver.run_query = Mock()
    deduplicator._merge_nodes_and_relationships(2, 1, ["Company"], "reason")
    assert deduplicator.driver.run_query.called
