"""
GraphRAG agent - Multi-hop reasoning over knowledge graph.
"""

import json
from typing import List, Dict, Optional
from neo4j import Driver
from neo4j.exceptions import ServiceUnavailable, DatabaseUnavailable, DriverError
from loguru import logger
from paladino.llm_manager import LLMManager


class CypherQueryTemplates:
    """Pre-validated Cypher query templates."""
    
    TEMPLATES = {
        "companies_by_region": """
            MATCH (c:Company)-[:LOCATED_IN]->(m:Municipality)-[:IN_REGION]->(r:Region {nome: $region})
            RETURN c.nome_normalizzato as company, c.total_tenders as tenders
            ORDER BY c.total_tenders DESC
            LIMIT $limit
        """,
        
        "pnrr_projects": """
            MATCH (p:Project)-[:FUNDED_BY]->(f:FundingSource {tipo: "PNRR"})
            RETURN p.cup, p.titolo, p.importo_finanziato, p.regione
            ORDER BY p.importo_finanziato DESC
            LIMIT $limit
        """,
        
        "tender_to_project": """
            MATCH (c:Company {cf: $cf})-[:WINS]->(t:Tender)-[:PART_OF_PROJECT]->(p:Project)
            RETURN t.cig, t.oggetto, p.cup, p.titolo, t.importo
            ORDER BY t.importo DESC
            LIMIT $limit
        """,
        
        "high_risk_companies": """
            MATCH (c:Company)
            WHERE c.risk_score > $min_risk
            RETURN c.nome_normalizzato, c.risk_score, c.anomaly_flags, c.total_tenders
            ORDER BY c.risk_score DESC
            LIMIT $limit
        """,
        
        "regional_spending": """
            MATCH (c:Company)-[:LOCATED_IN]->(m:Municipality)-[:IN_REGION]->(r:Region)
            MATCH (c)-[:WINS]->(t:Tender)
            RETURN r.nome as regione, 
                   count(t) as total_tenders,
                   sum(t.importo) as total_importo
            ORDER BY total_importo DESC
        """,
        
        "top_vendors": """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            RETURN c.nome_originale as company,
                   c.cf as codice_fiscale,
                   count(t) as tender_count,
                   sum(t.importo) as total_value
            ORDER BY tender_count DESC
            LIMIT $limit
        """,
        
        "top_centrality_companies": """
            MATCH (c:Company)
            WHERE c.centrality_score IS NOT NULL
            RETURN c.nome_originale as company,
                   c.centrality_score as influence_score,
                   c.community_id as community
            ORDER BY c.centrality_score DESC
            LIMIT $limit
        """,
        
        "project_funding_analysis": """
            MATCH (p:Project)-[:FUNDED_BY]->(f:FundingSource)
            RETURN f.tipo as funding_source,
                   count(p) as project_count,
                   sum(p.importo_finanziato) as total_funding
            ORDER BY total_funding DESC
            LIMIT $limit
        """,

        # ── Supply-chain & corporate graph (2024 additions) ─────────────────

        "ownership_chain": """
            // Trace all shareholders / UBOs above a company up to max_depth hops.
            // Required param: cf (company fiscal code)
            // Optional param: max_depth (default 10)
            MATCH path = (start:Company {cf: $cf})<-[:SHAREHOLDER_OF|SHARES_UBO*1..10]-(owner)
            WHERE owner:Company OR owner:Person
            RETURN
                labels(owner)[0]                         AS owner_type,
                coalesce(owner.nome_normalizzato,
                         owner.cognome + ' ' + owner.nome,
                         owner.cf)                       AS owner_name,
                owner.cf                                 AS owner_cf,
                length(path)                             AS hops,
                [n IN nodes(path) | coalesce(
                    n.nome_normalizzato, n.nome, n.cf)]  AS chain_names
            ORDER BY hops, owner_type
            LIMIT $limit
        """,

        "supply_chain": """
            // Show the downstream sub-contractor tree from a prime contractor.
            // Required param: cf (company fiscal code)
            // Optional param: max_depth (default 4), limit
            MATCH path = (start:Company {cf: $cf})-[:SUBCONTRACTS_TO|SUPPLIES_TO*1..4]->(downstream:Company)
            RETURN
                downstream.nome_normalizzato             AS sub_name,
                downstream.cf                            AS sub_cf,
                length(path)                             AS depth,
                [r IN relationships(path) | r.cig][0]   AS first_cig,
                [n IN nodes(path) | coalesce(
                    n.nome_normalizzato, n.cf)]          AS chain_names
            ORDER BY depth, sub_name
            LIMIT $limit
        """,

        "board_overlaps": """
            // Companies sharing board members, ranked by shared count.
            // Optional param: min_shared (default 1), limit
            MATCH (p:Person)-[:REPRESENTS]->(c1:Company)
            MATCH (p)-[:REPRESENTS]->(c2:Company)
            WHERE id(c1) < id(c2)
            WITH c1, c2,
                 count(DISTINCT p)                          AS shared_count,
                 collect(DISTINCT coalesce(
                     p.cognome + ' ' + p.nome, p.cf))      AS shared_persons
            WHERE shared_count >= $min_shared
            RETURN c1.nome_normalizzato  AS company_a,
                   c2.nome_normalizzato  AS company_b,
                   shared_count,
                   shared_persons
            ORDER BY shared_count DESC
            LIMIT $limit
        """,

        "carousel_risk": """
            // Companies found inside supply-chain strongly-connected components
            // (carousel fraud candidates).  Requires GDS SCC to have been run.
            MATCH (c:Company)
            WHERE c.supply_scc_id IS NOT NULL AND c.supply_scc_size > 1
            WITH c.supply_scc_id AS scc_id,
                 collect(c)      AS members
            RETURN scc_id,
                   size(members)                                     AS cycle_size,
                   [m IN members | m.nome_normalizzato]              AS company_names,
                   [m IN members | m.cf]                             AS company_cfs,
                   [m IN members | coalesce(m.risk_score, 0.0)]     AS risk_scores
            ORDER BY cycle_size DESC
            LIMIT $limit
        """,

        # ── Temporal / time-series (2024 additions) ──────────────────────────

        "tender_volume_trend": """
            // Quarterly tender count + value for the whole graph or one winner.
            // Optional param: cf (company fiscal code), quarters (default 8)
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE ($cf IS NULL OR c.cf = $cf)
              AND t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
            WITH c.cf                                   AS cf,
                 c.nome_normalizzato                    AS company,
                 t.data_aggiudicazione.year             AS year,
                 ((t.data_aggiudicazione.month-1)/3+1)  AS quarter,
                 t.importo                              AS importo
            WITH cf, company, year, quarter,
                 count(*)      AS tender_count,
                 sum(importo)  AS total_value,
                 avg(importo)  AS avg_value
            RETURN cf, company, year, quarter, tender_count, total_value, avg_value
            ORDER BY cf, year ASC, quarter ASC
            LIMIT $limit
        """,

        "single_bidder_trend": """
            // Quarterly single-bidder ratio per company (rising ratio = red flag).
            // Optional param: cf (company fiscal code), months (derived from quarters)
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE ($cf IS NULL OR c.cf = $cf)
              AND t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
            WITH c.cf                                    AS cf,
                 c.nome_normalizzato                     AS company,
                 t.data_aggiudicazione.year              AS year,
                 ((t.data_aggiudicazione.month-1)/3+1)   AS quarter,
                 t.single_bidder                         AS is_single
            WITH cf, company, year, quarter,
                 count(*)                                AS total_wins,
                 sum(CASE WHEN is_single = true THEN 1 ELSE 0 END) AS single_wins
            WITH cf, company, year, quarter, total_wins, single_wins,
                 toFloat(single_wins) / total_wins       AS ratio
            WHERE total_wins >= 2
            RETURN cf, company, year, quarter, total_wins, single_wins,
                   round(ratio * 1000) / 1000.0 AS single_bidder_ratio
            ORDER BY cf, year ASC, quarter ASC
            LIMIT $limit
        """,

        "sector_spending_trend": """
            // Quarterly spending aggregation for one ATECO sector prefix.
            // Required param: ateco_prefix  e.g. "C28"
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE c.ateco STARTS WITH $ateco_prefix
              AND t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
              AND t.importo IS NOT NULL
            WITH t.data_aggiudicazione.year             AS year,
                 ((t.data_aggiudicazione.month-1)/3+1)  AS quarter,
                 c.id                                   AS company_id,
                 t.importo                              AS importo
            WITH year, quarter, company_id,
                 sum(importo) AS company_quarterly_spend
            WITH year, quarter,
                 count(DISTINCT company_id)             AS company_count,
                 sum(company_quarterly_spend)           AS total_value,
                 stDev(company_quarterly_spend)         AS stddev_value
            RETURN $ateco_prefix AS ateco_prefix,
                   year, quarter, company_count, total_value,
                   round(stddev_value * 100) / 100.0 AS stddev_value
            ORDER BY year ASC, quarter ASC
            LIMIT $limit
        """,

        "sudden_spikes": """
            // Companies with latest quarter > threshold × their rolling mean.
            // This query returns the raw quarterly data; spike math happens in Python.
            // Params: months (window), min_bucket (minimum tenders per quarter)
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
            WITH c.cf                                   AS cf,
                 c.nome_normalizzato                    AS company,
                 t.data_aggiudicazione.year             AS year,
                 ((t.data_aggiudicazione.month-1)/3+1)  AS quarter,
                 count(*)                               AS tender_count,
                 sum(t.importo)                         AS total_value
            WHERE tender_count >= $min_bucket
            RETURN cf, company, year, quarter, tender_count, total_value
            ORDER BY cf, year ASC, quarter ASC
            LIMIT $limit
        """,
    }
    
    @classmethod
    def get_template(cls, template_name: str) -> Optional[str]:
        """Get a query template by name."""
        return cls.TEMPLATES.get(template_name)
    
    @classmethod
    def list_templates(cls) -> List[str]:
        """List all available templates."""
        return list(cls.TEMPLATES.keys())


