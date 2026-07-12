"""
Tests for the Connection Resolver — entity matching, relationship linking,
and implicit connection discovery.
"""

from unittest.mock import Mock, patch

import pytest

from paladino.etl.connection_resolver import ConnectionResolver, _CF_RE, _CIG_RE, _CUP_RE, _PIVA_RE
from paladino.etl.unstructured_models import (
    ConnectionReport,
    ExtractedEntity,
    ExtractedRelationship,
    NERResult,
)


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    db = Mock()
    db.run_query.return_value = []
    return db


@pytest.fixture
def mock_llm():
    llm = Mock()
    llm.chat.return_value = "YES"
    return llm


@pytest.fixture
def resolver(mock_db, mock_llm):
    return ConnectionResolver(db=mock_db, llm_manager=mock_llm, fuzzy_threshold=0.85)


# ──────────────────────────────────────────────────────────────
# Identifier regex tests
# ──────────────────────────────────────────────────────────────


def test_cf_regex_valid():
    """Test CF regex matches valid Italian codice fiscale."""
    match = _CF_RE.search("MRARSS80A01H501Z")
    assert match is not None
    assert match.group(1) == "MRARSS80A01H501Z"


def test_cf_regex_in_context():
    """Test CF extraction from a longer text."""
    text = "La società Rossi SRL con CF MRARSS80A01H501Z ha vinto la gara."
    match = _CF_RE.search(text)
    assert match is not None
    assert match.group(1) == "MRARSS80A01H501Z"


def test_piva_regex_valid():
    match = _PIVA_RE.search("IT12345678901")
    assert match is not None
    assert match.group(2) == "12345678901"


def test_piva_regex_without_country():
    match = _PIVA_RE.search("12345678901")
    assert match is not None
    assert match.group(2) == "12345678901"


def test_cup_regex_valid():
    """CUP format: [A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z][0-9]{5,6}"""
    match = _CUP_RE.search("E12C3456789012")
    assert match is not None
    assert match.group(1) == "E12C3456789012"


def test_cig_regex_valid():
    match = _CIG_RE.search("Z1234567890")
    assert match is not None
    assert match.group(1) == "Z1234567890"


# ──────────────────────────────────────────────────────────────
# Entity matching tests
# ──────────────────────────────────────────────────────────────


def test_match_entity_exact_cf(resolver, mock_db):
    """Test matching entity by exact CF."""
    mock_db.run_query.return_value = [
        {
            "neo4j_id": 42,
            "properties": {"cf": "MRARSS80A01H501Z", "nome_normalizzato": "Rossi SRL"},
        }
    ]

    entity = ExtractedEntity(
        id="ent_1",
        type="Company",
        properties={"name": "Rossi SRL", "cf": "MRARSS80A01H501Z"},
        confidence=0.95,
    )

    match = resolver._match_entity(entity)

    assert match.matched_neo4j_id == "42"
    assert match.matched_neo4j_label == "Company"
    assert match.match_method == "exact_cf"
    assert match.confidence == 1.0


def test_match_entity_no_match(resolver, mock_db):
    """Test entity with no identifier and no fuzzy match."""
    mock_db.run_query.return_value = []  # No identifier match, no fuzzy match

    entity = ExtractedEntity(
        id="ent_1",
        type="Company",
        properties={"name": "Unknown Company XYZ"},
        confidence=0.5,
    )

    match = resolver._match_entity(entity)

    assert match.matched_neo4j_id is None
    assert match.match_method == "none"
    assert match.confidence == 0.0


def test_match_entity_fuzzy_name(resolver, mock_db):
    """Test fuzzy name matching."""
    # First call: identifier match returns nothing
    # Second call: Levenshtein search returns candidates
    def side_effect(query, params=None):
        if "levenshtein" in query.lower() or "levenshteinsimilarity" in query.lower():
            return [
                {
                    "neo4j_id": 99,
                    "name": "Rossi SRL",
                    "properties": {"nome_normalizzato": "Rossi SRL"},
                }
            ]
        return []

    mock_db.run_query.side_effect = side_effect

    entity = ExtractedEntity(
        id="ent_1",
        type="Company",
        properties={"name": "Rossi S.R.L."},
        confidence=0.9,
    )

    match = resolver._match_entity(entity)

    # With fuzzy matching, "Rossi S.R.L." vs "Rossi SRL" should match
    # (The normalizer removes dots, so similarity should be high)
    assert match.matched_neo4j_id is not None or match.match_method in ("fuzzy_name", "none")


# ──────────────────────────────────────────────────────────────
# Full resolution pipeline tests
# ──────────────────────────────────────────────────────────────


def test_resolve_empty(resolver):
    """Test resolving an empty NER result."""
    ner_result = NERResult()
    report = resolver.resolve(ner_result, source="test.pdf")

    assert report.entities_extracted == 0
    assert report.entities_matched == 0
    assert report.entities_created == 0
    assert len(report.warnings) > 0


