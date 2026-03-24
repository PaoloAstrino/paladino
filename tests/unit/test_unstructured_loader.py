from paladino.etl.unstructured_loader import UnstructuredGraphLoader
from paladino.etl.unstructured_models import ExtractedDocument, ExtractedEntity


class FakeDB:
    def __init__(self):
        self.calls = []

    def run_query(self, query, parameters=None):
        self.calls.append((query, parameters or {}))
        return []


def test_loader_links_company_and_tender_by_identifiers():
    db = FakeDB()
    loader = UnstructuredGraphLoader(db=db)

    document = ExtractedDocument(
        source="sample.txt",
        source_type="text",
        title="sample",
        content="x",
        extraction_method="native_text_reader",
    )
    entity = ExtractedEntity(
        id="e1",
        type="Company",
        properties={"name": "ACME", "piva": "01234567890", "cig": "CIG123"},
        confidence=0.9,
    )

    loader._merge_source_document(document)
    loader._merge_entity(document, entity, "Company:01234567890")

    executed = "\n".join(call[0] for call in db.calls)
    assert "MATCHES_COMPANY" in executed
    assert "MATCHES_TENDER" in executed


def test_loader_links_project_by_cup():
    db = FakeDB()
    loader = UnstructuredGraphLoader(db=db)

    document = ExtractedDocument(
        source="sample2.txt",
        source_type="text",
        title="sample2",
        content="x",
        extraction_method="native_text_reader",
    )
    entity = ExtractedEntity(
        id="e2",
        type="Project",
        properties={"cup": "CUP0001"},
        confidence=0.7,
    )

    loader._merge_source_document(document)
    loader._merge_entity(document, entity, "Project:CUP0001")

    executed = "\n".join(call[0] for call in db.calls)
    assert "MATCHES_PROJECT" in executed
