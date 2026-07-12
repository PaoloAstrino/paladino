"""
Lightweight ABAC (Attribute-Based Access Control) for internal Paladino instances.

Works alongside RBAC to add attribute-based filtering.
For internal/prototype use - no external policy engine required.

Usage:
    from paladino.app.abac import abac_engine
    
    # In endpoint
    @app.get("/companies")
    async def get_companies(user: User = Depends(get_current_user)):
        # Get filter for user's attributes
        cypher_filter = abac_engine.get_cypher_filter(
            entity_type="Company",
            user=user,
            action="read"
        )
        
        # Inject filter into query
        query = f"MATCH (c:Company) {cypher_filter} RETURN c"
"""

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Policy Definition
# ─────────────────────────────────────────────────────────────────────────────

class PolicyCondition(BaseModel):
    """A single condition in a policy."""
    
    attribute: str  # e.g., "regione", "community_id"
    operator: str   # e.g., "==", "!=", "in", "contains"
    value: Any      # Value to compare against
    
    def evaluate(self, entity_attributes: dict) -> bool:
        """Evaluate condition against entity attributes."""
        entity_value = entity_attributes.get(self.attribute)
        
        if entity_value is None:
            return False
        
        if self.operator == "==":
            return entity_value == self.value
        elif self.operator == "!=":
            return entity_value != self.value
        elif self.operator == "in":
            return entity_value in self.value
        elif self.operator == "contains":
            return self.value in entity_value
        elif self.operator == "gte":
            return entity_value >= self.value
        elif self.operator == "lte":
            return entity_value <= self.value
        elif self.operator == "gt":
            return entity_value > self.value
        elif self.operator == "lt":
            return entity_value < self.value
        
        return False


class Policy(BaseModel):
    """
    Access control policy.
    
    Example:
    {
        "name": "regional_restriction",
        "description": "Users can only access data from their region",
        "effect": "allow",  # or "deny"
        "resource": "Company",
        "action": "read",
        "conditions": [
            {"attribute": "regione", "operator": "==", "value": "${user.region}"}
        ]
    }
    """
    
    name: str
    description: str = ""
    effect: str = "allow"  # "allow" or "deny"
    resource: str  # Entity type this applies to
    action: str  # Action (read, write, delete)
    conditions: list[PolicyCondition] = Field(default_factory=list)
    user_attributes: dict[str, Any] = Field(default_factory=dict)  # Required user attributes
    
    def matches(self, resource_type: str, action: str) -> bool:
        """Check if this policy applies to the given resource and action."""
        return self.resource == resource_type and self.action == action
    
    def evaluate(self, entity_attributes: dict, user_attributes: dict) -> bool:
        """
        Evaluate policy against entity and user attributes.
        
        Returns True if policy conditions are met (policy applies), False otherwise.
        The effect (allow/deny) is checked by the engine.
        """
        # Check if user has required attributes
        for attr in self.user_attributes.keys():
            if attr not in user_attributes:
                logger.warning(f"User missing required attribute: {attr}")
                # For internal use, continue without this attribute
        
        # Substitute user attributes in conditions
        resolved_conditions = []
        for cond in self.conditions:
            value = cond.value
            # Handle ${user.attribute} substitution
            if isinstance(value, str) and value.startswith("${user."):
                attr_name = value[7:-1]  # Extract attribute name (${user.X} → X)
                value = user_attributes.get(attr_name)

            if value is not None:  # Only add if we have a value
                resolved_conditions.append(PolicyCondition(
                    attribute=cond.attribute,
                    operator=cond.operator,
                    value=value,
                ))
        
        # All conditions must pass (AND logic)
        if not resolved_conditions:
            # No conditions = policy always applies
            return True
        
        for cond in resolved_conditions:
            if not cond.evaluate(entity_attributes):
                return False  # Condition not met
        
        return True  # All conditions met


# ─────────────────────────────────────────────────────────────────────────────
# Built-in Policies
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_POLICIES = [
    # Example: Regional restriction (commented out - enable when needed)
    # Policy(
    #     name="regional_restriction",
    #     description="Users can only read companies from their region",
    #     effect="allow",
    #     resource="Company",
    #     action="read",
    #     conditions=[
    #         PolicyCondition(attribute="regione", operator="==", value="${user.region}"),
    #     ],
    #     user_attributes={"region": str},
    # ),
]


# ─────────────────────────────────────────────────────────────────────────────
# ABAC Engine
# ─────────────────────────────────────────────────────────────────────────────

