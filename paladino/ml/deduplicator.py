"""
Company deduplication using blocking and fuzzy matching.
"""

import polars as pl
from typing import List, Dict, Tuple, Optional
from Levenshtein import ratio
from loguru import logger
from tqdm import tqdm

from paladino.ml.name_normalizer import CompanyNameNormalizer
from paladino.llm_manager import LLMManager


class CompanyDeduplicator:
    """Deduplicate companies using blocking and fuzzy matching."""
    
    def __init__(
        self,
        name_similarity_threshold: float = 0.85,
        llm_threshold: float = 0.65,
        cf_match_weight: float = 0.5,
        name_match_weight: float = 0.5,
        llm: Optional[LLMManager] = None
    ):
        """
        Initialize deduplicator.
        
        Args:
            name_similarity_threshold: Minimum Levenshtein ratio for automatic name match
            llm_threshold: Minimum ratio to trigger LLM verification
            cf_match_weight: Weight for CF matching in confidence score
            name_match_weight: Weight for name matching in confidence score
            llm: OllamaManager instance for advanced verification
        """
        self.name_threshold = name_similarity_threshold
        self.llm_threshold = llm_threshold
        self.cf_weight = cf_match_weight
        self.name_weight = name_match_weight
        self.normalizer = CompanyNameNormalizer()
        self.llm = llm
    
    def find_duplicates(self, companies_df: pl.DataFrame) -> pl.DataFrame:
        """
        Find duplicate companies.
        
        Args:
            companies_df: DataFrame with company data (must have 'cf', 'nome_normalizzato')
            
        Returns:
            DataFrame with duplicate pairs and confidence scores
        """
        logger.info(f"Finding duplicates in {len(companies_df)} companies...")
        
        # Strategy 1: Exact CF match
        cf_duplicates = self._find_cf_duplicates(companies_df)
        logger.info(f"Found {len(cf_duplicates)} CF-based duplicates")
        
        # Strategy 2: Fuzzy name match with blocking
        name_duplicates = self._find_name_duplicates(companies_df)
        logger.info(f"Found {len(name_duplicates)} name-based duplicates")
        
        # Combine and deduplicate
        all_duplicates = cf_duplicates + name_duplicates
        
        if all_duplicates:
            duplicates_df = pl.DataFrame(all_duplicates)
            
            # Keep highest confidence per pair
            duplicates_df = duplicates_df.sort("confidence", descending=True).unique(
                subset=["company_id_1", "company_id_2"],
                keep="first"
            )
            
            logger.success(f"Total unique duplicate pairs: {len(duplicates_df)}")
            return duplicates_df
        
        logger.warning("No duplicates found")
        return pl.DataFrame()
    
    def _find_cf_duplicates(self, df: pl.DataFrame) -> List[Dict]:
        """Find companies with same CF but different IDs."""
        duplicates = []
        
        if "cf" not in df.columns or "id" not in df.columns:
            return duplicates
        
        # Group by CF
        cf_groups = df.group_by("cf").agg([
            pl.col("id").alias("ids"),
            pl.count().alias("count")
        ]).filter(pl.col("count") > 1)
        
        for row in cf_groups.iter_rows(named=True):
            ids = row["ids"]
            
            # Create pairs
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    duplicates.append({
                        "company_id_1": ids[i],
                        "company_id_2": ids[j],
                        "confidence": 1.0,
                        "match_method": "cf_exact",
                    })
        
        return duplicates
    
    def _find_name_duplicates(self, df: pl.DataFrame) -> List[Dict]:
        """Find companies with similar names using blocking."""
        duplicates = []
        
        if "nome_normalizzato" not in df.columns or "id" not in df.columns:
            return duplicates
        
        # Create blocking key (first 3 chars of normalized name)
        df_with_block = df.with_columns([
            pl.col("nome_normalizzato").str.slice(0, 3).alias("block_key")
        ])
        
        # Group by blocking key
        blocks = df_with_block.group_by("block_key").agg([
            pl.col("id").alias("ids"),
            pl.col("nome_normalizzato").alias("names"),
            pl.col("cf").alias("cfs"),
            pl.count().alias("count")
        ]).filter(pl.col("count") > 1)
        
        logger.info(f"Processing {len(blocks)} blocks for fuzzy matching...")
        
        for block_row in tqdm(blocks.iter_rows(named=True), total=len(blocks), desc="Fuzzy matching"):
            ids = block_row["ids"]
            names = block_row["names"]
            cfs = block_row["cfs"]
            
            # Compare all pairs in block
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    # Skip if same CF (already handled)
                    if cfs[i] == cfs[j]:
                        continue
                    
                    # Compute name similarity
                    similarity = ratio(names[i], names[j])
                    
                    if similarity >= self.name_threshold:
                        duplicates.append({
                            "company_id_1": ids[i],
                            "company_id_2": ids[j],
                            "confidence": round(similarity, 2),
                            "match_method": "name_fuzzy",
                        })
                    elif self.llm and similarity >= self.llm_threshold:
                        # Ambiguous case: call LLM Judge
                        llm_response = self._verify_with_llm(names[i], names[j])
                        if llm_response.get("is_same"):
                            duplicates.append({
                                "company_id_1": ids[i],
                                "company_id_2": ids[j],
                                "confidence": llm_response.get("confidence", 0.7),
                                "match_method": "llm_judge",
                                "reason": llm_response.get("reason", "")
                            })
        
        return duplicates
    
    def merge_duplicates(
        self,
        companies_df: pl.DataFrame,
        duplicates_df: pl.DataFrame
    ) -> Tuple[pl.DataFrame, pl.DataFrame]:
        """
        Merge duplicate companies.
        
        Args:
            companies_df: Original companies DataFrame
            duplicates_df: Duplicates DataFrame
            
        Returns:
            Tuple of (merged_companies_df, same_as_relationships_df)
        """
        logger.info("Merging duplicate companies...")
        
        # Build equivalence classes using union-find
        id_to_canonical = {}
        
        for row in duplicates_df.iter_rows(named=True):
            id1 = row["company_id_1"]
            id2 = row["company_id_2"]
            
            # Find canonical IDs
            canonical1 = self._find_canonical(id_to_canonical, id1)
            canonical2 = self._find_canonical(id_to_canonical, id2)
            
            # Merge (use lexicographically smaller as canonical)
            if canonical1 != canonical2:
                if canonical1 < canonical2:
                    id_to_canonical[canonical2] = canonical1
                else:
                    id_to_canonical[canonical1] = canonical2
        
        # Create SAME_AS relationships
        same_as_rels = []
        
        for company_id, canonical_id in id_to_canonical.items():
            if company_id != canonical_id:
                same_as_rels.append({
                    "company_id": company_id,
                    "canonical_id": canonical_id,
                })
        
        same_as_df = pl.DataFrame(same_as_rels) if same_as_rels else pl.DataFrame()
        
        logger.success(f"Created {len(same_as_rels)} SAME_AS relationships")
        
        return companies_df, same_as_df
    
    def _find_canonical(self, id_to_canonical: Dict, company_id: str) -> str:
        """Find canonical ID using path compression."""
        if company_id not in id_to_canonical:
            id_to_canonical[company_id] = company_id
            return company_id
        
        # Path compression
        if id_to_canonical[company_id] != company_id:
            id_to_canonical[company_id] = self._find_canonical(
                id_to_canonical,
                id_to_canonical[company_id]
            )
        
        return id_to_canonical[company_id]

    def _verify_with_llm(self, name1: str, name2: str) -> Dict:
        """Verify if two company names refer to the same entity using LLM."""
        import json
        
        system_prompt = (
            "You are an expert in Italian corporate structures. "
            "Determine if two company names refer to the same legal entity, "
            "accounting for abbreviations (e.g., S.R.L. vs SRL), "
            "legal forms (S.p.A, S.r.l., S.n.c.), or minor typos. "
            "Return ONLY a JSON object: {\"is_same\": true/false, \"confidence\": 0.0-1.0, \"reason\": \"...\"}"
        )
        
        user_prompt = f"Name 1: {name1}\nName 2: {name2}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            response_text = self.llm.chat(messages, format="json")
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"LLM Judge failed: {e}")
            return {"is_same": False, "confidence": 0.0}
