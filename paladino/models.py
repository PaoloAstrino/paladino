"""
Core data models and validation schemas.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProvenanceMetadata(BaseModel):
    """Provenance tracking for all nodes and relationships."""

    source: list[str] = Field(description="Data sources (e.g., ['ANAC', 'OpenCUP'])")
    dataset_version: str = Field(description="Version of the source dataset (e.g., '2026-01')")
    retrieval_date: datetime = Field(
        default_factory=datetime.now, description="When the data was retrieved"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, default=1.0, description="Confidence score for this data"
    )


class NodeBase(BaseModel):
    """Base model for all graph nodes."""

    id: str = Field(description="Unique identifier (UUID)")
    labels: list[str] = Field(description="Neo4j labels")
    provenance: ProvenanceMetadata
    valid_from: datetime = Field(default_factory=datetime.utcnow, description="Start of temporal validity")
    valid_to: datetime | None = Field(None, description="End of temporal validity (NULL if current)")
    derived_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Propagated confidence score")


class CompanyNode(NodeBase):
    """Company/Organization node."""

    cf: str = Field(description="Codice Fiscale")
    piva: str | None = Field(None, description="Partita IVA")
    nome_normalizzato: str = Field(description="Normalized company name")
    nome_originale: str | None = None

    # Location
    provincia: str | None = None
    regione: str | None = None
    comune: str | None = None
    cod_istat: str | None = Field(None, description="Official ISTAT code")

    # Classification
    ateco: str | None = Field(None, description="ATECO sector code")
    dimensione: str | None = Field(None, description="Company size: microimpresa, PMI, Grande")

    # Risk & Analytics
    risk_score: float | None = Field(None, ge=0.0, le=1.0)
    anomaly_flags: list[str] = Field(default_factory=list)

    @field_validator("cf")
    @classmethod
    def validate_cf(cls, v: str) -> str:
        """Validate Codice Fiscale format."""
        v = v.strip().upper()
        if len(v) not in [11, 16]:
            raise ValueError("CF must be 11 or 16 characters")
        return v


class TenderNode(NodeBase):
    """ANAC Tender node."""

    cig: str = Field(description="Codice Identificativo Gara")
    ocid: str | None = Field(None, description="OCDS ID")
    oggetto: str = Field(description="Tender description")
    cod_istat: str | None = Field(None, description="Official ISTAT code")
    embedding: list[float] | None = Field(None, description="Vector embedding for semantic search")

    # Financial
    importo: float = Field(gt=0, description="Tender amount in EUR")

    # Procedure
    procedura: str | None = Field(
        None, description="Procurement method: open, restricted, negotiated"
    )
    data_aggiudicazione: datetime | None = None
    data_apertura: datetime | None = None

    # Flags
    red_flags: list[str] = Field(default_factory=list)
    single_bidder: bool = False


class ProjectNode(NodeBase):
    """OpenCUP Project node."""

    cup: str = Field(description="Codice Unico Progetto")
    titolo: str
    descrizione: str | None = None
    cod_istat: str | None = Field(None, description="Official ISTAT code")
    embedding: list[float] | None = Field(None, description="Vector embedding for semantic search")

    # Financing
    importo_previsto: float | None = Field(None, ge=0)
    importo_finanziato: float | None = Field(None, ge=0)
    fondi_comunitari: list[str] = Field(
        default_factory=list, description="EU funds: PNRR, FESR, FSE, etc."
    )

    # Timeline
    data_inizio: datetime | None = None
    data_fine: datetime | None = None
    stato: str | None = Field(
        None, description="Status: In programmazione, In attuazione, Concluso"
    )

    # Location
    regione: str | None = None
    provincia: str | None = None


class PersonNode(NodeBase):
    """Person node (Director, Shareholder, etc.)."""

    cf: str = Field(description="Codice Fiscale")
    nome: str
    cognome: str
    data_nascita: datetime | None = None
    luogo_nascita: str | None = None
    gender: str | None = None

    # Roles and Analysis
    ruoli_istituzionali: list[str] = Field(default_factory=list)
    risk_score: float | None = Field(None, ge=0.0, le=1.0)

    @field_validator("cf")
    @classmethod
    def validate_cf(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 16:
            raise ValueError("Person CF must be 16 characters")
        return v


class AssetNode(NodeBase):
    """Public Asset node (Building, Land, Infrastructure)."""

    id_immobile: str = Field(description="Unique asset identifier")
    nome: str
    tipo: str = Field(description="e.g., School, Hospital, Bridge")
    valore_stimato: float | None = None

    # Geographic
    indirizzo: str | None = None
    comune: str | None = None
    cod_istat: str | None = None
    coordinate: list[float] | None = Field(None, description="[lat, lon]")


class SectorNode(NodeBase):
    """Economic Sector node (ATECO)."""

    cod_ateco: str = Field(description="ATECO code")
    descrizione: str


class VersionNode(NodeBase):
    """Temporal history tracking node."""

    entity_id: str = Field(description="ID of the entity that changed")
    property_changed: str
    old_value: str | None = None
    new_value: str | None = None
    change_date: datetime = Field(default_factory=datetime.now)


class WinsRelationship(BaseModel):
    """Company WINS Tender relationship."""

    company_cf: str
    tender_cig: str
    data: datetime
    importo: float = Field(gt=0)
    percentuale_del_importo: float | None = Field(None, ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class PartOfProjectRelationship(BaseModel):
    """Tender PART_OF_PROJECT relationship."""

    tender_cig: str
    project_cup: str
    confidence: float = Field(ge=0.0, le=1.0)
    matching_method: str = Field(description="Method: explicit, temporal, semantic")
    match_date: datetime = Field(default_factory=datetime.now)


class RepresentsRelationship(BaseModel):
    """Person REPRESENTS Company relationship."""

    person_cf: str
    company_cf: str
    ruolo: str = Field(description="e.g., CEO, Amministratore Unico")
    data_inizio: datetime | None = None
    data_fine: datetime | None = None
    provenance: ProvenanceMetadata


class ShareholderRelationship(BaseModel):
    """Person or Company is SHAREHOLDER_OF a Company."""

    source_id: str  # CF of Person or Company
    target_company_cf: str
    quota: float = Field(ge=0.0, le=100.0, description="Percentage of ownership")
    data_rilevazione: datetime
    provenance: ProvenanceMetadata


class InterventionOnRelationship(BaseModel):
    """Tender or Project is an INTERVENTION_ON an Asset."""

    source_id: str  # CIG or CUP
    asset_id: str
    tipo_lavori: str | None = None
    confidence: float = Field(default=1.0)


class OperatesInRelationship(BaseModel):
    """Company OPERATES_IN an economic Sector."""

    company_cf: str
    cod_ateco: str
    primario: bool = True


class SubcontractsRelationship(BaseModel):
    """(:Company)-[:SUBCONTRACTS_TO]->(:Company) â€” prime contractor âžœ subcontractor.

    Sourced from PNRR_Subappaltatori_Gare.csv.  One relationship per CIG, so the
    same pair can have multiple edges (one per tender).
    """

    winner_cf: str = Field(description="CF of the prime contractor (tender winner)")
    sub_cf: str = Field(description="CF of the subcontractor")
    cig: str = Field(description="CIG that triggered the subcontract")
    cup: str | None = None
    ruolo: str | None = Field(None, description="e.g. 'IMPRESA SINGOLA'")
    ateco: str | None = Field(None, description="ATECO code of the subcontractor")
    importo: float | None = Field(None, ge=0)
    data_estrazione: datetime | None = None
    source: str = Field(default="pnrr_subappaltatori")


class SuppliesToRelationship(BaseModel):
    """(:Company)-[:SUPPLIES_TO]->(:Company) â€” generic supply/delivery relationship.

    Populated by future Registro Imprese / custom CSV imports.  The relationship
    can be one-directional (B delivers to A) and is separate from subcontracting.
    """

    buyer_cf: str = Field(description="CF of the purchasing company")
    supplier_cf: str = Field(description="CF of the supplying company")
    importo: float | None = Field(None, ge=0)
    category: str | None = Field(None, description="Product/service category")
    data: datetime | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = Field(default="unknown")


class FraudPatternNode(NodeBase):
    """
    A named fraud detection result stored as a first-class graph node.

    Created by FraudPatternLibrary detectors and linked to Company/Tender/Buyer
    nodes via FLAGGED_BY relationships, providing full auditability and
    graph-queryable fraud evidence chains.
    """

    pattern_name: str = Field(
        description="Canonical pattern key, e.g. 'bid_rotation'. See FRAUD_PATTERN_NAMES."
    )
    severity: str = Field(description="Risk severity: low | medium | high | critical")
    description: str = Field(
        description="Human-readable description of why this pattern was triggered."
    )
    evidence_summary: str = Field(
        description="JSON-serialised dict of supporting evidence (entity IDs, metrics, etc.)"
    )
    detected_at: datetime = Field(default_factory=datetime.now)
    run_id: str = Field(
        description="UUID of the analysis run, groups all patterns detected together."
    )
    affected_entity_ids: list[str] = Field(
        default_factory=list,
        description="IDs of Company/Tender/Buyer nodes flagged by this pattern.",
    )

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"low", "medium", "high", "critical"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v


class FlaggedByRelationship(BaseModel):
    """Relationship from Company|Tender|Buyer to a FraudPattern node."""

    entity_id: str = Field(description="ID of the flagged entity")
    fraud_pattern_id: str = Field(description="ID of the FraudPattern node")
    detected_at: datetime = Field(default_factory=datetime.now)
    score: float = Field(ge=0.0, le=1.0, description="Severity score contributing to entity risk")
    evidence: str = Field(description="JSON-serialised entity-specific evidence snippet")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Deduplication & Merge Models
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class MergeCandidate(BaseModel):
    """Candidate duplicate for review."""
    entity_id: str
    cf: str | None = None
    piva: str | None = None
    nome_normalizzato: str
    similarity_score: float
    match_reason: str  # "exact_cf", "exact_piva", "fuzzy_name", "geo_phonetic"
    properties: dict


class MergeReviewRequest(BaseModel):
    """Request to review merge candidates."""
    entity_id: str
    limit: int = Field(default=20, ge=1, le=100)
    min_similarity: float = Field(default=0.75, ge=0.0, le=1.0)


class MergeExecuteRequest(BaseModel):
    """Request to execute a merge."""
    source_ids: list[str] = Field(..., min_length=1)
    target_id: str
    dry_run: bool = Field(default=True, description="Preview merge without committing")


class MergeResponse(BaseModel):
    """Merge operation result."""
    status: str  # "success", "dry_run", "error"
    merged_count: int
    target_id: str
    source_ids: list[str]
    properties_merged: dict
    relationships_updated: int = 0
    comments_migrated: int = 0  # Number of comments migrated from source entities
    rollback_id: str | None = None  # For undo operations


class MergeHistoryItem(BaseModel):
    """Historical merge operation for audit."""
    rollback_id: str
    created_at: datetime
    target_id: str
    source_ids: list[str]
    status: str = "COMPLETED"


# =============================================================================
# Comment/Annotation System Models
# =============================================================================

class CommentNode(NodeBase):
    """
    Comment/Annotation node for attaching notes to any entity.
    
    Supports:
    - Threaded conversations via parent_comment_id
    - Entity mentions in content (e.g., @Company:12345678901)
    - Tagging for categorization
    - Soft delete via is_deleted flag
    - Full-text search on content
    """

    entity_id: str = Field(description="ID of the entity this comment is attached to")
    entity_type: str = Field(description="Type of entity: Company, Tender, Project, Person, Asset")
    author: str = Field(description="Author identifier (username or system)")
    content: str = Field(..., min_length=1, max_length=10000, description="Comment content")
    parent_comment_id: str | None = Field(None, description="Parent comment ID for threaded replies")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    mentions: list[str] = Field(default_factory=list, description="Entity IDs mentioned in content")
    is_deleted: bool = Field(default=False, description="Soft delete flag")
    edited_at: datetime | None = Field(None, description="Last edit timestamp")
    
    # Provenance for audit trail
    source: str = Field(default="user", description="Comment source: user, system, import")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        allowed = {"Company", "Tender", "Project", "Person", "Asset", "Buyer", "FraudPattern"}
        if v not in allowed:
            raise ValueError(f"entity_type must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        validated = []
        for tag in v:
            tag = tag.strip().lower()
            if not tag:
                continue
            if len(tag) > 50:
                raise ValueError(f"Tag '{tag[:20]}...' exceeds 50 characters")
            if not tag.replace("-", "").replace("_", "").isalnum():
                raise ValueError(f"Tag '{tag}' contains invalid characters (alphanumeric, -, _ only)")
            validated.append(tag)
        return validated


class CommentCreate(BaseModel):
    """Request model for creating a new comment."""

    entity_id: str = Field(..., description="ID of the entity to comment on")
    entity_type: str = Field(..., description="Type of entity: Company, Tender, Project, Person, Asset")
    content: str = Field(..., min_length=1, max_length=10000, description="Comment content")
    parent_comment_id: str | None = Field(None, description="Parent comment ID for threaded replies")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    author: str | None = Field(None, description="Author identifier (defaults to 'user' if not provided)")
    source: str = Field(default="user", description="Comment source: user, system, import")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        allowed = {"Company", "Tender", "Project", "Person", "Asset", "Buyer", "FraudPattern"}
        if v not in allowed:
            raise ValueError(f"entity_type must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        validated = []
        for tag in v:
            tag = tag.strip().lower()
            if not tag:
                continue
            if len(tag) > 50:
                raise ValueError(f"Tag '{tag[:20]}...' exceeds 50 characters")
            if not tag.replace("-", "").replace("_", "").isalnum():
                raise ValueError(f"Tag '{tag}' contains invalid characters (alphanumeric, -, _ only)")
            validated.append(tag)
        return validated


class CommentUpdate(BaseModel):
    """Request model for updating a comment."""

    content: str | None = Field(None, min_length=1, max_length=10000, description="Updated content")
    tags: list[str] | None = Field(None, description="Updated tags")
    is_deleted: bool | None = Field(None, description="Soft delete flag")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        validated = []
        for tag in v:
            tag = tag.strip().lower()
            if not tag:
                continue
            if len(tag) > 50:
                raise ValueError(f"Tag '{tag[:20]}...' exceeds 50 characters")
            if not tag.replace("-", "").replace("_", "").isalnum():
                raise ValueError(f"Tag '{tag}' contains invalid characters (alphanumeric, -, _ only)")
            validated.append(tag)
        return validated


class CommentResponse(BaseModel):
    """Response model for comment operations."""

    id: str
    entity_id: str
    entity_type: str
    author: str
    content: str
    parent_comment_id: str | None = None
    tags: list[str] = []
    mentions: list[str] = []
    is_deleted: bool = False
    created_at: datetime
    edited_at: datetime | None = None
    source: str = "user"
    confidence: float = 1.0
    provenance: ProvenanceMetadata | None = None
    
    # Computed fields for threaded views
    reply_count: int = 0
    has_replies: bool = False


class CommentListParams(BaseModel):
    """Query parameters for listing comments."""

    entity_id: str | None = Field(None, description="Filter by entity ID")
    entity_type: str | None = Field(None, description="Filter by entity type")
    author: str | None = Field(None, description="Filter by author")
    tag: str | None = Field(None, description="Filter by tag")
    include_deleted: bool = Field(default=False, description="Include deleted comments")
    parent_comment_id: str | None = Field(None, description="Filter by parent (get replies)")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")
    sort_by: str = Field(default="created_at", description="Sort field: created_at, edited_at")
    sort_order: str = Field(default="desc", description="Sort order: asc, desc")

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        allowed = {"Company", "Tender", "Project", "Person", "Asset", "Buyer", "FraudPattern"}
        if v not in allowed:
            raise ValueError(f"entity_type must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, v: str) -> str:
        allowed = {"created_at", "edited_at"}
        if v not in allowed:
            raise ValueError(f"sort_by must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v: str) -> str:
        allowed = {"asc", "desc"}
        if v not in allowed:
            raise ValueError(f"sort_order must be one of {sorted(allowed)}, got {v!r}")
        return v


class CommentSearchRequest(BaseModel):
    """Request model for full-text comment search."""

    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    entity_type: str | None = Field(None, description="Filter by entity type")
    entity_id: str | None = Field(None, description="Filter by entity ID")
    author: str | None = Field(None, description="Filter by author")
    tag: str | None = Field(None, description="Filter by tag")
    include_deleted: bool = Field(default=False, description="Include deleted comments")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum results")

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        allowed = {"Company", "Tender", "Project", "Person", "Asset", "Buyer", "FraudPattern"}
        if v not in allowed:
            raise ValueError(f"entity_type must be one of {sorted(allowed)}, got {v!r}")
        return v


class CommentThreadResponse(BaseModel):
    """Response model for threaded comment conversations."""

    comment: CommentResponse
    replies: list[CommentResponse] = []
    total_replies: int = 0


# =============================================================================
# Risk Score History Tracking Models
# =============================================================================

class RiskTier(str, Enum):
    """Risk tier classification based on score thresholds.
    
    Tiers:
    - HIGH: risk_score >= 0.7
    - MEDIUM: 0.4 <= risk_score < 0.7
    - LOW: risk_score < 0.4
    """
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    
    @classmethod
    def from_score(cls, score: float) -> "RiskTier":
        """Classify a risk score into a tier."""
        if score >= 0.7:
            return cls.HIGH
        elif score >= 0.4:
            return cls.MEDIUM
        else:
            return cls.LOW


class RiskSnapshot(BaseModel):
    """Single risk score snapshot for a company at a point in time."""
    
    company_id: str = Field(description="Company node ID")
    company_name: str | None = Field(None, description="Normalized company name")
    risk_score: float = Field(ge=0.0, le=1.0, description="Risk score (0.0-1.0)")
    risk_tier: RiskTier = Field(description="Risk tier classification")
    change_date: datetime = Field(description="When the snapshot was taken")
    anomaly_flags: list[str] = Field(default_factory=list, description="Active anomaly flags")
    
    @field_validator("risk_tier")
    @classmethod
    def validate_tier_matches_score(cls, v: RiskTier, info) -> RiskTier:
        """Ensure tier is consistent with score (auto-correct if needed)."""
        # Get the score from validation data if available
        data = info.data
        if "risk_score" in data:
            expected_tier = RiskTier.from_score(data["risk_score"])
            # Return the correct tier regardless of input
            return expected_tier
        return v


class TrendDirection(str, Enum):
    """Direction of risk trend."""
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"


class RiskTrendAnalysis(BaseModel):
    """Trend analysis for a company's risk score over time."""
    
    company_id: str = Field(description="Company node ID")
    company_name: str | None = Field(None, description="Normalized company name")
    
    # Current state
    current_score: float = Field(ge=0.0, le=1.0, description="Most recent risk score")
    current_tier: RiskTier = Field(description="Current risk tier")
    
    # Historical state
    previous_score: float | None = Field(None, ge=0.0, le=1.0, description="Previous risk score")
    previous_tier: RiskTier | None = Field(None, description="Previous risk tier")
    
    # Trend metrics
    delta: float = Field(description="Change from previous to current score")
    delta_percent: float | None = Field(None, description="Percentage change (null if previous is 0)")
    direction: TrendDirection = Field(description="Trend direction")
    volatility: float = Field(ge=0.0, description="Standard deviation of scores")
    
    # Range
    max_score: float = Field(ge=0.0, le=1.0, description="Maximum score in period")
    min_score: float = Field(ge=0.0, le=1.0, description="Minimum score in period")
    
    # Alert flags
    tier_crossed: bool = Field(default=False, description="True if tier boundary was crossed")
    significant_increase: bool = Field(default=False, description="True if delta > 0.3")
    
    # Time range
    snapshots_count: int = Field(ge=0, description="Number of snapshots analyzed")
    period_start: datetime | None = Field(None, description="Earliest snapshot date")
    period_end: datetime | None = Field(None, description="Latest snapshot date")


