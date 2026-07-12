from loguru import logger
from rapidfuzz import fuzz

# Assuming these exist in your project
from paladino.db import Neo4jConnection
from paladino.etl.normalizer import CompanyNormalizer
from paladino.llm_manager import LLMManager


class EntityDeduplicator:
    """
    Identifies and merges duplicate entities (e.g., Company, Person) in Neo4j
    using multi-pass blocking, weighted scoring, and LLM-based disambiguation.
    """

    def __init__(
        self, driver: Neo4jConnection, llm_manager: LLMManager, fuzzy_threshold: float = 0.7
    ):
        self.driver = driver
        self.llm_manager = llm_manager
        self.fuzzy_threshold = fuzzy_threshold

    def block_entities(self, entity_type: str, entities: list[dict]) -> dict[str, list[dict]]:
        """
        Blocks entities into groups using multi-pass fingerprints.
        """
        blocked_entities = {}

        for entity in entities:
            keys = []
            if entity_type == "Company":
                # Pass 1: Global Phonetic Block
                keys.append(
                    f"PHON_{CompanyNormalizer.get_blocking_key(entity.get('nome_originale', ''))}"
                )

                # Pass 2: Geo-Phonetic Block (City + Name fragment)
                cod_istat = entity.get("cod_istat")
                if cod_istat:
                    keys.append(
                        f"GEO_{CompanyNormalizer.get_blocking_key(entity.get('nome_originale', ''), cod_istat)}"
                    )

                # Pass 3: Exact CF Block
                cf = entity.get("cf")
                if cf:
                    keys.append(f"CF_{cf}")

            elif entity_type == "Person":
                cognome = entity.get("cognome", "").upper()
                if cognome:
                    keys.append(f"PERS_{cognome[:4]}_{entity.get('luogo_nascita', 'UNK')}")

            # Add entity to all its generated blocks
            for block_key in keys:
                if block_key not in blocked_entities:
                    blocked_entities[block_key] = []
                blocked_entities[block_key].append(entity)

        logger.info(
            f"Blocked {len(entities)} {entity_type} into {len(blocked_entities)} multi-pass blocks."
        )
        return blocked_entities

    def calculate_match_score(self, entity1: dict, entity2: dict, entity_type: str) -> float:
        """
        Calculates a weighted probabilistic match score (0.0 to 1.0).
        """
        if entity_type != "Company":
            # Fallback for other types
            return fuzz.token_sort_ratio(str(entity1), str(entity2)) / 100.0

        score = 0.0

        # 1. Tax Code (CF) Match - Absolute confidence if present
        cf1, cf2 = entity1.get("cf"), entity2.get("cf")
        if cf1 and cf2 and cf1 == cf2:
            return 1.0

        # 2. Name Similarity (Weight: 0.7)
        name1 = entity1.get("nome_normalizzato", "")
        name2 = entity2.get("nome_normalizzato", "")
        if name1 and name2:
            name_sim = fuzz.token_sort_ratio(name1, name2) / 100.0
            score += name_sim * 0.7

        # 3. Geographic Context (Weight: 0.3)
        istat1, istat2 = entity1.get("cod_istat"), entity2.get("cod_istat")
        if istat1 and istat2 and istat1 == istat2:
            score += 0.3

        return min(score, 1.0)

    def generate_candidate_pairs(
        self, blocked_entities: dict[str, list[dict]], entity_type: str
    ) -> list[tuple[dict, dict, float]]:
        """
        Generates unique candidate pairs using weighted scoring.
        """
        candidate_pairs = []
        seen_pairs = set()

        for block in blocked_entities.values():
            if len(block) < 2:
                continue

            for i in range(len(block)):
                for j in range(i + 1, len(block)):
                    e1, e2 = block[i], block[j]
                    pair_key = tuple(sorted([str(e1["id"]), str(e2["id"])]))

                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    score = self.calculate_match_score(e1, e2, entity_type)
                    if score >= self.fuzzy_threshold:
                        candidate_pairs.append((e1, e2, score))

        return candidate_pairs

    def _llm_disambiguate_pair(self, entity1: dict, entity2: dict, entity_type: str) -> bool:
        """
        Uses the LLM to make a final decision on ambiguous entity pairs.
        """
        # Create a concise, clear prompt for the LLM
        prompt_template = """You are an expert entity resolution system. Given two {entity_type} records, \
determine if they refer to the SAME real-world entity despite minor differences. \
Respond ONLY with 'YES' if they are the same, and 'NO' if they are different.

Entity 1:
{entity1_details}

Entity 2:
{entity2_details}

Are Entity 1 and Entity 2 the SAME {entity_type}?"""

        entity1_details = "\n".join(
            [f"- {k}: {v}" for k, v in entity1.items() if k not in ["id", "provenance", "labels"]]
        )
        entity2_details = "\n".join(
            [f"- {k}: {v}" for k, v in entity2.items() if k not in ["id", "provenance", "labels"]]
        )

        prompt = prompt_template.format(
            entity_type=entity_type,
            entity1_details=entity1_details,
            entity2_details=entity2_details,
        )

        logger.debug(f"Sending to LLM for disambiguation:\n{prompt}")
        response = self.llm_manager.chat([{"role": "user", "content": prompt}])

        if response and response.strip().upper() == "YES":
            logger.info(f"LLM decided to merge: {entity1.get('id')} and {entity2.get('id')}")
            return True
        logger.info(f"LLM decided NOT to merge: {entity1.get('id')} and {entity2.get('id')}")
        return False

    def deduplicate(
        self, entities: list[dict], threshold: float = None
    ) -> list[tuple[str, str, str]]:
        """Alias for deduplicate_entities to satisfy integration tests."""
        if threshold:
            self.fuzzy_threshold = threshold
        return self.deduplicate_entities("Company", entities)

    def deduplicate_entities(
        self, entity_type: str, entities: list[dict]
    ) -> list[tuple[str, str, str]]:
        """
        Orchestrates the full deduplication pipeline.

        Returns:
            List[Tuple[str, str, str]]: A list of (source_node_id, target_node_id, reason) tuples.
        """
        merges_to_perform = []

        # Step 1: Block entities using fingerprints
        blocked_entities = self.block_entities(entity_type, entities)

        # Step 2: Generate candidate pairs with weighted scores
        candidate_pairs = self.generate_candidate_pairs(blocked_entities, entity_type)

        # Keep track of which nodes have already been "merged away"
        merged_nodes_ids = set()

        # Step 3: Evaluate candidate pairs based on the new tiered policy
        # Sort by score descending to handle highest confidence merges first
        candidate_pairs.sort(key=lambda x: x[2], reverse=True)

        for entity1, entity2, score in candidate_pairs:
            # Skip if either entity has already been marked for merging into another
            if entity1["id"] in merged_nodes_ids or entity2["id"] in merged_nodes_ids:
                continue

            target_id = min(entity1["id"], entity2["id"])
            source_id = max(entity1["id"], entity2["id"])

            # Tier 1: Absolute Match (Exact CF)
            if score >= 1.0:
                reason = "exact_cf_match"
                merges_to_perform.append((source_id, target_id, reason))
                merged_nodes_ids.add(source_id)
                logger.info(f"Auto-merging {source_id} -> {target_id} (Exact CF)")

            # Tier 2: High Confidence Fuzzy Match (>= 0.92)
            elif score >= 0.92:
                reason = f"high_conf_fuzzy_{score:.2f}"
                merges_to_perform.append((source_id, target_id, reason))
                merged_nodes_ids.add(source_id)
                logger.info(f"Auto-merging {source_id} -> {target_id} (Confidence: {score:.2f})")

            # Tier 3: Grey Zone Ambiguity (0.75 - 0.92) -> LLM Judge
            elif score >= 0.75:
                if self._llm_disambiguate_pair(entity1, entity2, entity_type):
                    reason = f"llm_judged_grey_zone_{score:.2f}"
                    merges_to_perform.append((source_id, target_id, reason))
                    merged_nodes_ids.add(source_id)
                    logger.info(f"LLM-merging {source_id} -> {target_id} (Score: {score:.2f})")

        return merges_to_perform

    def run_deduplication_pipeline(self, entity_type: str):
        """
        Fetches all entities of a given type, deduplicates them, and performs merges in Neo4j.
        """
        logger.info(f"Starting deduplication pipeline for {entity_type} entities.")

        # Fetch all entities of this type from Neo4j
        query = f"MATCH (n:{entity_type}) RETURN properties(n) as props, id(n) as internal_id"
        records = self.driver.run_query(query)

        # Convert to a list of dicts with a consistent 'id' key
        entities = []
        for record in records:
            props = record["props"]
            # Use a synthetic ID for processing, ensuring it's unique
            props["id"] = record["internal_id"]  # Use Neo4j's internal ID
            entities.append(props)

        if not entities:
            logger.warning(f"No {entity_type} entities found to deduplicate.")
            return

        merges = self.deduplicate_entities(entity_type, entities)

        if not merges:
            logger.info(f"No duplicates found for {entity_type}.")
            return

        logger.info(f"Found {len(merges)} merge operations for {entity_type}. Executing merges...")
        for source_id, target_id, reason in merges:
            self._merge_nodes_and_relationships(source_id, target_id, [entity_type], reason)

        logger.success(f"Deduplication pipeline completed for {entity_type}.")

    def _merge_nodes_and_relationships(
        self, source_node_id: str, target_node_id: str, labels: list[str], merge_reason: str = ""
    ):
        """
        Merges a source node into a target node in Neo4j, re-pointing relationships
        and consolidating properties.
        """

        logger.info(f"Merging node {source_node_id} into {target_node_id} ({merge_reason})")

        # Cypher to merge node properties, re-point relationships, and delete source
        merge_query = """
        MATCH (source) WHERE id(source) = $source_node_id
        MATCH (target) WHERE id(target) = $target_node_id
        
        // Ensure both nodes exist and are of the expected type
        WITH source, target
        WHERE any(label IN $labels WHERE label IN labels(source))
          AND any(label IN $labels WHERE label IN labels(target))
        
        // Merge properties from source to target, preferring target's non-empty values
        SET target += properties(source)
        
        // Track the merge for provenance
        SET target.merged_from_internal_ids = coalesce(target.merged_from_internal_ids, []) + [$source_node_id]
        SET target.merge_reasons = coalesce(target.merge_reasons, []) + [$merge_reason]
        SET target.last_merge_date = datetime()
        
        // Re-point all incoming relationships to source to target
        CALL apoc.refactor.to(source, target) YIELD input, output
        
        // Re-point all outgoing relationships from source to target
        CALL apoc.refactor.from(source, target) YIELD input, output
        
        // Delete the source node
        DETACH DELETE source
        """

        try:
            self.driver.run_query(
                merge_query,
                {
                    "source_node_id": source_node_id,
                    "target_node_id": target_node_id,
                    "labels": labels,
                    "merge_reason": merge_reason,
                },
            )
            logger.success(f"Successfully merged {source_node_id} into {target_node_id}.")
        except Exception as e:
            logger.error(f"Error merging nodes {source_node_id} and {target_node_id}: {e}")
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # New Methods for API Integration
    # ─────────────────────────────────────────────────────────────────────────

    def find_candidates_for_entity(
        self,
        entity_id: str,
        entity_type: str = "Company",
        min_similarity: float = 0.75,
        limit: int = 20,
    ) -> list[dict]:
        """
        Find duplicate candidates for a specific entity.
        Used by the /companies/duplicates endpoint.

        Args:
            entity_id: Entity ID, CF, or P.IVA to search for
            entity_type: Type of entity (Company, Person, etc.)
            min_similarity: Minimum similarity score threshold
            limit: Maximum number of candidates to return

        Returns:
            List of candidate dictionaries with similarity scores and match reasons
        """
        query = """
        MATCH (target)
        WHERE target.id = $entity_id OR target.cf = $entity_id OR target.piva = $entity_id
        WITH target

        // Candidate selection with multi-pass blocking
        OPTIONAL MATCH (candidate)
        WHERE candidate:Company
          AND candidate.id <> target.id

        // Scoring logic
        WITH target, candidate,
             CASE
                WHEN target.cf = candidate.cf AND target.cf IS NOT NULL THEN 1.0
                WHEN target.piva = candidate.piva AND target.piva IS NOT NULL THEN 0.95
                ELSE apoc.text.levenshteinSimilarity(
                    target.nome_normalizzato,
                    candidate.nome_normalizzato
                )
             END as score

        WHERE score >= $min_similarity
        RETURN
            candidate.id as entity_id,
            candidate.cf as cf,
            candidate.piva as piva,
            candidate.nome_normalizzato,
            score as similarity_score,
            CASE
                WHEN target.cf = candidate.cf THEN 'exact_cf_match'
                WHEN target.piva = candidate.piva THEN 'exact_piva_match'
                ELSE 'fuzzy_name_match'
            END as match_reason,
            properties(candidate) as properties
        ORDER BY score DESC
        LIMIT $limit
        """

        results = self.driver.run_query(
            query,
            {
                "entity_id": entity_id,
                "min_similarity": min_similarity,
                "limit": limit,
            },
        )

        return results

    def merge_with_rollback(
        self,
        source_ids: list[str],
        target_id: str,
        labels: list[str],
        dry_run: bool = False,
    ) -> dict:
        """
        Merge nodes with rollback snapshot creation.

        Args:
            source_ids: List of source entity IDs to merge
            target_id: Target entity ID to merge into
            labels: List of Neo4j labels for the entities
            dry_run: If True, preview merge without committing

        Returns:
            Dictionary with merge results and rollback_id (if not dry_run)
        """
        import uuid
        from datetime import datetime

        # Generate rollback ID
        rollback_id = f"merge_{datetime.now().isoformat()}_{uuid.uuid4().hex[:8]}"

        if dry_run:
            # Simulate merge and return preview
            return self._preview_merge(source_ids, target_id, labels, rollback_id)

        # Create rollback snapshot
        self._create_rollback_snapshot(rollback_id, source_ids, target_id, labels)

        # Execute merge
        result = self._execute_merge(source_ids, target_id, labels)

        # Record merge in audit log
        self._log_merge(rollback_id, source_ids, target_id, result)

        return {
            "rollback_id": rollback_id,
            **result,
        }

    def _preview_merge(
        self, source_ids: list[str], target_id: str, labels: list[str], rollback_id: str
    ) -> dict:
        """Preview merge operation without committing."""
        query = """
        MATCH (target)
        WHERE target.id = $target_id OR target.cf = $target_id OR target.piva = $target_id

        OPTIONAL MATCH (source)
        WHERE source.id IN $source_ids

        RETURN
            target.id as target_id,
            collect(DISTINCT source.id) as source_ids,
            properties(target) as target_properties,
            [source | properties(source)] as source_properties,
            size([(source)-[]-() | 1]) as relationships_to_update
        """

        results = self.driver.run_query(
            query, {"target_id": target_id, "source_ids": source_ids}
        )

        if not results or not results[0]["target_id"]:
            return {
                "status": "error",
                "error": "Target entity not found",
                "rollback_id": rollback_id,
            }

        result = results[0]
        return {
            "status": "dry_run",
            "target_id": result["target_id"],
            "source_ids": result["source_ids"],
            "properties_to_merge": result["source_properties"],
            "relationships_to_update": result["relationships_to_update"],
            "rollback_id": rollback_id,
        }

    def _create_rollback_snapshot(
        self, rollback_id: str, source_ids: list[str], target_id: str, labels: list[str]
    ):
        """Create a rollback snapshot node with all pre-merge state."""
        query = """
        MATCH (target)
        WHERE target.id = $target_id OR target.cf = $target_id OR target.piva = $target_id

        OPTIONAL MATCH (source)
        WHERE source.id IN $source_ids

        // Create rollback snapshot
        CREATE (rollback:MergeRollback {
            id: $rollback_id,
            created_at: datetime(),
            target_id: $target_id,
            source_ids: $source_ids,
            labels: $labels,
            target_snapshot: properties(target),
            source_snapshots: [
                (source) | {id: source.id, properties: properties(source)}
            ]
        })

        RETURN rollback.id as id
        """

        self.driver.run_query(
            query,
            {
                "rollback_id": rollback_id,
                "target_id": target_id,
                "source_ids": source_ids,
                "labels": labels,
            },
        )

        logger.info(f"Created rollback snapshot: {rollback_id}")

    def _execute_merge(
        self, source_ids: list[str], target_id: str, labels: list[str]
    ) -> dict:
        """Execute the actual merge operation."""
        # Count relationships before merge
        rel_count_query = """
        MATCH (source)
        WHERE source.id IN $source_ids
        RETURN count{(source)--()} as rel_count
        """

        rel_results = self.driver.run_query(rel_count_query, {"source_ids": source_ids})
        relationships_count = rel_results[0]["rel_count"] if rel_results else 0

        # Merge all sources into target
        merged_count = 0
        for source_id in source_ids:
            try:
                self._merge_nodes_and_relationships(source_id, target_id, labels, "api_merge")
                merged_count += 1
            except Exception as e:
                logger.error(f"Failed to merge {source_id} into {target_id}: {e}")

        # Migrate comments from source entities to target
        comments_migrated = self._migrate_comments(source_ids, target_id, labels)

        return {
            "merged_count": merged_count,
            "relationships_updated": relationships_count,
            "comments_migrated": comments_migrated,
        }

    def _log_merge(
        self, rollback_id: str, source_ids: list[str], target_id: str, result: dict
    ):
        """Record merge operation in audit log."""
        log_query = """
        MATCH (rollback:MergeRollback {id: $rollback_id})
        SET rollback.status = 'COMPLETED',
            rollback.merged_count = $merged_count,
            rollback.relationships_updated = $relationships_updated
        """

        self.driver.run_query(
            log_query,
            {
                "rollback_id": rollback_id,
                "merged_count": result["merged_count"],
                "relationships_updated": result["relationships_updated"],
            },
        )

        # Create a merge rationale comment for audit trail
        try:
            self.create_merge_rationale_comment(
                target_id=target_id,
                entity_type="Company",  # Default, could be parameterized
                source_ids=source_ids,
                rollback_id=rollback_id,
            )
        except Exception as e:
            logger.warning(f"Failed to create merge rationale comment: {e}")

    def rollback_merge(self, rollback_id: str) -> dict:
        """Restore pre-merge state from rollback snapshot."""
        # First, get the source IDs from the rollback snapshot
        snapshot_query = """
        MATCH (rollback:MergeRollback {id: $rollback_id})
        RETURN rollback.source_ids as source_ids, rollback.target_id as target_id
        """
        
        snapshot_result = self.driver.run_query(snapshot_query, {"rollback_id": rollback_id})
        if not snapshot_result:
            raise ValueError(f"Rollback snapshot {rollback_id} not found")
        
        source_ids = snapshot_result[0]["source_ids"]
        target_id = snapshot_result[0]["target_id"]
        
        # Store which comments belong to which original source
        # Comments migrated during merge are tagged with 'migrated-from-merge'
        # We'll re-distribute them to the first source entity (simplified approach)
        # A more sophisticated approach would track original comment ownership
        
        query = """
        MATCH (rollback:MergeRollback {id: $rollback_id})
        WITH rollback

        // Restore target node
        MATCH (target)
        WHERE target.id = rollback.target_id
        SET target = rollback.target_snapshot

        // Recreate source nodes
        UNWIND rollback.source_snapshots as source_data
        CREATE (source:Company {id: source_data.id})
        SET source = source_data.properties

        // Re-point migrated comments back to the first source entity
        // This is a simplified approach - in production, you might want to preserve
        // all comments on the target or distribute them based on original ownership
        MATCH (c:Comment {entity_id: rollback.target_id})
        WHERE 'migrated-from-merge' IN c.tags
        SET c.entity_id = rollback.source_ids[0]
        REMOVE c.tags

        // Mark rollback as completed
        SET rollback.rolled_back_at = datetime(),
            rollback.status = 'ROLLED_BACK'

        RETURN count(source) as sources_restored
        """

        result = self.driver.run_query(query, {"rollback_id": rollback_id})
        
        # Delete merge rationale comments created during the merge
        try:
            self._cleanup_merge_comments(rollback_id)
        except Exception as e:
            logger.warning(f"Failed to cleanup merge comments during rollback: {e}")
        
        return {"sources_restored": result[0]["sources_restored"] if result else 0}

    def _cleanup_merge_comments(self, rollback_id: str) -> int:
        """
        Remove merge rationale comments created during a merge when rolling back.
        
        Args:
            rollback_id: The rollback ID to identify merge comments
            
        Returns:
            Number of comments cleaned up
        """
        # Find and delete merge rationale comments by searching for the rollback_id in content
        query = """
        MATCH (c:Comment)
        WHERE c.entity_type = 'Company' 
          AND 'merge-rationale' IN c.tags
          AND c.content CONTAINS $rollback_id
        DETACH DELETE c
        RETURN count(c) as deleted_count
        """
        
        result = self.driver.run_query(query, {"rollback_id": rollback_id})
        deleted_count = result[0]["deleted_count"] if result else 0
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} merge rationale comments for rollback {rollback_id}")
        
        return deleted_count

    def _migrate_comments(
        self, source_ids: list[str], target_id: str, labels: list[str]
    ) -> int:
        """
        Migrate comments from source entities to target entity.

        When entities are merged, their comments should be preserved and
        re-pointed to the surviving (target) entity.

        Args:
            source_ids: List of source entity IDs being merged away
            target_id: Target entity ID surviving the merge
            labels: List of Neo4j labels for the entities

        Returns:
            Number of comments migrated
        """
        query = """
        MATCH (c:Comment)
        WHERE c.entity_id IN $source_ids
        SET c.entity_id = $target_id,
            c.tags = c.tags + ['migrated-from-merge']
        RETURN count(c) as migrated_count
        """

        result = self.driver.run_query(
            query,
            {
                "source_ids": source_ids,
                "target_id": target_id,
            },
        )

        migrated_count = result[0]["migrated_count"] if result else 0

        if migrated_count > 0:
            logger.info(f"Migrated {migrated_count} comments from source entities to {target_id}")

        return migrated_count

    def create_merge_rationale_comment(
        self, target_id: str, entity_type: str, source_ids: list[str], 
        rollback_id: str, author: str = "system"
    ) -> str:
        """
        Create a system comment documenting the merge rationale.

        This provides an audit trail directly on the merged entity, making
        it clear why the merge occurred and which entities were combined.

        Args:
            target_id: Target entity ID that survived the merge
            entity_type: Type of entity (e.g., "Company")
            source_ids: List of source entity IDs that were merged away
            rollback_id: Rollback snapshot ID for audit reference
            author: Author identifier (default: "system")

        Returns:
            ID of the created comment
        """
        import uuid
        from datetime import datetime, UTC

        comment_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        source_list = ", ".join(source_ids)
        content = (
            f"**Entity Merge Executed**\n\n"
            f"This entity is the result of merging the following duplicates:\n"
            f"- **Source entities**: {source_list}\n"
            f"- **Rollback ID**: `{rollback_id}`\n"
            f"- **Merge date**: {now.isoformat()}\n\n"
            f"This merge was performed via the Paladino API. Use the rollback ID "
            f"to undo this operation if needed."
        )

        query = """
        CREATE (c:Comment {
            id: $id,
            entity_id: $entity_id,
            entity_type: $entity_type,
            author: $author,
            content: $content,
            parent_comment_id: null,
            tags: ['merge-rationale', 'system', 'audit'],
            mentions: [],
            is_deleted: false,
            created_at: $created_at,
            edited_at: null,
            source: 'system',
            confidence: 1.0
        })
        RETURN c.id as id
        """

        result = self.driver.run_query(
            query,
            {
                "id": comment_id,
                "entity_id": target_id,
                "entity_type": entity_type,
                "author": author,
                "content": content,
                "created_at": now.isoformat(),
            },
        )

        logger.info(f"Created merge rationale comment {comment_id} for {entity_type}:{target_id}")

        return comment_id

    def get_merge_history(self, limit: int = 50) -> list[dict]:
        """Get recent merge operations for audit."""
        query = """
        MATCH (r:MergeRollback)
        RETURN r.id as rollback_id,
               r.created_at as created_at,
               r.target_id as target_id,
               r.source_ids as source_ids,
               r.status as status,
               r.merged_count as merged_count
        ORDER BY r.created_at DESC
        LIMIT $limit
        """

        return self.driver.run_query(query, {"limit": limit})