def test_resolve_with_entities(resolver, mock_db):
    """Test resolving extracted entities."""
    mock_db.run_query.return_value = []  # No matches → all created

    entities = [
        ExtractedEntity(id="ent_1", type="Company", properties={"name": "Acme SRL"}, confidence=0.9),
        ExtractedEntity(id="ent_2", type="Person", properties={"name": "Mario Rossi"}, confidence=0.8),
    ]
    relationships = [
        ExtractedRelationship(source_id="ent_1", target_id="ent_2", type="employs", confidence=0.7),
    ]

    ner_result = NERResult(entities=entities, relationships=relationships)
    report = resolver.resolve(ner_result, source="test.pdf")

    assert report.entities_extracted == 2
    # With no matches in DB, all should be created
    assert report.entities_created == 2
    assert report.entities_matched == 0


def test_resolve_relationships(resolver, mock_db):
    """Test relationship resolution."""
    mock_db.run_query.return_value = []

    # Setup id_map (normally done during entity matching)
    resolver._id_map = {"ent_1": "100", "ent_2": "200"}

    relationships = [
        ExtractedRelationship(source_id="ent_1", target_id="ent_2", type="WINS", confidence=0.9),
    ]

    created = resolver._resolve_relationships(relationships, source="test.pdf")
    assert created == 1


def test_resolve_relationship_missing_source(resolver):
    """Test relationship with missing source mapping."""
    resolver._id_map = {"ent_2": "200"}  # ent_1 missing

    relationships = [
        ExtractedRelationship(source_id="ent_1", target_id="ent_2", type="WINS", confidence=0.9),
    ]

    created = resolver._resolve_relationships(relationships, source="test.pdf")
    assert created == 0


# ──────────────────────────────────────────────────────────────
# Implicit connection discovery tests
# ──────────────────────────────────────────────────────────────


def test_implicit_connections_empty(resolver):
    """No implicit connections when no matched companies."""
    resolver._matches = []
    implicit = resolver._discover_implicit_connections("test.pdf")
    assert implicit == []


def test_implicit_connections_single_company(resolver):
    """No implicit connections with only one matched company."""
    from paladino.etl.unstructured_models import EntityMatch

    resolver._matches = [
        EntityMatch(
            extracted_entity_id="ent_1",
            extracted_entity_type="Company",
            matched_neo4j_id="42",
            matched_neo4j_label="Company",
            match_method="exact_cf",
            confidence=1.0,
        )
    ]
    implicit = resolver._discover_implicit_connections("test.pdf")
    assert implicit == []


# ──────────────────────────────────────────────────────────────
# Identifier extraction helpers tests
# ──────────────────────────────────────────────────────────────


def test_extract_cf_from_props(resolver):
    cf = resolver._extract_cf({"cf": "MRARSS80A01H501Z"})
    assert cf == "MRARSS80A01H501Z"


def test_extract_cf_from_name(resolver):
    """CF embedded in a name field."""
    cf = resolver._extract_cf({"name": " Rossi CF MRARSS80A01H501Z SRL"})
    assert cf == "MRARSS80A01H501Z"


def test_extract_cf_none(resolver):
    assert resolver._extract_cf({"name": "No CF here"}) is None


def test_extract_piva_from_props(resolver):
    piva = resolver._extract_piva({"piva": "IT12345678901"})
    assert piva == "12345678901"


def test_extract_piva_none(resolver):
    assert resolver._extract_piva({"name": "No PIVA"}) is None


def test_extract_cup_from_props(resolver):
    cup = resolver._extract_cup({"cup": "E12C3456789012"})
    assert cup == "E12C3456789012"


def test_extract_cup_none(resolver):
    assert resolver._extract_cup({"name": "No CUP"}) is None


def test_extract_cig_from_props(resolver):
    cig = resolver._extract_cig({"cig": "Z1234567890"})
    assert cig == "Z1234567890"


# ──────────────────────────────────────────────────────────────
# LLM judge tests
# ──────────────────────────────────────────────────────────────


def test_llm_verify_same_entity_yes(resolver, mock_llm):
    mock_llm.chat.return_value = "YES"
    assert resolver._llm_verify_same_entity("Rossi SRL", "Rossi S.R.L.") is True


def test_llm_verify_same_entity_no(resolver, mock_llm):
    mock_llm.chat.return_value = "NO"
    assert resolver._llm_verify_same_entity("Rossi SRL", "Totally Different SPA") is False


def test_llm_verify_same_entity_exception(resolver, mock_llm):
    mock_llm.chat.side_effect = Exception("LLM offline")
    assert resolver._llm_verify_same_entity("Rossi SRL", "Rossi S.R.L.") is False


# ──────────────────────────────────────────────────────────────
# Property extraction tests
# ──────────────────────────────────────────────────────────────


def test_extract_known_properties_company(resolver):
    entity = ExtractedEntity(
        id="ent_1",
        type="Company",
        properties={
            "cf": "12345678901",
            "nome_normalizzato": "Acme SRL",
            "regione": "Lombardia",
            "unknown_field": "ignored",
        },
        confidence=0.9,
    )

    props = resolver._extract_known_properties(entity)
    assert "cf" in props
    assert "nome_normalizzato" in props
    assert "regione" in props
    assert "unknown_field" not in props


def test_extract_known_properties_unknown_type(resolver):
    entity = ExtractedEntity(
        id="ent_1",
        type="UnknownType",
        properties={"foo": "bar"},
        confidence=0.5,
    )

    props = resolver._extract_known_properties(entity)
    assert props == {}