class RiskDistribution(BaseModel):
    """Risk score distribution statistics for a time period."""
    
    period: str = Field(description="Time period identifier (e.g., '2024-Q1')")
    year: int = Field(description="Year")
    quarter: int = Field(ge=1, le=4, description="Quarter (1-4)")
    
    # Distribution by tier
    high_risk_count: int = Field(ge=0, description="Companies with risk >= 0.7")
    medium_risk_count: int = Field(ge=0, description="Companies with 0.4 <= risk < 0.7")
    low_risk_count: int = Field(ge=0, description="Companies with risk < 0.4")
    total_companies: int = Field(ge=0, description="Total companies with risk scores")
    
    # Statistics
    avg_risk_score: float = Field(ge=0.0, le=1.0, description="Average risk score")
    median_risk_score: float = Field(ge=0.0, le=1.0, description="Median risk score")
    stddev_risk_score: float | None = Field(None, ge=0.0, description="Standard deviation")
    
    # Percentages
    high_risk_percent: float = Field(ge=0.0, le=100.0, description="Percentage of high-risk companies")
    medium_risk_percent: float = Field(ge=0.0, le=100.0, description="Percentage of medium-risk companies")
    low_risk_percent: float = Field(ge=0.0, le=100.0, description="Percentage of low-risk companies")


