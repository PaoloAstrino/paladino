"""
Temporal Cypher Rewriter - Injects temporal filters into Cypher queries.
Enables 'AS OF' functionality by transparently filtering nodes/edges 
based on their validity window.
"""

import re
from loguru import logger

class TemporalRewriter:
    """
    Rewrites Cypher queries to inject temporal filters.
    
    Logic:
    - Finds all node/relationship aliases (e.g., (c:Company))
    - Appends a WHERE clause (or extends existing) with valid_from/valid_to checks.
    """
    
    def __init__(self, target_date_param: str = "as_of"):
        self.target_date_param = target_date_param

    def rewrite(self, cypher: str) -> str:
        """
        Inject temporal filters into a Cypher query.
        
        Example:
            MATCH (c:Company) RETURN c
        becomes:
            MATCH (c:Company) 
            WHERE c.valid_from <= $as_of AND (c.valid_to > $as_of OR c.valid_to IS NULL) 
            RETURN c
        """
        # 1. Identify all aliases in MATCH clauses
        # Pattern matches (alias:Label) or [alias:TYPE]
        # This is a simplified regex - in production we might use a proper Cypher parser
        node_pattern = r'\((\w+):(?:\w+)\)'
        rel_pattern = r'\[(\w+):(?:\w+)\+\d*\]|\[(\w+):(?:\w+)\]'
        
        aliases = set()
        for match in re.finditer(node_pattern, cypher):
            aliases.add(match.group(1))
        for match in re.finditer(rel_pattern, cypher):
            alias = match.group(1) or match.group(2)
            if alias:
                aliases.add(alias)
        
        if not aliases:
            return cypher
            
        logger.debug(f"Injecting temporal filters for aliases: {aliases}")
        
        # 2. Build the temporal filter string
        filters = []
        for alias in sorted(list(aliases)):
            filters.append(
                f"({alias}.valid_from <= ${self.target_date_param} AND "
                f"({alias}.valid_to > ${self.target_date_param} OR {alias}.valid_to IS NULL))"
            )
        
        temporal_where = " AND ".join(filters)
        
        # 3. Inject into the query
        # Find the first RETURN or WITH to inject the WHERE before it
        # If there's already a WHERE, we append to it
        if " WHERE " in cypher.upper():
            # Append to existing WHERE
            # Note: This is fragile with complex queries (multiple MATCHes)
            # A more robust approach would be per-clause injection
            rewritten = cypher.replace(" WHERE ", f" WHERE {temporal_where} AND ", 1)
        else:
            # Create new WHERE
            # We look for the last MATCH/OPTIONAL MATCH or the first RETURN/WITH
            # Simple heuristic: inject before RETURN
            if " RETURN " in cypher.upper():
                rewritten = cypher.replace(" RETURN ", f" WHERE {temporal_where} RETURN ", 1)
            elif " WITH " in cypher.upper():
                rewritten = cypher.replace(" WITH ", f" WHERE {temporal_where} WITH ", 1)
            else:
                rewritten = f"{cypher} WHERE {temporal_where}"
                
        return rewritten

def apply_temporal_filter(cypher: str, as_of: str | None = None) -> str:
    """Helper to apply filter if as_of is provided."""
    if not as_of:
        return cypher
    rewriter = TemporalRewriter()
    return rewriter.rewrite(cypher)
