"""
Graph Visualization Service for Paladino.

Provides interactive network graph exploration allowing analysts to:
- Visually explore entity relationships
- Filter by type, risk score, date range
- Expand nodes to see deeper connections
- Find paths between entities
- Export visualizations as images or data
- Use predefined graph templates for common views

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.app.graph_service import GraphService
    from paladino.db import Neo4jConnection

    conn = Neo4jConnection()
    service = GraphService(conn)

    # Get subgraph around an entity
    graph = service.get_entity_graph("company-uuid-123", depth=2)

    # Find shortest path
    path = service.get_path_between("company-a", "company-b")

    # Export as GraphML
    graphml = service.export_graphml(graph)

    # Apply template
    template_graph = service.apply_template("Company Network", "company-uuid")
"""

from __future__ import annotations

import hashlib
import io
import math
import random
import time
from collections import defaultdict, deque
from datetime import datetime, UTC
from typing import Any

from loguru import logger

from paladino.db import Neo4jConnection
from paladino.models import (
    GraphEdge,
    GraphEdgeType,
    GraphExportFormat,
    GraphFilter,
    GraphLayout,
    GraphNode,
    GraphNodeType,
    GraphPathRequest,
    GraphPathResponse,
    GraphQuery,
    GraphResponse,
    GraphStatistics,
    GraphStyleRequest,
    GraphTemplate,
)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MAX_DEPTH = 5
MAX_NODES = 500
MAX_PATH_DEPTH = 10

# Node type → color mapping
NODE_TYPE_COLORS: dict[str, str] = {
    GraphNodeType.COMPANY: "#3B82F6",       # Blue
    GraphNodeType.TENDER: "#10B981",         # Green
    GraphNodeType.PROJECT: "#8B5CF6",        # Purple
    GraphNodeType.PERSON: "#F59E0B",         # Amber
    GraphNodeType.BUYER: "#EF4444",          # Red
    GraphNodeType.ASSET: "#06B6D4",          # Cyan
    GraphNodeType.FRAUD_PATTERN: "#DC2626",  # Dark red
    GraphNodeType.COMMENT: "#6B7280",        # Gray
    GraphNodeType.ALERT: "#F97316",          # Orange
}

# Edge type → color mapping
EDGE_TYPE_COLORS: dict[str, str] = {
    GraphEdgeType.WINS: "#10B981",
    GraphEdgeType.ISSUES: "#3B82F6",
    GraphEdgeType.PART_OF: "#8B5CF6",
    GraphEdgeType.REPRESENTS: "#F59E0B",
    GraphEdgeType.OWNS: "#EF4444",
    GraphEdgeType.FLAGGED_BY: "#DC2626",
    GraphEdgeType.HAS_ALERT: "#F97316",
    GraphEdgeType.ANNOTATES: "#6B7280",
    GraphEdgeType.SAME_AS: "#06B6D4",
    GraphEdgeType.RELATED_TO: "#9CA3AF",
}

# Neo4j label → GraphNodeType mapping
NEO4J_LABEL_TO_GRAPH_TYPE: dict[str, GraphNodeType] = {
    "Company": GraphNodeType.COMPANY,
    "Tender": GraphNodeType.TENDER,
    "Project": GraphNodeType.PROJECT,
    "Person": GraphNodeType.PERSON,
    "Buyer": GraphNodeType.BUYER,
    "Asset": GraphNodeType.ASSET,
    "FraudPattern": GraphNodeType.FRAUD_PATTERN,
    "Comment": GraphNodeType.COMMENT,
    "Alert": GraphNodeType.ALERT,
}

# Neo4j relationship type → GraphEdgeType mapping
NEO4J_REL_TO_EDGE_TYPE: dict[str, GraphEdgeType] = {
    "WINS": GraphEdgeType.WINS,
    "ISSUES": GraphEdgeType.ISSUES,
    "PART_OF": GraphEdgeType.PART_OF,
    "REPRESENTS": GraphEdgeType.REPRESENTS,
    "OWNS": GraphEdgeType.OWNS,
    "FLAGGED_BY": GraphEdgeType.FLAGGED_BY,
    "HAS_ALERT": GraphEdgeType.HAS_ALERT,
    "ANNOTATES": GraphEdgeType.ANNOTATES,
    "SAME_AS": GraphEdgeType.SAME_AS,
    "RELATED_TO": GraphEdgeType.RELATED_TO,
}

