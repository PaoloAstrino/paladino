import json

from paladino.etl.ner_pipeline import UnstructuredNERPipeline
from paladino.etl.unstructured_models import ExtractedDocument


class DummyLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls = 0

    def chat(self, messages: list, format: str | None = None) -> str:
        index = self.calls if self.calls < len(self.responses) else len(self.responses) - 1
        response = self.responses[index]
        self.calls += 1
        return json.dumps(response)


def test_extract_single_chunk() -> None:
    llm = DummyLLM(
        [
            {
                "entities": [
                    {
                        "id": "ent_1",
                        "type": "Company",
                        "properties": {"name": "Rossi SRL", "piva": "01234567890"},
                        "confidence": 0.93,
                    }
                ],
                "relationships": [],
            }
        ]
    )

    pipeline = UnstructuredNERPipeline(llm_manager=llm, max_chars_per_chunk=1000)
    document = ExtractedDocument(
        source="sample.txt",
        source_type="text",
        title="sample",
        content="Azienda Rossi SRL con PIVA 01234567890",
        extraction_method="native_text_reader",
    )

    result = pipeline.extract(document)
    assert len(result.entities) == 1
    assert result.entities[0].properties.get("piva") == "01234567890"
    assert llm.calls == 1


def test_extract_merges_entities_and_relationships_across_chunks() -> None:
    llm = DummyLLM(
        [
            {
                "entities": [
                    {
                        "id": "company_a",
                        "type": "Company",
                        "properties": {"name": "Rossi SRL", "piva": "01234567890"},
                        "confidence": 0.90,
                    },
                    {
                        "id": "person_a",
                        "type": "Person",
                        "properties": {"name": "Mario Rossi"},
                        "confidence": 0.80,
                    },
                ],
                "relationships": [
                    {
                        "source_id": "person_a",
                        "target_id": "company_a",
                        "type": "WORKS_FOR",
                        "confidence": 0.70,
                    }
                ],
            },
            {
                "entities": [
                    {
                        "id": "company_b",
                        "type": "Company",
                        "properties": {
                            "name": "Rossi SRL",
                            "piva": "01234567890",
                            "city": "Roma",
                        },
                        "confidence": 0.95,
                    },
                    {
                        "id": "person_b",
                        "type": "Person",
                        "properties": {"name": "Mario Rossi"},
                        "confidence": 0.88,
                    },
                ],
                "relationships": [
                    {
                        "source_id": "person_b",
                        "target_id": "company_b",
                        "type": "WORKS_FOR",
                        "confidence": 0.92,
                    }
                ],
            },
        ]
    )

    long_text = " ".join(["Rossi"] * 200)
    pipeline = UnstructuredNERPipeline(llm_manager=llm, max_chars_per_chunk=300, chunk_overlap=30)
    document = ExtractedDocument(
        source="long.txt",
        source_type="text",
        title="long",
        content=long_text,
        extraction_method="native_text_reader",
    )

    result = pipeline.extract(document)

    assert len(result.entities) == 2
    assert len(result.relationships) == 1
    rel = result.relationships[0]
    assert rel.type == "WORKS_FOR"
    assert rel.confidence == 0.92
    assert llm.calls >= 2
