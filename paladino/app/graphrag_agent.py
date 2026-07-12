"""
GraphRAG agent - Multi-hop reasoning over knowledge graph.
"""

import json

from loguru import logger
from neo4j import Driver
from neo4j.exceptions import DatabaseUnavailable, DriverError, ServiceUnavailable

from paladino.llm_manager import LLMManager
from paladino.app.temporal_rewriter import apply_temporal_filter


class CypherQueryTemplates:
    """Pre-validated Cypher query templates."""

    TEMPLATES = {
        # ── Basic Company Queries ────────────────────────────────────────────
        "companies_by_region": """
            MATCH (c:Company)-[:LOCATED_IN]->(m:Municipality)-[:IN_REGION]->(r:Region {nome: $region})
            WHERE (c.valid_from <= $as_of AND (c.valid_to > $as_of OR c.valid_to IS NULL))
            RETURN c.nome_normalizzato as company, c.total_tenders as tenders
            ORDER BY c.total_tenders DESC
            LIMIT $limit
        """,
        "company_by_cf": """
            MATCH (c:Company {cf: $cf})
            WHERE (c.valid_from <= $as_of AND (c.valid_to > $as_of OR c.valid_to IS NULL))
            RETURN c.nome_normalizzato as name, c.cf, c.risk_score, c.anomaly_flags,
                   c.total_tenders, c.total_value, c.regione
        """,
        "companies_with_high_risk": """
            MATCH (c:Company)
            WHERE c.risk_score > $min_risk
              AND (c.valid_from <= $as_of AND (c.valid_to > $as_of OR c.valid_to IS NULL))
            RETURN c.nome_normalizzato, c.cf, c.risk_score, c.anomaly_flags
            ORDER BY c.risk_score DESC
            LIMIT $limit
        """,
        "top_vendors": """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE (c.valid_from <= $as_of AND (c.valid_to > $as_of OR c.valid_to IS NULL))
              AND (t.valid_from <= $as_of AND (t.valid_to > $as_of OR t.valid_to IS NULL))
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
              AND (c.valid_from <= $as_of AND (c.valid_to > $as_of OR c.valid_to IS NULL))
            RETURN c.nome_originale as company,
                   c.centrality_score as influence_score,
                   c.community_id as community
            ORDER BY c.centrality_score DESC
            LIMIT $limit
        """,
        
        # ── Regional & Geographic Analysis ───────────────────────────────────
        "regional_spending": """
            MATCH (c:Company)-[:LOCATED_IN]->(m:Municipality)-[:IN_REGION]->(r:Region)
            MATCH (c)-[w:WINS]->(t:Tender)
            WHERE (c.valid_from <= $as_of AND (c.valid_to > $as_of OR c.valid_to IS NULL))
              AND (t.valid_from <= $as_of AND (t.valid_to > $as_of OR t.valid_to IS NULL))
              AND (w.valid_from <= $as_of AND (w.valid_to > $as_of OR w.valid_to IS NULL))
            RETURN r.nome as regione,
                   count(t) as total_tenders,
                   sum(t.importo) as total_importo
            ORDER BY total_importo DESC
        """,
        "municipality_ranking": """
            MATCH (m:Municipality)<-[:LOCATED_IN]-(c:Company)-[w:WINS]->(t:Tender)
            WHERE (c.valid_from <= $as_of AND (c.valid_to > $as_of OR c.valid_to IS NULL))
              AND (t.valid_from <= $as_of AND (t.valid_to > $as_of OR t.valid_to IS NULL))
            RETURN m.nome as municipality, m.regione,
                   count(DISTINCT c) as companies,
                   count(t) as tenders,
                   sum(t.importo) as total_value
            ORDER BY total_value DESC
            LIMIT $limit
        """,
        
        # ── PNRR & EU Funding ────────────────────────────────────────────────
        "pnrr_projects": """
            MATCH (p:Project)-[:FUNDED_BY]->(f:FundingSource {tipo: "PNRR"})
            WHERE (p.valid_from <= $as_of AND (p.valid_to > $as_of OR p.valid_to IS NULL))
            RETURN p.cup, p.titolo, p.importo_finanziato, p.regione
            ORDER BY p.importo_finanziato DESC
            LIMIT $limit
        """,
        "pnrr_by_region": """
            MATCH (p:Project)-[:FUNDED_BY]->(f:FundingSource {tipo: "PNRR"})
            WHERE (p.valid_from <= $as_of AND (p.valid_to > $as_of OR p.valid_to IS NULL))
            RETURN p.regione,
                   count(p) as project_count,
                   sum(p.importo_finanziato) as total_funding
            ORDER BY total_funding DESC
        """,
        "project_funding_analysis": """
            MATCH (p:Project)-[:FUNDED_BY]->(f:FundingSource)
            WHERE (p.valid_from <= $as_of AND (p.valid_to > $as_of OR p.valid_to IS NULL))
            RETURN f.tipo as funding_source,
                   count(p) as project_count,
                   sum(p.importo_finanziato) as total_funding
            ORDER BY total_funding DESC
            LIMIT $limit
        """,
        
        # ── Tender Analysis ──────────────────────────────────────────────────
        "tender_to_project": """
            MATCH (c:Company {cf: $cf})-[w:WINS]->(t:Tender)-[ptp:PART_OF_PROJECT]->(p:Project)
            WHERE (c.valid_from <= $as_of AND (c.valid_to > $as_of OR c.valid_to IS NULL))
              AND (t.valid_from <= $as_of AND (t.valid_to > $as_of OR t.valid_to IS NULL))
              AND (p.valid_from <= $as_of AND (p.valid_to > $as_of OR p.valid_to IS NULL))
            RETURN t.cig, t.oggetto, p.cup, p.titolo, t.importo
            ORDER BY t.importo DESC
            LIMIT $limit
        """,
        "single_bidder_tenders": """
            MATCH (t:Tender)
            WHERE t.single_bidder = true
              AND (t.valid_from <= $as_of AND (t.valid_to > $as_of OR t.valid_to IS NULL))
            RETURN t.cig, t.oggetto, t.importo, t.data_aggiudicazione
            ORDER BY t.importo DESC
            LIMIT $limit
        """,
        "tenders_by_procedure": """
            MATCH (t:Tender)
            WHERE (t.valid_from <= $as_of AND (t.valid_to > $as_of OR t.valid_to IS NULL))
            RETURN t.procedura as procedure_type,
                   count(*) as count,
                   sum(t.importo) as total_value,
                   avg(t.importo) as avg_value
            ORDER BY total_value DESC
        """,
        
        # ── Supply Chain & Corporate Networks ────────────────────────────────
        "ownership_chain": """
            MATCH path = (start:Company {cf: $cf})<-[:SHAREHOLDER_OF|SHARES_UBO*1..10]-(owner)
            WHERE (owner:Company OR owner:Person)
              AND ALL(n IN nodes(path) WHERE n.valid_from <= $as_of AND (n.valid_to > $as_of OR n.valid_to IS NULL))
            RETURN
                labels(owner)[0] AS owner_type,
                coalesce(owner.nome_normalizzato, owner.cognome + ' ' + owner.nome, owner.cf) AS owner_name,
                owner.cf AS owner_cf,
                length(path) AS hops,
                [n IN nodes(path) | coalesce(n.nome_normalizzato, n.nome, n.cf)] AS chain_names
            ORDER BY hops, owner_type
            LIMIT $limit
        """,
        "supply_chain": """
            MATCH path = (start:Company {cf: $cf})-[:SUBCONTRACTS_TO|SUPPLIES_TO*1..4]->(downstream:Company)
            WHERE ALL(n IN nodes(path) WHERE n.valid_from <= $as_of AND (n.valid_to > $as_of OR n.valid_to IS NULL))
            RETURN
                downstream.nome_normalizzato AS sub_name,
                downstream.cf AS sub_cf,
                length(path) AS depth,
                [r IN relationships(path) | r.cig][0] AS first_cig,
                [n IN nodes(path) | coalesce(n.nome_normalizzato, n.cf)] AS chain_names
            ORDER BY depth, sub_name
            LIMIT $limit
        """,
        "board_overlaps": """
            MATCH (p:Person)-[:REPRESENTS]->(c1:Company)
            MATCH (p)-[:REPRESENTS]->(c2:Company)
            WHERE id(c1) < id(c2)
            WITH c1, c2,
                 count(DISTINCT p) AS shared_count,
                 collect(DISTINCT coalesce(p.cognome + ' ' + p.nome, p.cf)) AS shared_persons
            WHERE shared_count >= $min_shared
            RETURN c1.nome_normalizzato AS company_a,
                   c2.nome_normalizzato AS company_b,
                   shared_count,
                   shared_persons
            ORDER BY shared_count DESC
            LIMIT $limit
        """,
        "carousel_risk": """
            MATCH (c:Company)
            WHERE c.supply_scc_id IS NOT NULL AND c.supply_scc_size > 1
            WITH c.supply_scc_id AS scc_id, collect(c) AS members
            RETURN scc_id,
                   size(members) AS cycle_size,
                   [m IN members | m.nome_normalizzato] AS company_names,
                   [m IN members | m.cf] AS company_cfs,
                   [m IN members | coalesce(m.risk_score, 0.0)] AS risk_scores
            ORDER BY cycle_size DESC
            LIMIT $limit
        """,
        
        # ── Temporal / Time-Series Analysis ──────────────────────────────────
        "tender_volume_trend": """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE ($cf IS NULL OR c.cf = $cf)
              AND t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
            WITH c.cf AS cf, c.nome_normalizzato AS company,
                 t.data_aggiudicazione.year AS year,
                 ((t.data_aggiudicazione.month-1)/3+1) AS quarter,
                 t.importo AS importo
            WITH cf, company, year, quarter,
                 count(*) AS tender_count,
                 sum(importo) AS total_value,
                 avg(importo) AS avg_value
            RETURN cf, company, year, quarter, tender_count, total_value, avg_value
            ORDER BY cf, year ASC, quarter ASC
            LIMIT $limit
        """,
        "single_bidder_trend": """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE ($cf IS NULL OR c.cf = $cf)
              AND t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
            WITH c.cf AS cf, c.nome_normalizzato AS company,
                 t.data_aggiudicazione.year AS year,
                 ((t.data_aggiudicazione.month-1)/3+1) AS quarter,
                 t.single_bidder AS is_single
            WITH cf, company, year, quarter,
                 count(*) AS total_wins,
                 sum(CASE WHEN is_single = true THEN 1 ELSE 0 END) AS single_wins
            WITH cf, company, year, quarter, total_wins, single_wins,
                 toFloat(single_wins) / total_wins AS ratio
            WHERE total_wins >= 2
            RETURN cf, company, year, quarter, total_wins, single_wins,
                   round(ratio * 1000) / 1000.0 AS single_bidder_ratio
            ORDER BY cf, year ASC, quarter ASC
            LIMIT $limit
        """,
        "sector_spending_trend": """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE c.ateco STARTS WITH $ateco_prefix
              AND t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
              AND t.importo IS NOT NULL
            WITH t.data_aggiudicazione.year AS year,
                 ((t.data_aggiudicazione.month-1)/3+1) AS quarter,
                 c.id AS company_id,
                 t.importo AS importo
            WITH year, quarter, company_id,
                 sum(importo) AS company_quarterly_spend
            WITH year, quarter,
                 count(DISTINCT company_id) AS company_count,
                 sum(company_quarterly_spend) AS total_value,
                 stDev(company_quarterly_spend) AS stddev_value
            RETURN $ateco_prefix AS ateco_prefix,
                   year, quarter, company_count, total_value,
                   round(stddev_value * 100) / 100.0 AS stddev_value
            ORDER BY year ASC, quarter ASC
            LIMIT $limit
        """,
        "sudden_spikes": """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({months: $months})
            WITH c.cf AS cf, c.nome_normalizzato AS company,
                 t.data_aggiudicazione.year AS year,
                 ((t.data_aggiudicazione.month-1)/3+1) AS quarter,
                 count(*) AS tender_count,
                 sum(t.importo) AS total_value
            WHERE tender_count >= $min_bucket
            RETURN cf, company, year, quarter, tender_count, total_value
            ORDER BY cf, year ASC, quarter ASC
            LIMIT $limit
        """,
        
        # ── Fraud Detection & Red Flags ──────────────────────────────────────
        "companies_with_red_flags": """
            MATCH (c:Company)
            WHERE c.red_flags IS NOT NULL AND size(c.red_flags) > 0
            RETURN c.nome_normalizzato, c.cf, c.red_flags, c.risk_score
            ORDER BY size(c.red_flags) DESC, c.risk_score DESC
            LIMIT $limit
        """,
        "short_award_window": """
            MATCH (t:Tender)
            WHERE t.award_days IS NOT NULL AND t.award_days <= $max_days
            RETURN t.cig, t.oggetto, t.importo, t.award_days,
                   [(t)<-[:WINS]-(c:Company) | c.nome_normalizzato][0] AS winner
            ORDER BY t.award_days ASC
            LIMIT $limit
        """,
        "price_anomalies": """
            MATCH (t:Tender)
            WHERE t.z_score IS NOT NULL AND abs(t.z_score) > $threshold
            RETURN t.cig, t.oggetto, t.importo, t.z_score,
                   [(t)<-[:WINS]-(c:Company) | c.nome_normalizzato][0] AS winner
            ORDER BY abs(t.z_score) DESC
            LIMIT $limit
        """,
        
        # ── Network Analysis ─────────────────────────────────────────────────
        "community_analysis": """
            MATCH (c:Company)
            WHERE c.community_id IS NOT NULL
            RETURN c.community_id,
                   count(c) as members,
                   avg(c.risk_score) as avg_risk,
                   sum(c.total_tenders) as total_tenders
            ORDER BY members DESC
            LIMIT $limit
        """,
        "network_hubs": """
            MATCH (c:Company)-[]-(neighbor)
            RETURN c.nome_normalizzato, c.cf,
                   count(DISTINCT neighbor) as connections,
                   c.centrality_score
            ORDER BY connections DESC
            LIMIT $limit
        """,
    }

    @classmethod
    def get_template(cls, template_name: str) -> str | None:
        """Get a query template by name."""
        return cls.TEMPLATES.get(template_name)

    @classmethod
    def list_templates(cls) -> list[str]:
        """List all available templates."""
        return list(cls.TEMPLATES.keys())


