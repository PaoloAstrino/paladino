"""
Unit tests for Cypher query templates.
"""

import pytest
from paladino.app.graphrag_agent import CypherQueryTemplates


def test_all_templates_are_valid_cypher():
    """Test that all templates contain valid Cypher syntax."""
    templates = CypherQueryTemplates.TEMPLATES
    
    for name, query in templates.items():
        # Basic syntax checks
        assert "MATCH" in query or "CREATE" in query, f"Template {name} missing MATCH/CREATE"
        assert "RETURN" in query, f"Template {name} missing RETURN"


def test_pnrr_projects_template():
    """Test PNRR projects template structure."""
    template = CypherQueryTemplates.get_template("pnrr_projects")
    
    assert template is not None
    assert "Project" in template
    assert "FundingSource" in template
    assert "PNRR" in template
    assert "$limit" in template


def test_companies_by_region_template():
    """Test companies by region template."""
    template = CypherQueryTemplates.get_template("companies_by_region")
    
    assert template is not None
    assert "Company" in template
    assert "Municipality" in template
    assert "Region" in template
    assert "$region" in template


def test_high_risk_companies_template():
    """Test high risk companies template."""
    template = CypherQueryTemplates.get_template("high_risk_companies")
    
    assert template is not None
    assert "risk_score" in template
    assert "$min_risk" in template


def test_tender_to_project_template():
    """Test tender to project linking template."""
    template = CypherQueryTemplates.get_template("tender_to_project")
    
    assert template is not None
    assert "WINS" in template
    assert "PART_OF_PROJECT" in template
    assert "$cf" in template


def test_regional_spending_template():
    """Test regional spending aggregation template."""
    template = CypherQueryTemplates.get_template("regional_spending")
    
    assert template is not None
    assert "sum(t.importo)" in template or "sum" in template.lower()
    assert "count(t)" in template or "count" in template.lower()


def test_get_nonexistent_template():
    """Test getting a template that doesn't exist."""
    template = CypherQueryTemplates.get_template("nonexistent_template")
    
    assert template is None


def test_list_templates_completeness():
    """Test that list_templates returns all templates."""
    template_list = CypherQueryTemplates.list_templates()
    
    assert len(template_list) >= 5
    assert "pnrr_projects" in template_list
    assert "companies_by_region" in template_list
    assert "high_risk_companies" in template_list
    assert "tender_to_project" in template_list
    assert "regional_spending" in template_list
