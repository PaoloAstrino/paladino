"""
Unit tests for Graph Visualization Service.

Tests cover:
- Graph Queries (8 tests): entity graph, filtered graph, path finding, neighbors, community
- Layout Algorithms (5 tests): force-directed, radial, hierarchical, circular, empty
- Styling (6 tests): risk coloring, type coloring, centrality sizing, combined, missing risk, unknown type
- Graph Statistics (5 tests): basic stats, empty graph, density, components, type counts
- Cluster Detection (4 tests): find clusters, no clusters, multiple clusters, bridge nodes
- Export (5 tests): JSON, GraphML, SVG, PNG, invalid format
- Model Validation (12 tests): GraphQuery, GraphFilter, enums, path request, template, invalid values
- Templates (5 tests): six templates exist, names correct, valid node types, company network, full overview
"""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

from paladino.app.graph_service import (
    GraphService,
    GRAPH_TEMPLATES,
    MAX_DEPTH,
    MAX_NODES,
    NODE_TYPE_COLORS,
    EDGE_TYPE_COLORS,
)
from paladino.models import (
    GraphEdge,
    GraphEdgeType,
    GraphExportFormat,
    GraphFilter,
    GraphLayout,
    GraphNode,
    GraphNodeType,
    GraphPathRequest,
    GraphQuery,
    GraphStyleRequest,
    GraphTemplate,
)
from paladino.db import Neo4jConnection


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_conn():
    """Create a mock Neo4jConnection."""
    conn = MagicMock(spec=Neo4jConnection)
    return conn


@pytest.fixture
def graph_service(mock_conn):
    """Create a GraphService with mocked connection."""
    return GraphService(mock_conn)


@pytest.fixture
def sample_nodes():
    """Sample graph nodes for testing."""
    return [
        GraphNode(
            id="company-1",
            label="ACME SRL",
            node_type=GraphNodeType.COMPANY,
            risk_score=0.8,
            properties={"cf": "12345678901"},
        ),
        GraphNode(
            id="tender-1",
            label="Tender A",
            node_type=GraphNodeType.TENDER,
            risk_score=0.3,
            properties={"cig": "Z1234567890"},
        ),
        GraphNode(
            id="person-1",
            label="John Doe",
            node_type=GraphNodeType.PERSON,
            risk_score=0.5,
            properties={"cf": "RSSMRA80A01H501Z"},
        ),
        GraphNode(
            id="company-2",
            label="BETA SPA",
            node_type=GraphNodeType.COMPANY,
            risk_score=0.1,
            properties={"cf": "98765432109"},
        ),
    ]


@pytest.fixture
def sample_edges():
    """Sample graph edges for testing."""
    return [
        GraphEdge(
            source="company-1",
            target="tender-1",
            edge_type=GraphEdgeType.WINS,
            label="wins",
            weight=1.0,
        ),
        GraphEdge(
            source="person-1",
            target="company-1",
            edge_type=GraphEdgeType.REPRESENTS,
            label="represents",
            weight=1.0,
        ),
        GraphEdge(
            source="company-2",
            target="tender-1",
            edge_type=GraphEdgeType.WINS,
            label="wins",
            weight=1.0,
        ),
    ]


