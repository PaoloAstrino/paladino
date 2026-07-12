"""
Unit tests for GraphRAG query templates.
"""

from paladino.app.graphrag_agent import CypherQueryTemplates


class TestCypherQueryTemplates:
    """Test suite for Cypher query templates."""

    def test_get_template_existing(self):
        """Test retrieving an existing template."""
        template = CypherQueryTemplates.get_template("top_vendors")
        assert template is not None
        assert "MATCH (c:Company)-[:WINS]->(t:Tender)" in template
        assert "ORDER BY tender_count DESC" in template

    def test_get_template_nonexistent(self):
        """Test retrieving a non-existent template."""
        template = CypherQueryTemplates.get_template("nonexistent_template")
        assert template is None

    def test_list_templates(self):
        """Test listing all available templates."""
        templates = CypherQueryTemplates.list_templates()
        assert isinstance(templates, list)
        assert len(templates) > 0
        assert "top_vendors" in templates
        assert "top_centrality_companies" in templates
        assert "project_funding_analysis" in templates

    def test_all_templates_have_limit_param(self):
        """Test that all templates support the $limit parameter."""
        templates = CypherQueryTemplates.TEMPLATES

        # Templates that should have LIMIT
        limit_required = [
            "companies_by_region",
            "pnrr_projects",
            "tender_to_project",
            "companies_with_high_risk",
            "top_vendors",
            "top_centrality_companies",
            "project_funding_analysis",
        ]

        for template_name in limit_required:
            template = templates.get(template_name)
            assert template is not None, f"Template {template_name} not found"
            assert "$limit" in template or "LIMIT" in template, (
                f"Template {template_name} should support limiting results"
            )

    def test_templates_are_read_only(self):
        """Test that templates use only READ operations."""
        forbidden_keywords = ["DELETE", "DETACH", "REMOVE", "DROP", "CREATE", "MERGE", "SET"]

        for template_name, template in CypherQueryTemplates.TEMPLATES.items():
            template_upper = template.upper()
            for keyword in forbidden_keywords:
                assert keyword not in template_upper, (
                    f"Template {template_name} contains forbidden keyword: {keyword}"
                )

    def test_top_vendors_template_structure(self):
        """Test the structure of the top_vendors template."""
        template = CypherQueryTemplates.get_template("top_vendors")

        # Check for required components
        assert "MATCH (c:Company)-[:WINS]->(t:Tender)" in template
        assert "RETURN c.nome_originale" in template
        assert "count(t)" in template
        assert "sum(t.importo)" in template
        assert "ORDER BY tender_count DESC" in template
        assert "LIMIT $limit" in template

    def test_top_centrality_template_structure(self):
        """Test the structure of the top_centrality_companies template."""
        template = CypherQueryTemplates.get_template("top_centrality_companies")

        # Check for required components
        assert "MATCH (c:Company)" in template
        assert "WHERE c.centrality_score IS NOT NULL" in template
        assert "RETURN c.nome_originale" in template
        assert "c.centrality_score" in template
        assert "c.community_id" in template
        assert "ORDER BY c.centrality_score DESC" in template

    def test_project_funding_template_structure(self):
        """Test the structure of the project_funding_analysis template."""
        template = CypherQueryTemplates.get_template("project_funding_analysis")

        # Check for required components
        assert "MATCH (p:Project)-[:FUNDED_BY]->(f:FundingSource)" in template
        assert "RETURN f.tipo" in template
        assert "count(p)" in template
        assert "sum(p.importo_finanziato)" in template
        assert "ORDER BY total_funding DESC" in template
