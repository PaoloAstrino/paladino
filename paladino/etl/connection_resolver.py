"""
Connection Resolver — links extracted entities to existing Neo4j graph nodes.

After the NER pipeline extracts entities from unstructured text, this module:
1. Matches extracted entities to existing Neo4j nodes (identifier lookup, fuzzy name match)
2. MERGEs matched entities (updates properties) or CREATEs new nodes
3. Resolves relationship endpoints to existing node IDs
4. Discovers implicit connections via graph traversal
5. Returns a ConnectionReport summarizing what was found/created/linked
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from loguru import logger
from rapidfuzz import fuzz

from paladino.db import Neo4jConnection
from paladino.etl.unstructured_models import (
    ConnectionReport,
    DiscoveredPath,
    EntityMatch,
    ExtractedEntity,
    ExtractedRelationship,
    ImplicitConnection,
    NERResult,
)
from paladino.llm_manager import LLMManager
from paladino.ml.name_normalizer import CompanyNameNormalizer


# ──────────────────────────────────────────────────────────────
# Identifier extraction patterns
# ──────────────────────────────────────────────────────────────

_CF_RE = re.compile(r"\b([A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z])\b", re.IGNORECASE)
_PIVA_RE = re.compile(r"\b(IT)?(\d{11})\b")
_CUP_RE = re.compile(r"\b([A-Z]\d{2}[A-Z]\d{10,14})\b")  # E12C3456789012 format
_CIG_RE = re.compile(r"\b([A-Z0-9]{8,15})\b")  # broad — validated by context

# Mapping from extracted entity type → Neo4j label
_TYPE_TO_LABEL: dict[str, str] = {
    "Company": "Company",
    "Person": "Person",
    "Location": "DatasetContext",
    "Tender": "Tender",
    "Project": "Project",
    "Buyer": "Buyer",
    "Amount": "Identifier",
    "Identifier": "Identifier",
}

# Properties to carry from extracted entity → Neo4j node
_KNOWN_ENTITY_PROPERTIES: dict[str, list[str]] = {
    "Company": ["cf", "piva", "nome_normalizzato", "ateco", "regione", "provincia"],
    "Person": ["cf", "nome", "cognome", "data_nascita", "luogo_nascita"],
    "Tender": ["cig", "oggetto", "importo", "buyer_name", "data_aggiudicazione"],
    "Project": ["cup", "titolo", "descrizione", "importo", "cig_correlati"],
    "Buyer": ["nome", "codice_fiscale", "tipo"],
    "Location": ["nome", "codice_istat", "tipo"],
}


class ConnectionResolver:
    """
    Resolves extracted entities/relationships against the existing Neo4j graph.

    Usage:
        resolver = ConnectionResolver(db, llm_manager)
        report = resolver.resolve(ner_result, source="document.pdf")
    """

    def __init__(
        self,
        db: Neo4jConnection,
        llm_manager: LLMManager | None = None,
        fuzzy_threshold: float = 0.85,
        llm_threshold: float = 0.70,
    ) -> None:
        self.db = db
        self.llm = llm_manager
        self.fuzzy_threshold = fuzzy_threshold
        self.llm_threshold = llm_threshold
        self.normalizer = CompanyNameNormalizer()

        # Mapping: extracted_entity_id → resolved Neo4j node id (or new UUID)
        self._id_map: dict[str, str] = {}
        # Tracking: which extracted entities matched existing nodes
        self._matches: list[EntityMatch] = []

    # ──────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────

    def resolve(self, ner_result: NERResult, source: str) -> ConnectionReport:
        """
        Full resolution pipeline: match entities → MERGE/CREATE → resolve relationships → discover implicit links.

        Args:
            ner_result: Output from UnstructuredNERPipeline.extract()
            source: Original source file/URL path

        Returns:
            ConnectionReport summarizing all resolution activity
        """
        report = ConnectionReport(source=source)
        report.entities_extracted = len(ner_result.entities)

        if not ner_result.entities:
            report.warnings.append("No entities to resolve.")
            return report

        # Phase 1: Match each extracted entity to existing Neo4j nodes
        logger.info(f"[ConnectionResolver] Matching {len(ner_result.entities)} entities against graph…")
        for entity in ner_result.entities:
            match = self._match_entity(entity)
            self._matches.append(match)

            if match.matched_neo4j_id is not None:
                report.entities_matched += 1
                # Map extracted ID → existing Neo4j ID
                self._id_map[entity.id] = match.matched_neo4j_id
            else:
                # No match → assign a new UUID for creation
                new_id = f"ext_{uuid.uuid4().hex[:12]}"
                self._id_map[entity.id] = new_id
                report.entities_created += 1

        report.entity_matches = self._matches

        # Phase 2: Resolve relationships and create edges
        logger.info(f"[ConnectionResolver] Resolving {len(ner_result.relationships)} relationships…")
        resolved_rels = self._resolve_relationships(ner_result.relationships, source)
        report.relationships_resolved = len(ner_result.relationships)
        report.relationships_created = resolved_rels

        # Phase 3: Create unmatched entities as new nodes
        new_entities = [
            e for e in ner_result.entities
            if self._matches and any(
                m.extracted_entity_id == e.id and m.matched_neo4j_id is None
                for m in self._matches
            )
        ]
        if new_entities:
            self._create_new_entities(new_entities, source)

        # Phase 4: Update matched entities with new properties
        matched_entities = [
            e for e in ner_result.entities
            if any(m.extracted_entity_id == e.id and m.matched_neo4j_id is not None for m in self._matches)
        ]
        if matched_entities:
            self._update_matched_entities(matched_entities, source)

        # Phase 5: Discover implicit connections
        logger.info("[ConnectionResolver] Discovering implicit connections…")
        implicit = self._discover_implicit_connections(source)
        report.implicit_connections_found = len(implicit)
        report.implicit_connections = implicit

        # Phase 6: Discover shortest paths between newly-linked entities
        discovered_paths = self._discover_paths(ner_result)
        report.discovered_paths = discovered_paths

        logger.success(
            f"[ConnectionResolver] Done — matched {report.entities_matched}, "
            f"created {report.entities_created}, resolved {report.relationships_created} edges, "
            f"found {report.implicit_connections_found} implicit links."
        )
        return report

    # ──────────────────────────────────────────────────────
    # Phase 1: Entity Matching
    # ──────────────────────────────────────────────────────

    def _match_entity(self, entity: ExtractedEntity) -> EntityMatch:
        """
        Try to match an extracted entity to an existing Neo4j node.

        Strategy (in order):
        1. Exact identifier match (CF, P.IVA, CUP, CIG)
        2. Fuzzy name match via Levenshtein similarity
        3. LLM judge for ambiguous cases
        4. No match → return EntityMatch with matched_neo4j_id=None
        """
        props = entity.properties or {}
        neo4j_label = _TYPE_TO_LABEL.get(entity.type, "CustomRecord")

        # --- Strategy 1: Exact identifier match ---
        identifier_match = self._try_identifier_match(entity, neo4j_label)
        if identifier_match:
            return identifier_match

        # --- Strategy 2: Fuzzy name match (Company only) ---
        if entity.type == "Company":
            fuzzy_match = self._try_fuzzy_name_match(entity, neo4j_label)
            if fuzzy_match:
                return fuzzy_match

        # --- Strategy 3: LLM judge for ambiguous cases ---
        if entity.type == "Company" and self.llm:
            llm_match = self._try_llm_judge(entity, neo4j_label)
            if llm_match:
                return llm_match

        # --- Strategy 4: No match ---
        return EntityMatch(
            extracted_entity_id=entity.id,
            extracted_entity_type=entity.type,
            matched_neo4j_id=None,
            matched_neo4j_label=None,
            match_method="none",
            confidence=0.0,
        )

    def _try_identifier_match(self, entity: ExtractedEntity, neo4j_label: str) -> EntityMatch | None:
        """Match by CF, P.IVA, CUP, or CIG."""
        props = entity.properties or {}

        # Try CF match
        cf = props.get("cf") or props.get("codice_fiscale") or self._extract_cf(props)
        if cf:
            result = self._query_by_identifier("Company", "cf", cf.upper().strip())
            if result:
                return EntityMatch(
                    extracted_entity_id=entity.id,
                    extracted_entity_type=entity.type,
                    matched_neo4j_id=result["neo4j_id"],
                    matched_neo4j_label="Company",
                    match_method="exact_cf",
                    confidence=1.0,
                    matched_properties=result["properties"],
                )

        # Try P.IVA match
        piva = props.get("piva") or props.get("partita_iva") or self._extract_piva(props)
        if piva:
            result = self._query_by_identifier("Company", "piva", piva.upper().strip())
            if result:
                return EntityMatch(
                    extracted_entity_id=entity.id,
                    extracted_entity_type=entity.type,
                    matched_neo4j_id=result["neo4j_id"],
                    matched_neo4j_label="Company",
                    match_method="exact_piva",
                    confidence=1.0,
                    matched_properties=result["properties"],
                )

        # Try CUP match
        cup = props.get("cup") or self._extract_cup(props)
        if cup:
            result = self._query_by_identifier("Project", "cup", cup.upper().strip())
            if result:
                return EntityMatch(
                    extracted_entity_id=entity.id,
                    extracted_entity_type=entity.type,
                    matched_neo4j_id=result["neo4j_id"],
                    matched_neo4j_label="Project",
                    match_method="exact_cup",
                    confidence=1.0,
                    matched_properties=result["properties"],
                )

        # Try CIG match
        cig = props.get("cig") or self._extract_cig(props)
        if cig:
            result = self._query_by_identifier("Tender", "cig", cig.upper().strip())
            if result:
                return EntityMatch(
                    extracted_entity_id=entity.id,
                    extracted_entity_type=entity.type,
                    matched_neo4j_id=result["neo4j_id"],
                    matched_neo4j_label="Tender",
                    match_method="exact_cig",
                    confidence=1.0,
                    matched_properties=result["properties"],
                )

        return None

    def _try_fuzzy_name_match(self, entity: ExtractedEntity, neo4j_label: str) -> EntityMatch | None:
        """Fuzzy name match via Neo4j full-text index or APOC Levenshtein."""
        name = entity.properties.get("name") or entity.properties.get("nome") or entity.properties.get("ragione_sociale")
        if not name:
            return None

        # Use full-text index if available
        candidates = self._fulltext_search(name, neo4j_label, limit=5)
        if not candidates:
            # Fallback: scan all companies with Levenshtein (slower but works without full-text index)
            candidates = self._levenshtein_search(name, neo4j_label, limit=5)

        best = None
        best_score = 0.0

        for cand in candidates:
            cand_name = cand.get("name", "")
            score = fuzz.token_sort_ratio(name, cand_name) / 100.0
            if score > best_score:
                best_score = score
                best = cand

        if best and best_score >= self.fuzzy_threshold:
            return EntityMatch(
                extracted_entity_id=entity.id,
                extracted_entity_type=entity.type,
                matched_neo4j_id=best["neo4j_id"],
                matched_neo4j_label=neo4j_label,
                match_method="fuzzy_name",
                confidence=round(best_score, 2),
                matched_properties=best.get("properties", {}),
            )

        return None

    def _try_llm_judge(self, entity: ExtractedEntity, neo4j_label: str) -> EntityMatch | None:
        """LLM-assisted matching for ambiguous company names."""
        name = entity.properties.get("name") or entity.properties.get("nome")
        if not name:
            return None

        # Get candidates below fuzzy threshold but above LLM threshold
        candidates = self._levenshtein_search(name, neo4j_label, limit=3)
        ambiguous = [
            c for c in candidates
            if self.llm_threshold <= fuzz.token_sort_ratio(name, c.get("name", "")) / 100.0 < self.fuzzy_threshold
        ]

        for cand in ambiguous:
            if self._llm_verify_same_entity(name, cand.get("name", "")):
                return EntityMatch(
                    extracted_entity_id=entity.id,
                    extracted_entity_type=entity.type,
                    matched_neo4j_id=cand["neo4j_id"],
                    matched_neo4j_label=neo4j_label,
                    match_method="llm_judged",
                    confidence=0.85,
                    matched_properties=cand.get("properties", {}),
                )

        return None

    # ──────────────────────────────────────────────────────
    # Phase 2: Relationship Resolution
    # ──────────────────────────────────────────────────────

    def _resolve_relationships(self, relationships: list[ExtractedRelationship], source: str) -> int:
        """
        Resolve each relationship's source/target to Neo4j node IDs and CREATE edges.

        Returns the number of relationships created.
        """
        created = 0
        for rel in relationships:
            source_neo4j_id = self._id_map.get(rel.source_id)
            target_neo4j_id = self._id_map.get(rel.target_id)

            if not source_neo4j_id or not target_neo4j_id:
                logger.warning(
                    f"[ConnectionResolver] Relationship '{rel.type}' skipped: "
                    f"source={rel.source_id} → {source_neo4j_id}, target={rel.target_id} → {target_neo4j_id}"
                )
                continue

            # Sanitize relationship type (Neo4j uppercase, no spaces)
            rel_type = re.sub(r"[^A-Z_]", "_", rel.type.upper())
            if not rel_type:
                rel_type = "RELATED_TO"

            self._create_relationship(source_neo4j_id, target_neo4j_id, rel_type, rel.confidence, source)
            created += 1

        return created

    def _create_relationship(
        self, source_id: str, target_id: str, rel_type: str, confidence: float, source: str
    ) -> None:
        """CREATE or update a relationship between two Neo4j nodes."""
        query = f"""
        MATCH (a) WHERE id(a) = $source_id
        MATCH (b) WHERE id(b) = $target_id
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET
            r.confidence = $confidence,
            r.source = [$source],
            r.created_at = datetime()
        ON MATCH SET
            r.source = apoc.coll.toSet(coalesce(r.source, []) + [$source])
        """
        try:
            self.db.run_query(query, {
                "source_id": int(source_id) if source_id.isdigit() else source_id,
                "target_id": int(target_id) if target_id.isdigit() else target_id,
                "confidence": confidence,
                "source": source,
            })
        except Exception as exc:
            logger.warning(f"[ConnectionResolver] Failed to create relationship {rel_type}: {exc}")

    # ──────────────────────────────────────────────────────
    # Phase 3: Create New Nodes
    # ──────────────────────────────────────────────────────

    def _create_new_entities(self, entities: list[ExtractedEntity], source: str) -> None:
        """Create new Neo4j nodes for entities with no existing match."""
        for entity in entities:
            neo4j_id = self._id_map.get(entity.id)
            if not neo4j_id:
                continue

            neo4j_label = _TYPE_TO_LABEL.get(entity.type, "CustomRecord")
            props = self._extract_known_properties(entity)
            props["id"] = neo4j_id
            props["source"] = [source]
            props["_import_ts"] = datetime.now(UTC).isoformat()
            props["confidence"] = entity.confidence

            # Build SET clause dynamically
            set_clauses = []
            for key in props:
                set_clauses.append(f"n.{key} = ${key}")

            query = f"""
            MERGE (n:{neo4j_label} {{id: $id}})
            ON CREATE SET {", ".join(set_clauses)}
            """
            try:
                self.db.run_query(query, props)
                logger.debug(f"[ConnectionResolver] Created {neo4j_label} node with id={neo4j_id}")
            except Exception as exc:
                logger.warning(f"[ConnectionResolver] Failed to create {neo4j_label} node: {exc}")

    def _update_matched_entities(self, entities: list[ExtractedEntity], source: str) -> None:
        """Update existing Neo4j nodes with new properties from extracted entities."""
        for entity in entities:
            match = next((m for m in self._matches if m.extracted_entity_id == entity.id), None)
            if not match or not match.matched_neo4j_id:
                continue

            props = self._extract_known_properties(entity)
            if not props:
                continue

            # Only set properties that are currently null/empty (don't overwrite existing data)
            set_clauses = []
            for key, value in props.items():
                set_clauses.append(f"n.{key} = coalesce(n.{key}, ${key})")

            # Also add source to the list
            query = f"""
            MATCH (n) WHERE id(n) = $neo4j_id
            SET {", ".join(set_clauses)},
                n.source = apoc.coll.toSet(coalesce(n.source, []) + [$source])
            """
            try:
                self.db.run_query(query, {
                    "neo4j_id": int(match.matched_neo4j_id) if match.matched_neo4j_id.isdigit() else match.matched_neo4j_id,
                    "source": source,
                    **props,
                })
            except Exception as exc:
                logger.warning(f"[ConnectionResolver] Failed to update matched entity: {exc}")

    # ──────────────────────────────────────────────────────
    # Phase 5: Implicit Connection Discovery
    # ──────────────────────────────────────────────────────

    def _discover_implicit_connections(self, source: str) -> list[ImplicitConnection]:
        """
        Discover implicit relationships between newly-linked entities.

        Checks:
        1. Shared shareholders — two matched companies share the same owner
        2. Common tender participation — two matched companies won the same tender
        3. Geographic clustering — matched entities concentrated in same region
        """
        implicit: list[ImplicitConnection] = []
        matched_company_ids = [
            int(m.matched_neo4j_id) for m in self._matches
            if m.matched_neo4j_label == "Company" and m.matched_neo4j_id and m.matched_neo4j_id.isdigit()
        ]

        if len(matched_company_ids) < 2:
            return implicit

        # Cap input to prevent O(n²) explosion (50 companies = 1,225 pairs per query)
        capped_ids = matched_company_ids[:100]
        if len(matched_company_ids) > 100:
            logger.warning(
                f"[ConnectionResolver] Capped company IDs from {len(matched_company_ids)} to 100 "
                "to prevent performance degradation."
            )

        # 1. Shared shareholders
        shared = self._find_shared_shareholders(capped_ids)
        implicit.extend(shared)

        # 2. Common tender participation
        common_tenders = self._find_common_tender_winners(capped_ids)
        implicit.extend(common_tenders)

        # 3. Geographic clustering
        geo_cluster = self._find_geographic_clusters(capped_ids)
        implicit.extend(geo_cluster)

        return implicit

    def _find_shared_shareholders(self, company_ids: list[int]) -> list[ImplicitConnection]:
        """Find pairs of companies that share a common shareholder."""
        if len(company_ids) < 2:
            return []

        query = """
        MATCH (a:Company) WHERE id(a) IN $company_ids
        MATCH (b:Company) WHERE id(b) IN $company_ids AND id(a) < id(b)
        MATCH (a)<-[:SHAREHOLDER_OF]-(p:Person)-[:SHAREHOLDER_OF]->(b)
        RETURN a.nome_normalizzato AS name_a, b.nome_normalizzato AS name_b,
               coalesce(p.nome_normalizzato, p.name, p.nome, p.cognome, 'Unknown') AS person_name, count(p) AS shared_count
        ORDER BY shared_count DESC
        LIMIT 20
        """
        try:
            results = self.db.run_query(query, {"company_ids": company_ids}, timeout=30)
            connections: list[ImplicitConnection] = []
            for row in results:
                connections.append(ImplicitConnection(
                    entity_a=row["name_a"],
                    entity_b=row["name_b"],
                    discovery_type="shared_shareholder",
                    confidence=min(0.5 + row["shared_count"] * 0.15, 1.0),
                    description=f"Both companies share shareholder '{row['person_name']}' ({row['shared_count']} links)",
                ))
            return connections
        except Exception as exc:
            logger.warning(f"[ConnectionResolver] Shared shareholder discovery failed: {exc}")
            return []

    def _find_common_tender_winners(self, company_ids: list[int]) -> list[ImplicitConnection]:
        """Find pairs of companies that won the same tenders."""
        if len(company_ids) < 2:
            return []

        query = """
        MATCH (a:Company) WHERE id(a) IN $company_ids
        MATCH (b:Company) WHERE id(b) IN $company_ids AND id(a) < id(b)
        MATCH (a)-[:WINS]->(t:Tender)<-[:WINS]-(b)
        RETURN a.nome_normalizzato AS name_a, b.nome_normalizzato AS name_b,
               t.cig AS tender_cig, count(t) AS shared_tenders
        ORDER BY shared_tenders DESC
        LIMIT 20
        """
        try:
            results = self.db.run_query(query, {"company_ids": company_ids}, timeout=30)
            connections: list[ImplicitConnection] = []
            for row in results:
                connections.append(ImplicitConnection(
                    entity_a=row["name_a"],
                    entity_b=row["name_b"],
                    discovery_type="common_tender",
                    confidence=min(0.4 + row["shared_tenders"] * 0.2, 1.0),
                    description=f"Both companies won tender CIG={row['tender_cig']} ({row['shared_tenders']} shared)",
                ))
            return connections
        except Exception as exc:
            logger.warning(f"[ConnectionResolver] Common tender discovery failed: {exc}")
            return []

    def _find_geographic_clusters(self, company_ids: list[int]) -> list[ImplicitConnection]:
        """Find companies concentrated in the same region."""
        if len(company_ids) < 2:
            return []

        query = """
        MATCH (c:Company) WHERE id(c) IN $company_ids AND c.regione IS NOT NULL
        WITH c.regione AS region, collect(c) AS companies
        WHERE size(companies) >= 2
        UNWIND companies AS c1
        UNWIND companies AS c2
        WITH c1, c2, region
        WHERE id(c1) < id(c2)
        RETURN c1.nome_normalizzato AS name_a, c2.nome_normalizzato AS name_b,
               region, count(*) AS co_occurrences
        ORDER BY co_occurrences DESC
        LIMIT 20
        """
        try:
            results = self.db.run_query(query, {"company_ids": company_ids}, timeout=15)
            connections: list[ImplicitConnection] = []
            for row in results:
                connections.append(ImplicitConnection(
                    entity_a=row["name_a"],
                    entity_b=row["name_b"],
                    discovery_type="geographic_cluster",
                    confidence=0.5,
                    description=f"Both companies are in region '{row['region']}'",
                ))
            return connections
        except Exception as exc:
            logger.warning(f"[ConnectionResolver] Geographic clustering failed: {exc}")
            return []

    # ──────────────────────────────────────────────────────
    # Phase 6: Shortest Path Discovery
    # ──────────────────────────────────────────────────────

    def _discover_paths(self, ner_result: NERResult) -> list[DiscoveredPath]:
        """
        Discover shortest paths between entities that were newly linked to the graph.
        """
        paths: list[DiscoveredPath] = []
        matched_pairs = [
            (m1, m2)
            for i, m1 in enumerate(self._matches)
            for m2 in self._matches[i + 1:]
            if m1.matched_neo4j_id and m2.matched_neo4j_id
            and m1.matched_neo4j_id != m2.matched_neo4j_id
        ]

        # Limit to avoid explosion
        for m1, m2 in matched_pairs[:10]:
            path = self._find_shortest_path(m1, m2)
            if path:
                paths.append(path)

        return paths

    def _find_shortest_path(self, m1: EntityMatch, m2: EntityMatch) -> DiscoveredPath | None:
        """Find shortest path between two matched entities."""
        try:
            id1 = int(m1.matched_neo4j_id) if m1.matched_neo4j_id and m1.matched_neo4j_id.isdigit() else m1.matched_neo4j_id
            id2 = int(m2.matched_neo4j_id) if m2.matched_neo4j_id and m2.matched_neo4j_id.isdigit() else m2.matched_neo4j_id

            query = """
            MATCH path = shortestPath(
                (a)-[*1..4]-(b)
            )
            WHERE id(a) = $id1 AND id(b) = $id2
            RETURN path
            LIMIT 1
            """
            results = self.db.run_query(query, {"id1": id1, "id2": id2})
            if not results:
                return None

            # Extract path info
            path_data = results[0]["path"]
            nodes = list(path_data.nodes)
            rels = list(path_data.relationships)

            via = [n.get("name", n.get("nome_normalizzato", n.get("id", "?"))) for n in nodes[1:-1]]
            rel_types = [r.type for r in rels]

            return DiscoveredPath(
                from_entity=m1.matched_properties.get("name", m1.matched_properties.get("nome_normalizzato", "Unknown")),
                to_entity=m2.matched_properties.get("name", m2.matched_properties.get("nome_normalizzato", "Unknown")),
                path_length=len(rels),
                via=via,
                description=f"Connected via {', '.join(rel_types)}",
            )
        except Exception as exc:
            logger.debug(f"[ConnectionResolver] Shortest path failed: {exc}")
            return None

    # ──────────────────────────────────────────────────────
    # Helper: Neo4j queries
    # ──────────────────────────────────────────────────────

    def _query_by_identifier(self, label: str, field: str, value: str) -> dict | None:
        """Query Neo4j for a node by exact identifier match."""
        query = f"""
        MATCH (n:{label} {{{field}: $value}})
        RETURN id(n) AS neo4j_id, properties(n) AS properties
        LIMIT 1
        """
        results = self.db.run_query(query, {"value": value})
        if results:
            row = results[0]
            return {"neo4j_id": str(row["neo4j_id"]), "properties": dict(row["properties"])}
        return None

    def _fulltext_search(self, name: str, label: str, limit: int = 5) -> list[dict]:
        """Search using Neo4j full-text index (if available)."""
        query = f"""
        CALL db.index.fulltext.queryNodes("entity_search_idx", $name + "*", {{limit: $limit}})
        YIELD node, score
        WHERE '{label}' IN labels(node) OR '{label}' = 'CustomRecord'
        RETURN id(node) AS neo4j_id,
               coalesce(node.nome_normalizzato, node.name, node.nome, node.titolo, node.descrizione) AS name,
               properties(node) AS properties,
               score
        ORDER BY score DESC
        """
        try:
            results = self.db.run_query(query, {"name": name, "limit": limit})
            return [
                {
                    "neo4j_id": str(row["neo4j_id"]),
                    "name": row["name"] or "",
                    "properties": dict(row["properties"]),
                }
                for row in results
            ]
        except Exception:
            # Full-text index may not exist
            return []

    def _levenshtein_search(self, name: str, label: str, limit: int = 5) -> list[dict]:
        """Fallback: scan all nodes of the given label with Levenshtein similarity."""
        name_prop = "nome_normalizzato" if label == "Company" else "name"

        query = f"""
        MATCH (n:{label})
        WHERE n.{name_prop} IS NOT NULL
        WITH n, apoc.text.levenshteinSimilarity(n.{name_prop}, $name) AS sim
        WHERE sim > {self.llm_threshold}
        RETURN id(n) AS neo4j_id, n.{name_prop} AS name, properties(n) AS properties, sim
        ORDER BY sim DESC
        LIMIT $limit
        """
        try:
            results = self.db.run_query(query, {"name": name, "limit": limit})
            return [
                {
                    "neo4j_id": str(row["neo4j_id"]),
                    "name": row.get("name", ""),
                    "properties": dict(row["properties"]),
                }
                for row in results
            ]
        except Exception as exc:
            logger.debug(f"[ConnectionResolver] Levenshtein search failed: {exc}")
            return []

    # ──────────────────────────────────────────────────────
    # Helper: LLM
    # ──────────────────────────────────────────────────────

    def _llm_verify_same_entity(self, name1: str, name2: str) -> bool:
        """Ask LLM if two company names refer to the same entity."""
        if not self.llm:
            return False

        system_prompt = (
            "You are an expert in Italian corporate structures. "
            "Determine if two company names refer to the same legal entity, "
            "accounting for abbreviations, legal forms (S.R.L., S.p.A.), or minor typos. "
            "Respond with ONLY 'YES' or 'NO'."
        )

        user_prompt = f"Name 1: {name1}\nName 2: {name2}"

        try:
            response = self.llm.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            return response.strip().upper() == "YES"
        except Exception as exc:
            logger.warning(f"[ConnectionResolver] LLM verification failed: {exc}")
            return False

    # ──────────────────────────────────────────────────────
    # Helper: Property extraction
    # ──────────────────────────────────────────────────────

    def _extract_known_properties(self, entity: ExtractedEntity) -> dict:
        """Extract only known property fields from an extracted entity."""
        props = entity.properties or {}
        known_fields = _KNOWN_ENTITY_PROPERTIES.get(entity.type, [])
        return {k: v for k, v in props.items() if k in known_fields and v}

    def _extract_cf(self, props: dict) -> str | None:
        """Extract CF from any property field."""
        for key in ("cf", "codice_fiscale", "tax_id", "name"):
            val = props.get(key)
            if val and _CF_RE.search(str(val)):
                return _CF_RE.search(str(val)).group(1)
        # Try scanning the name field for embedded CF
        name = props.get("name", "")
        if name:
            match = _CF_RE.search(name)
            if match:
                return match.group(1)
        return None

    def _extract_piva(self, props: dict) -> str | None:
        """Extract P.IVA from any property field."""
        for key in ("piva", "partita_iva", "vat", "name"):
            val = props.get(key)
            if val and _PIVA_RE.search(str(val)):
                match = _PIVA_RE.search(str(val))
                if match:
                    return match.group(2)
        return None

    def _extract_cup(self, props: dict) -> str | None:
        """Extract CUP from any property field."""
        for key in ("cup", "codice_cup", "description", "name"):
            val = props.get(key)
            if val and _CUP_RE.search(str(val)):
                return _CUP_RE.search(str(val)).group(1)
        return None

    def _extract_cig(self, props: dict) -> str | None:
        """Extract CIG from any property field."""
        for key in ("cig", "codice_cig", "tender_id", "name"):
            val = props.get(key)
            if val and _CIG_RE.search(str(val)):
                return _CIG_RE.search(str(val)).group(1)
        return None
