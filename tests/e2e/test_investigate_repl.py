"""
End-to-end tests for the Terminal Investigator REPL.
Tests the complete workflow from user input to formatted output.
"""

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.console import Console

from scripts.debug.investigate import InvestigativeREPL


# Helper to strip ANSI escape codes for easier assertion
def strip_ansi(text):
    return text  # For now, let's keep it simple and assume tests handle rich output


@pytest.fixture
def mock_driver():
    """Mock Neo4j driver."""
    driver = Mock()
    session = Mock()

    # Mock session context manager
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = None

    return driver


@pytest.fixture
def mock_agent():
    """Mock GraphRAG agent."""
    agent = Mock()
    agent.templates.list_templates.return_value = [
        "top_vendors",
        "top_centrality_companies",
        "project_funding_analysis",
    ]
    return agent


class TestInvestigativeREPL:
    """End-to-end tests for the investigative REPL."""

    def test_format_results_with_data(self):
        """Test formatting results with actual data."""
        mock_console = Console(file=StringIO())  # Use a real console to capture rich output
        with patch("paladino.db.get_driver"), patch("paladino.schema_manager.SchemaManager"):
            repl = InvestigativeREPL(console=mock_console)  # Pass the mock console

            results = [
                {"company": "Test Company A", "tender_count": 100, "total_value": 1000000},
                {"company": "Test Company B", "tender_count": 50, "total_value": 500000},
            ]

            formatted = repl.format_results(results, title="Test Results")

            assert "Test Results" in formatted
            assert "Test Company A" in formatted
            assert "Test Company B" in formatted
            assert "100" in formatted
            assert "1,000,000" in formatted

    def test_format_results_empty(self):
        """Test formatting empty results."""
        mock_console = Console(file=StringIO())
        with patch("paladino.db.get_driver"), patch("paladino.schema_manager.SchemaManager"):
            repl = InvestigativeREPL(console=mock_console)
            formatted = repl.format_results([])

            assert "No records found for this investigation path." in formatted

    def test_format_results_with_limit(self):
        """Test that formatting respects the limit parameter."""
        mock_console = Console(file=StringIO())
        with patch("paladino.db.get_driver"), patch("paladino.schema_manager.SchemaManager"):
            repl = InvestigativeREPL(console=mock_console)

            # Create 20 results
            results = [{"id": i, "value": f"Item {i}"} for i in range(20)]

            formatted = repl.format_results(results, limit=5)

            assert "Item 0" in formatted
            assert "Item 4" in formatted
            assert "Item 5" not in formatted  # Ensure limit is respected

    def test_format_results_truncates_long_strings(self):
        """Test that long strings are truncated."""
        mock_console = Console(file=StringIO())
        with patch("paladino.db.get_driver"), patch("paladino.schema_manager.SchemaManager"):
            repl = InvestigativeREPL(console=mock_console)

            long_text = "A" * 100
            results = [{"description": long_text}]

            formatted = repl.format_results(results)

            # Should be truncated with ellipsis
            assert "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA..." in formatted
            # Check length is reasonable, not exact due to rich rendering
            assert len(formatted) < len(long_text) + 200  # Allow some overhead for rich formatting

    @patch("paladino.db.get_driver")
    @patch("paladino.schema_manager.SchemaManager")
    def test_show_templates(self, mock_schema, mock_driver_func):
        """Test displaying available templates."""
        mock_driver = Mock()
        mock_driver_func.return_value = mock_driver

        mock_console = Console(file=StringIO())

        repl = InvestigativeREPL(console=mock_console)
        repl.agent.templates.list_templates = Mock(
            return_value=["top_vendors", "top_centrality_companies", "project_funding_analysis"]
        )

        repl.show_templates()
        output = mock_console.file.getvalue()

        assert "Investigative Templates" in output
        assert "top_vendors" in output
        assert "top_centrality_companies" in output

    @patch("paladino.db.get_driver")
    @patch("paladino.schema_manager.SchemaManager")
    def test_direct_template_invocation_valid(self, mock_schema, mock_driver_func):
        """Test direct template invocation with @ prefix."""
        mock_driver = Mock()
        mock_driver_func.return_value = mock_driver

        mock_console = Console(file=StringIO())
        repl = InvestigativeREPL(console=mock_console)
        repl.agent.query = Mock(return_value=[{"company": "Test Co", "tender_count": 10}])
        repl.agent.templates.list_templates = Mock(return_value=["test_template"])

        # Simulate user input
        with patch("builtins.input", return_value="@test_template"):
            with patch.object(repl, "console", mock_console):  # Ensure repl uses our mock console
                repl.run()
                output = mock_console.file.getvalue()

            assert "Template: test_template" in output
            assert "Test Co" in output

    @patch("paladino.db.get_driver")
    @patch("paladino.schema_manager.SchemaManager")
    def test_process_query_with_results(self, mock_schema, mock_driver_func):
        """Test processing a query that returns results."""
        mock_driver = Mock()
        mock_driver_func.return_value = mock_driver

        mock_console = Console(file=StringIO())
        repl = InvestigativeREPL(console=mock_console)
        repl.agent.natural_language_query = Mock(
            return_value={
                "method": "template",
                "template": "top_vendors",
                "results": [{"company": "Test", "count": 5}],
                "count": 1,
                "insight": "Test insight.",
            }
        )

        repl.process_query("Show me top vendors")
        output = mock_console.file.getvalue()

        assert "Investigation: Show me top vendors" in output
        assert "Strategy: Pattern Matching (Template: top_vendors)" in output
        assert "Match Count: 1" in output
        assert "Test" in output
        assert "Insight" in output

    @patch("paladino.db.get_driver")
    @patch("paladino.schema_manager.SchemaManager")
    def test_process_query_with_error(self, mock_schema, mock_driver_func):
        """Test processing a query that returns an error."""
        mock_driver = Mock()
        mock_driver_func.return_value = mock_driver

        mock_console = Console(file=StringIO())
        repl = InvestigativeREPL(console=mock_console)
        repl.agent.natural_language_query = Mock(return_value={"error": "Template not found"})

        repl.process_query("Invalid query")
        output = mock_console.file.getvalue()

        assert "Investigation: Invalid query" in output
        assert "⚠️ Template not found" in output

    @patch("paladino.db.get_driver")
    @patch("paladino.schema_manager.SchemaManager")
    def test_context_tracking(self, mock_schema, mock_driver_func):
        """Test that REPL maintains context."""
        mock_driver = Mock()
        mock_driver_func.return_value = mock_driver

        mock_console = Console(file=StringIO())
        repl = InvestigativeREPL(console=mock_console)

        # Initially empty
        assert repl.context == {}

        # Can be updated
        repl.context["last_query"] = "test"
        assert repl.context["last_query"] == "test"

        # Can be cleared
        repl.context = {}
        assert repl.context == {}


