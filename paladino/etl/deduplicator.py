from typing import List, Dict, Tuple
from rapidfuzz import fuzz
from loguru import logger
import polars as pl

# Assuming these exist in your project
from paladino.db import Neo4jConnection
from paladino.llm_manager import LLMManager

from paladino.etl.normalizer import CompanyNormalizer

class EntityDeduplicator:
    """
    Identifies and merges duplicate entities (e.g., Company, Person) in Neo4j
    using multi-pass blocking, weighted scoring, and LLM-based disambiguation.
    """
    
    def __init__(self, driver: Neo4jConnection, llm_manager: LLMManager, fuzzy_threshold: float = 0.7):
        self.driver = driver
        self.llm_manager = llm_manager
        self.fuzzy_threshold = fuzzy_threshold

    def block_entities(self, entity_type: str, entities: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Blocks entities into groups using multi-pass fingerprints.
        """
        blocked_entities = {}
        
        for entity in entities:
            keys = []
            if entity_type == "Company":
                # Pass 1: Global Phonetic Block
                keys.append(f"PHON_{CompanyNormalizer.get_blocking_key(entity.get('nome_originale', ''))}")
                
                # Pass 2: Geo-Phonetic Block (City + Name fragment)
                cod_istat = entity.get('cod_istat')
                if cod_istat:
                    keys.append(f"GEO_{CompanyNormalizer.get_blocking_key(entity.get('nome_originale', ''), cod_istat)}")
                
                # Pass 3: Exact CF Block
                cf = entity.get('cf')
                if cf:
                    keys.append(f"CF_{cf}")
            
            elif entity_type == "Person":
                cognome = entity.get('cognome', '').upper()
                if cognome:
                    keys.append(f"PERS_{cognome[:4]}_{entity.get('luogo_nascita', 'UNK')}")

            # Add entity to all its generated blocks
            for block_key in keys:
                if block_key not in blocked_entities:
                    blocked_entities[block_key] = []
                blocked_entities[block_key].append(entity)
        
        logger.info(f"Blocked {len(entities)} {entity_type} into {len(blocked_entities)} multi-pass blocks.")
        return blocked_entities

    def calculate_match_score(self, entity1: Dict, entity2: Dict, entity_type: str) -> float:
        """
        Calculates a weighted probabilistic match score (0.0 to 1.0).
        """
        if entity_type != "Company":
            # Fallback for other types
            return fuzz.token_sort_ratio(str(entity1), str(entity2)) / 100.0

        score = 0.0
        
        # 1. Tax Code (CF) Match - Absolute confidence if present
        cf1, cf2 = entity1.get('cf'), entity2.get('cf')
        if cf1 and cf2 and cf1 == cf2:
            return 1.0
            
        # 2. Name Similarity (Weight: 0.7)
        name1 = entity1.get('nome_normalizzato', '')
        name2 = entity2.get('nome_normalizzato', '')
        if name1 and name2:
            name_sim = fuzz.token_sort_ratio(name1, name2) / 100.0
            score += name_sim * 0.7
            
        # 3. Geographic Context (Weight: 0.3)
        istat1, istat2 = entity1.get('cod_istat'), entity2.get('cod_istat')
        if istat1 and istat2 and istat1 == istat2:
            score += 0.3
            
        return min(score, 1.0)

    def generate_candidate_pairs(self, blocked_entities: Dict[str, List[Dict]], entity_type: str) -> List[Tuple[Dict, Dict, float]]:
        """
        Generates unique candidate pairs using weighted scoring.
        """
        candidate_pairs = []
        seen_pairs = set()

        for block in blocked_entities.values():
            if len(block) < 2: continue
            
            for i in range(len(block)):
                for j in range(i + 1, len(block)):
                    e1, e2 = block[i], block[j]
                    pair_key = tuple(sorted([str(e1['id']), str(e2['id'])]))
                    
                    if pair_key in seen_pairs: continue
                    seen_pairs.add(pair_key)
                    
                    score = self.calculate_match_score(e1, e2, entity_type)
                    if score >= self.fuzzy_threshold:
                        candidate_pairs.append((e1, e2, score))
        
        return candidate_pairs

    def _llm_disambiguate_pair(self, entity1: Dict, entity2: Dict, entity_type: str) -> bool:
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
        
        entity1_details = "\n".join([f"- {k}: {v}" for k, v in entity1.items() if k not in ['id', 'provenance', 'labels']])
        entity2_details = "\n".join([f"- {k}: {v}" for k, v in entity2.items() if k not in ['id', 'provenance', 'labels']])

        prompt = prompt_template.format(
            entity_type=entity_type,
            entity1_details=entity1_details,
            entity2_details=entity2_details
        )
        
        logger.debug(f"Sending to LLM for disambiguation:\n{prompt}")
        response = self.llm_manager.chat([{"role": "user", "content": prompt}])
        
        if response and response.strip().upper() == 'YES':
            logger.info(f"LLM decided to merge: {entity1.get('id')} and {entity2.get('id')}")
            return True
        logger.info(f"LLM decided NOT to merge: {entity1.get('id')} and {entity2.get('id')}")
        return False

    def deduplicate(self, entities: List[Dict], threshold: float = None) -> List[Tuple[str, str, str]]:
        """Alias for deduplicate_entities to satisfy integration tests."""
        if threshold: self.fuzzy_threshold = threshold
        return self.deduplicate_entities("Company", entities)

    def deduplicate_entities(self, entity_type: str, entities: List[Dict]) -> List[Tuple[str, str, str]]:
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
            if entity1['id'] in merged_nodes_ids or entity2['id'] in merged_nodes_ids:
                continue

            target_id = min(entity1['id'], entity2['id'])
            source_id = max(entity1['id'], entity2['id'])
            
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
            props = record['props']
            # Use a synthetic ID for processing, ensuring it's unique
            props['id'] = record['internal_id'] # Use Neo4j's internal ID
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

    def _merge_nodes_and_relationships(self, source_node_id: str, target_node_id: str, labels: List[str], merge_reason: str = ''):
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
            self.driver.run_query(merge_query, {
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "labels": labels,
                "merge_reason": merge_reason
            })
            logger.success(f"Successfully merged {source_node_id} into {target_node_id}.")
        except Exception as e:
            logger.error(f"Error merging nodes {source_node_id} and {target_node_id}: {e}")
            raise
