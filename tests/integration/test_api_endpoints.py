"""
Integration tests for FastAPI endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from paladino.app.api import app
import json


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


def test_root_endpoint(client):
    """Test root endpoint returns API info."""
    response = client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "name" in data
    assert "version" in data
    assert "endpoints" in data


def test_health_endpoint_success(client, clean_neo4j):
    """Test health endpoint with healthy Neo4j."""
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "healthy"
    assert data["neo4j"] == "connected"


def test_list_templates_endpoint(client):
    """Test templates listing endpoint."""
    response = client.get("/templates")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "templates" in data
    assert "count" in data
    assert len(data["templates"]) >= 5


def test_template_query_endpoint(client, clean_neo4j):
    """Test template query execution."""
    # Create test data
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (c:Company {
                nome_normalizzato: 'HIGH RISK CO',
                risk_score: 0.9,
                anomaly_flags: ['test'],
                total_tenders: 5,
                source: 'TEST'
            })
        """)
    
    # Execute template query
    response = client.post("/template", json={
        "template_name": "high_risk_companies",
        "params": {"min_risk": 0.5},
        "limit": 10
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["template"] == "high_risk_companies"
    assert data["count"] >= 1
    assert len(data["results"]) >= 1


def test_natural_language_query_endpoint(client, clean_neo4j, mock_ollama):
    """Test natural language query endpoint."""
    # Mock LLM response
    mock_ollama.return_value.json.return_value = {
        "message": {
            "content": '{"template_name": "high_risk_companies", "params": {"min_risk": 0.5}}'
        }
    }
    
    # Create test data
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (c:Company {
                nome_normalizzato: 'RISKY COMPANY',
                risk_score: 0.85,
                source: 'TEST'
            })
        """)
    
    response = client.post("/query", json={
        "question": "Show me high risk companies",
        "limit": 10
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert "template" in data
    assert "results" in data


def test_get_company_endpoint(client, clean_neo4j):
    """Test get company by CF endpoint."""
    # Create test company
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (c:Company {
                cf: 'TEST123',
                nome_normalizzato: 'TEST COMPANY',
                source: 'TEST'
            })
            CREATE (m:Municipality {nome: 'Roma', source: 'TEST'})
            CREATE (r:Region {nome: 'Lazio', source: 'TEST'})
            CREATE (c)-[:LOCATED_IN]->(m)
            CREATE (m)-[:IN_REGION]->(r)
        """)
    
    response = client.get("/companies/TEST123")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["company"]["cf"] == "TEST123"
    assert data["location"]["municipality"] == "Roma"
    assert data["location"]["region"] == "Lazio"


def test_get_company_not_found(client, clean_neo4j):
    """Test get company returns 404 for nonexistent CF."""
    response = client.get("/companies/NONEXISTENT")
    
    assert response.status_code == 404


def test_stats_endpoint(client, clean_neo4j):
    """Test graph statistics endpoint."""
    # Create test data
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (c:Company {cf: 'C1', source: 'TEST'})
            CREATE (t:Tender {cig: 'T1', source: 'TEST'})
            CREATE (c)-[:WINS]->(t)
        """)
    
    response = client.get("/stats")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "nodes" in data
    assert "relationships" in data
    assert "total_nodes" in data
    assert "total_relationships" in data
    
    assert data["nodes"]["Company"] >= 1
    assert data["nodes"]["Tender"] >= 1
    assert data["relationships"]["WINS"] >= 1


def test_unstructured_ingest_endpoint_structured_bypass(client):
    """Known structured source should be bypassed and routed to ETL hint."""
    response = client.post("/ingest/unstructured", json={
        "source": "data/pnnr/PNRR_Soggetti.csv",
        "to_neo4j": False,
        "max_chars": 2000,
        "chunk_overlap": 100,
    })

    assert response.status_code == 200
    data = response.json()

    assert data["mode"] == "structured_bypass"
    assert data["routing"]["route"] == "structured"
    assert data["routing"]["handler"] == "existing_pnrr_etl"


def test_unstructured_ingest_endpoint_processes_text_with_mocked_ner(client, tmp_path, monkeypatch):
    """Unstructured text source should be processed and return extracted entities/relationships."""
    source_file = tmp_path / "note.txt"
    source_file.write_text("Mario Rossi lavora per Edilizia Rossi SRL", encoding="utf-8")

    from paladino.etl.unstructured_models import NERResult, ExtractedEntity, ExtractedRelationship

    class FakePipeline:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, document):
            return NERResult(
                entities=[
                    ExtractedEntity(
                        id="e1",
                        type="Person",
                        properties={"name": "Mario Rossi"},
                        confidence=0.91,
                    ),
                    ExtractedEntity(
                        id="e2",
                        type="Company",
                        properties={"name": "Edilizia Rossi SRL", "piva": "01234567890"},
                        confidence=0.94,
                    ),
                ],
                relationships=[
                    ExtractedRelationship(
                        source_id="e1",
                        target_id="e2",
                        type="WORKS_FOR",
                        confidence=0.89,
                    )
                ],
            )

    monkeypatch.setattr("paladino.etl.ner_pipeline.UnstructuredNERPipeline", FakePipeline)

    response = client.post("/ingest/unstructured", json={
        "source": str(source_file),
        "to_neo4j": False,
        "max_chars": 2000,
        "chunk_overlap": 100,
    })

    assert response.status_code == 200
    data = response.json()

    assert data["mode"] == "unstructured_processed"
    assert data["routing"]["route"] == "unstructured"
    assert data["extraction"]["entities"] == 2
    assert data["extraction"]["relationships"] == 1


def test_unstructured_ingest_endpoint_loads_to_neo4j_with_mocked_loader(client, tmp_path, monkeypatch):
    """Unstructured source with to_neo4j=true should return load stats from loader."""
    source_file = tmp_path / "note2.txt"
    source_file.write_text("Azienda X collegata a Mario", encoding="utf-8")

    from paladino.etl.unstructured_models import NERResult, ExtractedEntity, ExtractedRelationship

    class FakePipeline:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, document):
            return NERResult(
                entities=[
                    ExtractedEntity(
                        id="e1",
                        type="Company",
                        properties={"name": "Azienda X", "piva": "12345678901"},
                        confidence=0.9,
                    ),
                    ExtractedEntity(
                        id="e2",
                        type="Person",
                        properties={"name": "Mario"},
                        confidence=0.85,
                    ),
                ],
                relationships=[
                    ExtractedRelationship(
                        source_id="e2",
                        target_id="e1",
                        type="WORKS_FOR",
                        confidence=0.8,
                    )
                ],
            )

    class FakeLoader:
        def __init__(self, *args, **kwargs):
            pass

        def load(self, document, result):
            return {"documents": 1, "entities": 2, "relationships": 1}

    monkeypatch.setattr("paladino.etl.ner_pipeline.UnstructuredNERPipeline", FakePipeline)
    monkeypatch.setattr("paladino.etl.unstructured_loader.UnstructuredGraphLoader", FakeLoader)

    response = client.post("/ingest/unstructured", json={
        "source": str(source_file),
        "to_neo4j": True,
        "max_chars": 2000,
        "chunk_overlap": 100,
    })

    assert response.status_code == 200
    data = response.json()

    assert data["mode"] == "unstructured_processed"
    assert data["routing"]["route"] == "unstructured"
    assert data["load_stats"] == {"documents": 1, "entities": 2, "relationships": 1}


def test_unstructured_ingest_endpoint_rejects_invalid_chunk_overlap(client):
    """chunk_overlap must be lower than max_chars and return validation error otherwise."""
    response = client.post("/ingest/unstructured", json={
        "source": "data/pnnr/PNRR_Soggetti.csv",
        "to_neo4j": False,
        "max_chars": 100,
        "chunk_overlap": 100,
    })

    assert response.status_code == 422


def test_custom_csv_ingest_endpoint_dry_run_preview(client, tmp_path):
    """Custom CSV endpoint should validate mapping and return preview in dry-run mode."""
    source_file = tmp_path / "custom_companies.csv"
    source_file.write_text("vat_id,company_name\n01234567890,EDIL ROSSI SRL\n", encoding="utf-8")

    response = client.post("/ingest/custom-csv", json={
        "source": str(source_file),
        "target": "company",
        "mapping": {
            "piva": "vat_id",
            "nome_normalizzato": "company_name",
        },
        "dry_run": True,
    })

    assert response.status_code == 200
    data = response.json()

    assert data["mode"] == "custom_csv_preview"
    assert data["target"] == "company"
    assert data["rows_total"] == 1
    assert data["effective_key_property"] == "piva"
    assert len(data["preview"]) == 1
    assert data["preview"][0]["piva"] == "01234567890"


def test_custom_csv_ingest_endpoint_import_with_mocked_importer(client, monkeypatch):
    """Custom CSV endpoint should return import stats when importer runs in write mode."""

    class FakeImporter:
        def __init__(self, *args, **kwargs):
            pass

        def import_csv(self, **kwargs):
            return {
                "mode": "imported",
                "target": "company",
                "source": kwargs["source"],
                "delimiter": ",",
                "headers": ["vat_id", "company_name"],
                "rows_total": 2,
                "effective_key_property": "piva",
                "rows_processed": 2,
                "rows_skipped_missing_key": 0,
                "nodes_merged": 2,
            }

    monkeypatch.setattr("paladino.etl.custom_csv_importer.CustomCSVImporter", FakeImporter)

    response = client.post("/ingest/custom-csv", json={
        "source": "data/custom/my_companies.csv",
        "target": "company",
        "mapping": {
            "piva": "vat_id",
            "nome_normalizzato": "company_name",
        },
        "dry_run": False,
    })

    assert response.status_code == 200
    data = response.json()

    assert data["mode"] == "custom_csv_imported"
    assert data["target"] == "company"
    assert data["stats"] == {
        "rows_processed": 2,
        "rows_skipped_missing_key": 0,
        "nodes_merged": 2,
    }


def test_custom_csv_upload_endpoint_dry_run_preview(client):
    """Upload endpoint should accept multipart CSV and return preview in dry-run mode."""
    content = "vat_id,company_name\n01234567890,EDIL ROSSI SRL\n"
    response = client.post(
        "/ingest/custom-csv/upload",
        data={
            "target": "company",
            "mapping_json": json.dumps({"piva": "vat_id", "nome_normalizzato": "company_name"}),
            "dry_run": "true",
        },
        files={"file": ("upload.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "custom_csv_preview"
    assert data["target"] == "company"
    assert data["source"] == "upload.csv"
    assert data["rows_total"] == 1
    assert data["effective_key_property"] == "piva"
    assert data["preview"][0]["piva"] == "01234567890"


def test_custom_csv_upload_endpoint_import_with_mocked_importer(client, monkeypatch):
    """Upload endpoint should return import stats when importer is run in write mode."""

    class FakeImporter:
        def __init__(self, *args, **kwargs):
            pass

        def import_csv(self, **kwargs):
            return {
                "mode": "imported",
                "target": "tender",
                "source": kwargs["source"],
                "delimiter": ",",
                "headers": ["cig_code", "title"],
                "rows_total": 1,
                "effective_key_property": "cig",
                "rows_processed": 1,
                "rows_skipped_missing_key": 0,
                "nodes_merged": 1,
            }

    monkeypatch.setattr("paladino.etl.custom_csv_importer.CustomCSVImporter", FakeImporter)

    response = client.post(
        "/ingest/custom-csv/upload",
        data={
            "target": "tender",
            "mapping_json": json.dumps({"cig": "cig_code", "title": "title"}),
            "dry_run": "false",
        },
        files={"file": ("tenders.csv", "cig_code,title\nCIG1,Works\n", "text/csv")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "custom_csv_imported"
    assert data["target"] == "tender"
    assert data["source"] == "tenders.csv"
    assert data["stats"] == {
        "rows_processed": 1,
        "rows_skipped_missing_key": 0,
        "nodes_merged": 1,
    }


def test_custom_csv_ingest_tender_requires_importo_mapping(client, tmp_path):
    """Tender imports must include importo mapping because schema requires Tender.importo."""
    source_file = tmp_path / "custom_tenders.csv"
    source_file.write_text("cig_code,title\nCIG-777,Works\n", encoding="utf-8")

    response = client.post("/ingest/custom-csv", json={
        "source": str(source_file),
        "target": "tender",
        "mapping": {
            "cig": "cig_code",
            "title": "title",
        },
        "dry_run": False,
    })

    assert response.status_code == 400
    assert "importo" in response.json()["detail"]