class TestREPLCommands:
    """Test REPL command handling."""

    @patch("paladino.db.get_driver")
    @patch("paladino.schema_manager.SchemaManager")
    def test_stats_command(self, mock_schema, mock_driver_func):
        """Test the stats command."""
        mock_driver = Mock()
        mock_session = Mock()

        # Mock the session context manager
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_driver.session.return_value.__exit__.return_value = None

        # Mock query results for nodes and relationships
        mock_session.run.side_effect = [
            MagicMock(
                return_value=iter(
                    [{"label": "Project", "count": 1000}, {"label": "Company", "count": 500}]
                )
            ),
            MagicMock(
                return_value=iter(
                    [{"type": "WINS", "count": 2000}, {"type": "PART_OF", "count": 800}]
                )
            ),
            MagicMock(
                return_value=MockResult([{"nodes_with_centrality": 100, "avg_centrality": 0.05}])
            ),
        ]

        mock_driver_func.return_value = mock_driver

        mock_console = Console(file=StringIO())
        repl = InvestigativeREPL(console=mock_console)

        repl.show_stats()
        output = mock_console.file.getvalue()

        assert "Graph Infrastructure Statistics" in output
        assert "Knowledge Nodes" in output
        assert "Project" in output
        assert "1,000" in output
        assert "Graph Connections" in output
        assert "WINS" in output
        assert "2,000" in output
        assert "Intelligence Layer" in output
        assert "PageRank Active Nodes: 100" in output

    @patch("paladino.db.get_driver")
    @patch("paladino.schema_manager.SchemaManager")
    def test_templates_command(self, mock_schema, mock_driver_func):
        """Test the templates command."""
        mock_driver = Mock()
        mock_driver_func.return_value = mock_driver

        mock_console = Console(file=StringIO())
        repl = InvestigativeREPL(console=mock_console)
        repl.agent.templates.list_templates = Mock(
            return_value=["top_vendors", "top_centrality_companies"]
        )

        repl.show_templates()
        output = mock_console.file.getvalue()

        assert "Investigative Templates" in output
        assert "top_vendors" in output
        assert "top_centrality_companies" in output


@pytest.mark.e2e
class TestFullREPLWorkflow:
    """End-to-end workflow tests."""

    @patch("paladino.db.get_driver")
    @patch("paladino.schema_manager.SchemaManager")
    def test_initialization(self, mock_schema, mock_driver_func):
        """Test REPL initialization."""
        mock_driver = Mock()
        mock_driver_func.return_value = mock_driver

        mock_console = Console(file=StringIO())
        repl = InvestigativeREPL(console=mock_console)
        output = mock_console.file.getvalue()

        assert "Paladino Terminal Investigator" in output
        assert "System Ready" in output

    @patch("paladino.db.get_driver")
    @patch("paladino.schema_manager.SchemaManager")
    def test_query_execution_flow(self, mock_schema, mock_driver_func):
        """Test complete query execution flow."""
        mock_driver = Mock()
        mock_driver_func.return_value = mock_driver

        mock_console = Console(file=StringIO())
        repl = InvestigativeREPL(console=mock_console)

        # Mock agent response
        repl.agent.natural_language_query = Mock(
            return_value={
                "method": "template",
                "template": "top_vendors",
                "results": [
                    {"company": "Vendor A", "tender_count": 100, "total_value": 1000000},
                    {"company": "Vendor B", "tender_count": 50, "total_value": 500000},
                ],
                "count": 2,
                "insight": "Vendor A dominates the market with twice the tender count.",
            }
        )

        repl.process_query("Who are the top vendors?")
        output = mock_console.file.getvalue()

        # Verify complete workflow output
        assert "Investigation: Who are the top vendors?" in output
        assert "Strategy: Pattern Matching (Template: top_vendors)" in output
        assert "Match Count: 2" in output
        assert "Vendor A" in output
        assert "Vendor B" in output
        assert "Detective Insight" in output
        assert "Vendor A dominates the market with twice the tender count." in output
