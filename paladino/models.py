"""
Core data models and validation schemas.
"""

from datetime import datetime

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
    """(:Company)-[:SUBCONTRACTS_TO]->(:Company) — prime contractor ➜ subcontractor.

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
    """(:Company)-[:SUPPLIES_TO]->(:Company) — generic supply/delivery relationship.

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