class RiskChangeItem(BaseModel):
    """Company with significant risk score change."""
    
    company_id: str = Field(description="Company node ID")
    company_name: str = Field(description="Normalized company name")
    region: str | None = Field(None, description="Company region")
    ateco: str | None = Field(None, description="ATECO sector code")
    
    # Risk scores
    old_score: float = Field(ge=0.0, le=1.0, description="Previous risk score")
    new_score: float = Field(ge=0.0, le=1.0, description="Current risk score")
    delta: float = Field(description="Change in risk score")
    
    # Tier info
    old_tier: RiskTier = Field(description="Previous risk tier")
    new_tier: RiskTier = Field(description="Current risk tier")
    tier_crossed: bool = Field(description="True if tier changed")
    
    # Classification
    change_type: str = Field(description="Type of change: 'increase' or 'decrease'")
    severity: str = Field(description="Severity: 'critical' if delta > 0.3, else 'moderate'")


class RiskDashboardResponse(BaseModel):
    """Global risk distribution dashboard data."""
    
    generated_at: datetime = Field(default_factory=datetime.now, description="When the dashboard was generated")
    
    # Current snapshot
    total_companies: int = Field(ge=0, description="Total companies in graph")
    companies_with_risk: int = Field(ge=0, description="Companies with risk_score > 0")
    
    # Current distribution
    high_risk_count: int = Field(ge=0, description="Current high-risk companies")
    medium_risk_count: int = Field(ge=0, description="Current medium-risk companies")
    low_risk_count: int = Field(ge=0, description="Current low-risk companies")
    
    # Distribution over time
    distribution_history: list[RiskDistribution] = Field(
        default_factory=list,
        description="Historical risk distribution by quarter"
    )
    
    # Biggest changes
    biggest_increases: list[RiskChangeItem] = Field(
        default_factory=list,
        description="Companies with largest risk increases"
    )
    biggest_decreases: list[RiskChangeItem] = Field(
        default_factory=list,
        description="Companies with largest risk decreases"
    )
    
    # Alerts
    critical_alerts: list[RiskChangeItem] = Field(
        default_factory=list,
        description="Companies with risk increase > 0.3 in last period"
    )
    tier_crossings: list[RiskChangeItem] = Field(
        default_factory=list,
        description="Companies that crossed tier boundaries"
    )


