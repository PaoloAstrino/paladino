"""
Test data models and validation.
"""

import pytest
from datetime import datetime
from paladino.models import (
    ProvenanceMetadata,
    CompanyNode,
    TenderNode,
    ProjectNode,
    WinsRelationship,
)


def test_provenance_metadata():
    """Test provenance metadata model."""
    prov = ProvenanceMetadata(
        source=["ANAC"],
        dataset_version="2026-01",
        confidence=0.95
    )
    
    assert prov.source == ["ANAC"]
    assert prov.confidence == 0.95
    assert isinstance(prov.retrieval_date, datetime)


def test_company_node_validation():
    """Test company node validation."""
    prov = ProvenanceMetadata(source=["ANAC"], dataset_version="2026-01")
    
    # Valid company
    company = CompanyNode(
        id="test-123",
        labels=["Company"],
        cf="12345678901",
        nome_normalizzato="ACME SRL",
        provenance=prov
    )
    
    assert company.cf == "12345678901"
    assert company.nome_normalizzato == "ACME SRL"


def test_company_cf_validation():
    """Test CF validation."""
    prov = ProvenanceMetadata(source=["ANAC"], dataset_version="2026-01")
    
    # Invalid CF (too short)
    with pytest.raises(ValueError):
        CompanyNode(
            id="test-123",
            labels=["Company"],
            cf="123",  # Too short
            nome_normalizzato="TEST",
            provenance=prov
        )


def test_tender_node():
    """Test tender node model."""
    prov = ProvenanceMetadata(source=["ANAC"], dataset_version="2026-01")
    
    tender = TenderNode(
        id="tender-123",
        labels=["Tender"],
        cig="Z1234567890",
        oggetto="Fornitura servizi IT",
        importo=150000.0,
        provenance=prov
    )
    
    assert tender.cig == "Z1234567890"
    assert tender.importo == 150000.0


def test_project_node():
    """Test project node model."""
    prov = ProvenanceMetadata(source=["OpenCUP"], dataset_version="2026-01")
    
    project = ProjectNode(
        id="project-123",
        labels=["Project"],
        cup="F12345678901",
        titolo="Progetto PNRR",
        fondi_comunitari=["PNRR"],
        provenance=prov
    )
    
    assert project.cup == "F12345678901"
    assert "PNRR" in project.fondi_comunitari


def test_wins_relationship():
    """Test WINS relationship model."""
    wins = WinsRelationship(
        company_cf="12345678901",
        tender_cig="Z1234567890",
        data=datetime.now(),
        importo=150000.0,
        confidence=0.95
    )
    
    assert wins.company_cf == "12345678901"
    assert wins.importo == 150000.0