# Predefined graph templates
GRAPH_TEMPLATES: list[GraphTemplate] = [
    GraphTemplate(
        name="Company Network",
        description="Company + tenders + buyers + related companies",
        center_type="Company",
        depth=2,
        node_types=[
            GraphNodeType.COMPANY,
            GraphNodeType.TENDER,
            GraphNodeType.BUYER,
            GraphNodeType.PERSON,
        ],
        edge_types=[
            GraphEdgeType.WINS,
            GraphEdgeType.ISSUES,
            GraphEdgeType.REPRESENTS,
        ],
        style_by_risk=True,
        max_nodes=500,
    ),
    GraphTemplate(
        name="Fraud Pattern View",
        description="Entities flagged by fraud patterns + connections",
        center_type=None,
        depth=2,
        node_types=[
            GraphNodeType.COMPANY,
            GraphNodeType.FRAUD_PATTERN,
            GraphNodeType.PERSON,
        ],
        edge_types=[
            GraphEdgeType.FLAGGED_BY,
            GraphEdgeType.REPRESENTS,
        ],
        style_by_risk=True,
        max_nodes=500,
    ),
    GraphTemplate(
        name="Supply Chain",
        description="Upstream/downstream relationships",
        center_type="Company",
        depth=3,
        node_types=[
            GraphNodeType.COMPANY,
            GraphNodeType.TENDER,
        ],
        edge_types=[
            GraphEdgeType.WINS,
            GraphEdgeType.RELATED_TO,
        ],
        style_by_risk=True,
        max_nodes=500,
    ),
    GraphTemplate(
        name="Risk Hotspot",
        description="High-risk entities + their relationships",
        center_type=None,
        depth=2,
        node_types=[
            GraphNodeType.COMPANY,
            GraphNodeType.PERSON,
            GraphNodeType.BUYER,
        ],
        edge_types=[
            GraphEdgeType.WINS,
            GraphEdgeType.ISSUES,
            GraphEdgeType.REPRESENTS,
            GraphEdgeType.OWNS,
            GraphEdgeType.FLAGGED_BY,
        ],
        style_by_risk=True,
        max_nodes=500,
    ),
    GraphTemplate(
        name="Project Ecosystem",
        description="Project + linked tenders + companies + funding",
        center_type="Project",
        depth=2,
        node_types=[
            GraphNodeType.PROJECT,
            GraphNodeType.TENDER,
            GraphNodeType.COMPANY,
        ],
        edge_types=[
            GraphEdgeType.PART_OF,
            GraphEdgeType.WINS,
        ],
        style_by_risk=True,
        max_nodes=500,
    ),
    GraphTemplate(
        name="Full Overview",
        description="Top 100 entities by centrality (sampled)",
        center_type=None,
        depth=1,
        node_types=[
            GraphNodeType.COMPANY,
            GraphNodeType.TENDER,
            GraphNodeType.PROJECT,
            GraphNodeType.PERSON,
            GraphNodeType.BUYER,
            GraphNodeType.ASSET,
        ],
        edge_types=[
            GraphEdgeType.WINS,
            GraphEdgeType.ISSUES,
            GraphEdgeType.PART_OF,
            GraphEdgeType.REPRESENTS,
            GraphEdgeType.OWNS,
            GraphEdgeType.RELATED_TO,
        ],
        style_by_risk=True,
        max_nodes=100,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class GraphService:
    """
    Service layer for graph visualization operations.

    Handles graph queries, layout algorithms, styling, analysis,
    export, and template management.
    """

    def __init__(self, conn: Neo4jConnection) -> None:
        self.conn = conn

    # ── Graph Queries ───────────────────────────────────────────────────────

    def get_entity_graph(
        self,
        entity_id: str,
        depth: int = 2,
        max_nodes: int = MAX_NODES,
        filters: GraphFilter | None = None,
        layout: GraphLayout = GraphLayout.FORCE_DIRECTED,
        style_by_risk: bool = True,
        style_by_centrality: bool = True,
    ) -> GraphResponse:
        """
        Get subgraph around an entity with configurable depth.

        Parameters
        ----------
        entity_id:
            ID of the center entity.
        depth:
            Traversal depth (1-5).
        max_nodes:
            Maximum nodes to return (10-500).
        filters:
            Optional filter criteria.
        layout:
            Layout algorithm to apply.
        style_by_risk:
            Color nodes by risk score.
        style_by_centrality:
            Size nodes by centrality.

        Returns
        -------
        GraphResponse with nodes, edges, and statistics.
        """
        self._validate_depth(depth)
        self._validate_max_nodes(max_nodes)

        start_time = time.time()
        filters = filters or GraphFilter()

        cypher, params = self._build_cypher(
            center_entity_id=entity_id,
            depth=depth,
            max_nodes=max_nodes,
            filters=filters,
        )

        result = self.conn.run_query(cypher, params)
        query_time_ms = (time.time() - start_time) * 1000

        if not result:
            return GraphResponse(
                nodes=[],
                edges=[],
                statistics=GraphStatistics(
                    node_count=0,
                    edge_count=0,
                    density=0.0,
                    avg_degree=0.0,
                    max_degree=0,
                    connected_components=0,
                    avg_clustering=0.0,
                ),
                layout=layout,
                query_time_ms=round(query_time_ms, 2),
                truncated=False,
                center_entity_id=entity_id,
            )

        nodes, edges = self._transform_to_graph(result, filters)
        truncated = len(nodes) >= max_nodes

        # Apply styling
        if style_by_risk:
            nodes = self._style_by_risk(nodes)
        if style_by_centrality:
            nodes = self._style_by_centrality(nodes, edges)

        # Apply layout
        nodes = self.apply_layout(nodes, edges, layout)

        # Calculate statistics
        stats = self._calculate_statistics(nodes, edges)

        logger.info(
            f"Entity graph for {entity_id}: {len(nodes)} nodes, {len(edges)} edges "
            f"(depth={depth}, {query_time_ms:.0f}ms)"
        )

        return GraphResponse(
            nodes=nodes,
            edges=edges,
            statistics=stats,
            layout=layout,
            query_time_ms=round(query_time_ms, 2),
            truncated=truncated,
            center_entity_id=entity_id,
        )

    def get_filtered_graph(
        self,
        filters: GraphFilter,
        max_nodes: int = MAX_NODES,
        layout: GraphLayout = GraphLayout.FORCE_DIRECTED,
        style_by_risk: bool = True,
        style_by_centrality: bool = True,
    ) -> GraphResponse:
        """
        Get graph with applied filters (type, risk, date).

        Parameters
        ----------
        filters:
            Filter criteria.
        max_nodes:
            Maximum nodes to return.
        layout:
            Layout algorithm.
        style_by_risk:
            Color nodes by risk score.
        style_by_centrality:
            Size nodes by centrality.

        Returns
        -------
        GraphResponse with filtered graph.
        """
        self._validate_max_nodes(max_nodes)

        start_time = time.time()

        cypher, params = self._build_filtered_cypher(filters, max_nodes)
        result = self.conn.run_query(cypher, params)
        query_time_ms = (time.time() - start_time) * 1000

        if not result:
            return GraphResponse(
                nodes=[],
                edges=[],
                statistics=GraphStatistics(
                    node_count=0,
                    edge_count=0,
                    density=0.0,
                    avg_degree=0.0,
                    max_degree=0,
                    connected_components=0,
                    avg_clustering=0.0,
                ),
                layout=layout,
                query_time_ms=round(query_time_ms, 2),
                truncated=False,
            )

        nodes, edges = self._transform_to_graph(result, filters)
        truncated = len(nodes) >= max_nodes

        if style_by_risk:
            nodes = self._style_by_risk(nodes)
        if style_by_centrality:
            nodes = self._style_by_centrality(nodes, edges)

        nodes = self.apply_layout(nodes, edges, layout)
        stats = self._calculate_statistics(nodes, edges)

        logger.info(
            f"Filtered graph: {len(nodes)} nodes, {len(edges)} edges ({query_time_ms:.0f}ms)"
        )

        return GraphResponse(
            nodes=nodes,
            edges=edges,
            statistics=stats,
            layout=layout,
            query_time_ms=round(query_time_ms, 2),
            truncated=truncated,
        )

    def get_path_between(
        self,
        request: GraphPathRequest,
    ) -> GraphPathResponse:
        """
        Find shortest path between two entities.

        Parameters
        ----------
        request:
            GraphPathRequest with source, target, and constraints.

        Returns
        -------
        GraphPathResponse with path nodes and edges.
        """
        if request.source_id == request.target_id:
            return GraphPathResponse(
                path=[],
                edges=[],
                length=0,
                found=False,
            )

        start_time = time.time()

        # Build edge type constraint
        edge_type_filter = ""
        if request.edge_types:
            rel_types = [self._edge_type_to_rel_type(et) for et in request.edge_types]
            edge_type_filter = f"| r.type IN {rel_types}"

        cypher = f"""
        MATCH path = shortestPath(
            (source {{id: $source_id}})-[*1..{request.max_depth}]-(target {{id: $target_id}})
        )
        WHERE source.id IS NOT NULL AND target.id IS NOT NULL
        {edge_type_filter}
        RETURN path
        LIMIT 1
        """

        params = {
            "source_id": request.source_id,
            "target_id": request.target_id,
        }

        result = self.conn.run_query(cypher, params)
        query_time_ms = (time.time() - start_time) * 1000

        if not result or not result[0].get("path"):
            logger.info(
                f"No path found between {request.source_id} and {request.target_id}"
            )
            return GraphPathResponse(
                path=[],
                edges=[],
                length=0,
                found=False,
            )

        # Parse path
        path_data = result[0]["path"]
        nodes, edges = self._parse_path_to_graph(path_data)

        logger.info(
            f"Path found: {len(nodes)} nodes, {len(edges)} edges ({query_time_ms:.0f}ms)"
        )

        return GraphPathResponse(
            path=nodes,
            edges=edges,
            length=len(edges),
            found=True,
        )

    def get_neighbors(
        self,
        entity_id: str,
        edge_types: list[GraphEdgeType] | None = None,
    ) -> GraphResponse:
        """
        Get 1-hop neighbors of an entity.

        Parameters
        ----------
        entity_id:
            Center entity ID.
        edge_types:
            Optional filter on relationship types.

        Returns
        -------
        GraphResponse with center node and its neighbors.
        """
        start_time = time.time()

        rel_type_filter = ""
        params: dict[str, Any] = {"entity_id": entity_id}

        if edge_types:
            rel_types = [self._edge_type_to_rel_type(et) for et in edge_types]
            rel_type_filter = f"| r.type IN {rel_types}"

        cypher = f"""
        MATCH (center {{id: $entity_id}})
        MATCH (center)-[r]-(neighbor)
        WHERE neighbor.id IS NOT NULL
        {rel_type_filter}
        RETURN
            center.id AS center_id,
            center,
            r,
            neighbor
        """

        result = self.conn.run_query(cypher, params)
        query_time_ms = (time.time() - start_time) * 1000

        if not result:
            # Return just the center node if no neighbors
            center_query = """
            MATCH (n {id: $entity_id})
            RETURN n
            LIMIT 1
            """
            center_result = self.conn.run_query(center_query, params)
            if not center_result:
                return GraphResponse(
                    nodes=[],
                    edges=[],
                    statistics=self._empty_statistics(),
                    layout=GraphLayout.FORCE_DIRECTED,
                    query_time_ms=round(query_time_ms, 2),
                    center_entity_id=entity_id,
                )

            center_node = self._record_to_node(center_result[0]["n"])
            return GraphResponse(
                nodes=[center_node],
                edges=[],
                statistics=GraphStatistics(
                    node_count=1,
                    edge_count=0,
                    density=0.0,
                    avg_degree=0.0,
                    max_degree=0,
                    connected_components=1,
                    avg_clustering=0.0,
                    node_types={center_node.node_type.value: 1},
                    edge_types={},
                ),
                layout=GraphLayout.FORCE_DIRECTED,
                query_time_ms=round(query_time_ms, 2),
                center_entity_id=entity_id,
            )

        nodes_dict: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        for row in result:
            center_rec = row["center"]
            neighbor_rec = row["neighbor"]
            rel_rec = row["r"]

            # Add center
            center_id = center_rec.get("id", "")
            if center_id not in nodes_dict:
                nodes_dict[center_id] = self._record_to_node(center_rec)

            # Add neighbor
            neighbor_id = neighbor_rec.get("id", "")
            if neighbor_id not in nodes_dict:
                nodes_dict[neighbor_id] = self._record_to_node(neighbor_rec)

            # Add edge
            edge = self._record_to_edge(rel_rec, center_id, neighbor_id)
            edges.append(edge)

        nodes = list(nodes_dict.values())
        nodes = self._style_by_risk(nodes)
        nodes = self._style_by_centrality(nodes, edges)
        nodes = self.apply_layout(nodes, edges, GraphLayout.RADIAL)

        stats = self._calculate_statistics(nodes, edges)

        return GraphResponse(
            nodes=nodes,
            edges=edges,
            statistics=stats,
            layout=GraphLayout.RADIAL,
            query_time_ms=round(query_time_ms, 2),
            center_entity_id=entity_id,
        )

    def get_community_graph(
        self,
        community_id: str,
        max_nodes: int = MAX_NODES,
        layout: GraphLayout = GraphLayout.FORCE_DIRECTED,
    ) -> GraphResponse:
        """
        Get graph for a Louvain community.

        Parameters
        ----------
        community_id:
            Community identifier.
        max_nodes:
            Maximum nodes to return.
        layout:
            Layout algorithm.

        Returns
        -------
        GraphResponse with community subgraph.
        """
        self._validate_max_nodes(max_nodes)

        start_time = time.time()

        cypher = """
        MATCH (n {community_id: $community_id})
        WITH n LIMIT $max_nodes
        MATCH (n)-[r]-(m {community_id: $community_id})
        RETURN n, r, m
        """

        params = {
            "community_id": community_id,
            "max_nodes": max_nodes,
        }

        result = self.conn.run_query(cypher, params)
        query_time_ms = (time.time() - start_time) * 1000

        if not result:
            return GraphResponse(
                nodes=[],
                edges=[],
                statistics=self._empty_statistics(),
                layout=layout,
                query_time_ms=round(query_time_ms, 2),
            )

        nodes_dict: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        for row in result:
            n_rec = row["n"]
            m_rec = row["m"]
            r_rec = row["r"]

            n_id = n_rec.get("id", "")
            m_id = m_rec.get("id", "")

            if n_id not in nodes_dict:
                nodes_dict[n_id] = self._record_to_node(n_rec)
            if m_id not in nodes_dict:
                nodes_dict[m_id] = self._record_to_node(m_rec)

            edges.append(self._record_to_edge(r_rec, n_id, m_id))

        nodes = list(nodes_dict.values())
        nodes = self._style_by_risk(nodes)
        nodes = self._style_by_centrality(nodes, edges)
        nodes = self.apply_layout(nodes, edges, layout)

        stats = self._calculate_statistics(nodes, edges)

        return GraphResponse(
            nodes=nodes,
            edges=edges,
            statistics=stats,
            layout=layout,
            query_time_ms=round(query_time_ms, 2),
        )

    # ── Layout Algorithms ───────────────────────────────────────────────────

    def apply_layout(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        layout: GraphLayout,
    ) -> list[GraphNode]:
        """
        Calculate node positions using the specified layout algorithm.

        Parameters
        ----------
        nodes:
            List of graph nodes.
        edges:
            List of graph edges.
        layout:
            Layout algorithm to use.

        Returns
        -------
        Nodes with x,y coordinates set.
        """
        if not nodes:
            return nodes

        try:
            if layout == GraphLayout.FORCE_DIRECTED:
                return self._calculate_force_directed(nodes, edges)
            elif layout == GraphLayout.RADIAL:
                return self._calculate_radial(nodes, edges)
            elif layout == GraphLayout.HIERARCHICAL:
                return self._calculate_hierarchical(nodes, edges)
            elif layout == GraphLayout.CIRCULAR:
                return self._calculate_circular(nodes)
        except Exception as e:
            logger.warning(f"Layout {layout.value} failed, using fallback: {e}")

        # Fallback: simple grid
        return self._calculate_grid(nodes)

    def _calculate_force_directed(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        iterations: int = 50,
    ) -> list[GraphNode]:
        """
        Simple force-directed layout approximation.

        Uses repulsion between all nodes and attraction along edges.
        """
        if len(nodes) <= 1:
            nodes[0].x = 0.0
            nodes[0].y = 0.0
            return nodes

        node_ids = [n.id for n in nodes]
        node_map = {n.id: i for i, n in enumerate(nodes)}

        # Initialize positions randomly
        positions = [(random.uniform(-100, 100), random.uniform(-100, 100)) for _ in nodes]

        # Build adjacency
        adjacency: dict[int, list[int]] = defaultdict(list)
        for edge in edges:
            if edge.source in node_map and edge.target in node_map:
                src_idx = node_map[edge.source]
                tgt_idx = node_map[edge.target]
                adjacency[src_idx].append(tgt_idx)
                adjacency[tgt_idx].append(src_idx)

        k = math.sqrt(10000.0 / len(nodes))  # Ideal spring length

        for _ in range(iterations):
            forces = [(0.0, 0.0)] * len(nodes)

            # Repulsion (all pairs)
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    dx = positions[i][0] - positions[j][0]
                    dy = positions[i][1] - positions[j][1]
                    dist_sq = dx * dx + dy * dy + 0.01  # Avoid division by zero
                    dist = math.sqrt(dist_sq)
                    rep_force = (k * k) / dist

                    fx = (dx / dist) * rep_force
                    fy = (dy / dist) * rep_force

                    fx_i, fy_i = forces[i]
                    forces[i] = (fx_i + fx, fy_i + fy)

                    fx_j, fy_j = forces[j]
                    forces[j] = (fx_j - fx, fy_j - fy)

            # Attraction (edges)
            for i in range(len(nodes)):
                for j in adjacency[i]:
                    if j <= i:
                        continue
                    dx = positions[j][0] - positions[i][0]
                    dy = positions[j][1] - positions[i][1]
                    dist = math.sqrt(dx * dx + dy * dy) + 0.01
                    att_force = (dist * dist) / k

                    fx = (dx / dist) * att_force
                    fy = (dy / dist) * att_force

                    fx_i, fy_i = forces[i]
                    forces[i] = (fx_i + fx, fy_i + fy)

                    fx_j, fy_j = forces[j]
                    forces[j] = (fx_j - fx, fy_j - fy)

            # Apply forces with cooling
            temperature = 0.1 * (1 - _ / iterations)
            new_positions = []
            for i, (px, py) in enumerate(positions):
                fx, fy = forces[i]
                # Clamp force
                max_force = 10.0
                fx = max(-max_force, min(max_force, fx))
                fy = max(-max_force, min(max_force, fy))

                new_x = px + fx * temperature
                new_y = py + fy * temperature
                new_positions.append((new_x, new_y))

            positions = new_positions

        # Normalize to 0-1000 range
        min_x = min(p[0] for p in positions)
        max_x = max(p[0] for p in positions)
        min_y = min(p[1] for p in positions)
        max_y = max(p[1] for p in positions)

        range_x = max_x - min_x or 1
        range_y = max_y - min_y or 1

        for i, node in enumerate(nodes):
            node.x = round(((positions[i][0] - min_x) / range_x) * 1000, 2)
            node.y = round(((positions[i][1] - min_y) / range_y) * 1000, 2)

        return nodes

    def _calculate_radial(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> list[GraphNode]:
        """
        Radial layout from center node.

        Center node at origin, neighbors in concentric circles.
        """
        if not nodes:
            return nodes

        # Find center node (first node or node with most connections)
        degree_count: dict[str, int] = defaultdict(int)
        for edge in edges:
            degree_count[edge.source] += 1
            degree_count[edge.target] += 1

        center_id = nodes[0].id
        if degree_count:
            center_id = max(degree_count, key=degree_count.get)

        # BFS to find distances from center
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            adjacency[edge.source].append(edge.target)
            adjacency[edge.target].append(edge.source)

        distances: dict[str, int] = {center_id: 0}
        queue = deque([center_id])

        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor not in distances:
                    distances[neighbor] = distances[current] + 1
                    queue.append(neighbor)

        # Group by distance
        by_distance: dict[int, list[str]] = defaultdict(list)
        for node_id, dist in distances.items():
            by_distance[dist].append(node_id)

        # Place nodes
        node_map = {n.id: n for n in nodes}
        center_node = node_map.get(center_id)
        if center_node:
            center_node.x = 500.0
            center_node.y = 500.0

        for dist, node_ids in by_distance.items():
            if dist == 0:
                continue

            radius = dist * 200
            count = len(node_ids)

            for i, node_id in enumerate(node_ids):
                angle = (2 * math.pi * i / count) - (math.pi / 2)
                node = node_map.get(node_id)
                if node:
                    node.x = round(500 + radius * math.cos(angle), 2)
                    node.y = round(500 + radius * math.sin(angle), 2)

        # Handle nodes not reached by BFS
        for node in nodes:
            if node.x is None:
                node.x = random.uniform(0, 1000)
                node.y = random.uniform(0, 1000)

        return nodes

    def _calculate_hierarchical(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> list[GraphNode]:
        """
        Hierarchical (layered) layout.

        Uses topological sorting to assign layers.
        """
        if not nodes:
            return nodes

        # Build adjacency and in-degree
        adjacency: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {n.id: 0 for n in nodes}

        for edge in edges:
            adjacency[edge.source].append(edge.target)
            if edge.target in in_degree:
                in_degree[edge.target] += 1

        # Kahn's algorithm for topological sort with layer assignment
        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        layers: dict[str, int] = {}

        while queue:
            current = queue.popleft()
            if current not in layers:
                layers[current] = 0

            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                layers[neighbor] = max(layers.get(neighbor, 0), layers[current] + 1)
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Handle cycles: assign remaining nodes to layer 0
        for node in nodes:
            if node.id not in layers:
                layers[node.id] = 0

        # Group by layer
        by_layer: dict[int, list[str]] = defaultdict(list)
        for node_id, layer in layers.items():
            by_layer[layer].append(node_id)

        # Place nodes
        node_map = {n.id: n for n in nodes}
        max_layer = max(by_layer.keys()) if by_layer else 0

        for layer, node_ids in by_layer.items():
            y = (layer / max(max_layer, 1)) * 800 + 100
            count = len(node_ids)

            for i, node_id in enumerate(node_ids):
                x = (i / max(count - 1, 1)) * 800 + 100
                node = node_map.get(node_id)
                if node:
                    node.x = round(x, 2)
                    node.y = round(y, 2)

        return nodes

    def _calculate_circular(self, nodes: list[GraphNode]) -> list[GraphNode]:
        """
        Circular layout with nodes on a circle.
        """
        if not nodes:
            return nodes

        count = len(nodes)
        radius = 400
        center_x, center_y = 500, 500

        for i, node in enumerate(nodes):
            angle = (2 * math.pi * i / count) - (math.pi / 2)
            node.x = round(center_x + radius * math.cos(angle), 2)
            node.y = round(center_y + radius * math.sin(angle), 2)

        return nodes

    def _calculate_grid(self, nodes: list[GraphNode]) -> list[GraphNode]:
        """
        Fallback grid layout.
        """
        count = len(nodes)
        cols = math.ceil(math.sqrt(count))
        rows = math.ceil(count / cols)

        spacing_x = 1000 / max(cols, 1)
        spacing_y = 1000 / max(rows, 1)

        for i, node in enumerate(nodes):
            col = i % cols
            row = i // cols
            node.x = round(col * spacing_x + spacing_x / 2, 2)
            node.y = round(row * spacing_y + spacing_y / 2, 2)

        return nodes

    # ── Styling ─────────────────────────────────────────────────────────────

    def _style_by_risk(self, nodes: list[GraphNode]) -> list[GraphNode]:
        """
        Color nodes by risk score: green (0) → yellow (0.5) → red (1.0).
        """
        for node in nodes:
            if node.risk_score is not None:
                score = node.risk_score
                # Interpolate: green (0, 255, 0) → yellow (255, 255, 0) → red (255, 0, 0)
                if score <= 0.5:
                    # Green to yellow
                    r = int(score * 2 * 255)
                    g = 255
                else:
                    # Yellow to red
                    r = 255
                    g = int((1 - score) * 2 * 255)

                node.color = f"#{r:02x}{g:02x}00"
            else:
                # Default color by type
                node.color = NODE_TYPE_COLORS.get(node.node_type, "#666666")

        return nodes

    def _style_by_centrality(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> list[GraphNode]:
        """
        Size nodes by centrality (degree-based if not available).
        """
        # Calculate degree centrality if not set
        degree: dict[str, int] = defaultdict(int)
        for edge in edges:
            degree[edge.source] += 1
            degree[edge.target] += 1

        max_degree = max(degree.values()) if degree else 1

        for node in nodes:
            if node.centrality is not None:
                # Use existing centrality
                node.size = round(10 + node.centrality * 80, 1)
            else:
                # Calculate from degree
                node_degree = degree.get(node.id, 0)
                centrality = node_degree / max(max_degree, 1)
                node.centrality = round(centrality, 4)
                node.size = round(10 + centrality * 80, 1)

        return nodes

    def style_by_type(self, nodes: list[GraphNode]) -> list[GraphNode]:
        """
        Shape/color nodes by type.
        """
        for node in nodes:
            node.color = NODE_TYPE_COLORS.get(node.node_type, "#666666")

        return nodes

    def apply_style(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        style_request: GraphStyleRequest,
    ) -> GraphResponse:
        """
        Apply styling rules to existing graph data.

        Parameters
        ----------
        nodes:
            List of graph nodes.
        edges:
            List of graph edges.
        style_request:
            Styling options.

        Returns
        -------
        GraphResponse with styled nodes and edges.
        """
        start_time = time.time()

        if style_request.style_by_risk:
            nodes = self._style_by_risk(nodes)

        if style_request.style_by_centrality:
            nodes = self._style_by_centrality(nodes, edges)

        if style_request.style_by_type:
            nodes = self.style_by_type(nodes)

        nodes = self.apply_layout(nodes, edges, style_request.layout)
        stats = self._calculate_statistics(nodes, edges)

        return GraphResponse(
            nodes=nodes,
            edges=edges,
            statistics=stats,
            layout=style_request.layout,
            query_time_ms=round((time.time() - start_time) * 1000, 2),
        )

    # ── Analysis ────────────────────────────────────────────────────────────

    def get_graph_statistics(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> GraphStatistics:
        """
        Calculate graph statistics.

        Parameters
        ----------
        nodes:
            List of graph nodes.
        edges:
            List of graph edges.

        Returns
        -------
        GraphStatistics with node/edge counts, density, etc.
        """
        return self._calculate_statistics(nodes, edges)

    def find_clusters(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> dict[str, list[str]]:
        """
        Detect communities in subgraph using connected components.

        Parameters
        ----------
        nodes:
            List of graph nodes.
        edges:
            List of graph edges.

        Returns
        -------
        Dictionary mapping cluster_id to list of node IDs.
        """
        if not nodes:
            return {}

        # Build adjacency
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)

        # Find connected components using BFS
        visited: set[str] = set()
        clusters: dict[str, list[str]] = {}
        cluster_id = 0

        for node in nodes:
            if node.id not in visited:
                cluster_nodes: list[str] = []
                queue = deque([node.id])
                visited.add(node.id)

                while queue:
                    current = queue.popleft()
                    cluster_nodes.append(current)

                    for neighbor in adjacency[current]:
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)

                clusters[f"cluster_{cluster_id}"] = cluster_nodes
                cluster_id += 1

        return clusters

    def find_hubs(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        top_n: int = 10,
    ) -> list[GraphNode]:
        """
        Find high-centrality (hub) nodes.

        Parameters
        ----------
        nodes:
            List of graph nodes.
        edges:
            List of graph edges.
        top_n:
            Number of top hubs to return.

        Returns
        -------
        Top N nodes by degree centrality.
        """
        degree: dict[str, int] = defaultdict(int)
        for edge in edges:
            degree[edge.source] += 1
            degree[edge.target] += 1

        # Sort by degree
        sorted_nodes = sorted(nodes, key=lambda n: degree.get(n.id, 0), reverse=True)
        return sorted_nodes[:top_n]

    def find_bridges(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> list[GraphNode]:
        """
        Find bridge nodes connecting communities.

        Bridge nodes are those whose removal would increase the number
        of connected components.
        """
        if not nodes or not edges:
            return []

        # Build adjacency
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)

        # Count original components
        original_components = self._count_components(adjacency, [n.id for n in nodes])

        bridge_nodes: list[GraphNode] = []

        for node in nodes:
            # Remove node and count components
            reduced_adj = {
                k: v - {node.id} for k, v in adjacency.items() if k != node.id
            }
            reduced_nodes = [n.id for n in nodes if n.id != node.id]
            new_components = self._count_components(reduced_adj, reduced_nodes)

            if new_components > original_components:
                bridge_nodes.append(node)

        return bridge_nodes

    def _count_components(
        self,
        adjacency: dict[str, set[str]],
        node_ids: list[str],
    ) -> int:
        """Count connected components in a graph."""
        visited: set[str] = set()
        components = 0

        for node_id in node_ids:
            if node_id not in visited:
                components += 1
                queue = deque([node_id])
                visited.add(node_id)

                while queue:
                    current = queue.popleft()
                    for neighbor in adjacency.get(current, set()):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)

        return components

    # ── Templates ───────────────────────────────────────────────────────────

    def list_templates(self) -> list[GraphTemplate]:
        """
        List predefined graph templates.

        Returns
        -------
        List of GraphTemplate.
        """
        return GRAPH_TEMPLATES.copy()

    def get_template(self, name: str) -> GraphTemplate | None:
        """
        Get specific template by name.

        Parameters
        ----------
        name:
            Template name.

        Returns
        -------
        GraphTemplate if found, None otherwise.
        """
        for template in GRAPH_TEMPLATES:
            if template.name == name:
                return template
        return None

    def apply_template(
        self,
        template_name: str,
        center_entity_id: str | None = None,
    ) -> GraphResponse:
        """
        Get graph using template settings.

        Parameters
        ----------
        template_name:
            Name of the template to apply.
        center_entity_id:
            Optional center entity ID.

        Returns
        -------
        GraphResponse with template-applied graph.

        Raises
        ------
        ValueError if template not found.
        """
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")

        filters = GraphFilter(
            node_types=template.node_types,
            edge_types=template.edge_types,
        )

        if center_entity_id:
            return self.get_entity_graph(
                entity_id=center_entity_id,
                depth=template.depth,
                max_nodes=template.max_nodes,
                filters=filters,
                style_by_risk=template.style_by_risk,
            )
        else:
            return self.get_filtered_graph(
                filters=filters,
                max_nodes=template.max_nodes,
                style_by_risk=template.style_by_risk,
            )

    # ── Export ──────────────────────────────────────────────────────────────

    def export_graph_json(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> dict:
        """
        Export graph as JSON.

        Parameters
        ----------
        nodes:
            List of graph nodes.
        edges:
            List of graph edges.

        Returns
        -------
        Dictionary suitable for JSON serialization.
        """
        return {
            "nodes": [node.model_dump() for node in nodes],
            "edges": [edge.model_dump() for edge in edges],
            "statistics": self._calculate_statistics(nodes, edges).model_dump(),
            "exported_at": datetime.now(UTC).isoformat(),
        }

    def export_graphml(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> str:
        """
        Export graph as GraphML (for Gephi/Cytoscape).

        Parameters
        ----------
        nodes:
            List of graph nodes.
        edges:
            List of graph edges.

        Returns
        -------
        GraphML XML string.
        """
        # Build GraphML XML
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns"',
            '         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
            '         xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns',
            '         http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">',
            '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
            '  <key id="node_type" for="node" attr.name="node_type" attr.type="string"/>',
            '  <key id="risk_score" for="node" attr.name="risk_score" attr.type="double"/>',
            '  <key id="centrality" for="node" attr.name="centrality" attr.type="double"/>',
            '  <key id="size" for="node" attr.name="size" attr.type="double"/>',
            '  <key id="color" for="node" attr.name="color" attr.type="string"/>',
            '  <key id="edge_type" for="edge" attr.name="edge_type" attr.type="string"/>',
            '  <key id="weight" for="edge" attr.name="weight" attr.type="double"/>',
            '  <graph id="G" edgedefault="undirected">',
        ]

        # Add nodes
        for node in nodes:
            lines.append(f'    <node id="{self._escape_xml(node.id)}">')
            lines.append(f'      <data key="label">{self._escape_xml(node.label)}</data>')
            lines.append(f'      <data key="node_type">{node.node_type.value}</data>')
            if node.risk_score is not None:
                lines.append(f'      <data key="risk_score">{node.risk_score}</data>')
            if node.centrality is not None:
                lines.append(f'      <data key="centrality">{node.centrality}</data>')
            lines.append(f'      <data key="size">{node.size}</data>')
            lines.append(f'      <data key="color">{node.color}</data>')
            lines.append('    </node>')

        # Add edges
        for edge in edges:
            lines.append(
                f'    <edge source="{self._escape_xml(edge.source)}" '
                f'target="{self._escape_xml(edge.target)}">'
            )
            lines.append(f'      <data key="edge_type">{edge.edge_type.value}</data>')
            lines.append(f'      <data key="weight">{edge.weight}</data>')
            lines.append('    </edge>')

        lines.append('  </graph>')
        lines.append('</graphml>')

        return "\n".join(lines)

    def export_image(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
        fmt: GraphExportFormat = GraphExportFormat.SVG,
    ) -> bytes:
        """
        Render graph to SVG/PNG via matplotlib.

        Parameters
        ----------
        nodes:
            List of graph nodes.
        edges:
            List of graph edges.
        fmt:
            Output format (SVG or PNG).

        Returns
        -------
        Image bytes.

        Raises
        ------
        ValueError if format is not SVG or PNG.
        """
        if fmt not in (GraphExportFormat.SVG, GraphExportFormat.PNG):
            raise ValueError(f"Image export requires SVG or PNG format, got {fmt.value}")

        try:
            import matplotlib
            matplotlib.use("Agg")  # Non-interactive backend
            import matplotlib.pyplot as plt
            import networkx as nx
        except ImportError:
            raise RuntimeError(
                "Image export requires matplotlib and networkx. "
                "Install with: pip install matplotlib networkx"
            )

        if not nodes:
            return b""

        # Build networkx graph
        G = nx.Graph()

        # Add nodes with attributes
        for node in nodes:
            G.add_node(
                node.id,
                label=node.label,
                node_type=node.node_type.value,
                risk_score=node.risk_score,
                size=node.size,
                color=node.color,
            )

        # Add edges
        for edge in edges:
            G.add_edge(
                edge.source,
                edge.target,
                edge_type=edge.edge_type.value,
                weight=edge.weight,
            )

        # Calculate layout
        pos = nx.spring_layout(G, k=0.5, iterations=50, seed=42)

        # Extract attributes for drawing
        node_colors = [G.nodes[n].get("color", "#666666") for n in G.nodes()]
        node_sizes = [G.nodes[n].get("size", 20) * 2 for n in G.nodes()]

        # Create figure
        fig, ax = plt.subplots(figsize=(12, 12))

        # Draw nodes
        nx.draw_networkx_nodes(
            G, pos,
            node_color=node_colors,
            node_size=node_sizes,
            alpha=0.8,
            ax=ax,
        )

        # Draw edges
        nx.draw_networkx_edges(
            G, pos,
            width=1.5,
            alpha=0.5,
            ax=ax,
        )

        # Draw labels
        labels = {n: G.nodes[n].get("label", n) for n in G.nodes()}
        nx.draw_networkx_labels(
            G, pos,
            labels=labels,
            font_size=8,
            ax=ax,
        )

        ax.set_axis_off()
        plt.tight_layout()

        # Export
        buf = io.BytesIO()
        if fmt == GraphExportFormat.SVG:
            plt.savefig(buf, format="svg", bbox_inches="tight", dpi=100)
        else:
            plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)

        plt.close(fig)
        buf.seek(0)

        return buf.read()

    # ── Internal Helpers ────────────────────────────────────────────────────

    def _build_cypher(
        self,
        center_entity_id: str,
        depth: int,
        max_nodes: int,
        filters: GraphFilter,
    ) -> tuple[str, dict[str, Any]]:
        """
        Construct Cypher query from filters for entity-centered graph.

        Parameters
        ----------
        center_entity_id:
            ID of the center entity.
        depth:
            Traversal depth.
        max_nodes:
            Maximum nodes to return.
        filters:
            Filter criteria.

        Returns
        -------
        Tuple of (cypher_query, parameters).
        """
        # Build relationship type filter
        rel_type_pattern = "*"
        if filters.edge_types:
            rel_types = [self._edge_type_to_rel_type(et) for et in filters.edge_types]
            rel_type_pattern = f"{rel_types[0]}|{'|'.join(rel_types[1:])}" if rel_types else "*"

        # Build node type filter
        node_type_filter = ""
        if filters.node_types:
            neo4j_labels = [
                self._node_type_to_label(nt) for nt in filters.node_types
            ]
            label_conditions = " OR ".join(
                f"'{label}' IN labels(n)" for label in neo4j_labels
            )
            node_type_filter = f" AND ({label_conditions})"

        # Build risk score filter
        risk_filter = ""
        if filters.min_risk_score is not None:
            risk_filter += " AND (n.risk_score IS NULL OR n.risk_score >= $min_risk)"
        if filters.max_risk_score is not None:
            risk_filter += " AND (n.risk_score IS NULL OR n.risk_score <= $max_risk)"

        # Build date filter
        date_filter = ""
        if filters.date_from:
            date_filter += " AND (n.created_at IS NULL OR n.created_at >= $date_from)"
        if filters.date_to:
            date_filter += " AND (n.created_at IS NULL OR n.created_at <= $date_to)"

        # Build entity ID filter
        entity_filter = ""
        if filters.entity_ids:
            entity_filter = " AND n.id IN $entity_ids"

        # Build fraud pattern exclusion
        fraud_filter = ""
        if filters.exclude_fraud_patterns:
            fraud_filter = """
            AND NOT EXISTS {
                MATCH (n)-[:FLAGGED_BY]->(fp:FraudPattern)
                WHERE fp.pattern_name IN $exclude_fraud_patterns
            }
            """

        cypher = f"""
        MATCH (center {{id: $center_id}})
        CALL {{
            WITH center
            MATCH path = (center)-[{rel_type_pattern}1..{depth}]-(n)
            WHERE n.id IS NOT NULL
            {node_type_filter}
            {risk_filter}
            {date_filter}
            {entity_filter}
            {fraud_filter}
            RETURN DISTINCT n,
                   relationships(path) AS rels
            LIMIT $max_nodes
        }}
        WITH collect(DISTINCT n) AS nodes,
             collect(DISTINCT rels) AS all_rels
        UNWIND nodes AS node
        OPTIONAL MATCH (node)-[r]-(other)
        WHERE other IN nodes
        RETURN
            node,
            collect(DISTINCT r) AS edges
        """

        params: dict[str, Any] = {
            "center_id": center_entity_id,
            "max_nodes": max_nodes,
        }

        if filters.min_risk_score is not None:
            params["min_risk"] = filters.min_risk_score
        if filters.max_risk_score is not None:
            params["max_risk"] = filters.max_risk_score
        if filters.date_from:
            params["date_from"] = filters.date_from.isoformat()
        if filters.date_to:
            params["date_to"] = filters.date_to.isoformat()
        if filters.entity_ids:
            params["entity_ids"] = filters.entity_ids
        if filters.exclude_fraud_patterns:
            params["exclude_fraud_patterns"] = filters.exclude_fraud_patterns

        return cypher, params

    def _build_filtered_cypher(
        self,
        filters: GraphFilter,
        max_nodes: int,
    ) -> tuple[str, dict[str, Any]]:
        """
        Construct Cypher query for filtered graph (no center entity).

        Parameters
        ----------
        filters:
            Filter criteria.
        max_nodes:
            Maximum nodes to return.

        Returns
        -------
        Tuple of (cypher_query, parameters).
        """
        where_clauses = ["n.id IS NOT NULL"]
        params: dict[str, Any] = {}

        # Node type filter
        if filters.node_types:
            neo4j_labels = [
                self._node_type_to_label(nt) for nt in filters.node_types
            ]
            label_conditions = " OR ".join(
                f"'{label}' IN labels(n)" for label in neo4j_labels
            )
            where_clauses.append(f"({label_conditions})")

        # Risk score filter
        if filters.min_risk_score is not None:
            where_clauses.append("n.risk_score >= $min_risk")
            params["min_risk"] = filters.min_risk_score
        if filters.max_risk_score is not None:
            where_clauses.append("n.risk_score <= $max_risk")
            params["max_risk"] = filters.max_risk_score

        # Date filter
        if filters.date_from:
            where_clauses.append("n.created_at >= $date_from")
            params["date_from"] = filters.date_from.isoformat()
        if filters.date_to:
            where_clauses.append("n.created_at <= $date_to")
            params["date_to"] = filters.date_to.isoformat()

        # Entity ID filter
        if filters.entity_ids:
            where_clauses.append("n.id IN $entity_ids")
            params["entity_ids"] = filters.entity_ids

        where_clause = " AND ".join(where_clauses)

        cypher = f"""
        MATCH (n)
        WHERE {where_clause}
        WITH n LIMIT $max_nodes
        MATCH (n)-[r]-(m)
        WHERE m.id IN [x IN collect(DISTINCT n) | x.id]
        RETURN n, r, m
        """

        params["max_nodes"] = max_nodes

        return cypher, params

    def _transform_to_graph(
        self,
        result: list[dict],
        filters: GraphFilter,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """
        Convert Neo4j results to GraphResponse nodes and edges.

        Parameters
        ----------
        result:
            Neo4j query results.
        filters:
            Applied filters (for edge type filtering).

        Returns
        -------
        Tuple of (nodes, edges).
        """
        nodes_dict: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        for row in result:
            # Handle different result formats
            node_rec = row.get("node") or row.get("n") or row.get("center")
            edge_recs = row.get("edges") or row.get("r") or []
            neighbor_rec = row.get("m")

            if node_rec:
                node_id = node_rec.get("id", "")
                if node_id and node_id not in nodes_dict:
                    nodes_dict[node_id] = self._record_to_node(node_rec)

            if neighbor_rec:
                neighbor_id = neighbor_rec.get("id", "")
                if neighbor_id and neighbor_id not in nodes_dict:
                    nodes_dict[neighbor_id] = self._record_to_node(neighbor_rec)

            # Handle edges
            if isinstance(edge_recs, list):
                for edge_rec in edge_recs:
                    edge = self._record_to_edge_from_rel(edge_rec)
                    if edge:
                        edges.append(edge)
            elif edge_recs:
                edge = self._record_to_edge_from_rel(edge_recs)
                if edge:
                    edges.append(edge)

        # Deduplicate edges
        seen_edges: set[tuple[str, str, str]] = set()
        unique_edges: list[GraphEdge] = []
        for edge in edges:
            key = (edge.source, edge.target, edge.edge_type.value)
            reverse_key = (edge.target, edge.source, edge.edge_type.value)
            if key not in seen_edges and reverse_key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(edge)

        return list(nodes_dict.values()), unique_edges

    def _parse_path_to_graph(
        self,
        path_data: Any,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """
        Parse a Neo4j path object to nodes and edges.
        """
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        if not path_data:
            return nodes, edges

        # Neo4j path has nodes and relationships
        try:
            path_nodes = path_data.nodes if hasattr(path_data, 'nodes') else []
            path_rels = path_data.relationships if hasattr(path_data, 'relationships') else []

            for node_rec in path_nodes:
                nodes.append(self._record_to_node(node_rec))

            for rel_rec in path_rels:
                edge = self._record_to_edge_from_rel(rel_rec)
                if edge:
                    edges.append(edge)
        except Exception:
            logger.warning("Failed to parse path data")

        return nodes, edges

    def _record_to_node(self, record: dict) -> GraphNode:
        """
        Convert a Neo4j node record to GraphNode.
        """
        node_id = record.get("id", "")
        labels = record.get("labels", []) or self._infer_labels(record)

        # Determine node type
        node_type = GraphNodeType.COMPANY  # default
        for label in labels:
            if label in NEO4J_LABEL_TO_GRAPH_TYPE:
                node_type = NEO4J_LABEL_TO_GRAPH_TYPE[label]
                break

        # Get label for display
        label = (
            record.get("nome_normalizzato")
            or record.get("oggetto")
            or record.get("titolo")
            or record.get("name")
            or record.get("nome")
            or node_id
        )

        # Extract properties (exclude internal fields)
        internal_keys = {
            "id", "labels", "provenance", "embedding", "created_at",
            "updated_at", "risk_score", "centrality", "community_id",
        }
        properties = {
            k: v for k, v in record.items()
            if k not in internal_keys and v is not None
        }

        risk_score = record.get("risk_score")
        if risk_score is not None:
            try:
                risk_score = float(risk_score)
            except (ValueError, TypeError):
                risk_score = None

        return GraphNode(
            id=node_id,
            label=str(label),
            node_type=node_type,
            properties=properties,
            risk_score=risk_score,
        )

    def _record_to_edge(
        self,
        rel_rec: dict,
        source_id: str,
        target_id: str,
    ) -> GraphEdge:
        """
        Convert a Neo4j relationship record to GraphEdge.
        """
        rel_type = rel_rec.get("type", "") or "RELATED_TO"

        edge_type = NEO4J_REL_TO_EDGE_TYPE.get(
            rel_type.upper(),
            GraphEdgeType.RELATED_TO,
        )

        label = rel_rec.get("label", "") or rel_type.lower()
        weight = float(rel_rec.get("weight", 1.0))

        properties = {
            k: v for k, v in rel_rec.items()
            if k not in {"type", "label", "weight", "source", "target"}
            and v is not None
        }

        color = EDGE_TYPE_COLORS.get(edge_type, "#cccccc")

        return GraphEdge(
            source=source_id,
            target=target_id,
            edge_type=edge_type,
            label=label,
            weight=weight,
            properties=properties,
            color=color,
        )

    def _record_to_edge_from_rel(self, rel_rec: dict) -> GraphEdge | None:
        """
        Convert a relationship record to GraphEdge, extracting source/target.
        """
        if not rel_rec:
            return None

        rel_type = rel_rec.get("type", "") or "RELATED_TO"
        edge_type = NEO4J_REL_TO_EDGE_TYPE.get(
            rel_type.upper(),
            GraphEdgeType.RELATED_TO,
        )

        source = rel_rec.get("source_id") or rel_rec.get("start_node_id", "")
        target = rel_rec.get("target_id") or rel_rec.get("end_node_id", "")

        if not source or not target:
            return None

        label = rel_rec.get("label", "") or rel_type.lower()
        weight = float(rel_rec.get("weight", 1.0))

        properties = {
            k: v for k, v in rel_rec.items()
            if k not in {"type", "label", "weight", "source_id", "target_id",
                         "start_node_id", "end_node_id"}
            and v is not None
        }

        color = EDGE_TYPE_COLORS.get(edge_type, "#cccccc")

        return GraphEdge(
            source=source,
            target=target,
            edge_type=edge_type,
            label=label,
            weight=weight,
            properties=properties,
            color=color,
        )

    def _infer_labels(self, record: dict) -> list[str]:
        """
        Infer Neo4j labels from record properties.
        """
        labels = []
        if "cf" in record and len(record.get("cf", "")) in (11, 16):
            labels.append("Company")
        if "cig" in record:
            labels.append("Tender")
        if "cup" in record:
            labels.append("Project")
        if "nome" in record or "cognome" in record:
            labels.append("Person")
        if "pattern_name" in record:
            labels.append("FraudPattern")
        if "content" in record:
            labels.append("Comment")
        if "alert_hash" in record:
            labels.append("Alert")
        return labels

    def _edge_type_to_rel_type(self, edge_type: GraphEdgeType) -> str:
        """Convert GraphEdgeType to Neo4j relationship type."""
        mapping = {
            GraphEdgeType.WINS: "WINS",
            GraphEdgeType.ISSUES: "ISSUES",
            GraphEdgeType.PART_OF: "PART_OF",
            GraphEdgeType.REPRESENTS: "REPRESENTS",
            GraphEdgeType.OWNS: "OWNS",
            GraphEdgeType.FLAGGED_BY: "FLAGGED_BY",
            GraphEdgeType.HAS_ALERT: "HAS_ALERT",
            GraphEdgeType.ANNOTATES: "ANNOTATES",
            GraphEdgeType.SAME_AS: "SAME_AS",
            GraphEdgeType.RELATED_TO: "RELATED_TO",
        }
        return mapping.get(edge_type, "RELATED_TO")

    def _node_type_to_label(self, node_type: GraphNodeType) -> str:
        """Convert GraphNodeType to Neo4j label."""
        mapping = {
            GraphNodeType.COMPANY: "Company",
            GraphNodeType.TENDER: "Tender",
            GraphNodeType.PROJECT: "Project",
            GraphNodeType.PERSON: "Person",
            GraphNodeType.BUYER: "Buyer",
            GraphNodeType.ASSET: "Asset",
            GraphNodeType.FRAUD_PATTERN: "FraudPattern",
            GraphNodeType.COMMENT: "Comment",
            GraphNodeType.ALERT: "Alert",
        }
        return mapping.get(node_type, "Entity")

    def _calculate_statistics(
        self,
        nodes: list[GraphNode],
        edges: list[GraphEdge],
    ) -> GraphStatistics:
        """
        Calculate graph statistics.
        """
        node_count = len(nodes)
        edge_count = len(edges)

        if node_count == 0:
            return self._empty_statistics()

        # Degree calculation
        degree: dict[str, int] = defaultdict(int)
        for edge in edges:
            degree[edge.source] += 1
            degree[edge.target] += 1

        degrees = list(degree.values()) if degree else [0]
        max_degree = max(degrees)
        avg_degree = sum(degrees) / len(degrees) if degrees else 0.0

        # Density: 2E / (N * (N-1)) for undirected
        max_edges = node_count * (node_count - 1) / 2
        density = edge_count / max_edges if max_edges > 0 else 0.0
        density = min(density, 1.0)

        # Connected components
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)

        components = self._count_components(adjacency, [n.id for n in nodes])

        # Average clustering coefficient (approximation)
        avg_clustering = self._approximate_clustering(adjacency, nodes)

        # Node type counts
        node_types: dict[str, int] = defaultdict(int)
        for node in nodes:
            node_types[node.node_type.value] += 1

        # Edge type counts
        edge_types: dict[str, int] = defaultdict(int)
        for edge in edges:
            edge_types[edge.edge_type.value] += 1

        return GraphStatistics(
            node_count=node_count,
            edge_count=edge_count,
            density=round(density, 4),
            avg_degree=round(avg_degree, 2),
            max_degree=max_degree,
            connected_components=components,
            avg_clustering=round(avg_clustering, 4),
            node_types=dict(node_types),
            edge_types=dict(edge_types),
        )

    def _approximate_clustering(
        self,
        adjacency: dict[str, set[str]],
        nodes: list[GraphNode],
        sample_size: int = 50,
    ) -> float:
        """
        Approximate average clustering coefficient.
        """
        if not nodes:
            return 0.0

        # Sample nodes for performance
        sample = nodes[:sample_size]
        clustering_coeffs = []

        for node in sample:
            neighbors = adjacency.get(node.id, set())
            k = len(neighbors)

            if k < 2:
                clustering_coeffs.append(0.0)
                continue

            # Count edges between neighbors
            neighbor_edges = 0
            neighbor_list = list(neighbors)
            for i in range(len(neighbor_list)):
                for j in range(i + 1, len(neighbor_list)):
                    if neighbor_list[j] in adjacency.get(neighbor_list[i], set()):
                        neighbor_edges += 1

            max_neighbor_edges = k * (k - 1) / 2
            if max_neighbor_edges > 0:
                clustering_coeffs.append(neighbor_edges / max_neighbor_edges)
            else:
                clustering_coeffs.append(0.0)

        return sum(clustering_coeffs) / len(clustering_coeffs) if clustering_coeffs else 0.0

    def _empty_statistics(self) -> GraphStatistics:
        """Return empty graph statistics."""
        return GraphStatistics(
            node_count=0,
            edge_count=0,
            density=0.0,
            avg_degree=0.0,
            max_degree=0,
            connected_components=0,
            avg_clustering=0.0,
            node_types={},
            edge_types={},
        )

    def _validate_depth(self, depth: int) -> None:
        """Prevent runaway queries (max depth 5)."""
        if depth < 1 or depth > MAX_DEPTH:
            raise ValueError(
                f"Depth must be between 1 and {MAX_DEPTH}, got {depth}"
            )

    def _validate_max_nodes(self, max_nodes: int) -> None:
        """Prevent memory issues (max 500)."""
        if max_nodes < 10 or max_nodes > MAX_NODES:
            raise ValueError(
                f"max_nodes must be between 10 and {MAX_NODES}, got {max_nodes}"
            )

    def _escape_xml(self, text: str) -> str:
        """Escape special XML characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )
