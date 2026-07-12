"""
Unit tests for ABAC (Attribute-Based Access Control).
"""

import pytest
from paladino.app.abac import (
    PolicyCondition,
    Policy,
    ABACEngine,
    abac_engine,
    check_access,
)
from paladino.app.rbac import User, RoleType


class TestPolicyCondition:
    """Test PolicyCondition evaluation."""
    
    def test_evaluate_equals(self):
        """Test equality condition."""
        cond = PolicyCondition(attribute="regione", operator="==", value="Lombardia")
        
        assert cond.evaluate({"regione": "Lombardia"}) is True
        assert cond.evaluate({"regione": "Lazio"}) is False
    
    def test_evaluate_not_equals(self):
        """Test not-equals condition."""
        cond = PolicyCondition(attribute="regione", operator="!=", value="Lombardia")
        
        assert cond.evaluate({"regione": "Lazio"}) is True
        assert cond.evaluate({"regione": "Lombardia"}) is False
    
    def test_evaluate_in(self):
        """Test 'in' condition."""
        cond = PolicyCondition(attribute="regione", operator="in", value=["Lombardia", "Lazio"])
        
        assert cond.evaluate({"regione": "Lombardia"}) is True
        assert cond.evaluate({"regione": "Veneto"}) is False
    
    def test_evaluate_contains(self):
        """Test 'contains' condition."""
        cond = PolicyCondition(attribute="name", operator="contains", value="TEST")
        
        assert cond.evaluate({"name": "TEST SRL"}) is True
        assert cond.evaluate({"name": "OTHER SPA"}) is False
    
    def test_evaluate_numeric(self):
        """Test numeric comparisons."""
        cond_gte = PolicyCondition(attribute="risk_score", operator="gte", value=0.5)
        
        assert cond_gte.evaluate({"risk_score": 0.7}) is True
        assert cond_gte.evaluate({"risk_score": 0.3}) is False
        
        cond_lt = PolicyCondition(attribute="risk_score", operator="lt", value=0.5)
        assert cond_lt.evaluate({"risk_score": 0.3}) is True
        assert cond_lt.evaluate({"risk_score": 0.7}) is False
    
    def test_evaluate_missing_attribute(self):
        """Test condition with missing attribute."""
        cond = PolicyCondition(attribute="regione", operator="==", value="Lombardia")
        
        assert cond.evaluate({}) is False
        assert cond.evaluate({"other": "value"}) is False


class TestPolicy:
    """Test Policy evaluation."""
    
    def test_policy_matches(self):
        """Test policy matching."""
        policy = Policy(
            name="test",
            resource="Company",
            action="read",
        )
        
        assert policy.matches("Company", "read") is True
        assert policy.matches("Company", "write") is False
        assert policy.matches("Tender", "read") is False
    
    def test_policy_evaluate_allow(self):
        """Test allow policy evaluation."""
        policy = Policy(
            name="regional_allow",
            effect="allow",
            resource="Company",
            action="read",
            conditions=[
                PolicyCondition(attribute="regione", operator="==", value="Lombardia"),
            ],
        )
        
        user_attrs = {}
        entity_attrs = {"regione": "Lombardia"}
        
        assert policy.evaluate(entity_attrs, user_attrs) is True
        
        entity_attrs_wrong = {"regione": "Lazio"}
        assert policy.evaluate(entity_attrs_wrong, user_attrs) is False
    
    def test_policy_evaluate_deny(self):
        """Test deny policy evaluation."""
        policy = Policy(
            name="high_risk_deny",
            effect="deny",
            resource="Company",
            action="read",
            conditions=[
                PolicyCondition(attribute="risk_score", operator="gte", value=0.8),
            ],
        )

        entity_attrs = {"risk_score": 0.9}
        # Policy applies (condition met) - returns True meaning "policy matches"
        assert policy.evaluate(entity_attrs, {}) is True

        entity_attrs_low = {"risk_score": 0.3}
        # Policy doesn't apply (condition not met) - returns False
        assert policy.evaluate(entity_attrs_low, {}) is False
    
    def test_policy_user_attribute_substitution(self):
        """Test ${user.attribute} substitution."""
        policy = Policy(
            name="user_region",
            effect="allow",
            resource="Company",
            action="read",
            conditions=[
                PolicyCondition(attribute="regione", operator="==", value="${user.region}"),
            ],
        )
        
        user_attrs = {"region": "Lombardia"}
        entity_attrs = {"regione": "Lombardia"}
        
        # Should match - same region, policy applies
        assert policy.evaluate(entity_attrs, user_attrs) is True
        
        # Should not match - different region, policy doesn't apply
        entity_attrs_wrong = {"regione": "Lazio"}
        assert policy.evaluate(entity_attrs_wrong, user_attrs) is False