class GraphRAGAgent:
    """GraphRAG agent for multi-hop reasoning."""
    
    def __init__(self, driver: Driver, schema_metadata: Optional[str] = None):
        """
        Initialize agent.
        
        Args:
            driver: Neo4j driver instance
            schema_metadata: Text description of the graph schema
        """
        self.driver = driver
        self.templates = CypherQueryTemplates()
        self.llm = LLMManager()
        self.schema_metadata = schema_metadata
    
    def query(
        self,
        template_name: str,
        params: Optional[Dict] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Execute a templated query.
        
        Args:
            template_name: Name of the template
            params: Query parameters
            limit: Result limit
            
        Returns:
            List of result records
        """
        template = self.templates.get_template(template_name)
        
        if not template:
            logger.error(f"Template not found: {template_name}")
            return []
        
        # Merge default params
        query_params = params or {}
        if "limit" not in query_params:
            query_params["limit"] = limit
        
        logger.info(f"Executing template: {template_name}")
        
        try:
            with self.driver.session() as session:
                result = session.run(template, **query_params)
                records = [dict(r) for r in result]
            
            logger.success(f"Retrieved {len(records)} results")
            return records
        except (ServiceUnavailable, DatabaseUnavailable, DriverError) as e:
            logger.error(f"Neo4j connection failed: {e}")
            raise RuntimeError(
                "\n🔴 Neo4j Database is not running!\n\n"
                "Please start Neo4j:"
                "  • Docker: docker-compose -f infra/docker-compose.yml up -d\n"
                "  • Desktop: Open Neo4j Desktop and start the DBMS\n"
                "\nThen try again."
            ) from e

    def execute_custom_cypher(self, cypher: str, params: Optional[Dict] = None) -> List[Dict]:
        """Execute a raw Cypher query safely."""
        logger.info(f"Executing custom Cypher: {cypher}")
        try:
            with self.driver.session() as session:
                result = session.run(cypher, **(params or {}))
                records = [dict(r) for r in result]
            return records
        except (ServiceUnavailable, DatabaseUnavailable, DriverError) as e:
            logger.error(f"Neo4j connection failed: {e}")
            raise RuntimeError(
                "\n🔴 Neo4j Database is not running!\n\n"
                "Please start Neo4j:"
                "  • Docker: docker-compose -f infra/docker-compose.yml up -d\n"
                "  • Desktop: Open Neo4j Desktop and start the DBMS\n"
                "\nThen try again."
            ) from e

    def thematic_search(self, keyword: str, limit: int = 15) -> List[dict]:
        """
        High-performance keyword search using Neo4j Full-Text Index.
        More resource-efficient than Vectors for simple topic matching.
        """
        logger.info(f"Performing thematic search for: {keyword}")
        query = """
        CALL db.index.fulltext.queryNodes('search_topics', $keyword)
        YIELD node, score
        RETURN labels(node)[0] as type, properties(node) as data, score
        LIMIT $limit
        """
        # Note: $keyword can use Lucene syntax, e.g. "Scuola~" for fuzzy
        try:
            with self.driver.session() as session:
                result = session.run(query, keyword=f"{keyword}~", limit=limit)
                return [dict(record) for record in result]
        except (ServiceUnavailable, DatabaseUnavailable, DriverError) as e:
            logger.error(f"Neo4j connection failed: {e}")
            raise RuntimeError(
                "\n🔴 Neo4j Database is not running!\n\n"
                "Please start Neo4j:"
                "  • Docker: docker-compose -f infra/docker-compose.yml up -d\n"
                "  • Desktop: Open Neo4j Desktop and start the DBMS\n"
                "\nThen try again."
            ) from e
    
    def generate_insight(self, question: str, results: List[Dict]) -> str:
        """Generate a natural language insight based on the data results."""
        if not results:
            return "No data found to analyze."
            
        system_prompt = (
            "You are a strategic analyst. Based on the provided data from a Knowledge Graph "
            "and the user's question, provide a 2-sentence executive summary. "
            "Highlight any potential risks or interesting patterns (e.g., concentration of funds)."
        )
        
        # Prepare data snippet for LLM (first 5 results to save tokens)
        data_snippet = json.dumps(results[:5], indent=2)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {question}\nData: {data_snippet}"}
        ]
        
        return self.llm.chat(messages)

    def natural_language_query(self, question: str) -> Dict:
        """
        Process natural language question.

        1. Classify intent to a template
        2. If no template, generate dynamic Cypher
        3. Execute query
        4. Generate natural language insight
        """
        logger.info(f"Processing NL query: {question}")

        template_list = self.templates.list_templates()
        intent = self.llm.classify_intent(question, template_list)

        template_name = intent.get("template_name")
        params = intent.get("params", {})

        final_result = {}

        # 1. Try template
        if template_name and template_name in template_list:
            try:
                results = self.query(template_name, params)
                final_result = {
                    "method": "template",
                    "template": template_name,
                    "params": params,
                    "results": results,
                    "count": len(results)
                }
            except RuntimeError as e:
                # Handle Neo4j connection errors with helpful message
                if "Neo4j Database is not running" in str(e):
                    logger.error(f"Database unavailable: {e}")
                    return {
                        "error": "🔴 Neo4j Database is not running!",
                        "help": "Start Neo4j and try again:",
                        "instructions": [
                            "Docker: docker-compose -f infra/docker-compose.yml up -d",
                            "Desktop: Open Neo4j Desktop and start the DBMS"
                        ]
                    }
                raise
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Template execution failed: {error_msg}")

                # Check for missing parameter error (multiple formats)
                missing_params = None

                # Format 1: "Expected parameter(s): cf, months"
                import re
                match = re.search(r'Expected parameter\(s\): ([^}]+)', error_msg)
                if match:
                    missing_params = match.group(1).strip()

                # Format 2: Neo4j structured error
                if not missing_params:
                    match = re.search(r'Expected parameter\(s\): (.+?)\}', error_msg)
                    if match:
                        missing_params = match.group(1).strip()

                if missing_params:
                    return {
                        "error": f"Missing required parameters: {missing_params}",
                        "help": f"This template needs specific values. Try providing more details in your question.",
                        "template": template_name,
                        "missing_params": missing_params,
                        "example": f"Try: 'Show trends for company CF 12345678901 over 6 months'"
                    }

                # Generic template error
                return {
                    "error": f"Template execution failed: {error_msg}",
                    "help": "This template may require specific parameters. Try being more specific in your question.",
                    "template": template_name
                }
        
        # 2. Try dynamic Cypher generation
        elif self.schema_metadata:
            logger.info("No matching template. Attempting dynamic Cypher generation...")
            
            cypher = self.llm.generate_cypher(question, self.schema_metadata)
            max_retries = 3
            attempt = 0
            
            while attempt < max_retries:
                attempt += 1
                if not cypher:
                    break
                    
                try:
                    logger.info(f"Execution attempt {attempt} for: {cypher}")
                    results = self.execute_custom_cypher(cypher)
                    final_result = {
                        "method": "dynamic_cypher",
                        "cypher": cypher,
                        "attempts": attempt,
                        "results": results,
                        "count": len(results)
                    }
                    break # Success!
                except RuntimeError as e:
                    # Handle Neo4j connection errors
                    if "Neo4j Database is not running" in str(e):
                        logger.error(f"Database unavailable: {e}")
                        return {
                            "error": "🔴 Neo4j Database is not running!",
                            "help": "Start Neo4j and try again:",
                            "instructions": [
                                "Docker: docker-compose -f infra/docker-compose.yml up -d",
                                "Desktop: Open Neo4j Desktop and start the DBMS"
                            ]
                        }
                    raise
                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"Attempt {attempt} failed: {error_msg}")
                    if attempt < max_retries:
                        logger.info("Attempting self-correction...")
                        cypher = self.llm.fix_cypher(cypher, error_msg, self.schema_metadata)
                    else:
                        logger.error("Max retries reached for dynamic Cypher.")

        # 3. Add Insight if we have results
        if final_result.get("results"):
            final_result["insight"] = self.generate_insight(question, final_result["results"])
            return final_result
        
        return {
            "error": "I couldn't find a standard query or generate a safe one for that question.",
            "available_templates": template_list
        }
