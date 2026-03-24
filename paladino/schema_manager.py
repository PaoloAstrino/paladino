"""
Schema initialization and validation utilities.
"""

from pathlib import Path
from typing import List
from neo4j import Driver
from loguru import logger


class SchemaManager:
    """Manage Neo4j schema initialization and validation."""
    
    def __init__(self, driver: Driver, schema_dir: Path):
        self.driver = driver
        self.schema_dir = schema_dir
    
    def initialize_schema(self, vector_dimensions: int = 768):
        """Initialize the complete schema (constraints + indexes)."""
        logger.info("Initializing Neo4j schema...")
        
        # Apply constraints first
        self._apply_cypher_file("constraints.cypher")
        
        # Then apply indexes
        self._apply_cypher_file("indexes.cypher")
        
        # Create vector indices for semantic search
        self.create_vector_indices(dimensions=vector_dimensions)
        
        # New Quick Win: Full-Text Search
        self.create_fulltext_index()
        
        # Track version
        self._set_schema_version(1)
        
        logger.success("Schema initialization complete (Version 1)")

    def _set_schema_version(self, version: int):
        """Record the schema version in the database."""
        with self.driver.session() as session:
            session.run("""
                MERGE (v:SchemaVersion {id: 'CURRENT'})
                SET v.version = $version,
                    v.applied_at = datetime()
            """, version=version)

    def get_current_version(self) -> int:
        """Get the current schema version from the database."""
        with self.driver.session() as session:
            result = session.run("MATCH (v:SchemaVersion {id: 'CURRENT'}) RETURN v.version as version")
            record = result.single()
            return record["version"] if record else 0
    
    def _apply_cypher_file(self, filename: str):
        """Execute a Cypher file."""
        file_path = self.schema_dir / filename
        
        if not file_path.exists():
            logger.warning(f"Schema file not found: {file_path}")
            return
        
        logger.info(f"Applying {filename}...")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Split by semicolon and execute each statement
        statements = self._parse_cypher_statements(content)
        
        with self.driver.session() as session:
            for i, statement in enumerate(statements, 1):
                if statement.strip():
                    try:
                        session.run(statement)
                        logger.debug(f"  ✓ Statement {i} executed")
                    except Exception as e:
                        logger.warning(f"  ✗ Statement {i} failed: {e}")
    
    def _parse_cypher_statements(self, content: str) -> List[str]:
        """Parse Cypher file into individual statements."""
        # Remove comments
        lines = []
        for line in content.split('\n'):
            # Remove line comments
            if '//' in line:
                line = line[:line.index('//')]
            lines.append(line)
        
        content = '\n'.join(lines)
        
        # Split by semicolon
        statements = [s.strip() for s in content.split(';') if s.strip()]
        return statements
    
    def list_constraints(self) -> List[dict]:
        """List all current constraints."""
        with self.driver.session() as session:
            return [dict(record) for record in session.run("SHOW CONSTRAINTS")]

    def list_indexes(self) -> List[dict]:
        """List all current indexes."""
        with self.driver.session() as session:
            return [dict(record) for record in session.run("SHOW INDEXES")]

    def validate_schema(self) -> bool:
        """Validate that schema is properly initialized."""
        logger.info("Validating schema...")
        
        with self.driver.session() as session:
            # Check constraints
            result = session.run("SHOW CONSTRAINTS")
            constraints = list(result)
            logger.info(f"Found {len(constraints)} constraints")
            
            # Check indexes
            result = session.run("SHOW INDEXES")
            indexes = list(result)
            logger.info(f"Found {len(indexes)} indexes")
            
            if len(constraints) == 0:
                logger.error("No constraints found - schema not initialized")
                return False
            
            logger.success("Schema validation passed")
            return True
    
    def create_vector_indices(self, dimensions: int = 768):
        """Create vector indices for semantic search."""
        logger.info(f"Creating vector indices (dimensions: {dimensions})...")
        
        queries = [
            # Project vector index
            f"""
            CREATE VECTOR INDEX project_description_index IF NOT EXISTS
            FOR (n:Project) ON (n.embedding)
            OPTIONS {{ indexConfig: {{
              `vector.dimensions`: {dimensions},
              `vector.similarity_function`: 'cosine'
            }} }}
            """,
            # Tender vector index
            f"""
            CREATE VECTOR INDEX tender_oggetto_index IF NOT EXISTS
            FOR (n:Tender) ON (n.embedding)
            OPTIONS {{ indexConfig: {{
              `vector.dimensions`: {dimensions},
              `vector.similarity_function`: 'cosine'
            }} }}
            """
        ]
        
        with self.driver.session() as session:
            for query in queries:
                session.run(query)
                
        logger.success("Vector indices created")

    def create_fulltext_index(self):
        """
        Create Lucene-based full-text index for thematic keyword search.
        Resource-efficient way to handle 'concept' searching.
        """
        logger.info("Creating full-text search index for topics...")
        query = """
        CREATE FULLTEXT INDEX search_topics IF NOT EXISTS
        FOR (n:Tender|Project)
        ON EACH [n.oggetto, n.descrizione_estesa, n.titolo, n.descrizione]
        """
        with self.driver.session() as session:
            session.run(query)
        logger.success("Full-text index 'search_topics' created.")

    def get_schema_metadata(self) -> str:
        """Get a text description of the schema for LLM context."""
        logger.info("Generating schema metadata for LLM...")
        
        # In a real system, you could introspect the DB
        # For this prototype, we return the expected schema
        metadata = """
        Node Labels and Properties:
        - Company {id, cf, piva, nome_normalizzato, nome_originale, regione, provincia, comune, risk_score, anomaly_flags, total_tenders}
        - Tender {id, cig, ocid, oggetto, importo, procedura, data_aggiudicazione, data_apertura, red_flags, single_bidder}
        - Project {id, cup, titolo, descrizione, importo_previsto, importo_finanziato, fondi_comunitari, data_inizio, data_fine, stato, regione}
        - Person {id, cf, nome, cognome, gender, ruoli_istituzionali, risk_score}
        - Asset {id, id_immobile, nome, tipo, valore_stimato, indirizzo, comune, coordinate}
        - Sector {id, cod_ateco, descrizione}
        - Municipality {id, cod_istat, nome, sigla_provincia, cod_regione, popolazione}
        - Region {id, cod_regione, nome}
        - FundingSource {id, nome, tipo} (tipo can be 'PNRR', 'FESR', etc.)
        - Buyer {id, cf, nome, tipo}

        Relationships:
        - (Company)-[:WINS {data, importo, confidence}]->(Tender)
        - (Tender)-[:PART_OF_PROJECT {confidence, matching_method}]->(Project)
        - (Person)-[:REPRESENTS {ruolo, data_inizio}]->(Company)
        - (Person)-[:SHAREHOLDER_OF {quota, data_rilevazione}]->(Company)
        - (Company)-[:SHAREHOLDER_OF {quota}]->(Company)
        - (Tender)-[:INTERVENTION_ON {tipo_lavori}]->(Asset)
        - (Project)-[:INTERVENTION_ON]->(Asset)
        - (Company)-[:OPERATES_IN {primario}]->(Sector)
        - (Company)-[:LOCATED_IN]->(Municipality)
        - (Municipality)-[:IN_REGION]->(Region)
        - (Project)-[:FUNDED_BY]->(FundingSource)
        - (Buyer)-[:ISSUES]->(Tender)
        """
        return metadata.strip()

    def drop_all_constraints_and_indexes(self):
        """Drop all constraints and indexes (for testing/reset)."""
        logger.warning("Dropping all constraints and indexes...")

        with self.driver.session() as session:
            # Drop constraints
            result = session.run("SHOW CONSTRAINTS")
            for record in result:
                constraint_name = record.get('name')
                if constraint_name:
                    session.run("DROP CONSTRAINT $name IF EXISTS", name=constraint_name)

            # Drop indexes
            result = session.run("SHOW INDEXES")
            for record in result:
                index_name = record.get('name')
                if index_name and not index_name.startswith('constraint_'):
                    session.run("DROP INDEX $name IF EXISTS", name=index_name)

        logger.success("All constraints and indexes dropped")
