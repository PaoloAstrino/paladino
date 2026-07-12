from datetime import datetime

from pydantic import BaseModel, Field


class ExtractedDocument(BaseModel):
    """Normalized textual representation of a source document."""

    source: str
    source_type: str
    title: str = ""
    content: str
    extracted_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    extraction_method: str


class ExtractedEntity(BaseModel):
    """Entity extracted from unstructured text."""

    id: str
    type: str
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    confidence: float = 0.0


class ExtractedRelationship(BaseModel):
    """Relationship extracted between two entities."""

    source_id: str
    target_id: str
    type: str
    confidence: float = 0.0


class NERResult(BaseModel):
    """Structured extraction payload from LLM."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# Connection Discovery Models
# ──────────────────────────────────────────────────────────────


class EntityMatch(BaseModel):
    """A single match between an extracted entity and an existing Neo4j node."""

    extracted_entity_id: str
    extracted_entity_type: str
    matched_neo4j_id: str | None  # None means no match found → CREATE new node
    matched_neo4j_label: str | None  # The Neo4j label of the matched node
    match_method: str  # "exact_cf", "exact_piva", "exact_cup", "exact_cig", "fuzzy_name", "llm_judged", "none"
    confidence: float
    matched_properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class DiscoveredPath(BaseModel):
    """An indirect path discovered between two entities after linking."""

    from_entity: str
    to_entity: str
    path_length: int
    via: list[str]  # Node labels/types along the path
    description: str = ""


class ImplicitConnection(BaseModel):
    """An implicit relationship discovered via graph traversal."""

    entity_a: str
    entity_b: str
    discovery_type: str  # "shared_shareholder", "common_tender", "geographic_cluster", "temporal_pattern"
    confidence: float
    description: str = ""


class ConnectionReport(BaseModel):
    """Summary of connection resolution for one ingestion run."""

    source: str
    processed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    # Counts
    entities_extracted: int = 0
    entities_matched: int = 0
    entities_created: int = 0
    relationships_resolved: int = 0
    relationships_created: int = 0
    implicit_connections_found: int = 0

    # Details
    entity_matches: list[EntityMatch] = Field(default_factory=list)
    discovered_paths: list[DiscoveredPath] = Field(default_factory=list)
    implicit_connections: list[ImplicitConnection] = Field(default_factory=list)

    # Warnings
    warnings: list[str] = Field(default_factory=list)
