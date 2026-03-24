import json
import re
import uuid

from paladino.etl.unstructured_models import (
    ExtractedDocument,
    ExtractedEntity,
    ExtractedRelationship,
    NERResult,
)
from paladino.llm_manager import LLMManager


class UnstructuredNERPipeline:
    """Extract entities and relationships from unstructured text using configured LLM."""

    def __init__(
        self,
        llm_manager: LLMManager | None = None,
        max_chars_per_chunk: int = 12000,
        chunk_overlap: int = 400,
    ) -> None:
        self.llm = llm_manager or LLMManager()
        self.max_chars_per_chunk = max_chars_per_chunk
        self.chunk_overlap = chunk_overlap

    def extract(self, document: ExtractedDocument) -> NERResult:
        chunks = self._build_chunks(document.content)
        if not chunks:
            return NERResult()

        partial_results: list[NERResult] = []
        for index, chunk in enumerate(chunks, start=1):
            payload = self._extract_chunk(document=document, chunk=chunk, index=index, total=len(chunks))
            payload = self._sanitize_payload(payload)
            partial_results.append(NERResult.model_validate(payload))

        return self._merge_results(partial_results)

    def _extract_chunk(self, document: ExtractedDocument, chunk: str, index: int, total: int) -> dict:
        system_prompt = (
            "You are an information extraction engine for Italian public-sector documents. "
            "Extract entities and relationships into valid JSON. "
            "Do not return markdown, comments, or extra text."
        )

        user_prompt = (
            "Return JSON with schema: "
            "{\"entities\": [{\"id\": \"...\", \"type\": \"Company|Person|Location|Tender|Project|Amount|Identifier\", "
            "\"properties\": { ... }, \"confidence\": 0.0}], "
            "\"relationships\": [{\"source_id\": \"...\", \"target_id\": \"...\", \"type\": \"...\", \"confidence\": 0.0}]}. "
            "Preserve CIG/CUP/CF/PIVA values when found. "
            f"Source: {document.source}. Chunk {index}/{total}. Content:\n\n{chunk}"
        )

        raw = self.llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            format="json",
        )

        return self._parse_json(raw)

    def _sanitize_payload(self, payload: dict) -> dict:
        entities = payload.get("entities") if isinstance(payload, dict) else []
        relationships = payload.get("relationships") if isinstance(payload, dict) else []

        safe_entities: list[dict] = []
        for index, entity in enumerate(entities or []):
            if not isinstance(entity, dict):
                continue
            entity_type = str(entity.get("type") or "Identifier").strip() or "Identifier"
            entity_id = str(entity.get("id") or f"ent_{index}").strip() or f"ent_{index}"
            properties = entity.get("properties") if isinstance(entity.get("properties"), dict) else {}
            confidence = entity.get("confidence")
            try:
                confidence_value = float(confidence) if confidence is not None else 0.0
            except (TypeError, ValueError):
                confidence_value = 0.0

            safe_entities.append(
                {
                    "id": entity_id,
                    "type": entity_type,
                    "properties": properties,
                    "confidence": confidence_value,
                }
            )

        valid_entity_ids = {item["id"] for item in safe_entities}
        safe_relationships: list[dict] = []
        for rel in relationships or []:
            if not isinstance(rel, dict):
                continue
            source_id = rel.get("source_id")
            target_id = rel.get("target_id")
            rel_type = rel.get("type")

            if not source_id or not target_id or not rel_type:
                continue
            if source_id not in valid_entity_ids or target_id not in valid_entity_ids:
                continue

            confidence = rel.get("confidence")
            try:
                confidence_value = float(confidence) if confidence is not None else 0.0
            except (TypeError, ValueError):
                confidence_value = 0.0

            safe_relationships.append(
                {
                    "source_id": str(source_id),
                    "target_id": str(target_id),
                    "type": str(rel_type),
                    "confidence": confidence_value,
                }
            )

        return {"entities": safe_entities, "relationships": safe_relationships}

    def _build_chunks(self, content: str) -> list[str]:
        text = (content or "").strip()
        if not text:
            return []

        if len(text) <= self.max_chars_per_chunk:
            return [text]

        chunks: list[str] = []
        step = max(1, self.max_chars_per_chunk - self.chunk_overlap)
        start = 0

        while start < len(text):
            end = min(start + self.max_chars_per_chunk, len(text))
            if end < len(text):
                pivot = text.rfind("\n", start, end)
                if pivot <= start:
                    pivot = text.rfind(" ", start, end)
                if pivot > start:
                    end = pivot

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            if end >= len(text):
                break
            start = max(end - self.chunk_overlap, start + step)

        return chunks

    def _merge_results(self, results: list[NERResult]) -> NERResult:
        merged_entities: dict[str, ExtractedEntity] = {}
        rel_index: dict[tuple[str, str, str], ExtractedRelationship] = {}

        for result in results:
            local_id_map: dict[str, str] = {}
            for entity in result.entities:
                key = self._entity_key(entity)
                if key in merged_entities:
                    current = merged_entities[key]
                    current.confidence = max(current.confidence, entity.confidence)
                    current.properties = self._merge_properties(current.properties, entity.properties)
                    merged_id = current.id
                else:
                    merged_id = entity.id or f"ent_{uuid.uuid4().hex[:10]}"
                    merged_entities[key] = ExtractedEntity(
                        id=merged_id,
                        type=entity.type,
                        properties=dict(entity.properties),
                        confidence=entity.confidence,
                    )
                local_id_map[entity.id] = merged_id

            for rel in result.relationships:
                src = local_id_map.get(rel.source_id)
                dst = local_id_map.get(rel.target_id)
                if not src or not dst:
                    continue
                relation_key = (src, dst, rel.type)
                if relation_key in rel_index:
                    rel_index[relation_key].confidence = max(
                        rel_index[relation_key].confidence,
                        rel.confidence,
                    )
                else:
                    rel_index[relation_key] = ExtractedRelationship(
                        source_id=src,
                        target_id=dst,
                        type=rel.type,
                        confidence=rel.confidence,
                    )

        return NERResult(
            entities=list(merged_entities.values()),
            relationships=list(rel_index.values()),
        )

    @staticmethod
    def _merge_properties(base: dict, incoming: dict) -> dict:
        merged = dict(base or {})
        for key, value in (incoming or {}).items():
            if key not in merged or merged[key] in (None, "", []):
                merged[key] = value
        return merged

    @staticmethod
    def _entity_key(entity: ExtractedEntity) -> str:
        properties = entity.properties or {}
        for identifier in ("vat_number", "piva", "cf", "cup", "cig", "id"):
            value = properties.get(identifier)
            if value:
                return f"{entity.type}:{str(value).strip().upper()}"

        name = str(properties.get("name", entity.id)).strip().upper()
        return f"{entity.type}:{name}"

    @staticmethod
    def _parse_json(raw: str) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                raise ValueError("LLM did not return valid JSON")
            return json.loads(match.group(0))