class RiskHistoryResponse(BaseModel):
    """Response for risk history endpoint."""
    
    company_id: str = Field(description="Company node ID")
    company_name: str | None = Field(None, description="Normalized company name")
    current_risk_score: float | None = Field(None, ge=0.0, le=1.0, description="Current risk score")
    current_risk_tier: RiskTier | None = Field(None, description="Current risk tier")
    snapshots: list[RiskSnapshot] = Field(default_factory=list, description="Risk score history")
    snapshots_count: int = Field(ge=0, description="Number of snapshots")


class RiskTrendResponse(BaseModel):
    """Response for risk trend endpoint."""

    company_id: str = Field(description="Company node ID")
    company_name: str | None = Field(None, description="Normalized company name")
    trend: RiskTrendAnalysis
    snapshots: list[RiskSnapshot] = Field(default_factory=list, description="Underlying snapshots")


# =============================================================================
# Alert/Notification System Models
# =============================================================================

class AlertType(str, Enum):
    """Type of alert triggered by the system.
    
    Alert types correspond to different detection mechanisms:
    - risk_spike: Risk score crossed a threshold or tier changed
    - fraud_pattern: Fraud detector matched a known pattern
    - sanction_match: Entity linked to sanctions/adverse media
    - activity_spike: Unusual activity volume/value detected
    - merge_candidate: Duplicate entity found for review
    """
    RISK_SPIKE = "risk_spike"
    FRAUD_PATTERN = "fraud_pattern"
    SANCTION_MATCH = "sanction_match"
    ACTIVITY_SPIKE = "activity_spike"
    MERGE_CANDIDATE = "merge_candidate"