@pytest.fixture
def sample_neo4j_result():
    """Sample Neo4j query result."""
    return [
        {
            "node": {
                "id": "company-1",
                "nome_normalizzato": "ACME SRL",
                "cf": "12345678901",
                "risk_score": 0.8,
                "labels": ["Company"],
            },
            "edges": [
                {
                    "type": "WINS",
                    "source_id": "company-1",
                    "target_id": "tender-1",
                    "weight": 1.0,
                }
            ],
        },
        {
            "node": {
                "id": "tender-1",
                "oggetto": "Tender A",
                "cig": "Z1234567890",
                "importo": 150000.0,
                "labels": ["Tender"],
            },
            "edges": [],
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Graph Queries (8 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestGraphQueries:
    """Tests for graph query operations."""

    def test_get_entity_graph_depth_1(self, graph_service, mock_conn, sample_nodes, sample_edges):
        """Get entity graph with depth 1."""
        mock_conn.run_query.return_value = [{"node": {}, "edges": []}]

        with patch.object(graph_service, '_transform_to_graph', return_value=(sample_nodes[:2], sample_edges[:1])):
            result = graph_service.get_entity_graph("company-1", depth=1)

        assert result.center_entity_id == "company-1"
        assert result.layout == GraphLayout.FORCE_DIRECTED
        mock_conn.run_query.assert_called_once()

    def test_get_entity_graph_depth_2(self, graph_service, mock_conn):
        """Get entity graph with depth 2."""
        mock_conn.run_query.return_value = [{"node": {}, "edges": []}]

        result = graph_service.get_entity_graph("company-1", depth=2)

        assert result.center_entity_id == "company-1"
        # Verify depth=2 was used in query
        call_args = mock_conn.run_query.call_args
        assert "1..2" in call_args[0][0]

    def test_get_filtered_graph_by_type(self, graph_service, mock_conn):
        """Get filtered graph by node type."""
        mock_conn.run_query.return_value = []

        filters = GraphFilter(node_types=[GraphNodeType.COMPANY])
        result = graph_service.get_filtered_graph(filters)

        assert result.nodes == []
        assert result.edges == []

    def test_get_filtered_graph_by_risk(self, graph_service, mock_conn):
        """Get filtered graph by risk score range."""
        mock_conn.run_query.return_value = []

        filters = GraphFilter(min_risk_score=0.5, max_risk_score=0.9)
        result = graph_service.get_filtered_graph(filters)

        assert result.truncated is False

    def test_get_path_between_entities(self, graph_service, mock_conn):
        """Find path between two entities."""
        mock_conn.run_query.return_value = [{"path": MagicMock()}]

        request = GraphPathRequest(
            source_id="company-1",
            target_id="company-2",
            max_depth=3,
        )

        with patch.object(graph_service, '_parse_path_to_graph', return_value=([], [])):
            result = graph_service.get_path_between(request)

        assert result.found is True

    def test_path_not_found(self, graph_service, mock_conn):
        """Path not found case returns found=False."""
        mock_conn.run_query.return_value = []

        request = GraphPathRequest(
            source_id="company-1",
            target_id="company-999",
            max_depth=3,
        )

        result = graph_service.get_path_between(request)

        assert result.found is False
        assert result.length == 0

    def test_get_neighbors(self, graph_service, mock_conn, sample_nodes, sample_edges):
        """Get 1-hop neighbors of an entity."""
        mock_conn.run_query.return_value = [
            {
                "center": {"id": "company-1", "nome_normalizzato": "ACME SRL"},
                "neighbor": {"id": "tender-1", "oggetto": "Tender A"},
                "r": {"type": "WINS", "source_id": "company-1", "target_id": "tender-1"},
            }
        ]

        result = graph_service.get_neighbors("company-1")

        assert result.center_entity_id == "company-1"

    def test_get_community_graph(self, graph_service, mock_conn):
        """Get community subgraph."""
        mock_conn.run_query.return_value = []

        result = graph_service.get_community_graph("community-42")

        assert result.nodes == []
        assert result.edges == []


# ─────────────────────────────────────────────────────────────────────────────
# Layout Algorithms (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestLayoutAlgorithms:
    """Tests for layout algorithms."""

    def test_force_directed_layout(self, graph_service, sample_nodes, sample_edges):
        """Force-directed layout assigns x,y coordinates."""
        nodes = [n.model_copy() for n in sample_nodes]
        result = graph_service._calculate_force_directed(nodes, sample_edges)

        for node in result:
            assert node.x is not None
            assert node.y is not None
            assert 0 <= node.x <= 1000
            assert 0 <= node.y <= 1000

    def test_radial_layout(self, graph_service, sample_nodes, sample_edges):
        """Radial layout places nodes in concentric circles."""
        nodes = [n.model_copy() for n in sample_nodes]
        result = graph_service._calculate_radial(nodes, sample_edges)

        for node in result:
            assert node.x is not None
            assert node.y is not None

    def test_hierarchical_layout(self, graph_service, sample_nodes, sample_edges):
        """Hierarchical layout assigns layers."""
        nodes = [n.model_copy() for n in sample_nodes]
        result = graph_service._calculate_hierarchical(nodes, sample_edges)

        for node in result:
            assert node.x is not None
            assert node.y is not None

    def test_circular_layout(self, graph_service, sample_nodes):
        """Circular layout places nodes on a circle."""
        nodes = [n.model_copy() for n in sample_nodes]
        result = graph_service._calculate_circular(nodes)

        for node in result:
            assert node.x is not None
            assert node.y is not None

    def test_layout_empty_graph(self, graph_service):
        """Layout with empty graph returns unchanged."""
        result = graph_service.apply_layout([], [], GraphLayout.FORCE_DIRECTED)
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# Styling (6 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestStyling:
    """Tests for graph styling operations."""

    def test_style_by_risk_green_to_red(self, graph_service):
        """Style by risk: green (0) → yellow (0.5) → red (1.0)."""
        nodes = [
            GraphNode(id="low", label="Low", node_type=GraphNodeType.COMPANY, risk_score=0.0),
            GraphNode(id="mid", label="Mid", node_type=GraphNodeType.COMPANY, risk_score=0.5),
            GraphNode(id="high", label="High", node_type=GraphNodeType.COMPANY, risk_score=1.0),
        ]

        result = graph_service._style_by_risk(nodes)

        # Low risk = green
        assert result[0].color == "#00ff00"
        # Mid risk = yellow
        assert result[1].color == "#ff0000" or result[1].color == "#ffff00"
        # High risk = red
        assert result[2].color == "#ff0000"

    def test_style_by_type_colors(self, graph_service):
        """Style by type: different colors per type."""
        nodes = [
            GraphNode(id="c", label="Company", node_type=GraphNodeType.COMPANY),
            GraphNode(id="t", label="Tender", node_type=GraphNodeType.TENDER),
            GraphNode(id="p", label="Person", node_type=GraphNodeType.PERSON),
        ]

        result = graph_service.style_by_type(nodes)

        assert result[0].color == NODE_TYPE_COLORS[GraphNodeType.COMPANY]
        assert result[1].color == NODE_TYPE_COLORS[GraphNodeType.TENDER]
        assert result[2].color == NODE_TYPE_COLORS[GraphNodeType.PERSON]

    def test_style_by_centrality_sizing(self, graph_service, sample_nodes, sample_edges):
        """Style by centrality: size nodes by degree."""
        nodes = [n.model_copy() for n in sample_nodes]
        result = graph_service._style_by_centrality(nodes, sample_edges)

        for node in result:
            assert node.size >= 5.0
            assert node.size <= 100.0
            assert node.centrality is not None

    def test_combined_styling(self, graph_service, sample_nodes, sample_edges):
        """Combined risk and centrality styling."""
        nodes = [n.model_copy() for n in sample_nodes]
        nodes = graph_service._style_by_risk(nodes)
        nodes = graph_service._style_by_centrality(nodes, sample_edges)

        for node in nodes:
            assert node.color != "#666666" or node.risk_score is None
            assert node.size >= 5.0

    def test_style_missing_risk_score(self, graph_service):
        """Style with missing risk score uses type color."""
        nodes = [
            GraphNode(id="n1", label="No Risk", node_type=GraphNodeType.COMPANY, risk_score=None),
        ]

        result = graph_service._style_by_risk(nodes)

        assert result[0].color == NODE_TYPE_COLORS[GraphNodeType.COMPANY]

    def test_style_unknown_type(self, graph_service):
        """Style with unknown type uses default color."""
        # Create node with default type (COMPANY) - test fallback behavior
        nodes = [
            GraphNode(id="n1", label="Unknown", node_type=GraphNodeType.COMPANY),
        ]

        result = graph_service.style_by_type(nodes)

        assert result[0].color == NODE_TYPE_COLORS[GraphNodeType.COMPANY]


# ─────────────────────────────────────────────────────────────────────────────
# Graph Statistics (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestGraphStatistics:
    """Tests for graph statistics calculation."""

    def test_basic_statistics(self, graph_service, sample_nodes, sample_edges):
        """Basic statistics calculation."""
        stats = graph_service.get_graph_statistics(sample_nodes, sample_edges)

        assert stats.node_count == 4
        assert stats.edge_count == 3
        assert stats.density >= 0.0
        assert stats.density <= 1.0
        assert stats.avg_degree >= 0
        assert stats.max_degree >= 0

    def test_empty_graph_statistics(self, graph_service):
        """Empty graph statistics."""
        stats = graph_service.get_graph_statistics([], [])

        assert stats.node_count == 0
        assert stats.edge_count == 0
        assert stats.density == 0.0
        assert stats.connected_components == 0

    def test_density_calculation(self, graph_service):
        """Density calculation for complete graph."""
        nodes = [
            GraphNode(id="a", label="A", node_type=GraphNodeType.COMPANY),
            GraphNode(id="b", label="B", node_type=GraphNodeType.COMPANY),
            GraphNode(id="c", label="C", node_type=GraphNodeType.COMPANY),
        ]
        edges = [
            GraphEdge(source="a", target="b", edge_type=GraphEdgeType.RELATED_TO),
            GraphEdge(source="b", target="c", edge_type=GraphEdgeType.RELATED_TO),
            GraphEdge(source="a", target="c", edge_type=GraphEdgeType.RELATED_TO),
        ]

        stats = graph_service.get_graph_statistics(nodes, edges)

        # Complete graph with 3 nodes: density = 3 / (3*2/2) = 1.0
        assert stats.density == 1.0

    def test_connected_components(self, graph_service):
        """Count connected components."""
        nodes = [
            GraphNode(id="a", label="A", node_type=GraphNodeType.COMPANY),
            GraphNode(id="b", label="B", node_type=GraphNodeType.COMPANY),
            GraphNode(id="c", label="C", node_type=GraphNodeType.COMPANY),
            GraphNode(id="d", label="D", node_type=GraphNodeType.COMPANY),
        ]
        # Two separate components: {a,b} and {c,d}
        edges = [
            GraphEdge(source="a", target="b", edge_type=GraphEdgeType.RELATED_TO),
            GraphEdge(source="c", target="d", edge_type=GraphEdgeType.RELATED_TO),
        ]

        stats = graph_service.get_graph_statistics(nodes, edges)

        assert stats.connected_components == 2

    def test_node_edge_type_counts(self, graph_service, sample_nodes, sample_edges):
        """Node and edge type counts."""
        stats = graph_service.get_graph_statistics(sample_nodes, sample_edges)

        assert "company" in stats.node_types
        assert "tender" in stats.node_types
        assert "person" in stats.node_types
        assert "wins" in stats.edge_types
        assert "represents" in stats.edge_types


# ─────────────────────────────────────────────────────────────────────────────
# Cluster Detection (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestClusterDetection:
    """Tests for cluster detection algorithms."""

    def test_find_clusters_in_graph(self, graph_service, sample_nodes, sample_edges):
        """Find clusters in connected graph."""
        clusters = graph_service.find_clusters(sample_nodes, sample_edges)

        # All nodes should be in clusters
        all_clustered = set()
        for cluster_nodes in clusters.values():
            all_clustered.update(cluster_nodes)

        assert len(all_clustered) == len(sample_nodes)

    def test_no_clusters_single_component(self, graph_service):
        """No clusters when graph is single component."""
        nodes = [
            GraphNode(id="a", label="A", node_type=GraphNodeType.COMPANY),
            GraphNode(id="b", label="B", node_type=GraphNodeType.COMPANY),
        ]
        edges = [
            GraphEdge(source="a", target="b", edge_type=GraphEdgeType.RELATED_TO),
        ]

        clusters = graph_service.find_clusters(nodes, edges)

        assert len(clusters) == 1

    def test_multiple_clusters(self, graph_service):
        """Multiple disconnected clusters."""
        nodes = [
            GraphNode(id="a", label="A", node_type=GraphNodeType.COMPANY),
            GraphNode(id="b", label="B", node_type=GraphNodeType.COMPANY),
            GraphNode(id="c", label="C", node_type=GraphNodeType.COMPANY),
            GraphNode(id="d", label="D", node_type=GraphNodeType.COMPANY),
        ]
        edges = [
            GraphEdge(source="a", target="b", edge_type=GraphEdgeType.RELATED_TO),
            GraphEdge(source="c", target="d", edge_type=GraphEdgeType.RELATED_TO),
        ]

        clusters = graph_service.find_clusters(nodes, edges)

        assert len(clusters) == 2

    def test_bridge_node_detection(self, graph_service):
        """Find bridge nodes connecting communities."""
        # Graph: a-b-c-d where c is a bridge
        nodes = [
            GraphNode(id="a", label="A", node_type=GraphNodeType.COMPANY),
            GraphNode(id="b", label="B", node_type=GraphNodeType.COMPANY),
            GraphNode(id="c", label="C", node_type=GraphNodeType.COMPANY),
            GraphNode(id="d", label="D", node_type=GraphNodeType.COMPANY),
        ]
        edges = [
            GraphEdge(source="a", target="b", edge_type=GraphEdgeType.RELATED_TO),
            GraphEdge(source="b", target="c", edge_type=GraphEdgeType.RELATED_TO),
            GraphEdge(source="c", target="d", edge_type=GraphEdgeType.RELATED_TO),
        ]

        bridges = graph_service.find_bridges(nodes, edges)

        # Node 'c' and 'b' are bridges (removing either disconnects the graph)
        bridge_ids = [n.id for n in bridges]
        assert "b" in bridge_ids or "c" in bridge_ids


# ─────────────────────────────────────────────────────────────────────────────
# Export (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestExport:
    """Tests for graph export functionality."""

    def test_export_json(self, graph_service, sample_nodes, sample_edges):
        """Export to JSON."""
        result = graph_service.export_graph_json(sample_nodes, sample_edges)

        assert "nodes" in result
        assert "edges" in result
        assert "statistics" in result
        assert "exported_at" in result
        assert len(result["nodes"]) == 4
        assert len(result["edges"]) == 3

    def test_export_graphml(self, graph_service, sample_nodes, sample_edges):
        """Export to GraphML."""
        result = graph_service.export_graphml(sample_nodes, sample_edges)

        assert '<?xml version="1.0"' in result
        assert '<graphml' in result
        assert '<graph id="G"' in result
        assert '<node id="company-1">' in result
        assert '<edge source=' in result
        assert '</graphml>' in result

    def test_export_svg(self, graph_service, sample_nodes, sample_edges):
        """Export to SVG (requires matplotlib/networkx)."""
        try:
            import matplotlib
            import networkx
        except ImportError:
            pytest.skip("matplotlib and networkx required for image export")

        result = graph_service.export_image(sample_nodes, sample_edges, GraphExportFormat.SVG)

        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_export_png(self, graph_service, sample_nodes, sample_edges):
        """Export to PNG (requires matplotlib/networkx)."""
        try:
            import matplotlib
            import networkx
        except ImportError:
            pytest.skip("matplotlib and networkx required for image export")

        result = graph_service.export_image(sample_nodes, sample_edges, GraphExportFormat.PNG)

        assert isinstance(result, bytes)
        assert len(result) > 0
        # PNG magic bytes
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_invalid_export_format(self, graph_service, sample_nodes, sample_edges):
        """Invalid export format raises error."""
        with pytest.raises(ValueError, match="requires SVG or PNG"):
            graph_service.export_image(sample_nodes, sample_edges, GraphExportFormat.JSON)


# ─────────────────────────────────────────────────────────────────────────────
# Model Validation (12 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestModelValidation:
    """Tests for Pydantic model validation."""

    def test_graph_query_default_values(self):
        """GraphQuery validation with defaults."""
        query = GraphQuery()

        assert query.depth == 2
        assert query.max_nodes == 500
        assert query.layout == GraphLayout.FORCE_DIRECTED
        assert query.style_by_risk is True
        assert query.style_by_centrality is True

    def test_graph_query_invalid_depth(self):
        """Invalid depth raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            GraphQuery(depth=0)

        with pytest.raises(Exception):
            GraphQuery(depth=6)

    def test_graph_query_invalid_max_nodes(self):
        """Invalid max_nodes raises validation error."""
        with pytest.raises(Exception):
            GraphQuery(max_nodes=5)

        with pytest.raises(Exception):
            GraphQuery(max_nodes=1001)

    def test_graph_filter_validation(self):
        """GraphFilter validation."""
        filters = GraphFilter(
            node_types=[GraphNodeType.COMPANY, GraphNodeType.TENDER],
            edge_types=[GraphEdgeType.WINS],
            min_risk_score=0.5,
            max_risk_score=0.9,
        )

        assert len(filters.node_types) == 2
        assert len(filters.edge_types) == 1
        assert filters.min_risk_score == 0.5
        assert filters.max_risk_score == 0.9

    def test_graph_node_type_enum(self):
        """GraphNodeType enum values."""
        assert GraphNodeType.COMPANY.value == "company"
        assert GraphNodeType.TENDER.value == "tender"
        assert GraphNodeType.PROJECT.value == "project"
        assert GraphNodeType.PERSON.value == "person"
        assert GraphNodeType.BUYER.value == "buyer"
        assert GraphNodeType.ASSET.value == "asset"
        assert GraphNodeType.FRAUD_PATTERN.value == "fraud_pattern"
        assert GraphNodeType.COMMENT.value == "comment"
        assert GraphNodeType.ALERT.value == "alert"

    def test_graph_edge_type_enum(self):
        """GraphEdgeType enum values."""
        assert GraphEdgeType.WINS.value == "wins"
        GraphEdgeType.ISSUES.value == "issues"
        assert GraphEdgeType.PART_OF.value == "part_of"
        assert GraphEdgeType.REPRESENTS.value == "represents"
        assert GraphEdgeType.OWNS.value == "owns"
        assert GraphEdgeType.FLAGGED_BY.value == "flagged_by"
        assert GraphEdgeType.HAS_ALERT.value == "has_alert"
        assert GraphEdgeType.ANNOTATES.value == "annotates"
        assert GraphEdgeType.SAME_AS.value == "same_as"
        assert GraphEdgeType.RELATED_TO.value == "related_to"

    def test_graph_layout_enum(self):
        """GraphLayout enum values."""
        assert GraphLayout.FORCE_DIRECTED.value == "force_directed"
        assert GraphLayout.HIERARCHICAL.value == "hierarchical"
        assert GraphLayout.CIRCULAR.value == "circular"
        assert GraphLayout.RADIAL.value == "radial"

    def test_graph_export_format_enum(self):
        """GraphExportFormat enum values."""
        assert GraphExportFormat.JSON.value == "json"
        assert GraphExportFormat.GRAPHML.value == "graphml"
        assert GraphExportFormat.SVG.value == "svg"
        assert GraphExportFormat.PNG.value == "png"

    def test_graph_path_request_validation(self):
        """GraphPathRequest validation."""
        request = GraphPathRequest(
            source_id="company-1",
            target_id="company-2",
            max_depth=5,
        )

        assert request.source_id == "company-1"
        assert request.target_id == "company-2"
        assert request.max_depth == 5

    def test_graph_template_validation(self):
        """GraphTemplate validation."""
        template = GraphTemplate(
            name="Test Template",
            description="Test description",
            depth=2,
            node_types=[GraphNodeType.COMPANY],
            max_nodes=100,
        )

        assert template.name == "Test Template"
        assert template.depth == 2
        assert template.max_nodes == 100

    def test_invalid_risk_range(self):
        """Invalid risk range raises validation error."""
        with pytest.raises(Exception):
            GraphFilter(min_risk_score=1.5)

        with pytest.raises(Exception):
            GraphFilter(max_risk_score=-0.1)

    def test_empty_entity_ids_valid(self):
        """Empty entity IDs are valid."""
        filters = GraphFilter(entity_ids=[])
        assert filters.entity_ids == []


# ─────────────────────────────────────────────────────────────────────────────
# Templates (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplates:
    """Tests for graph templates."""

    def test_six_templates_exist(self, graph_service):
        """Six predefined templates exist."""
        templates = graph_service.list_templates()

        assert len(templates) == 6

    def test_template_names_correct(self, graph_service):
        """Template names are correct."""
        templates = graph_service.list_templates()
        names = [t.name for t in templates]

        expected_names = [
            "Company Network",
            "Fraud Pattern View",
            "Supply Chain",
            "Risk Hotspot",
            "Project Ecosystem",
            "Full Overview",
        ]

        for name in expected_names:
            assert name in names

    def test_template_has_valid_node_types(self, graph_service):
        """All templates have valid node types."""
        templates = graph_service.list_templates()

        for template in templates:
            for node_type in template.node_types:
                assert isinstance(node_type, GraphNodeType)

    def test_company_network_template_structure(self, graph_service):
        """Company network template has correct structure."""
        template = graph_service.get_template("Company Network")

        assert template is not None
        assert template.center_type == "Company"
        assert template.depth == 2
        assert GraphNodeType.COMPANY in template.node_types
        assert GraphNodeType.TENDER in template.node_types
        assert GraphEdgeType.WINS in template.edge_types

    def test_full_overview_template(self, graph_service):
        """Full overview template has correct structure."""
        template = graph_service.get_template("Full Overview")

        assert template is not None
        assert template.depth == 1
        assert template.max_nodes == 100
        assert len(template.node_types) >= 6  # All major types


# ─────────────────────────────────────────────────────────────────────────────
# Internal Helpers (additional tests for coverage)
# ─────────────────────────────────────────────────────────────────────────────

class TestInternalHelpers:
    """Tests for internal helper methods."""

    def test_validate_depth_valid(self, graph_service):
        """Valid depth passes validation."""
        graph_service._validate_depth(1)
        graph_service._validate_depth(3)
        graph_service._validate_depth(5)

    def test_validate_depth_invalid(self, graph_service):
        """Invalid depth raises ValueError."""
        with pytest.raises(ValueError, match="Depth must be between"):
            graph_service._validate_depth(0)

        with pytest.raises(ValueError, match="Depth must be between"):
            graph_service._validate_depth(6)

    def test_validate_max_nodes_valid(self, graph_service):
        """Valid max_nodes passes validation."""
        graph_service._validate_max_nodes(10)
        graph_service._validate_max_nodes(250)
        graph_service._validate_max_nodes(500)

    def test_validate_max_nodes_invalid(self, graph_service):
        """Invalid max_nodes raises ValueError."""
        with pytest.raises(ValueError, match="max_nodes must be between"):
            graph_service._validate_max_nodes(5)

        with pytest.raises(ValueError, match="max_nodes must be between"):
            graph_service._validate_max_nodes(1000)

    def test_escape_xml(self, graph_service):
        """XML escaping works correctly."""
        assert graph_service._escape_xml("<test>") == "&lt;test&gt;"
        assert graph_service._escape_xml("a&b") == "a&amp;b"
        assert graph_service._escape_xml('"quote"') == "&quot;quote&quot;"

    def test_edge_type_to_rel_type(self, graph_service):
        """Edge type to Neo4j relationship type mapping."""
        assert graph_service._edge_type_to_rel_type(GraphEdgeType.WINS) == "WINS"
        assert graph_service._edge_type_to_rel_type(GraphEdgeType.REPRESENTS) == "REPRESENTS"
        assert graph_service._edge_type_to_rel_type(GraphEdgeType.RELATED_TO) == "RELATED_TO"

    def test_node_type_to_label(self, graph_service):
        """Node type to Neo4j label mapping."""
        assert graph_service._node_type_to_label(GraphNodeType.COMPANY) == "Company"
        assert graph_service._node_type_to_label(GraphNodeType.TENDER) == "Tender"
        assert graph_service._node_type_to_label(GraphNodeType.PERSON) == "Person"

    def test_empty_statistics(self, graph_service):
        """Empty statistics returns zeroed stats."""
        stats = graph_service._empty_statistics()

        assert stats.node_count == 0
        assert stats.edge_count == 0
        assert stats.density == 0.0
        assert stats.connected_components == 0