class ABACEngine:
    """
    Attribute-Based Access Control engine.
    
    For internal use, policies are simple Python objects.
    Can be extended to use AWS Cedar or OPA for production.
    """
    
    def __init__(self):
        self._policies: list[Policy] = DEFAULT_POLICIES.copy()
    
    def add_policy(self, policy: Policy) -> None:
        """Add a policy to the engine."""
        self._policies.append(policy)
        logger.info(f"Added ABAC policy: {policy.name}")
    
    def remove_policy(self, name: str) -> bool:
        """Remove a policy by name."""
        for i, policy in enumerate(self._policies):
            if policy.name == name:
                del self._policies[i]
                logger.info(f"Removed ABAC policy: {name}")
                return True
        return False
    
    def list_policies(self) -> list[Policy]:
        """List all policies."""
        return self._policies.copy()
    
    def evaluate(
        self,
        resource_type: str,
        action: str,
        entity_attributes: dict,
        user_attributes: dict,
    ) -> bool:
        """
        Evaluate all applicable policies.
        
        Returns True if access is allowed, False if denied.
        
        Logic:
        - If any DENY policy matches → deny
        - If any ALLOW policy matches → allow
        - Otherwise → allow (default allow for internal use)
        """
        applicable_policies = [
            p for p in self._policies
            if p.matches(resource_type, action)
        ]
        
        if not applicable_policies:
            # No policies → default allow for internal use
            return True
        
        # Check for explicit denies first (deny takes precedence)
        for policy in applicable_policies:
            if policy.effect == "deny":
                if policy.evaluate(entity_attributes, user_attributes):
                    logger.info(
                        f"ABAC DENY: {policy.name} for {resource_type}:{action}"
                    )
                    return False
        
        # Check for allows
        for policy in applicable_policies:
            if policy.effect == "allow":
                # For allow policies with conditions, check if conditions match
                if policy.conditions:
                    if policy.evaluate(entity_attributes, user_attributes):
                        logger.debug(
                            f"ABAC ALLOW: {policy.name} for {resource_type}:{action}"
                        )
                        return True
                else:
                    # No conditions = allow all
                    logger.debug(
                        f"ABAC ALLOW: {policy.name} for {resource_type}:{action}"
                    )
                    return True
        
        # Default allow if no deny matched and no allow matched
        logger.debug(f"ABAC DEFAULT ALLOW: No matching policy for {resource_type}:{action}")
        return True
    
    def get_cypher_filter(
        self,
        entity_type: str,
        user_attributes: dict,
        action: str = "read",
    ) -> str:
        """
        Generate a Cypher WHERE clause from applicable policies.
        
        This is a simplified version - for complex policies,
        you'd need a full Cypher AST generator.
        
        Returns empty string if no filter needed.
        """
        applicable_policies = [
            p for p in self._policies
            if p.matches(entity_type, action) and p.effect == "allow"
        ]
        
        if not applicable_policies:
            return ""
        
        # Build WHERE clause from conditions
        conditions = []
        for policy in applicable_policies:
            for cond in policy.conditions:
                # Handle ${user.attribute} substitution
                value = cond.value
                if isinstance(value, str) and value.startswith("${user."):
                    attr_name = value[8:-1]
                    value = user_attributes.get(attr_name)
                
                # Convert to Cypher
                if value is None:
                    continue
                
                # Cypher operator mapping
                op_map = {
                    "==": "=",
                    "!=": "<>",
                    "in": "IN",
                    "contains": "CONTAINS",
                    "gte": ">=",
                    "lte": "<=",
                    "gt": ">",
                    "lt": "<",
                }
                cypher_op = op_map.get(cond.operator, "=")
                
                # Format value for Cypher
                if isinstance(value, str):
                    cypher_value = f"'{value}'"
                elif isinstance(value, list):
                    cypher_value = "[" + ", ".join(
                        f"'{v}'" if isinstance(v, str) else str(v)
                        for v in value
                    ) + "]"
                else:
                    cypher_value = str(value)
                
                conditions.append(f"c.{cond.attribute} {cypher_op} {cypher_value}")
        
        if conditions:
            return "WHERE " + " AND ".join(conditions)
        
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Global ABAC Engine Instance
# ─────────────────────────────────────────────────────────────────────────────

abac_engine = ABACEngine()


# ─────────────────────────────────────────────────────────────────────────────
# Integration with RBAC
# ─────────────────────────────────────────────────────────────────────────────

def check_access(
    user: "User",  # type: ignore
    resource_type: str,
    action: str,
    entity_attributes: dict | None = None,
) -> bool:
    """
    Combined RBAC + ABAC check.
    
    1. Check RBAC permission first (fast path)
    2. If RBAC passes, check ABAC policies (fine-grained)
    
    Usage:
        from paladino.app.abac import check_access
        
        @app.get("/companies/{id}")
        async def get_company(id: str, user: User = Depends(get_current_user)):
            company = get_company_by_id(id)
            
            if not check_access(user, "Company", "read", {
                "regione": company.regione,
                "community_id": company.community_id,
            }):
                raise HTTPException(403, "Access denied")
            
            return company
    """
    from paladino.app.rbac import Permission
    
    # Step 1: RBAC check
    perm_name = f"{resource_type.lower()}:{action}"
    try:
        perm = Permission(perm_name)
        if not user.has_permission(perm):
            logger.info(f"RBAC DENY: {user.username} lacks {perm_name}")
            return False
    except ValueError:
        # Unknown permission - check generic ones
        if action == "read" and not user.has_permission(Permission.COMPANY_READ):
            return False
    
    # Step 2: ABAC check (if entity attributes provided)
    if entity_attributes:
        if not abac_engine.evaluate(
            resource_type=resource_type,
            action=action,
            entity_attributes=entity_attributes,
            user_attributes={"region": user.email.split("@")[-1] if user.email else None},
        ):
            logger.info(f"ABAC DENY: {user.username} for {resource_type}:{action}")
            return False
    
    return True