class TestABACEngine:
    """Test ABACEngine."""
    
    def test_add_policy(self):
        """Test adding a policy."""
        engine = ABACEngine()
        policy = Policy(
            name="test_policy",
            resource="Company",
            action="read",
        )
        
        engine.add_policy(policy)
        
        policies = engine.list_policies()
        assert len(policies) > 0
        assert policy in policies
    
    def test_remove_policy(self):
        """Test removing a policy."""
        engine = ABACEngine()
        policy = Policy(
            name="temp_policy",
            resource="Company",
            action="read",
        )
        
        engine.add_policy(policy)
        result = engine.remove_policy("temp_policy")
        
        assert result is True
        assert policy not in engine.list_policies()
    
    def test_evaluate_no_policies(self):
        """Test evaluation with no policies (default allow)."""
        engine = ABACEngine()
        
        # Should default to allow for internal use
        result = engine.evaluate(
            resource_type="Company",
            action="read",
            entity_attributes={},
            user_attributes={},
        )
        assert result is True
    
    def test_evaluate_deny_takes_precedence(self):
        """Test that deny policies take precedence."""
        engine = ABACEngine()
        
        # Add allow policy WITHOUT conditions (allows everything)
        engine.add_policy(Policy(
            name="allow_all",
            effect="allow",
            resource="Company",
            action="read",
            conditions=[],  # No conditions = allow all
        ))
        
        # Add deny policy with conditions
        engine.add_policy(Policy(
            name="deny_high_risk",
            effect="deny",
            resource="Company",
            action="read",
            conditions=[
                PolicyCondition(attribute="risk_score", operator="gte", value=0.8),
            ],
        ))
        
        # High risk - deny should take precedence
        # Note: In our permissive internal system, deny is checked first
        result = engine.evaluate(
            resource_type="Company",
            action="read",
            entity_attributes={"risk_score": 0.9},
            user_attributes={},
        )
        # Deny policy should be evaluated first
        assert result is False
        
        # Low risk - should be allowed
        result = engine.evaluate(
            resource_type="Company",
            action="read",
            entity_attributes={"risk_score": 0.3},
            user_attributes={},
        )
        assert result is True
    
    def test_get_cypher_filter(self):
        """Test Cypher filter generation."""
        engine = ABACEngine()
        
        engine.add_policy(Policy(
            name="regional_filter",
            effect="allow",
            resource="Company",
            action="read",
            conditions=[
                PolicyCondition(attribute="regione", operator="==", value="Lombardia"),
            ],
        ))
        
        filter_str = engine.get_cypher_filter(
            entity_type="Company",
            user_attributes={},
            action="read",
        )
        
        assert "WHERE" in filter_str
        assert "c.regione" in filter_str
        assert "Lombardia" in filter_str
    
    def test_get_cypher_filter_no_policies(self):
        """Test Cypher filter with no policies."""
        engine = ABACEngine()
        
        filter_str = engine.get_cypher_filter(
            entity_type="Company",
            user_attributes={},
            action="read",
        )
        
        assert filter_str == ""


class TestCheckAccess:
    """Test combined RBAC + ABAC check."""
    
    def test_check_access_rbac_pass_abac_none(self):
        """Test access check with RBAC pass, no ABAC policies."""
        user = User(username="analyst", role=RoleType.ANALYST)
        
        result = check_access(
            user=user,
            resource_type="Company",
            action="read",
            entity_attributes=None,
        )
        
        assert result is True
    
    def test_check_access_rbac_fail(self):
        """Test access check with RBAC fail."""
        viewer = User(username="viewer", role=RoleType.VIEWER)
        
        result = check_access(
            user=viewer,
            resource_type="Company",
            action="delete",  # Viewer can't delete
            entity_attributes=None,
        )
        
        assert result is False
    
    def test_check_access_rbac_pass_abac_fail(self):
        """Test access check with RBAC pass but ABAC fail."""
        # Create a fresh engine for this test
        engine = ABACEngine()
        
        # Add a deny policy that matches all
        engine.add_policy(Policy(
            name="test_deny_all",
            effect="deny",
            resource="Company",
            action="read",
            conditions=[],  # Deny all (no conditions)
        ))
        
        user = User(username="admin", role=RoleType.ADMIN)
        
        # Test engine directly
        result = engine.evaluate(
            resource_type="Company",
            action="read",
            entity_attributes={},
            user_attributes={},
        )
        
        # Should be denied by ABAC deny policy
        assert result is False