class AlertSeverity(str, Enum):
    """Alert severity levels for prioritization.
    
    Severity determines visual priority and escalation:
    - critical: Immediate attention required (e.g., critical fraud pattern)
    - high: Important, review within 24h (e.g., risk tier crossing)
    - medium: Review within week (e.g., activity spike)
    - low: Informational, review when convenient (e.g., merge candidate)
    - info: System notifications, no action needed
    """
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus(str, Enum):
    """Alert lifecycle status.
    
    Status workflow:
    pending â†’ acknowledged â†’ resolved | dismissed
    
    - pending: New alert, requires attention
    - acknowledged: Analyst is investigating
    - resolved: Issue addressed, closed successfully
    - dismissed: False positive or not actionable
    """
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class AlertRule(str, Enum):
    """Predefined alert rule templates.
    
    These are the built-in rule types that can be customized:
    - risk_score_high: Risk score >= threshold
    - risk_tier_crossing: Risk tier changed (LOWâ†’MEDIUM, MEDIUMâ†’HIGH, etc.)
    - fraud_detector_match: Fraud pattern detected
    - activity_volume_spike: Tender volume increased significantly
    - activity_value_spike: Tender value increased significantly
    - duplicate_entity: Similar entity found (merge candidate)
    - sanction_list_match: Entity on sanctions list
    - adverse_media_match: Entity in adverse media
    """
    RISK_SCORE_HIGH = "risk_score_high"
    RISK_TIER_CROSSING = "risk_tier_crossing"
    FRAUD_DETECTOR_MATCH = "fraud_detector_match"
    ACTIVITY_VOLUME_SPIKE = "activity_volume_spike"
    ACTIVITY_VALUE_SPIKE = "activity_value_spike"
    DUPLICATE_ENTITY = "duplicate_entity"
    SANCTION_LIST_MATCH = "sanction_list_match"
    ADVERSE_MEDIA_MATCH = "adverse_media_match"


class Alert(BaseModel):
    """
    Alert node for proactive fraud detection and monitoring.
    
    Alerts are automatically generated when:
    - Risk score crosses threshold (e.g., Medium â†’ High)
    - New fraud pattern detected (carousel, subcontractor concentration)
    - New sanction/adverse media linked to monitored entity
    - Significant activity spike (tender volume, value)
    - Merge candidate found (duplicate entity)
    
    Alert deduplication:
    - Alerts are deduplicated by hash within 24h window
    - Prevents alert spam from repeated detector runs
    """
    id: str = Field(description="Unique identifier (UUID)")
    type: AlertType = Field(description="Alert type classification")
    severity: AlertSeverity = Field(description="Alert severity level")
    status: AlertStatus = Field(default=AlertStatus.PENDING, description="Alert lifecycle status")
    title: str = Field(..., min_length=1, max_length=200, description="Alert title")
    description: str = Field(..., min_length=1, max_length=2000, description="Alert description")
    
    # Entity linkage
    entity_type: str | None = Field(None, description="Type of entity: Company, Tender, Buyer, Person")
    entity_id: str | None = Field(None, description="ID of the entity this alert is about")
    entity_cf: str | None = Field(None, description="Codice Fiscale of the entity (if applicable)")
    
    # Rule linkage
    rule_id: str | None = Field(None, description="ID of the alert rule that triggered this (optional)")
    triggered_by: str = Field(default="system", description="What triggered this alert: system, rule, manual")
    
    # Metadata
    metadata: dict = Field(default_factory=dict, description="Additional context data (JSON)")
    alert_hash: str | None = Field(None, description="Hash for deduplication (same alert within 24h)")
    
    # Timestamps
    acknowledged_at: datetime | None = Field(None, description="When alert was acknowledged")
    resolved_at: datetime | None = Field(None, description="When alert was resolved")
    dismissed_at: datetime | None = Field(None, description="When alert was dismissed")
    created_at: datetime = Field(default_factory=datetime.now, description="When alert was created")
    
    # Provenance
    provenance: ProvenanceMetadata | None = Field(None, description="Provenance metadata")


class AlertCreate(BaseModel):
    """Request model for creating a new alert."""
    
    type: AlertType = Field(description="Alert type")
    severity: AlertSeverity = Field(description="Alert severity")
    title: str = Field(..., min_length=1, max_length=200, description="Alert title")
    description: str = Field(..., min_length=1, max_length=2000, description="Alert description")
    
    # Entity linkage (optional)
    entity_type: str | None = Field(None, description="Type of entity")
    entity_id: str | None = Field(None, description="ID of the entity")
    entity_cf: str | None = Field(None, description="Codice Fiscale")
    
    # Rule linkage (optional)
    rule_id: str | None = Field(None, description="Rule ID if triggered by rule")
    triggered_by: str = Field(default="system", description="What triggered this alert")
    
    # Additional context
    metadata: dict = Field(default_factory=dict, description="Additional context data")
    skip_dedup: bool = Field(default=False, description="Skip deduplication check (for manual alerts)")


class AlertUpdate(BaseModel):
    """Request model for updating an alert."""
    
    title: str | None = Field(None, min_length=1, max_length=200, description="Updated title")
    description: str | None = Field(None, min_length=1, max_length=2000, description="Updated description")
    metadata: dict | None = Field(None, description="Updated metadata")


