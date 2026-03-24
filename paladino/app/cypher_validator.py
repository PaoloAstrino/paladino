"""
Cypher query validator for security.

This module validates Cypher queries before execution to prevent:
- Injection attacks
- Dangerous operations (DELETE, DROP, etc.)
- Expensive queries that could crash Neo4j
"""

import re
from typing import List, Tuple, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class ValidationResult:
    """Result of Cypher validation."""
    is_safe: bool
    errors: List[str]
    warnings: List[str]
    blocked_reason: Optional[str] = None


class CypherValidator:
    """
    Validate Cypher queries for safety before execution.
    
    Security controls:
    - Block dangerous operations (DELETE, DROP, DBMS commands)
    - Warn about expensive patterns (unbounded traversals)
    - Prevent injection via parameterization checks
    """
    
    # Dangerous patterns that should be blocked entirely
    DANGEROUS_PATTERNS = [
        (r"\bCALL\s+apoc\.util\.validate\b", "Apoc validation bypass attempt"),
        (r"\bEXECUTE\s+DBMS\b", "DBMS command execution"),
        (r"\bCREATE\s+USER\b", "User creation attempt"),
        (r"\bDROP\s+(DATABASE|CONSTRAINT|INDEX|USER)\b", "Schema modification"),
        (r"\bDETACH\s+DELETE\b", "Node deletion"),
        (r"\bDELETE\b", "DELETE operation (use ETL pipeline instead)"),
        (r"\bREMOVE\b\s+\w+\s*\.", "Property removal"),
        (r"\bCREATE\s+CONSTRAINT\b", "Constraint creation"),
        (r"\bCREATE\s+INDEX\b", "Index creation"),
        (r"\bLOAD\s+CSV\b", "CSV loading (use ETL pipeline instead)"),
        (r"\bCALL\s+dbms\.", "DBMS procedure call"),
        (r"\bCALL\s+apoc\.schema\.", "Schema manipulation"),
        (r"\bCALL\s+apoc\.create\.", "Dynamic node creation"),
        (r"\bCALL\s+apoc\.cypher\.run\b", "Dynamic Cypher execution"),
    ]
    
    # Warning patterns for potentially expensive queries
    WARNING_PATTERNS = [
        (r"\bMATCH\s+\(\)-\[", "Unbounded relationship traversal - consider adding depth limit"),
        (r"\bMATCH\s+\(n\)\s*WHERE\s+NOT\s+exists\b", "Negation without label - may be slow"),
        (r"\bOPTIONAL\s+MATCH\b.*\bWITH\s+collect\b", "Large collection risk"),
        (r"\bCROSS\s+JOIN\b", "Cross join - may produce cartesian explosion"),
        (r"\bMATCH\s+\([^)]*\),\s*\([^)]*\)", "Multiple MATCH without relationship - cartesian product risk"),
        (r"\bWITH\s+\w+\s+ORDER\s+BY\s+\w+\s+LIMIT\s+\d+\s*$", "Large sort without index"),
        (r"\bCOUNT\s*\(\s*\*\s*\)", "Full graph count - may be slow on large graphs"),
    ]
    
    # Parameterization checks to prevent injection
    INJECTION_PATTERNS = [
        (r"['\"].*\$[a-zA-Z_]", "Parameters must not be inside quotes"),
        (r"\$\d+", "Numeric parameter indices not supported - use named parameters"),
        (r"\$\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\+", "Parameter concatenation detected - potential injection"),
    ]
    
    # Allowed write operations (for templates that need them)
    ALLOWED_WRITE_OPERATIONS = [
        "MERGE",  # Allowed in controlled templates
        "CREATE",  # Allowed in controlled templates
        "SET",     # Allowed in controlled templates
    ]
    
    def __init__(self, allow_writes: bool = False):
        """
        Initialize validator.
        
        Args:
            allow_writes: If True, allow MERGE/CREATE/SET operations
        """
        self.allow_writes = allow_writes
    
    def validate(self, cypher: str) -> ValidationResult:
        """
        Validate Cypher query.
        
        Args:
            cypher: Cypher query string to validate
        
        Returns:
            ValidationResult with is_safe flag, errors, and warnings
        """
        errors = []
        warnings = []
        cypher_upper = cypher.upper()
        
        # Check dangerous patterns (always blocked)
        for pattern, description in self.DANGEROUS_PATTERNS:
            if re.search(pattern, cypher_upper, re.IGNORECASE | re.MULTILINE):
                errors.append(f"Blocked: {description}")
                logger.warning(f"Cypher validation blocked dangerous pattern: {description}")
        
        # Check injection patterns
        for pattern, description in self.INJECTION_PATTERNS:
            if re.search(pattern, cypher):
                errors.append(f"Blocked: {description}")
                logger.warning(f"Cypher validation blocked injection attempt: {description}")
        
        # Check warning patterns (not blocked, but logged)
        for pattern, description in self.WARNING_PATTERNS:
            if re.search(pattern, cypher_upper, re.IGNORECASE | re.MULTILINE):
                warnings.append(f"Warning: {description}")
        
        # Check for write operations if not allowed
        if not self.allow_writes:
            for op in ["MERGE", "CREATE", "SET"]:
                # Check if operation exists and is not in a comment
                if self._is_operation_present(cypher_upper, op):
                    errors.append(f"Blocked: {op} operation not allowed in read-only mode")
        
        # Check for parameterization (basic heuristic)
        if "$" not in cypher and self._has_user_input_markers(cypher):
            warnings.append("Warning: Query has no parameters - ensure user input is properly escaped")
        
        is_safe = len(errors) == 0
        blocked_reason = errors[0] if errors else None
        
        return ValidationResult(
            is_safe=is_safe,
            errors=errors,
            warnings=warnings,
            blocked_reason=blocked_reason,
        )
    
    def _is_operation_present(self, cypher_upper: str, operation: str) -> bool:
        """Check if operation is present and not in a comment."""
        # Remove comments
        cypher_no_comments = re.sub(r'//.*$', '', cypher_upper, flags=re.MULTILINE)
        cypher_no_comments = re.sub(r'/\*.*?\*/', '', cypher_no_comments, flags=re.DOTALL)
        
        # Check for operation as word boundary
        return bool(re.search(rf'\b{operation}\b', cypher_no_comments))
    
    def _has_user_input_markers(self, cypher: str) -> bool:
        """Check if query appears to have user input placeholders."""
        markers = ["{user_", "{input", "$user_", "$input"]
        return any(marker in cypher.lower() for marker in markers)
    
    @classmethod
    def validate_and_raise(cls, cypher: str, allow_writes: bool = False) -> None:
        """
        Validate Cypher and raise exception if unsafe.
        
        Args:
            cypher: Cypher query to validate
            allow_writes: If True, allow write operations
        
        Raises:
            ValueError: If query is unsafe
        """
        validator = cls(allow_writes=allow_writes)
        result = validator.validate(cypher)
        
        if not result.is_safe:
            error_msg = "; ".join(result.errors)
            logger.error(f"Cypher validation failed: {error_msg}")
            raise ValueError(f"Cypher query validation failed: {error_msg}")
        
        # Log warnings
        for warning in result.warnings:
            logger.warning(f"Cypher validation warning: {warning}")


def validate_cypher(cypher: str, allow_writes: bool = False) -> Tuple[bool, List[str], List[str]]:
    """
    Convenience function to validate Cypher.
    
    Args:
        cypher: Cypher query to validate
        allow_writes: If True, allow write operations
    
    Returns:
        Tuple of (is_safe, errors, warnings)
    """
    validator = CypherValidator(allow_writes=allow_writes)
    result = validator.validate(cypher)
    return result.is_safe, result.errors, result.warnings
