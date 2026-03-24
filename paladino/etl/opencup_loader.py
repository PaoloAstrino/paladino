"""
OpenCUP data loader - Bulk load projects to Neo4j.
"""

import polars as pl
from typing import Optional
from neo4j import Driver
from loguru import logger
from tqdm import tqdm


class OpencupNeo4jLoader:
    """Load OpenCUP data into Neo4j graph database."""
    
    def __init__(self, driver: Driver, batch_size: int = 1000):
        """
        Initialize loader.
        
        Args:
            driver: Neo4j driver instance
            batch_size: Number of records per batch
        """
        self.driver = driver
        self.batch_size = batch_size
    
    def load_projects(self, df: pl.DataFrame) -> int:
        """
        Load project nodes.
        
        Args:
            df: DataFrame with project data
            
        Returns:
            Number of projects loaded
        """
        if df.is_empty():
            logger.warning("No projects to load")
            return 0
        
        logger.info(f"Loading {len(df)} projects...")
        
        total_loaded = 0
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading projects"):
                batch = df[i:i + self.batch_size]
                rows = batch.to_dicts()
                
                try:
                    result = session.run("""
                        UNWIND $rows as row
                        
                        // 1. Find existing project
                        OPTIONAL MATCH (p:Project {cup: row.cup})
                        
                        // 2. Archive current state if exists
                        FOREACH (ignore IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END |
                            CREATE (v:Version)
                            SET v = properties(p),
                                v.id = row.id + "_" + toString(timestamp()),
                                v.entityId = p.id,
                                v.archived_at = datetime()
                            CREATE (p)-[:HAS_VERSION]->(v)
                        )
                        
                        // 3. Update/Create main node
                        MERGE (p_new:Project {cup: row.cup})
                        SET p_new.id = row.id,
                            p_new.titolo = row.titolo,
                            p_new.descrizione = row.descrizione,
                            p_new.importo_previsto = row.importo_previsto,
                            p_new.importo_finanziato = row.importo_finanziato,
                            p_new.data_inizio = CASE WHEN row.data_inizio IS NOT NULL THEN row.data_inizio ELSE p_new.data_inizio END,
                            p_new.data_fine = CASE WHEN row.data_fine IS NOT NULL THEN row.data_fine ELSE p_new.data_fine END,
                            p_new.stato = row.stato,
                            p_new.regione = row.regione,
                            p_new.provincia = row.provincia,
                            p_new.settore = row.settore,
                            p_new.fondi_comunitari = row.fondi_comunitari,
                            p_new.source = row.source,
                            p_new.dataset_version = row.dataset_version,
                            p_new.retrieval_date = datetime(row.retrieval_date),
                            p_new.confidence = row.confidence,
                            p_new.last_updated = datetime()
                        RETURN count(p_new) as loaded
                    """, rows=rows)
                    
                    loaded = result.single()["loaded"]
                    total_loaded += loaded
                except Exception as e:
                    logger.error(f"Failed to load projects batch: {e}")
                    if rows:
                        logger.error(f"Sample row: {rows[0]}")
                    raise
        
        logger.success(f"Loaded {total_loaded} projects")
        return total_loaded
    
    def load_funding_sources(self, df: pl.DataFrame) -> int:
        """
        Load funding source nodes.
        
        Args:
            df: DataFrame with funding source data
            
        Returns:
            Number of funding sources loaded
        """
        if df.is_empty():
            logger.warning("No funding sources to load")
            return 0
        
        logger.info(f"Loading {len(df)} funding sources...")
        
        total_loaded = 0
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading funding sources"):
                batch = df[i:i + self.batch_size]
                rows = batch.to_dicts()
                
                try:
                    result = session.run("""
                        UNWIND $rows as row
                        MERGE (f:FundingSource {nome: row.nome})
                        SET f.id = row.id,
                            f.tipo = row.tipo,
                            f.source = row.source
                        RETURN count(f) as loaded
                    """, rows=rows)
                    
                    loaded = result.single()["loaded"]
                    total_loaded += loaded
                except Exception as e:
                    logger.error(f"Failed to load funding sources batch: {e}")
                    raise
        
        logger.success(f"Loaded {total_loaded} funding sources")
        return total_loaded
    
    def load_part_of_project(self, df: pl.DataFrame) -> int:
        """
        Load PART_OF_PROJECT relationships (CUP-CIG matches).
        
        Args:
            df: DataFrame with match data
            
        Returns:
            Number of relationships loaded
        """
        if df.is_empty():
            logger.warning("No PART_OF_PROJECT relationships to load")
            return 0
        
        logger.info(f"Loading {len(df)} PART_OF_PROJECT relationships...")
        
        total_loaded = 0
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading PART_OF_PROJECT"):
                batch = df[i:i + self.batch_size]
                rows = batch.to_dicts()
                
                try:
                    result = session.run("""
                        UNWIND $rows as row
                        MATCH (t:Tender {cig: row.tender_cig})
                        MATCH (p:Project {cup: row.project_cup})
                        MERGE (t)-[r:PART_OF_PROJECT]->(p)
                        SET r.confidence = row.confidence,
                            r.matching_method = row.matching_method,
                            r.match_date = datetime(row.match_date)
                        RETURN count(r) as loaded
                    """, rows=rows)
                    
                    loaded = result.single()["loaded"]
                    total_loaded += loaded
                except Exception as e:
                    logger.error(f"Failed to load PART_OF_PROJECT batch: {e}")
                    raise
        
        logger.success(f"Loaded {total_loaded} PART_OF_PROJECT relationships")
        return total_loaded
    
    def load_funded_by(self, projects_df: pl.DataFrame) -> int:
        """
        Load FUNDED_BY relationships from projects to funding sources.
        
        Args:
            projects_df: DataFrame with project data (must have fondi_comunitari)
            
        Returns:
            Number of relationships loaded
        """
        if projects_df.is_empty():
            logger.warning("No projects for FUNDED_BY relationships")
            return 0
        
        if "fondi_comunitari" not in projects_df.columns:
            return 0
            
        logger.info("Creating FUNDED_BY relationships...")
        
        # Expand fondi_comunitari lists into individual relationships
        relationships = []
        
        for row in projects_df.iter_rows(named=True):
            cup = row.get("cup", "")
            fondi = row.get("fondi_comunitari", [])
            
            if not cup or not fondi:
                continue
            
            # Ensure fondi is a list
            if isinstance(fondi, str):
                import json
                try:
                    fondi = json.loads(fondi.replace("'", '"'))
                except:
                    fondi = [f.strip() for f in fondi.split(",") if f.strip()]
            
            for fondo in fondi:
                relationships.append({
                    "project_cup": cup,
                    "funding_nome": fondo,
                })
        
        if not relationships:
            return 0
        
        rel_df = pl.DataFrame(relationships)
        total_loaded = 0
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(rel_df), self.batch_size), desc="Loading FUNDED_BY"):
                batch = rel_df[i:i + self.batch_size]
                rows = batch.to_dicts()
                
                try:
                    result = session.run("""
                        UNWIND $rows as row
                        MATCH (p:Project {cup: row.project_cup})
                        MATCH (f:FundingSource {nome: row.funding_nome})
                        MERGE (p)-[r:FUNDED_BY]->(f)
                        RETURN count(r) as loaded
                    """, rows=rows)
                    
                    loaded = result.single()["loaded"]
                    total_loaded += loaded
                except Exception as e:
                    logger.error(f"Failed to load FUNDED_BY batch: {e}")
                    raise
        
        logger.success(f"Loaded {total_loaded} FUNDED_BY relationships")
        return total_loaded
    
    def load_localization(self, df: pl.DataFrame) -> int:
        """Load IN_MUNICIPALITY relationships."""
        if df.is_empty():
            return 0
            
        logger.info(f"Loading {len(df)} localization relationships...")
        total_loaded = 0
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading IN_MUNICIPALITY"):
                batch = df[i:i + self.batch_size]
                rows = batch.to_dicts()
                
                try:
                    # Note: we match Municipality by cod_istat
                    # OpenCUP codice_comune is often the 6-digit ISTAT code
                    result = session.run("""
                        UNWIND $rows as row
                        MATCH (p:Project {cup: row.cup})
                        MATCH (m:Municipality {cod_istat: row.codice_comune})
                        MERGE (p)-[r:IN_MUNICIPALITY]->(m)
                        RETURN count(r) as loaded
                    """, rows=rows)
                    
                    loaded = result.single()["loaded"]
                    total_loaded += loaded
                except Exception as e:
                    logger.error(f"Failed to load localization batch: {e}")
                    raise
                    
        return total_loaded

    def load_subjects(self, df: pl.DataFrame) -> int:
        """Load HAS_ACTOR relationships."""
        # For OpenCUP, projects are often linked to actors in the 'Soggetti' file.
        # But wait, Soggetti.csv preview didn't have CUP.
        # If it's just a subjects-only file, we load them as Company nodes or specific 'Actor' nodes?
        # Let's treat them as Company nodes for now to align with ANAC.
        if df.is_empty():
            return 0
            
        logger.info(f"Loading {len(df)} actors...")
        total_loaded = 0
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading Actors"):
                batch = df[i:i + self.batch_size]
                rows = batch.to_dicts()
                
                try:
                    result = session.run("""
                        UNWIND $rows as row
                        MERGE (c:Company {cf: row.cf})
                        SET c.nome_originale = row.nome,
                            c.categoria = row.categoria,
                            c.sottocategoria = row.sottocategoria,
                            c.source = CASE WHEN row.source IN c.source THEN c.source ELSE c.source + row.source END
                        RETURN count(c) as loaded
                    """, rows=rows)
                    
                    loaded = result.single()["loaded"]
                    total_loaded += loaded
                except Exception as e:
                    logger.error(f"Failed to load actors batch: {e}")
                    raise
                    
        return total_loaded
    
    def load_all(self, data: dict, matches_df: pl.DataFrame = None) -> dict:
        """
        Load all OpenCUP data (projects, funding sources, relationships).
        
        Args:
            data: Dictionary with DataFrames (projects, funding_sources, localization, subjects)
            matches_df: DataFrame with CUP-CIG matches
            
        Returns:
            Statistics dictionary
        """
        if matches_df is None:
            matches_df = pl.DataFrame()
            
        stats = {
            "projects": self.load_projects(data.get("projects", pl.DataFrame())),
            "funding_sources": self.load_funding_sources(data.get("funding_sources", pl.DataFrame())),
            "part_of_project": self.load_part_of_project(matches_df),
            "funded_by": self.load_funded_by(data.get("projects", pl.DataFrame())),
            "localization": self.load_localization(data.get("localization", pl.DataFrame())),
            "subjects": self.load_subjects(data.get("subjects", pl.DataFrame())),
        }
        
        logger.success(f"Load complete: {stats}")
        return stats