class AlertRuleCreate(BaseModel):
    """Request model for creating a custom alert rule."""
    
    name: str = Field(..., min_length=1, max_length=100, description="Rule name")
    description: str = Field(..., min_length=1, max_length=500, description="Rule description")
    alert_type: AlertType = Field(description="Type of alert this rule generates")
    trigger_condition: str = Field(..., min_length=1, max_length=2000, description="Trigger condition (Cypher or expression)")
    threshold: float | None = Field(None, description="Numeric threshold for triggering")
    severity: AlertSeverity = Field(default=AlertSeverity.MEDIUM, description="Default severity for alerts from this rule")
    enabled: bool = Field(default=True, description="Whether rule is active")


class AlertRuleResponse(BaseModel):
    """Response model for alert rule operations."""
    
    id: str
    name: str
    description: str
    alert_type: AlertType
    trigger_condition: str
    threshold: float | None
    severity: AlertSeverity
    enabled: bool
    created_at: datetime
    updated_at: datetime | None = None


class AlertListParams(BaseModel):
    """Query parameters for listing alerts with filters."""
    
    status: AlertStatus | None = Field(None, description="Filter by status")
    type: AlertType | None = Field(None, description="Filter by type")
    severity: AlertSeverity | None = Field(None, description="Filter by severity")
    entity_id: str | None = Field(None, description="Filter by entity ID")
    entity_type: str | None = Field(None, description="Filter by entity type")
    entity_cf: str | None = Field(None, description="Filter by Codice Fiscale")
    rule_id: str | None = Field(None, description="Filter by rule ID")
    
    # Date range
    date_from: datetime | None = Field(None, description="Filter alerts from this date")
    date_to: datetime | None = Field(None, description="Filter alerts until this date")
    
    # Pagination
    limit: int = Field(default=50, ge=1, le=200, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")
    
    # Sorting
    sort_by: str = Field(default="created_at", description="Sort field: created_at, severity, type")
    sort_order: str = Field(default="desc", description="Sort order: asc, desc")
    
    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, v: str) -> str:
        allowed = {"created_at", "severity", "type", "acknowledged_at", "resolved_at"}
        if v not in allowed:
            raise ValueError(f"sort_by must be one of {sorted(allowed)}, got {v!r}")
        return v
    
    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v: str) -> str:
        allowed = {"asc", "desc"}
        if v not in allowed:
            raise ValueError(f"sort_order must be one of {sorted(allowed)}, got {v!r}")
        return v


class AlertBulkAction(BaseModel):
    """Request model for bulk alert actions."""
    
    alert_ids: list[str] = Field(..., min_length=1, max_length=100, description="List of alert IDs to update")
    action: str = Field(..., description="Action to perform: acknowledge, resolve, dismiss")
    
    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        allowed = {"acknowledge", "resolve", "dismiss"}
        if v not in allowed:
            raise ValueError(f"action must be one of {sorted(allowed)}, got {v!r}")
        return v


class AlertStatistics(BaseModel):
    """Alert statistics for dashboard."""
    
    # Counts by status
    pending_count: int = Field(ge=0, description="Pending alerts")
    acknowledged_count: int = Field(ge=0, description="Acknowledged alerts")
    resolved_count: int = Field(ge=0, description="Resolved alerts")
    dismissed_count: int = Field(ge=0, description="Dismissed alerts")
    
    # Counts by type
    risk_spike_count: int = Field(ge=0, description="Risk spike alerts")
    fraud_pattern_count: int = Field(ge=0, description="Fraud pattern alerts")
    sanction_match_count: int = Field(ge=0, description="Sanction match alerts")
    activity_spike_count: int = Field(ge=0, description="Activity spike alerts")
    merge_candidate_count: int = Field(ge=0, description="Merge candidate alerts")
    
    # Counts by severity
    critical_count: int = Field(ge=0, description="Critical severity alerts")
    high_count: int = Field(ge=0, description="High severity alerts")
    medium_count: int = Field(ge=0, description="Medium severity alerts")
    low_count: int = Field(ge=0, description="Low severity alerts")
    info_count: int = Field(ge=0, description="Info severity alerts")
    
    # Time-based
    last_24h_count: int = Field(ge=0, description="Alerts in last 24 hours")
    last_7d_count: int = Field(ge=0, description="Alerts in last 7 days")
    
    generated_at: datetime = Field(default_factory=datetime.now, description="When statistics were generated")


class AlertGeneratorResult(BaseModel):
    """Result from running alert generators."""
    
    generator_name: str = Field(description="Name of the generator that ran")
    alerts_created: int = Field(ge=0, description="Number of new alerts created")
    alerts_deduplicated: int = Field(ge=0, description="Number of alerts skipped (duplicate)")
    execution_time_ms: float = Field(ge=0, description="Execution time in milliseconds")
    errors: list[str] = Field(default_factory=list, description="Any errors encountered")


class AlertGenerationReport(BaseModel):
    """Comprehensive report from running all alert generators."""

    run_id: str = Field(description="Unique run identifier")
    started_at: datetime = Field(description="When generation started")
    completed_at: datetime = Field(description="When generation completed")
    total_alerts_created: int = Field(ge=0, description="Total new alerts created")
    total_alerts_deduplicated: int = Field(ge=0, description="Total duplicates skipped")
    generators: list[AlertGeneratorResult] = Field(default_factory=list, description="Results per generator")
    errors: list[str] = Field(default_factory=list, description="Any errors encountered")


# =============================================================================
# Investigation Notebook System Models
# =============================================================================

class NotebookCellType(str, Enum):
    """Type of notebook cell."""
    MARKDOWN = "markdown"
    CYPHER_QUERY = "cypher_query"
    RESULTS_TABLE = "results_table"
    VISUALIZATION = "visualization"
    CODE = "code"
    CONNECTION_INSIGHT = "connection_insight"  # Auto-discovers connections between linked entities


class NotebookStatus(str, Enum):
    """Notebook lifecycle status."""
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class NotebookExportFormat(str, Enum):
    """Export format options."""
    JSON = "json"
    MARKDOWN = "markdown"
    HTML = "html"


