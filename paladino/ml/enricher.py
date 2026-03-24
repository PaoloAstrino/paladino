"""
Company enrichment - Aggregate statistics and risk scoring.
"""

import polars as pl
from typing import Dict
from loguru import logger
from neo4j import Driver


class CompanyEnricher:
    """Enrich companies with aggregated statistics and risk scores."""
    
    def __init__(self, driver: Driver):
        """
        Initialize enricher.
        
        Args:
            driver: Neo4j driver instance
        """
        self.driver = driver
    
    def enrich_all_companies(self):
        """Enrich all companies in the graph."""
        logger.info("Enriching companies with statistics and risk scores...")
        
        with self.driver.session() as session:
            # Get all companies
            result = session.run("""
                MATCH (c:Company)
                RETURN c.id as id, c.cf as cf
            """)
            
            companies = [dict(r) for r in result]
            logger.info(f"Enriching {len(companies)} companies...")
            
            for company in companies:
                stats = self._compute_company_stats(company["cf"])
                risk_score = self._compute_risk_score(company["cf"], stats)
                
                # Update company node
                session.run("""
                    MATCH (c:Company {cf: $cf})
                    SET c.total_tenders = $total_tenders,
                        c.total_importo = $total_importo,
                        c.avg_importo = $avg_importo,
                        c.risk_score = $risk_score,
                        c.anomaly_flags = $anomaly_flags
                """, 
                    cf=company["cf"],
                    total_tenders=stats["total_tenders"],
                    total_importo=stats["total_importo"],
                    avg_importo=stats["avg_importo"],
                    risk_score=risk_score["score"],
                    anomaly_flags=risk_score["flags"]
                )
        
        logger.success("Company enrichment complete")
    
    def _compute_company_stats(self, cf: str) -> Dict:
        """Compute aggregate statistics for a company."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (c:Company {cf: $cf})-[w:WINS]->(t:Tender)
                RETURN count(t) as total_tenders,
                       sum(w.importo) as total_importo,
                       avg(w.importo) as avg_importo
            """, cf=cf)
            
            record = result.single()
            
            if record:
                return {
                    "total_tenders": record["total_tenders"] or 0,
                    "total_importo": record["total_importo"] or 0.0,
                    "avg_importo": record["avg_importo"] or 0.0,
                }
            
            return {
                "total_tenders": 0,
                "total_importo": 0.0,
                "avg_importo": 0.0,
            }
    
    def _compute_risk_score(self, cf: str, stats: Dict) -> Dict:
        """
        Compute risk score based on anomaly detection.
        
        Risk factors:
        - Single bidder tenders
        - Unusually high win rate
        - Concentration in specific buyers
        - Outlier amounts
        """
        flags = []
        risk_score = 0.0
        
        with self.driver.session() as session:
            # Check for single bidder tenders
            result = session.run("""
                MATCH (c:Company {cf: $cf})-[:WINS]->(t:Tender)
                WHERE t.single_bidder = true
                RETURN count(t) as single_bidder_count
            """, cf=cf)
            
            single_bidder_count = result.single()["single_bidder_count"] or 0
            
            if single_bidder_count > 0:
                single_bidder_pct = single_bidder_count / max(stats["total_tenders"], 1)
                
                if single_bidder_pct > 0.5:
                    flags.append("high_single_bidder_rate")
                    risk_score += 0.3
            
            # Check for buyer concentration
            result = session.run("""
                MATCH (c:Company {cf: $cf})-[:WINS]->(t:Tender)-[:AWARDED_BY]->(b:Buyer)
                WITH b, count(t) as tender_count
                ORDER BY tender_count DESC
                LIMIT 1
                RETURN tender_count as max_buyer_tenders
            """, cf=cf)
            
            record = result.single()
            if record:
                max_buyer_tenders = record["max_buyer_tenders"] or 0
                buyer_concentration = max_buyer_tenders / max(stats["total_tenders"], 1)
                
                if buyer_concentration > 0.7:
                    flags.append("buyer_concentration")
                    risk_score += 0.2
            
            # Check for amount outliers
            if stats["avg_importo"] > 5_000_000:  # >5M EUR average
                flags.append("high_avg_amount")
                risk_score += 0.1
        
        # Normalize risk score to 0-1
        risk_score = min(risk_score, 1.0)
        
        return {
            "score": round(risk_score, 2),
            "flags": flags,
        }
