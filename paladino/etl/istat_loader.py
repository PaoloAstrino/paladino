"""
ISTAT data loader - Bulk load geographic entities to Neo4j.
"""

import polars as pl
from neo4j import Driver
from loguru import logger
from tqdm import tqdm


class IstatNeo4jLoader:
    """Load ISTAT data into Neo4j graph database."""
    
    def __init__(self, driver: Driver, batch_size: int = 1000):
        """
        Initialize loader.
        
        Args:
            driver: Neo4j driver instance
            batch_size: Number of records per batch
        """
        self.driver = driver
        self.batch_size = batch_size
    
    def load_municipalities(self, df: pl.DataFrame) -> int:
        """
        Load municipality nodes.
        
        Args:
            df: DataFrame with municipality data
            
        Returns:
            Number of municipalities loaded
        """
        if df.is_empty():
            logger.warning("No municipalities to load")
            return 0
        
        logger.info(f"Loading {len(df)} municipalities...")
        
        total_loaded = 0
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading municipalities"):
                batch = df[i:i + self.batch_size]
                rows = batch.to_dicts()
                
                result = session.run("""
                    UNWIND $rows as row
                    MERGE (m:Municipality {cod_istat: row.cod_istat})
                    SET m.id = row.id,
                        m.nome = row.nome,
                        m.sigla_provincia = row.sigla_provincia,
                        m.cod_regione = row.cod_regione,
                        m.popolazione = row.popolazione,
                        m.source = row.source,
                        m.dataset_version = row.dataset_version,
                        m.retrieval_date = datetime(row.retrieval_date)
                    RETURN count(m) as loaded
                """, rows=rows)
                
                loaded = result.single()["loaded"]
                total_loaded += loaded
        
        logger.success(f"Loaded {total_loaded} municipalities")
        return total_loaded
    
    def load_provinces(self, df: pl.DataFrame) -> int:
        """
        Load province nodes.
        
        Args:
            df: DataFrame with province data
            
        Returns:
            Number of provinces loaded
        """
        if df.is_empty():
            logger.warning("No provinces to load")
            return 0
        
        logger.info(f"Loading {len(df)} provinces...")
        
        total_loaded = 0
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading provinces"):
                batch = df[i:i + self.batch_size]
                rows = batch.to_dicts()
                
                result = session.run("""
                    UNWIND $rows as row
                    MERGE (p:Province {cod_provincia: row.cod_provincia})
                    SET p.id = row.id,
                        p.nome = row.nome,
                        p.sigla = row.sigla,
                        p.cod_regione = row.cod_regione,
                        p.source = row.source
                    RETURN count(p) as loaded
                """, rows=rows)
                
                loaded = result.single()["loaded"]
                total_loaded += loaded
        
        logger.success(f"Loaded {total_loaded} provinces")
        return total_loaded
    
    def load_regions(self, df: pl.DataFrame) -> int:
        """
        Load region nodes.
        
        Args:
            df: DataFrame with region data
            
        Returns:
            Number of regions loaded
        """
        if df.is_empty():
            logger.warning("No regions to load")
            return 0
        
        logger.info(f"Loading {len(df)} regions...")
        
        total_loaded = 0
        
        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading regions"):
                batch = df[i:i + self.batch_size]
                rows = batch.to_dicts()
                
                result = session.run("""
                    UNWIND $rows as row
                    MERGE (r:Region {cod_regione: row.cod_regione})
                    SET r.id = row.id,
                        r.nome = row.nome,
                        r.source = row.source
                    RETURN count(r) as loaded
                """, rows=rows)
                
                loaded = result.single()["loaded"]
                total_loaded += loaded
        
        logger.success(f"Loaded {total_loaded} regions")
        return total_loaded
    
    def create_geographic_relationships(self) -> dict:
        """
        Create geographic relationships (Municipality → Province → Region).
        
        Returns:
            Statistics dictionary
        """
        logger.info("Creating geographic relationships...")
        
        stats = {}
        
        with self.driver.session() as session:
            # Municipality → Province
            result = session.run("""
                MATCH (m:Municipality)
                MATCH (p:Province {sigla: m.sigla_provincia})
                MERGE (m)-[r:IN_PROVINCE]->(p)
                RETURN count(r) as created
            """)
            stats["municipality_province"] = result.single()["created"]
            
            # Municipality → Region
            result = session.run("""
                MATCH (m:Municipality)
                MATCH (r:Region {cod_regione: m.cod_regione})
                MERGE (m)-[rel:IN_REGION]->(r)
                RETURN count(rel) as created
            """)
            stats["municipality_region"] = result.single()["created"]
            
            # Province → Region
            result = session.run("""
                MATCH (p:Province)
                MATCH (r:Region {cod_regione: p.cod_regione})
                MERGE (p)-[rel:IN_REGION]->(r)
                RETURN count(rel) as created
            """)
            stats["province_region"] = result.single()["created"]
        
        logger.success(f"Created geographic relationships: {stats}")
        return stats
    
    def link_companies_to_municipalities(self) -> int:
        """
        Create LOCATED_IN relationships from companies to municipalities.
        
        Returns:
            Number of relationships created
        """
        logger.info("Linking companies to municipalities...")
        
        with self.driver.session() as session:
            # Match by province code (companies have 'provincia' field)
            result = session.run("""
                MATCH (c:Company)
                WHERE c.provincia IS NOT NULL
                MATCH (m:Municipality {sigla_provincia: c.provincia})
                MERGE (c)-[r:LOCATED_IN]->(m)
                RETURN count(r) as created
            """)
            
            created = result.single()["created"]
        
        logger.success(f"Created {created} LOCATED_IN relationships")
        return created
    
    def load_all(self, data: dict) -> dict:
        """
        Load all ISTAT data (municipalities, provinces, regions, relationships).
        
        Args:
            data: Dictionary with DataFrames
            
        Returns:
            Statistics dictionary
        """
        stats = {
            "municipalities": self.load_municipalities(data.get("municipalities", pl.DataFrame())),
            "provinces": self.load_provinces(data.get("provinces", pl.DataFrame())),
            "regions": self.load_regions(data.get("regions", pl.DataFrame())),
        }
        
        # Create relationships
        geo_rels = self.create_geographic_relationships()
        stats.update(geo_rels)
        
        # Link companies
        stats["company_locations"] = self.link_companies_to_municipalities()
        
        logger.success(f"Load complete: {stats}")
        return stats