class Notebook(BaseModel):
    """Investigation notebook container."""
    id: str
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    status: NotebookStatus = Field(default=NotebookStatus.DRAFT)
    template_name: str | None = Field(None, description="Template this was created from")
    linked_entity_ids: list[str] = Field(default_factory=list)
    linked_alert_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    cell_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    author: str = Field(default="user")


class NotebookCreate(BaseModel):
    """Request model for creating a notebook."""
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    template_name: str | None = None
    linked_entity_ids: list[str] = Field(default_factory=list)
    linked_alert_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    author: str = Field(default="user")


class NotebookUpdate(BaseModel):
    """Request model for updating a notebook."""
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    status: NotebookStatus | None = None
    tags: list[str] | None = None
    linked_entity_ids: list[str] | None = None
    linked_alert_ids: list[str] | None = None


class NotebookCell(BaseModel):
    """Single cell in a notebook."""
    id: str
    notebook_id: str
    cell_type: NotebookCellType
    content: str = Field(default="", description="Cell content (markdown or Cypher)")
    position: int = Field(ge=0, description="Order in notebook")
    title: str | None = Field(None, max_length=200)
    execution_result: dict | None = Field(None, description="Last execution output")
    execution_count: int = Field(default=0, ge=0)
    last_executed_at: datetime | None = None
    linked_entity_id: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class NotebookCellCreate(BaseModel):
    """Request model for creating a cell."""
    cell_type: NotebookCellType
    content: str = Field(default="")
    position: int | None = Field(None, ge=0, description="Auto-append if None")
    title: str | None = Field(None, max_length=200)
    linked_entity_id: str | None = None


class NotebookCellUpdate(BaseModel):
    """Request model for updating a cell."""
    content: str | None = None
    cell_type: NotebookCellType | None = None
    title: str | None = Field(None, max_length=200)
    linked_entity_id: str | None = None


class NotebookResponse(BaseModel):
    """Response model for notebook operations."""
    id: str
    title: str
    description: str
    status: NotebookStatus
    template_name: str | None
    linked_entity_ids: list[str]
    linked_alert_ids: list[str]
    tags: list[str]
    cell_count: int
    cells: list[NotebookCell] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None
    completed_at: datetime | None
    author: str


