import json
from datetime import datetime

from paladino.db import Neo4jConnection
from paladino.etl.unstructured_models import ExtractedDocument, ExtractedEntity, NERResult


class UnstructuredGraphLoader:
    """Load extracted entities/relationships into Neo4j with provenance metadata."""

    def __init__(self, db: Neo4jConnection | None = None) -> None:
        self.db = db or Neo4jConnection()

    def load(self, document: ExtractedDocument, result: NERResult) -> dict[str, int]:
        self._merge_source_document(document)

        entity_map: dict[str, str] = {}
        for entity in result.entities:
            key = self._canonical_key(entity)
            entity_map[entity.id] = key
            self._merge_entity(document, entity, key)

        rel_count = 0
        for rel in result.relationships:
            source_key = entity_map.get(rel.source_id)
            target_key = entity_map.get(rel.target_id)
            if not source_key or not target_key:
                continue
            self._merge_relationship(document, source_key, target_key, rel.type, rel.confidence)
            rel_count += 1

        return {
            "documents": 1,
            "entities": len(result.entities),
            "relationships": rel_count,
        }

    def _merge_source_document(self, document: ExtractedDocument) -> None:
        query = """
        MERGE (d:SourceDocument {source: $source})
        SET d.source_type = $source_type,
            d.title = $title,
            d.extracted_at = $extracted_at,
            d.extraction_method = $extraction_method,
            d.updated_at = datetime()
        """
        self.db.run_query(
            query,
            {
                "source": document.source,
                "source_type": document.source_type,
                "title": document.title,
                "extracted_at": document.extracted_at,
                "extraction_method": document.extraction_method,
            },
        )

    def _merge_entity(self, document: ExtractedDocument, entity: ExtractedEntity, key: str) -> None:
        display_name = str((entity.properties or {}).get("name") or "")
        properties_json = json.dumps(entity.properties or {}, ensure_ascii=False)
        query = """
        MERGE (e:Entity {canonical_key: $canonical_key})
        SET e.entity_type = $entity_type,
            e.display_name = $display_name,
            e.properties_json = $properties_json,
            e._confidence_score = $confidence,
            e._source_file = $source_file,
            e._extraction_date = $extraction_date,
            e._extraction_method = $extraction_method,
            e.updated_at = datetime()
        WITH e
        MATCH (d:SourceDocument {source: $source_file})
        MERGE (d)-[m:MENTIONS]->(e)
        SET m.confidence = $confidence,
            m.created_at = datetime()
        """
        self.db.run_query(
            query,
            {
                "canonical_key": key,
                "entity_type": entity.type,
                "display_name": display_name,
                "properties_json": properties_json,
                "confidence": float(entity.confidence),
                "source_file": document.source,
                "extraction_date": datetime.utcnow().isoformat(),
                "extraction_method": document.extraction_method,
            },
        )

        self._link_to_domain_nodes(document, key, entity.properties or {})

    def _link_to_domain_nodes(
        self, document: ExtractedDocument, canonical_key: str, properties: dict
    ) -> None:
        piva = str(properties.get("piva") or properties.get("vat_number") or "").strip()
        cf = str(properties.get("cf") or "").strip()
        cig = str(properties.get("cig") or "").strip()
        cup = str(properties.get("cup") or "").strip()

        if piva or cf:
            query = """
            MATCH (e:Entity {canonical_key: $canonical_key})
            MATCH (d:SourceDocument {source: $source_file})
            MATCH (c:Company)
            WHERE ($piva <> '' AND c.piva = $piva) OR ($cf <> '' AND c.cf = $cf)
            MERGE (e)-[m:MATCHES_COMPANY]->(c)
            SET m.match_method = 'identifier',
                m.updated_at = datetime()
            MERGE (d)-[mc:MENTIONS_COMPANY]->(c)
            SET mc.match_method = 'identifier',
                mc.updated_at = datetime()
            """
            self.db.run_query(
                query,
                {
                    "canonical_key": canonical_key,
                    "source_file": document.source,
                    "piva": piva,
                    "cf": cf,
                },
            )

        if cig:
            query = """
            MATCH (e:Entity {canonical_key: $canonical_key})
            MATCH (d:SourceDocument {source: $source_file})
            MATCH (t:Tender {cig: $cig})
            MERGE (e)-[m:MATCHES_TENDER]->(t)
            SET m.match_method = 'identifier',
                m.updated_at = datetime()
            MERGE (d)-[mt:MENTIONS_TENDER]->(t)
            SET mt.match_method = 'identifier',
                mt.updated_at = datetime()
            """
            self.db.run_query(
                query,
                {
                    "canonical_key": canonical_key,
                    "source_file": document.source,
                    "cig": cig,
                },
            )

        if cup:
            query = """
            MATCH (e:Entity {canonical_key: $canonical_key})
            MATCH (d:SourceDocument {source: $source_file})
            MATCH (p:Project {cup: $cup})
            MERGE (e)-[m:MATCHES_PROJECT]->(p)
            SET m.match_method = 'identifier',
                m.updated_at = datetime()
            MERGE (d)-[mp:MENTIONS_PROJECT]->(p)
            SET mp.match_method = 'identifier',
                mp.updated_at = datetime()
            """
            self.db.run_query(
                query,
                {
                    "canonical_key": canonical_key,
                    "source_file": document.source,
                    "cup": cup,
                },
            )

    def _merge_relationship(
        self,
        document: ExtractedDocument,
        source_key: str,
        target_key: str,
        rel_type: str,
        confidence: float,
    ) -> None:
        query = """
        MATCH (a:Entity {canonical_key: $source_key})
        MATCH (b:Entity {canonical_key: $target_key})
        MERGE (a)-[r:RELATED_TO {relation_type: $relation_type}]->(b)
        SET r._source_file = $source_file,
            r._extraction_date = $extraction_date,
            r._extraction_method = $extraction_method,
            r._confidence_score = $confidence,
            r.updated_at = datetime()
        """
        self.db.run_query(
            query,
            {
                "source_key": source_key,
                "target_key": target_key,
                "relation_type": rel_type,
                "source_file": document.source,
                "extraction_date": datetime.utcnow().isoformat(),
                "extraction_method": document.extraction_method,
                "confidence": float(confidence),
            },
        )

    @staticmethod
    def _canonical_key(entity: ExtractedEntity) -> str:
        properties = entity.properties or {}
        for identifier in ("vat_number", "piva", "cf", "cup", "cig", "id"):
            value = properties.get(identifier)
            if value:
                return f"{entity.type}:{str(value).strip().upper()}"

        name = str(properties.get("name", entity.id)).strip().upper()
        return f"{entity.type}:{name}"