class GraphRAGAgent:
    """GraphRAG agent for multi-hop reasoning."""

    def __init__(self, driver: Driver, schema_metadata: str | None = None):
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

    def query(self, template_name: str, params: dict | None = None, limit: int = 10) -> list[dict]:
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
            
        # Tier 3: Inject default as_of for temporal templates
        if "as_of" not in query_params:
            from datetime import datetime
            query_params["as_of"] = datetime.utcnow().isoformat()

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

    def execute_custom_cypher(self, cypher: str, params: dict | None = None, as_of: str | None = None) -> list[dict]:
        """Execute a raw Cypher query safely with optional temporal filtering."""
        params = params or {}
        if as_of:
            logger.info(f"Applying temporal filter for as_of: {as_of}")
            cypher = apply_temporal_filter(cypher, as_of)
            params["as_of"] = as_of

        logger.info(f"Executing Cypher: {cypher}")
        try:
            with self.driver.session() as session:
                result = session.run(cypher, **params)
                records = [dict(r) for r in result]
            return records
        except (ServiceUnavailable, DatabaseUnavailable, DriverError) as e:
            logger.error(f"Neo4j connection failed: {e}")
            raise RuntimeError(
                "\n🔴 Neo4j Database is not running!\n\n"
                "Please start Neo4j:\n"
                "  • Docker: docker-compose -f infra/docker-compose.yml up -d\n"
                "  • Desktop: Open Neo4j Desktop and start the DBMS\n"
                "\nThen try again."
            ) from e

    def thematic_search(self, keyword: str, limit: int = 15) -> list[dict]:
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

    def generate_insight(self, question: str, results: list[dict]) -> str:
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
            {"role": "user", "content": f"Question: {question}\nData: {data_snippet}"},
        ]

        return self.llm.chat(messages)

    def natural_language_query(self, question: str, as_of: str | None = None) -> dict:
        """
        Process natural language question.

        1. Classify intent to a template
        2. If no template, generate dynamic Cypher
        3. Execute query
        4. Generate natural language insight
        """
        logger.info(f"Processing NL query: {question} (as_of: {as_of})")

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
                    "count": len(results),
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
                            "Desktop: Open Neo4j Desktop and start the DBMS",
                        ],
                    }
                raise
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Template execution failed: {error_msg}")

                # Check for missing parameter error (multiple formats)
                missing_params = None

                # Format 1: "Expected parameter(s): cf, months"
                import re

                match = re.search(r"Expected parameter\(s\): ([^}]+)", error_msg)
                if match:
                    missing_params = match.group(1).strip()

                # Format 2: Neo4j structured error
                if not missing_params:
                    match = re.search(r"Expected parameter\(s\): (.+?)\}", error_msg)
                    if match:
                        missing_params = match.group(1).strip()

                if missing_params:
                    return {
                        "error": f"Missing required parameters: {missing_params}",
                        "help": "This template needs specific values. Try providing more details in your question.",
                        "template": template_name,
                        "missing_params": missing_params,
                        "example": "Try: 'Show trends for company CF 12345678901 over 6 months'",
                    }

                # Generic template error
                return {
                    "error": f"Template execution failed: {error_msg}",
                    "help": "This template may require specific parameters. Try being more specific in your question.",
                    "template": template_name,
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
                    results = self.execute_custom_cypher(cypher, as_of=as_of)
                    final_result = {
                        "method": "dynamic_cypher",
                        "cypher": cypher,
                        "as_of": as_of,
                        "attempts": attempt,
                        "results": results,
                        "count": len(results),
                    }
                    break  # Success!
                except RuntimeError as e:
                    # Handle Neo4j connection errors
                    if "Neo4j Database is not running" in str(e):
                        logger.error(f"Database unavailable: {e}")
                        return {
                            "error": "🔴 Neo4j Database is not running!",
                            "help": "Start Neo4j and try again:",
                            "instructions": [
                                "Docker: docker-compose -f infra/docker-compose.yml up -d",
                                "Desktop: Open Neo4j Desktop and start the DBMS",
                            ],
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
            "available_templates": template_list,
        }