class NotebookListParams(BaseModel):
    """Query parameters for listing notebooks."""
    status: NotebookStatus | None = None
    template_name: str | None = None
    tag: str | None = None
    entity_id: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    sort_by: str = Field(default="updated_at")
    sort_order: str = Field(default="desc")

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, v: str) -> str:
        allowed = {"updated_at", "created_at", "title", "status"}
        if v not in allowed:
            raise ValueError(f"sort_by must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v: str) -> str:
        allowed = {"asc", "desc"}
        if v not in allowed:
            raise ValueError(f"sort_order must be one of {sorted(allowed)}, got {v!r}")
        return v


class NotebookCellReorder(BaseModel):
    """Request model for reordering cells."""
    cell_positions: list[dict] = Field(
        ...,
        min_length=1,
        description="List of {cell_id: str, position: int} dicts",
    )


class NotebookCellExecuteResponse(BaseModel):
    """Response model for cell execution."""
    cell_id: str
    cell_type: NotebookCellType
    execution_count: int
    execution_result: dict | None = None
    last_executed_at: datetime | None = None
    error: str | None = None


class NotebookExecuteAllResponse(BaseModel):
    """Response model for executing all cells."""
    notebook_id: str
    total_cells: int
    executed_count: int
    failed_count: int
    results: list[NotebookCellExecuteResponse] = Field(default_factory=list)


class NotebookChangeHistoryItem(BaseModel):
    """Single change history entry."""
    changed_at: datetime
    change_type: str = Field(description="Type of change: cell_added, cell_updated, cell_deleted, cell_executed, metadata_updated")
    cell_id: str | None = None
    details: dict = Field(default_factory=dict)


class NotebookChangeHistoryResponse(BaseModel):
    """Response model for notebook change history."""
    notebook_id: str
    changes: list[NotebookChangeHistoryItem] = Field(default_factory=list)
    total_changes: int = 0


# =============================================================================
# Graph Visualization System Models
# =============================================================================

class GraphNodeType(str, Enum):
    """Type of graph node for styling/filtering."""
    COMPANY = "company"
    TENDER = "tender"
    PROJECT = "project"
    PERSON = "person"
    BUYER = "buyer"
    ASSET = "asset"
    FRAUD_PATTERN = "fraud_pattern"
    COMMENT = "comment"
    ALERT = "alert"


class GraphEdgeType(str, Enum):
    """Type of graph edge for styling/filtering."""
    WINS = "wins"
    ISSUES = "issues"
    PART_OF = "part_of"
    REPRESENTS = "represents"
    OWNS = "owns"
    FLAGGED_BY = "flagged_by"
    HAS_ALERT = "has_alert"
    HAS_TEMPORAL_ALERT = "has_temporal_alert"
    ANNOTATES = "annotates"
    SAME_AS = "same_as"
    RELATED_TO = "related_to"


class GraphLayout(str, Enum):
    """Layout algorithm for node positioning."""
    FORCE_DIRECTED = "force_directed"
    HIERARCHICAL = "hierarchical"
    CIRCULAR = "circular"
    RADIAL = "radial"


class GraphExportFormat(str, Enum):
    """Export format for graph data."""
    JSON = "json"
    GRAPHML = "graphml"
    SVG = "svg"
    PNG = "png"


class GraphNode(BaseModel):
    """Node in the visualization graph."""
    id: str
    label: str = Field(..., description="Display label")
    node_type: GraphNodeType = Field(description="Type for styling")
    properties: dict = Field(default_factory=dict, description="Entity properties")
    risk_score: float | None = Field(None, ge=0.0, le=1.0, description="Risk score for coloring")
    centrality: float | None = Field(None, ge=0.0, le=1.0, description="Centrality for sizing")
    x: float | None = Field(None, description="Layout X position")
    y: float | None = Field(None, description="Layout Y position")
    size: float = Field(default=20.0, ge=5.0, le=100.0, description="Node size")
    color: str = Field(default="#666666", description="Node color (hex)")
    comment_count: int = Field(default=0, ge=0)
    alert_count: int = Field(default=0, ge=0)


class GraphEdge(BaseModel):
    """Edge in the visualization graph."""
    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    edge_type: GraphEdgeType = Field(description="Type for styling")
    label: str = Field(default="", description="Edge label")
    weight: float = Field(default=1.0, gt=0, description="Edge thickness")
    properties: dict = Field(default_factory=dict)
    color: str = Field(default="#cccccc", description="Edge color (hex)")


class GraphFilter(BaseModel):
    """Filter criteria for graph queries."""
    node_types: list[GraphNodeType] = Field(default_factory=list, description="Include these types")
    edge_types: list[GraphEdgeType] = Field(default_factory=list, description="Include these relationships")
    min_risk_score: float | None = Field(None, ge=0.0, le=1.0, description="Minimum risk score")
    max_risk_score: float | None = Field(None, ge=0.0, le=1.0, description="Maximum risk score")
    date_from: datetime | None = None
    date_to: datetime | None = None
    entity_ids: list[str] = Field(default_factory=list, description="Specific entities to include")
    exclude_fraud_patterns: list[str] = Field(default_factory=list, description="Pattern names to exclude")


class GraphQuery(BaseModel):
    """Request model for graph queries."""
    center_entity_id: str | None = Field(None, description="Start from this entity")
    depth: int = Field(default=2, ge=1, le=5, description="Traversal depth (max 5)")
    max_nodes: int = Field(default=500, ge=10, le=1000, description="Maximum nodes to return")
    filters: GraphFilter = Field(default_factory=GraphFilter)
    layout: GraphLayout = Field(default=GraphLayout.FORCE_DIRECTED)
    style_by_risk: bool = Field(default=True, description="Color nodes by risk score")
    style_by_centrality: bool = Field(default=True, description="Size nodes by centrality")


class GraphStatistics(BaseModel):
    """Graph statistics."""
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    density: float = Field(ge=0.0, le=1.0)
    avg_degree: float = Field(ge=0)
    max_degree: int = Field(ge=0)
    connected_components: int = Field(ge=0)
    avg_clustering: float = Field(ge=0.0, le=1.0)
    node_types: dict = Field(default_factory=dict, description="Count by type")
    edge_types: dict = Field(default_factory=dict, description="Count by type")


class GraphResponse(BaseModel):
    """Response model for graph queries."""
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    statistics: GraphStatistics | None = Field(None, description="Graph stats")
    layout: GraphLayout = Field(description="Layout algorithm used")
    query_time_ms: float = Field(ge=0, description="Query execution time")
    truncated: bool = Field(default=False, description="True if results were limited")
    center_entity_id: str | None = None


class GraphPathRequest(BaseModel):
    """Request for finding path between entities."""
    source_id: str = Field(..., description="Start entity ID")
    target_id: str = Field(..., description="End entity ID")
    max_depth: int = Field(default=5, ge=1, le=10)
    edge_types: list[GraphEdgeType] = Field(default_factory=list, description="Allowed relationship")


class GraphPathResponse(BaseModel):
    """Response for path finding."""
    path: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    length: int = Field(ge=0, description="Number of hops")
    found: bool = Field(description="Whether path exists")


class GraphTemplate(BaseModel):
    """Predefined graph view template."""
    name: str
    description: str
    center_type: str | None = Field(None, description="Entity type to center on")
    depth: int = Field(default=2, ge=1, le=5)
    node_types: list[GraphNodeType] = Field(default_factory=list)
    edge_types: list[GraphEdgeType] = Field(default_factory=list)
    style_by_risk: bool = Field(default=True)
    max_nodes: int = Field(default=500, ge=10, le=1000)


class GraphStyleRequest(BaseModel):
    """Request model for applying styling rules."""
    style_by_risk: bool = Field(default=True, description="Color nodes by risk score")
    style_by_centrality: bool = Field(default=True, description="Size nodes by centrality")
    style_by_type: bool = Field(default=False, description="Shape/color by type")
    layout: GraphLayout = Field(default=GraphLayout.FORCE_DIRECTED)


class GraphExportRequest(BaseModel):
    """Request model for graph export."""
    format: GraphExportFormat = Field(default=GraphExportFormat.JSON)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    filename: str | None = Field(None, description="Output filename (without extension)")

# =============================================================================
# Temporal / Time-Travel Models
# =============================================================================

class TemporalQueryRequest(BaseModel):
    """Request model for AS OF queries."""
    question: str = Field(..., description="Natural language question")
    as_of: datetime = Field(..., description="Point in time to query the data as of")
    limit: int = Field(default=10, ge=1, le=100)

class TemporalAlertNode(NodeBase):
    """Persistent alert for significant temporal shifts."""
    alert_type: str = Field(description="e.g., risk_spike, community_migration")
    entity_id: str
    old_value: Any
    new_value: Any
    delta: float | None = None
    date_a: datetime
    date_b: datetime
    severity: str = Field(default="medium")


class DiffRequest(BaseModel):
    """Request model for comparing entity states."""
    entity_id: str = Field(..., description="ID of the entity (CF, CIG, CUP or UUID)")
    date_a: datetime = Field(..., description="First date (base state)")
    date_b: datetime = Field(..., description="Second date (target state)")

class PropertyChange(BaseModel):
    """Single property change details."""
    old: Any | None = None
    new: Any | None = None

class DiffDelta(BaseModel):
    """Delta between two entity states, including structural changes."""
    added: dict[str, Any] = Field(default_factory=dict, description="Added properties")
    removed: dict[str, Any] = Field(default_factory=dict, description="Removed properties")
    changed: dict[str, PropertyChange] = Field(default_factory=dict, description="Changed properties")
    
    # Structural changes (1-hop)
    added_links: list[dict] = Field(default_factory=list, description="New connections: [{type, target_id, props}]")
    removed_links: list[dict] = Field(default_factory=list, description="Removed connections")
    changed_links: list[dict] = Field(default_factory=list, description="Connections with changed metadata")

class DiffResponse(BaseModel):
    """Response model for entity diff."""
    entity_id: str
    date_a: datetime
    date_b: datetime
    diff: DiffDelta
    has_changes: bool
