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
