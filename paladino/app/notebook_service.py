"""
Investigation Notebook Service for Paladino.

Provides a Jupyter-style investigation workspace where analysts can:
- Combine Cypher queries, notes, visualizations, and evidence
- Save investigation sessions for later
- Reuse investigation templates
- Link investigations to entities, alerts, comments
- Export investigations as reports

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.app.notebook_service import NotebookService
    from paladino.db import Neo4jConnection

    conn = Neo4jConnection()
    service = NotebookService(conn)

    # Create a notebook
    notebook = service.create_notebook(NotebookCreate(
        title="Company Due Diligence - ACME SRL",
        description="Investigation into ACME SRL procurement patterns",
        linked_entity_ids=["company-uuid-123"],
        tags=["due-diligence", "procurement"],
    ))

    # Add cells
    cell = service.add_cell(notebook.id, NotebookCellCreate(
        cell_type=NotebookCellType.CYPHER_QUERY,
        content="MATCH (c:Company {id: 'company-uuid-123'}) RETURN c",
        title="Company Details",
    ))

    # Execute cell
    result = service.execute_cell(notebook.id, cell.id)

    # Export
    export = service.export_notebook(notebook.id, "markdown")
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import uuid
from datetime import datetime, UTC
from typing import Any

from loguru import logger

from paladino.db import Neo4jConnection
from paladino.models import (
    Notebook,
    NotebookCell,
    NotebookCellCreate,
    NotebookCellExecuteResponse,
    NotebookCellType,
    NotebookCellUpdate,
    NotebookChangeHistoryItem,
    NotebookChangeHistoryResponse,
    NotebookCreate,
    NotebookExecuteAllResponse,
    NotebookExportFormat,
    NotebookListParams,
    NotebookResponse,
    NotebookStatus,
    NotebookUpdate,
)
from paladino.etl.unstructured_models import EntityMatch


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Cypher keywords that indicate write operations (rejected for safety)
_WRITE_CYPHER_KEYWORDS = {"CREATE", "DELETE", "MERGE", "SET", "REMOVE", "DROP", "ALTER", "GRANT", "REVOKE", "ADD", "CONSTRAINT", "INDEX"}

# Read-only Cypher keywords (allowed)
_READ_CYPHER_KEYWORDS = {"MATCH", "RETURN", "WHERE", "WITH", "UNWIND", "CALL", "YIELD", "OPTIONAL", "ORDER", "BY", "SKIP", "LIMIT", "AS", "DISTINCT", "COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT", "COALESCE", "CASE", "WHEN", "THEN", "ELSE", "END", "IN", "NOT", "AND", "OR", "XOR", "IS", "NULL", "TRUE", "FALSE", "EXISTS", "STARTS", "WITH", "ENDS", "CONTAINS", "TO", "INTEGER", "FLOAT", "STRING", "BOOLEAN", "DURATION", "DATE", "LOCALTIME", "LOCALDATETIME", "TIME", "DATETIME", "POINT", "REDUCE", "FILTER", "TAIL", "RANGE", "NODES", "RELATIONSHIPS", "STARTNODE", "ENDNODE", "TYPE", "ID", "KEYS", "PROPERTIES", "LABELS", "SHORTESTPATH", "ALLSHORTESTPATHS", "REVERSE", "HEAD", "LAST", "LENGTH", "SIZE", "ABS", "CEIL", "FLOOR", "RAND", "ROUND", "SIGN", "E", "EXP", "LOG", "LOG10", "SQRT", "PI", "SIN", "COS", "TAN", "COT", "ASIN", "ACOS", "ATAN", "ATAN2", "HAVERSIN", "DEGREES", "RADIANS", "UPPER", "LOWER", "LTRIM", "RTRIM", "TRIM", "SPLIT", "REPLACE", "SUBSTRING", "LEFT", "RIGHT", "REVERSE", "TOUPPER", "TOLOWER", "TOSTRING", "TOINTEGER", "TOFLOAT", "TYPEOF", "DATE", "TIME", "LOCALTIME", "DATETIME", "LOCALDATETIME", "DURATION", "TIMESTAMP", "LOCALTIME", "LOCALDATETIME"}

# Pre-built investigation templates
INVESTIGATION_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "Company Due Diligence",
        "description": "Standard template for investigating a company's procurement history and risk profile.",
        "cells": [
            {
                "cell_type": "markdown",
                "content": "## Company Overview\n\nInvestigation target details and basic information.",
                "position": 0,
                "title": "Introduction",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (c:Company {id: $entity_id})\nRETURN c.nome_normalizzato AS name,\n       c.cf AS fiscal_code,\n       c.piva AS vat_number,\n       c.regione AS region,\n       c.provincia AS province,\n       c.ateco AS sector,\n       c.risk_score AS risk_score,\n       c.anomaly_flags AS anomaly_flags",
                "position": 1,
                "title": "Company Details",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (c:Company {id: $entity_id})-[:WINS]->(t:Tender)\nRETURN t.cig AS tender_cig,\n       t.oggetto AS description,\n       t.importo AS amount,\n       t.data_aggiudicazione AS award_date,\n       t.single_bidder AS single_bidder,\n       t.red_flags AS red_flags\nORDER BY t.data_aggiudicazione DESC\nLIMIT 20",
                "position": 2,
                "title": "Tender Wins",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (c:Company {id: $entity_id})\nOPTIONAL MATCH (c)-[:WINS]->(t:Tender)\nWITH c, count(t) AS total_wins,\n     sum(t.importo) AS total_value,\n     avg(t.importo) AS avg_value,\n     sum(CASE WHEN t.single_bidder THEN 1 ELSE 0 END) AS single_bidder_count\nRETURN c.nome_normalizzato AS name,\n       total_wins,\n       coalesce(total_value, 0) AS total_value,\n       coalesce(avg_value, 0) AS avg_value,\n       single_bidder_count,\n       CASE WHEN total_wins > 0 THEN toFloat(single_bidder_count) / total_wins ELSE 0 END AS single_bidder_ratio",
                "position": 3,
                "title": "Risk Score History",
            },
            {
                "cell_type": "markdown",
                "content": "## Findings\n\nDocument key findings and conclusions here.",
                "position": 4,
                "title": "Findings",
            },
        ],
    },
    {
        "name": "Fraud Pattern Analysis",
        "description": "Template for analyzing fraud patterns and network connections for an entity.",
        "cells": [
            {
                "cell_type": "markdown",
                "content": "## Fraud Pattern Investigation\n\nAnalyzing suspicious activity patterns and network connections.",
                "position": 0,
                "title": "Introduction",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (e)-[:FLAGGED_BY]->(fp:FraudPattern)\nWHERE e.id = $entity_id\nRETURN fp.pattern_name AS pattern,\n       fp.severity AS severity,\n       fp.description AS description,\n       fp.detected_at AS detected_at,\n       fp.evidence_summary AS evidence\nORDER BY fp.detected_at DESC",
                "position": 1,
                "title": "Fraud Patterns",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (e {id: $entity_id})--(related)\nWITH labels(related) AS labels, related, count(*) AS connection_count\nRETURN labels, count(*) AS entity_count, sum(connection_count) AS total_connections\nORDER BY entity_count DESC\nLIMIT 20",
                "position": 2,
                "title": "Related Entities",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH path = (e {id: $entity_id})-[*1..3]-(connected)\nWHERE NOT e = connected\nWITH path, length(path) AS hop_count\nRETURN hop_count,\n       count(DISTINCT connected) AS entities_at_distance,\n       collect(DISTINCT labels(connected)[0]) AS entity_types\nORDER BY hop_count",
                "position": 3,
                "title": "Network Connections",
            },
            {
                "cell_type": "markdown",
                "content": "## Evidence Summary\n\nCompile evidence and document conclusions.",
                "position": 4,
                "title": "Evidence Summary",
            },
        ],
    },
    {
        "name": "Risk Assessment",
        "description": "Template for comprehensive risk score analysis and anomaly detection review.",
        "cells": [
            {
                "cell_type": "markdown",
                "content": "## Risk Score Analysis\n\nEvaluating current and historical risk scores for the target entity.",
                "position": 0,
                "title": "Introduction",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (c:Company {id: $entity_id})\nRETURN c.nome_normalizzato AS name,\n       c.risk_score AS current_risk_score,\n       CASE\n           WHEN c.risk_score >= 0.7 THEN 'HIGH'\n           WHEN c.risk_score >= 0.4 THEN 'MEDIUM'\n           ELSE 'LOW'\n       END AS risk_tier,\n       c.anomaly_flags AS active_anomalies,\n       c.centrality_score AS centrality",
                "position": 1,
                "title": "Current Risk Score",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (c:Company {id: $entity_id})-[:HAS_VERSION]->(v:Version {snapshot_type: 'risk_score'})\nRETURN v.risk_score AS risk_score,\n       v.change_date AS snapshot_date,\n       v.anomaly_flags AS anomaly_flags\nORDER BY v.change_date DESC\nLIMIT 20",
                "position": 2,
                "title": "Risk History",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (c:Company {id: $entity_id})\nUNWIND c.anomaly_flags AS flag\nRETURN flag, count(*) AS occurrence_count\nORDER BY occurrence_count DESC",
                "position": 3,
                "title": "Anomaly Flags",
            },
            {
                "cell_type": "markdown",
                "content": "## Risk Assessment\n\nDocument risk assessment conclusions and recommended actions.",
                "position": 4,
                "title": "Risk Assessment",
            },
        ],
    },
    {
        "name": "Supply Chain Analysis",
        "description": "Template for investigating supply chain relationships and subcontractor patterns.",
        "cells": [
            {
                "cell_type": "markdown",
                "content": "## Supply Chain Investigation\n\nAnalyzing upstream and downstream supply chain relationships.",
                "position": 0,
                "title": "Introduction",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (c:Company {id: $entity_id})<-[:WINS]-(t:Tender)<-[:ISSUES]-(b:Buyer)\nRETURN b.nome AS buyer_name,\n       count(t) AS tenders_issued,\n       sum(t.importo) AS total_value\nORDER BY total_value DESC\nLIMIT 20",
                "position": 1,
                "title": "Upstream Relationships (Buyers)",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (c:Company {id: $entity_id})-[:SUBCONTRACTS_TO]->(sub:Company)\nRETURN sub.nome_normalizzato AS subcontractor,\n       sub.cf AS cf,\n       count(*) AS subcontract_count,\n       sum(coalesce(sc.importo, 0)) AS total_subcontract_value\nORDER BY total_subcontract_value DESC\nLIMIT 20",
                "position": 2,
                "title": "Downstream Relationships (Subcontractors)",
            },
            {
                "cell_type": "cypher_query",
                "content": "MATCH (c:Company {id: $entity_id})-[:SUBCONTRACTS_TO]->(sub:Company)\nWITH sub, count(*) AS sub_count\nWITH count(sub) AS total_subcontractors,\n     max(sub_count) AS max_sub_count\nRETURN total_subcontractors,\n       max_sub_count,\n       CASE WHEN total_subcontractors > 0 THEN toFloat(max_sub_count) / total_subcontractors ELSE 0 END AS concentration_ratio",
                "position": 3,
                "title": "Subcontractor Concentration",
            },
            {
                "cell_type": "markdown",
                "content": "## Supply Chain Findings\n\nDocument supply chain analysis findings and risk indicators.",
                "position": 4,
                "title": "Findings",
            },
        ],
    },
    {
        "name": "Blank Investigation",
        "description": "Empty starter notebook for custom investigations.",
        "cells": [
            {
                "cell_type": "markdown",
                "content": "## New Investigation\n\nStart your investigation here. Add cells using the + button.",
                "position": 0,
                "title": "Introduction",
            },
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class NotebookService:
    """
    Service layer for investigation notebook operations.

    Handles all CRUD operations for notebooks and cells,
    cell execution, templates, and export functionality.
    """

    def __init__(self, conn: Neo4jConnection) -> None:
        self.conn = conn

    # ── Notebook CRUD ───────────────────────────────────────────────────────

    def create_notebook(self, notebook_data: NotebookCreate) -> NotebookResponse:
        """
        Create a new investigation notebook.

        Parameters
        ----------
        notebook_data:
            NotebookCreate schema with notebook details.

        Returns
        -------
        NotebookResponse with the created notebook details.
        """
        notebook_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        query = """
        CREATE (n:Notebook {
            id: $id,
            title: $title,
            description: $description,
            status: $status,
            template_name: $template_name,
            linked_entity_ids: $linked_entity_ids,
            linked_alert_ids: $linked_alert_ids,
            tags: $tags,
            cell_count: 0,
            author: $author,
            created_at: $created_at,
            updated_at: $created_at,
            completed_at: null
        })
        RETURN n
        """

        params = {
            "id": notebook_id,
            "title": notebook_data.title,
            "description": notebook_data.description,
            "status": NotebookStatus.DRAFT.value,
            "template_name": notebook_data.template_name,
            "linked_entity_ids": notebook_data.linked_entity_ids,
            "linked_alert_ids": notebook_data.linked_alert_ids,
            "tags": notebook_data.tags,
            "author": notebook_data.author,
            "created_at": now.isoformat(),
        }

        result = self.conn.run_query(query, params)
        if not result:
            raise RuntimeError("Failed to create notebook")

        logger.info(f"Created notebook {notebook_id}: {notebook_data.title}")

        # Log change
        self._log_change(notebook_id, "notebook_created", details={"title": notebook_data.title})

        return self._record_to_response(result[0]["n"])

    def get_notebook(self, notebook_id: str) -> NotebookResponse | None:
        """
        Get a full notebook with all its cells.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.

        Returns
        -------
        NotebookResponse with cells if found, None otherwise.
        """
        # Get notebook
        notebook_query = """
        MATCH (n:Notebook {id: $notebook_id})
        WHERE n.status <> 'archived'
        RETURN n
        """

        notebook_result = self.conn.run_query(notebook_query, {"notebook_id": notebook_id})
        if not notebook_result:
            return None

        notebook = self._record_to_response(notebook_result[0]["n"])

        # Get cells
        cells_query = """
        MATCH (c:NotebookCell {notebook_id: $notebook_id})
        RETURN c
        ORDER BY c.position ASC
        """

        cells_result = self.conn.run_query(cells_query, {"notebook_id": notebook_id})
        cells = [self._record_to_cell(record["c"]) for record in cells_result]

        notebook.cells = cells
        notebook.cell_count = len(cells)

        return notebook

    def list_notebooks(self, params: NotebookListParams) -> tuple[list[NotebookResponse], int]:
        """
        List notebooks with filtering and pagination.

        Parameters
        ----------
        params:
            NotebookListParams with filters, pagination, and sorting.

        Returns
        -------
        Tuple of (list of NotebookResponse, total count).
        """
        where_clauses = ["n.status <> 'archived'"]
        query_params: dict[str, Any] = {}

        if params.status:
            where_clauses.append("n.status = $status")
            query_params["status"] = params.status.value

        if params.template_name:
            where_clauses.append("n.template_name = $template_name")
            query_params["template_name"] = params.template_name

        if params.tag:
            where_clauses.append("$tag IN n.tags")
            query_params["tag"] = params.tag

        if params.entity_id:
            where_clauses.append("$entity_id IN n.linked_entity_ids")
            query_params["entity_id"] = params.entity_id

        where_clause = " AND ".join(where_clauses)

        # Count query
        count_query = f"""
        MATCH (n:Notebook)
        WHERE {where_clause}
        RETURN count(n) as total
        """

        count_result = self.conn.run_query(count_query, query_params)
        total = count_result[0]["total"] if count_result else 0

        if total == 0:
            return [], 0

        # Data query
        sort_direction = "ASC" if params.sort_order == "asc" else "DESC"
        data_query = f"""
        MATCH (n:Notebook)
        WHERE {where_clause}
        RETURN n
        ORDER BY n.{params.sort_by} {sort_direction}
        SKIP $offset
        LIMIT $limit
        """

        query_params["offset"] = params.offset
        query_params["limit"] = params.limit

        result = self.conn.run_query(data_query, query_params)
        notebooks = [self._record_to_response(record["n"]) for record in result]

        return notebooks, total

    def update_notebook(self, notebook_id: str, update_data: NotebookUpdate) -> NotebookResponse | None:
        """
        Update notebook metadata.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.
        update_data:
            NotebookUpdate with fields to update.

        Returns
        -------
        NotebookResponse if updated, None if not found.
        """
        current = self.get_notebook(notebook_id)
        if not current:
            return None

        now = datetime.now(UTC)
        set_clauses = ["n.updated_at = $updated_at"]
        params: dict[str, Any] = {"notebook_id": notebook_id, "updated_at": now.isoformat()}

        if update_data.title is not None:
            set_clauses.append("n.title = $title")
            params["title"] = update_data.title

        if update_data.description is not None:
            set_clauses.append("n.description = $description")
            params["description"] = update_data.description

        if update_data.status is not None:
            set_clauses.append("n.status = $status")
            params["status"] = update_data.status.value if hasattr(update_data.status, 'value') else update_data.status
            if update_data.status == NotebookStatus.COMPLETED:
                set_clauses.append("n.completed_at = $completed_at")
                params["completed_at"] = now.isoformat()

        if update_data.tags is not None:
            set_clauses.append("n.tags = $tags")
            params["tags"] = update_data.tags

        if update_data.linked_entity_ids is not None:
            set_clauses.append("n.linked_entity_ids = $linked_entity_ids")
            params["linked_entity_ids"] = update_data.linked_entity_ids

        if update_data.linked_alert_ids is not None:
            set_clauses.append("n.linked_alert_ids = $linked_alert_ids")
            params["linked_alert_ids"] = update_data.linked_alert_ids

        set_clause = ", ".join(set_clauses)

        query = f"""
        MATCH (n:Notebook {{id: $notebook_id}})
        SET {set_clause}
        RETURN n
        """

        result = self.conn.run_query(query, params)
        if not result:
            return None

        logger.info(f"Updated notebook {notebook_id}")

        # Log change
        changed_fields = [k for k, v in update_data.model_dump(exclude_none=True).items() if v is not None]
        self._log_change(notebook_id, "metadata_updated", details={"fields": changed_fields})

        return self._record_to_response(result[0]["n"])

    def delete_notebook(self, notebook_id: str) -> bool:
        """
        Soft delete a notebook (set status to ARCHIVED).

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.

        Returns
        -------
        True if archived, False if not found.
        """
        now = datetime.now(UTC)

        query = """
        MATCH (n:Notebook {id: $notebook_id})
        WHERE n.status <> 'archived'
        SET n.status = 'archived',
            n.updated_at = $updated_at
        RETURN n
        """

        result = self.conn.run_query(query, {"notebook_id": notebook_id, "updated_at": now.isoformat()})
        if not result:
            return False

        logger.info(f"Soft-deleted (archived) notebook {notebook_id}")

        # Log change
        self._log_change(notebook_id, "notebook_archived")

        return True

    # ── Cell Operations ──────────────────────────────────────────────────────

    def add_cell(self, notebook_id: str, cell_data: NotebookCellCreate) -> NotebookCell:
        """
        Add a cell to a notebook.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.
        cell_data:
            NotebookCellCreate with cell details.

        Returns
        -------
        NotebookCell with the created cell.

        Raises
        ------
        ValueError if notebook not found.
        """
        # Check notebook exists
        notebook = self._get_notebook_basic(notebook_id)
        if not notebook:
            raise ValueError(f"Notebook {notebook_id} not found")

        cell_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Determine position
        if cell_data.position is None:
            # Auto-append: get max position
            max_pos_query = """
            MATCH (c:NotebookCell {notebook_id: $notebook_id})
            RETURN max(c.position) as max_pos
            """
            max_pos_result = self.conn.run_query(max_pos_query, {"notebook_id": notebook_id})
            max_pos = max_pos_result[0]["max_pos"] if max_pos_result and max_pos_result[0]["max_pos"] is not None else -1
            position = max_pos + 1
        else:
            position = cell_data.position

        query = """
        CREATE (c:NotebookCell {
            id: $id,
            notebook_id: $notebook_id,
            cell_type: $cell_type,
            content: $content,
            position: $position,
            title: $title,
            execution_result: null,
            execution_count: 0,
            last_executed_at: null,
            linked_entity_id: $linked_entity_id,
            created_at: $created_at,
            updated_at: null
        })
        RETURN c
        """

        params = {
            "id": cell_id,
            "notebook_id": notebook_id,
            "cell_type": cell_data.cell_type.value,
            "content": cell_data.content,
            "position": position,
            "title": cell_data.title,
            "linked_entity_id": cell_data.linked_entity_id,
            "created_at": now.isoformat(),
        }

        result = self.conn.run_query(query, params)
        if not result:
            raise RuntimeError("Failed to create cell")

        logger.info(f"Added cell {cell_id} to notebook {notebook_id} at position {position}")

        # Log change
        self._log_change(notebook_id, "cell_added", cell_id=cell_id, details={"position": position, "cell_type": cell_data.cell_type.value})

        return self._record_to_cell(result[0]["c"])

    def update_cell(self, notebook_id: str, cell_id: str, update_data: NotebookCellUpdate) -> NotebookCell | None:
        """
        Update a cell's content.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.
        cell_id:
            UUID of the cell.
        update_data:
            NotebookCellUpdate with fields to update.

        Returns
        -------
        NotebookCell if updated, None if not found.
        """
        current = self._get_cell_basic(cell_id)
        if not current or current.get("notebook_id") != notebook_id:
            return None

        now = datetime.now(UTC)
        set_clauses = ["c.updated_at = $updated_at"]
        params: dict[str, Any] = {"cell_id": cell_id, "updated_at": now.isoformat()}

        if update_data.content is not None:
            set_clauses.append("c.content = $content")
            params["content"] = update_data.content

        if update_data.cell_type is not None:
            set_clauses.append("c.cell_type = $cell_type")
            params["cell_type"] = update_data.cell_type.value

        if update_data.title is not None:
            set_clauses.append("c.title = $title")
            params["title"] = update_data.title

        if update_data.linked_entity_id is not None:
            set_clauses.append("c.linked_entity_id = $linked_entity_id")
            params["linked_entity_id"] = update_data.linked_entity_id

        set_clause = ", ".join(set_clauses)

        query = f"""
        MATCH (c:NotebookCell {{id: $cell_id}})
        SET {set_clause}
        RETURN c
        """

        result = self.conn.run_query(query, params)
        if not result:
            return None

        logger.info(f"Updated cell {cell_id} in notebook {notebook_id}")

        # Log change
        self._log_change(notebook_id, "cell_updated", cell_id=cell_id)

        return self._record_to_cell(result[0]["c"])

    def delete_cell(self, notebook_id: str, cell_id: str) -> bool:
        """
        Delete a cell from a notebook.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.
        cell_id:
            UUID of the cell.

        Returns
        -------
        True if deleted, False if not found.
        """
        # Verify cell belongs to notebook
        current = self._get_cell_basic(cell_id)
        if not current or current.get("notebook_id") != notebook_id:
            return False

        query = """
        MATCH (c:NotebookCell {id: $cell_id, notebook_id: $notebook_id})
        DETACH DELETE c
        """

        result = self.conn.run_query(query, {"cell_id": cell_id, "notebook_id": notebook_id})
        # Check if anything was deleted
        deleted = result[0].get("deleted", 0) if result else 0

        if deleted > 0:
            logger.info(f"Deleted cell {cell_id} from notebook {notebook_id}")
            # Log change
            self._log_change(notebook_id, "cell_deleted", cell_id=cell_id)

        return deleted > 0

    def reorder_cells(self, notebook_id: str, cell_positions: list[dict]) -> bool:
        """
        Reorder cells by updating their positions.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.
        cell_positions:
            List of dicts with 'cell_id' and 'position' keys.

        Returns
        -------
        True if reordered, False if validation failed.
        """
        if not cell_positions:
            return False

        # Verify all cells belong to the notebook
        cell_ids = [cp["cell_id"] for cp in cell_positions]
        verify_query = """
        MATCH (c:NotebookCell)
        WHERE c.id IN $cell_ids AND c.notebook_id = $notebook_id
        RETURN count(c) as matched
        """

        verify_result = self.conn.run_query(verify_query, {"cell_ids": cell_ids, "notebook_id": notebook_id})
        if not verify_result or verify_result[0]["matched"] != len(cell_ids):
            return False

        # Update positions in a single query using UNWIND
        reorder_query = """
        UNWIND $positions AS pos
        MATCH (c:NotebookCell {id: pos.cell_id, notebook_id: $notebook_id})
        SET c.position = pos.position
        RETURN count(c) as updated
        """

        positions_data = [{"cell_id": cp["cell_id"], "position": cp["position"]} for cp in cell_positions]

        result = self.conn.run_query(reorder_query, {"positions": positions_data, "notebook_id": notebook_id})
        updated = result[0]["updated"] if result else 0

        if updated > 0:
            logger.info(f"Reordered {updated} cells in notebook {notebook_id}")
            # Log change
            self._log_change(notebook_id, "cells_reordered", details={"cell_count": updated})

        return updated > 0

    def get_cell(self, notebook_id: str, cell_id: str) -> NotebookCell | None:
        """
        Get a single cell.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.
        cell_id:
            UUID of the cell.

        Returns
        -------
        NotebookCell if found, None otherwise.
        """
        query = """
        MATCH (c:NotebookCell {id: $cell_id, notebook_id: $notebook_id})
        RETURN c
        """

        result = self.conn.run_query(query, {"cell_id": cell_id, "notebook_id": notebook_id})
        if not result:
            return None

        return self._record_to_cell(result[0]["c"])

    # ── Cell Execution ───────────────────────────────────────────────────────

    def execute_cell(self, notebook_id: str, cell_id: str) -> NotebookCellExecuteResponse:
        """
        Execute a single cell (Cypher query or render markdown).

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.
        cell_id:
            UUID of the cell.

        Returns
        -------
        NotebookCellExecuteResponse with execution result.
        """
        cell = self.get_cell(notebook_id, cell_id)
        if not cell:
            return NotebookCellExecuteResponse(
                cell_id=cell_id,
                cell_type=NotebookCellType.MARKDOWN,
                execution_count=0,
                error="Cell not found",
            )

        now = datetime.now(UTC)
        execution_count = cell.execution_count + 1

        try:
            if cell.cell_type == NotebookCellType.CYPHER_QUERY:
                # Validate Cypher for safety
                self._validate_cypher(cell.content)

                # Execute read-only Cypher
                results = self._execute_cypher(cell.content)

                # Auto-discover connections between returned entities
                connection_insights: list[dict] = []
                entity_ids = self._extract_entity_ids_from_results(results)
                if entity_ids and len(entity_ids) >= 2:
                    connection_insights = self._discover_connections(entity_ids)

                # Update cell with execution result
                update_query = """
                MATCH (c:NotebookCell {id: $cell_id})
                SET c.execution_result = $execution_result,
                    c.execution_count = $execution_count,
                    c.last_executed_at = $last_executed_at
                RETURN c
                """

                result_data = {
                    "status": "success",
                    "row_count": len(results),
                    "data": results,
                    "executed_at": now.isoformat(),
                }
                if connection_insights:
                    result_data["connection_insights"] = connection_insights

                update_result = self.conn.run_query(
                    update_query,
                    {
                        "cell_id": cell_id,
                        "execution_result": json.dumps(result_data),
                        "execution_count": execution_count,
                        "last_executed_at": now.isoformat(),
                    },
                )

                # Log change
                self._log_change(notebook_id, "cell_executed", cell_id=cell_id, details={"row_count": len(results), "connections_found": len(connection_insights)})

                return NotebookCellExecuteResponse(
                    cell_id=cell_id,
                    cell_type=cell.cell_type,
                    execution_count=execution_count,
                    execution_result=result_data,
                    last_executed_at=now,
                )

            elif cell.cell_type == NotebookCellType.CONNECTION_INSIGHT:
                # Run implicit connection discovery on linked entities
                linked_ids = self._get_linked_entity_ids(notebook_id, cell)
                insights = self._discover_connections(linked_ids) if len(linked_ids) >= 2 else []

                result_data = {
                    "status": "success",
                    "insights": insights,  # already dicts from _discover_connections
                    "insight_count": len(insights),
                    "executed_at": now.isoformat(),
                }

                update_query = """
                MATCH (c:NotebookCell {id: $cell_id})
                SET c.execution_result = $execution_result,
                    c.execution_count = $execution_count,
                    c.last_executed_at = $last_executed_at
                RETURN c
                """
                self.conn.run_query(
                    update_query,
                    {
                        "cell_id": cell_id,
                        "execution_result": json.dumps(result_data),
                        "execution_count": execution_count,
                        "last_executed_at": now.isoformat(),
                    },
                )

                self._log_change(notebook_id, "cell_executed", cell_id=cell_id, details={"type": "connection_insight", "connections_found": len(insights)})

                return NotebookCellExecuteResponse(
                    cell_id=cell_id,
                    cell_type=cell.cell_type,
                    execution_count=execution_count,
                    execution_result=result_data,
                    last_executed_at=now,
                )

            elif cell.cell_type == NotebookCellType.MARKDOWN:
                # Render markdown to HTML
                html_content = self._render_markdown(cell.content)

                # Update cell
                update_query = """
                MATCH (c:NotebookCell {id: $cell_id})
                SET c.execution_result = $execution_result,
                    c.execution_count = $execution_count,
                    c.last_executed_at = $last_executed_at
                RETURN c
                """

                result_data = {
                    "status": "success",
                    "html": html_content,
                    "executed_at": now.isoformat(),
                }

                self.conn.run_query(
                    update_query,
                    {
                        "cell_id": cell_id,
                        "execution_result": json.dumps(result_data),
                        "execution_count": execution_count,
                        "last_executed_at": now.isoformat(),
                    },
                )

                return NotebookCellExecuteResponse(
                    cell_id=cell_id,
                    cell_type=cell.cell_type,
                    execution_count=execution_count,
                    execution_result=result_data,
                    last_executed_at=now,
                )

            elif cell.cell_type in (NotebookCellType.RESULTS_TABLE, NotebookCellType.VISUALIZATION, NotebookCellType.CODE):
                # For these types, just record a successful execution
                # (actual rendering happens client-side)
                update_query = """
                MATCH (c:NotebookCell {id: $cell_id})
                SET c.execution_count = $execution_count,
                    c.last_executed_at = $last_executed_at
                RETURN c
                """

                result_data = {
                    "status": "success",
                    "executed_at": now.isoformat(),
                    "note": "Rendering handled client-side",
                }

                self.conn.run_query(
                    update_query,
                    {
                        "cell_id": cell_id,
                        "execution_count": execution_count,
                        "last_executed_at": now.isoformat(),
                    },
                )

                return NotebookCellExecuteResponse(
                    cell_id=cell_id,
                    cell_type=cell.cell_type,
                    execution_count=execution_count,
                    execution_result=result_data,
                    last_executed_at=now,
                )

            else:
                return NotebookCellExecuteResponse(
                    cell_id=cell_id,
                    cell_type=cell.cell_type,
                    execution_count=execution_count,
                    error=f"Unsupported cell type: {cell.cell_type}",
                )

        except ValueError as e:
            # Cypher validation error
            error_result = {
                "status": "error",
                "error": str(e),
                "executed_at": now.isoformat(),
            }

            self.conn.run_query(
                """
                MATCH (c:NotebookCell {id: $cell_id})
                SET c.execution_result = $execution_result,
                    c.execution_count = $execution_count,
                    c.last_executed_at = $last_executed_at
                """,
                {
                    "cell_id": cell_id,
                    "execution_result": json.dumps(error_result),
                    "execution_count": execution_count,
                    "last_executed_at": now.isoformat(),
                },
            )

            return NotebookCellExecuteResponse(
                cell_id=cell_id,
                cell_type=cell.cell_type,
                execution_count=execution_count,
                error=str(e),
            )

        except Exception as e:
            # General execution error
            error_result = {
                "status": "error",
                "error": f"Execution failed: {str(e)}",
                "executed_at": now.isoformat(),
            }

            self.conn.run_query(
                """
                MATCH (c:NotebookCell {id: $cell_id})
                SET c.execution_result = $execution_result,
                    c.execution_count = $execution_count,
                    c.last_executed_at = $last_executed_at
                """,
                {
                    "cell_id": cell_id,
                    "execution_result": json.dumps(error_result),
                    "execution_count": execution_count,
                    "last_executed_at": now.isoformat(),
                },
            )

            logger.warning(f"Cell execution failed: {e}")

            return NotebookCellExecuteResponse(
                cell_id=cell_id,
                cell_type=cell.cell_type,
                execution_count=execution_count,
                error=str(e),
            )

    def execute_all_cells(self, notebook_id: str) -> NotebookExecuteAllResponse:
        """
        Execute all cells in a notebook in order.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.

        Returns
        -------
        NotebookExecuteAllResponse with results for each cell.
        """
        notebook = self.get_notebook(notebook_id)
        if not notebook:
            return NotebookExecuteAllResponse(
                notebook_id=notebook_id,
                total_cells=0,
                executed_count=0,
                failed_count=0,
            )

        results = []
        executed_count = 0
        failed_count = 0

        for cell in notebook.cells:
            result = self.execute_cell(notebook_id, cell.id)
            results.append(result)
            if result.error:
                failed_count += 1
            else:
                executed_count += 1

        return NotebookExecuteAllResponse(
            notebook_id=notebook_id,
            total_cells=len(notebook.cells),
            executed_count=executed_count,
            failed_count=failed_count,
            results=results,
        )

    # ── Templates ────────────────────────────────────────────────────────────

    def list_templates(self) -> list[dict[str, Any]]:
        """
        List available investigation templates.

        Returns
        -------
        List of template metadata.
        """
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "cell_count": len(t["cells"]),
            }
            for t in INVESTIGATION_TEMPLATES
        ]

    def create_notebook_from_template(self, template_name: str, author: str = "user", title: str | None = None) -> NotebookResponse:
        """
        Create a notebook from a template.

        Parameters
        ----------
        template_name:
            Name of the template to use.
        author:
            Author of the notebook.
        title:
            Optional custom title (defaults to template name).

        Returns
        -------
        NotebookResponse with the created notebook.

        Raises
        ------
        ValueError if template not found.
        """
        template = None
        for t in INVESTIGATION_TEMPLATES:
            if t["name"] == template_name:
                template = t
                break

        if not template:
            raise ValueError(f"Template '{template_name}' not found. Available: {[t['name'] for t in INVESTIGATION_TEMPLATES]}")

        # Create notebook
        notebook = self.create_notebook(NotebookCreate(
            title=title or template["name"],
            description=template["description"],
            template_name=template_name,
            author=author,
        ))

        # Create cells from template
        for cell_template in template["cells"]:
            self.add_cell(
                notebook.id,
                NotebookCellCreate(
                    cell_type=NotebookCellType(cell_template["cell_type"]),
                    content=cell_template["content"],
                    position=cell_template["position"],
                    title=cell_template.get("title"),
                ),
            )

        # Reload to get cells
        return self.get_notebook(notebook.id) or notebook

    # ── Export ───────────────────────────────────────────────────────────────

    def export_notebook(self, notebook_id: str, export_format: str | NotebookExportFormat = "json") -> str:
        """
        Export a notebook to the specified format.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.
        export_format:
            Format to export to: 'json', 'markdown', 'html'.

        Returns
        -------
        Exported notebook as string.

        Raises
        ------
        ValueError if format not supported.
        """
        # Normalize format
        if isinstance(export_format, str):
            try:
                export_format = NotebookExportFormat(export_format.lower())
            except ValueError:
                raise ValueError(f"Unsupported export format: {export_format}. Supported: {[f.value for f in NotebookExportFormat]}")

        notebook = self.get_notebook(notebook_id)
        if not notebook:
            raise ValueError(f"Notebook {notebook_id} not found")

        if export_format == NotebookExportFormat.JSON:
            return self._export_json(notebook)
        elif export_format == NotebookExportFormat.MARKDOWN:
            return self._export_markdown(notebook)
        elif export_format == NotebookExportFormat.HTML:
            return self._export_html(notebook)
        else:
            raise ValueError(f"Unsupported export format: {export_format}")

    def duplicate_notebook(self, notebook_id: str, new_title: str | None = None) -> NotebookResponse:
        """
        Clone a notebook with all its cells.

        Parameters
        ----------
        notebook_id:
            UUID of the source notebook.
        new_title:
            Optional title for the duplicate (defaults to "Copy of ...").

        Returns
        -------
        NotebookResponse with the duplicated notebook.
        """
        source = self.get_notebook(notebook_id)
        if not source:
            raise ValueError(f"Notebook {notebook_id} not found")

        # Create duplicate notebook
        duplicate = self.create_notebook(NotebookCreate(
            title=new_title or f"Copy of {source.title}",
            description=source.description,
            template_name=source.template_name,
            linked_entity_ids=source.linked_entity_ids,
            linked_alert_ids=source.linked_alert_ids,
            tags=source.tags,
            author=source.author,
        ))

        # Copy cells
        for cell in source.cells:
            self.add_cell(
                duplicate.id,
                NotebookCellCreate(
                    cell_type=cell.cell_type,
                    content=cell.content,
                    position=cell.position,
                    title=cell.title,
                    linked_entity_id=cell.linked_entity_id,
                ),
            )

        # Reload to get cells
        return self.get_notebook(duplicate.id) or duplicate

    def get_change_history(self, notebook_id: str) -> NotebookChangeHistoryResponse:
        """
        Get change history for a notebook.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.

        Returns
        -------
        NotebookChangeHistoryResponse with change log.
        """
        query = """
        MATCH (h:NotebookChangeHistory {notebook_id: $notebook_id})
        RETURN h
        ORDER BY h.changed_at DESC
        LIMIT 100
        """

        result = self.conn.run_query(query, {"notebook_id": notebook_id})
        changes = []
        for record in result:
            h = record["h"]
            changes.append(NotebookChangeHistoryItem(
                changed_at=datetime.fromisoformat(h["changed_at"]) if isinstance(h["changed_at"], str) else datetime.now(UTC),
                change_type=h.get("change_type", "unknown"),
                cell_id=h.get("cell_id"),
                details=json.loads(h["details"]) if isinstance(h.get("details"), str) else (h.get("details") or {}),
            ))

        return NotebookChangeHistoryResponse(
            notebook_id=notebook_id,
            changes=changes,
            total_changes=len(changes),
        )

    # ── Internal Helpers ─────────────────────────────────────────────────────

    def _validate_cypher(self, query: str) -> None:
        """
        Validate that a Cypher query is read-only.

        Rejects queries containing WRITE/DELETE/MERGE/SET/REMOVE keywords
        at the start of a clause (not within strings or identifiers).

        Parameters
        ----------
        query:
            Cypher query to validate.

        Raises
        ------
        ValueError if query contains write operations.
        """
        if not query or not query.strip():
            raise ValueError("Empty Cypher query")

        # Remove comments
        cleaned = re.sub(r'//.*$', '', query, flags=re.MULTILINE)
        cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)

        # Remove string literals to avoid false positives
        cleaned = re.sub(r'"[^"]*"', '""', cleaned)
        cleaned = re.sub(r"'[^']*'", "''", cleaned)

        # Check for write keywords at clause boundaries or standalone
        # Split by whitespace and check each token
        tokens = re.split(r'[\s,()]+', cleaned.upper())

        for token in tokens:
            token = token.strip()
            if token in _WRITE_CYPHER_KEYWORDS:
                raise ValueError(
                    f"Security: Cypher query contains write operation '{token}'. "
                    "Only read-only queries (MATCH/RETURN) are allowed in notebooks."
                )

    def _execute_cypher(self, query: str) -> list[dict]:
        """
        Execute a read-only Cypher query.

        Parameters
        ----------
        query:
            Cypher query to execute.

        Returns
        -------
        List of result dicts.
        """
        try:
            result = self.conn.run_query(query)
            if not result:
                return []

            # Convert Neo4j records to dicts
            rows = []
            for record in result:
                row = {}
                for key, value in record.items():
                    # Handle Neo4j types
                    if hasattr(value, 'isoformat'):
                        row[key] = value.isoformat()
                    elif hasattr(value, '__float__'):
                        row[key] = float(value)
                    elif hasattr(value, '__int__'):
                        row[key] = int(value)
                    else:
                        row[key] = value
                rows.append(row)

            return rows
        except Exception as e:
            raise RuntimeError(f"Cypher execution failed: {e}")

    def _render_markdown(self, content: str) -> str:
        """
        Simple markdown to HTML converter.

        Supports: headings, bold, italic, lists, code blocks, links.

        Parameters
        ----------
        content:
            Markdown content to render.

        Returns
        -------
        HTML string.
        """
        if not content:
            return ""

        lines = content.split("\n")
        html_lines = []
        in_list = False
        in_code_block = False

        for line in lines:
            # Code blocks
            if line.startswith("```"):
                if in_code_block:
                    html_lines.append("</code></pre>")
                    in_code_block = False
                else:
                    if in_list:
                        html_lines.append("</ul>")
                        in_list = False
                    html_lines.append("<pre><code>")
                    in_code_block = True
                continue

            if in_code_block:
                html_lines.append(html.escape(line))
                continue

            # Headings
            heading_match = re.match(r'^(#{1,6})\s+(.+)', line)
            if heading_match:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                level = len(heading_match.group(1))
                text = self._inline_formatting(heading_match.group(2))
                html_lines.append(f"<h{level}>{text}</h{level}>")
                continue

            # Unordered lists
            list_match = re.match(r'^[-*+]\s+(.+)', line)
            if list_match:
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                text = self._inline_formatting(list_match.group(1))
                html_lines.append(f"<li>{text}</li>")
                continue

            # Close list if we're in one and hit a non-list line
            if in_list:
                html_lines.append("</ul>")
                in_list = False

            # Empty lines
            if not line.strip():
                continue

            # Paragraphs
            text = self._inline_formatting(line)
            html_lines.append(f"<p>{text}</p>")

        # Close any open tags
        if in_list:
            html_lines.append("</ul>")
        if in_code_block:
            html_lines.append("</code></pre>")

        return "\n".join(html_lines)

    def _inline_formatting(self, text: str) -> str:
        """Apply inline markdown formatting."""
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        # Inline code
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        # Links
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
        return text

    def _format_results(self, results: list[dict]) -> dict:
        """
        Format query results for display.

        Parameters
        ----------
        results:
            List of result dicts.

        Returns
        -------
        Formatted result dict with metadata.
        """
        if not results:
            return {"status": "success", "row_count": 0, "data": [], "columns": []}

        columns = list(results[0].keys())
        return {
            "status": "success",
            "row_count": len(results),
            "columns": columns,
            "data": results,
        }

    def _get_notebook_basic(self, notebook_id: str) -> dict | None:
        """Get basic notebook info without cells."""
        query = """
        MATCH (n:Notebook {id: $notebook_id})
        RETURN n
        """
        result = self.conn.run_query(query, {"notebook_id": notebook_id})
        if not result:
            return None
        return result[0]["n"]

    def _get_cell_basic(self, cell_id: str) -> dict | None:
        """Get basic cell info."""
        query = """
        MATCH (c:NotebookCell {id: $cell_id})
        RETURN c
        """
        result = self.conn.run_query(query, {"cell_id": cell_id})
        if not result:
            return None
        return result[0]["c"]

    def _record_to_response(self, record: dict[str, Any]) -> NotebookResponse:
        """Convert a Neo4j notebook record to NotebookResponse."""
        created_at = record.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(UTC)
        elif not created_at:
            created_at = datetime.now(UTC)

        updated_at = record.get("updated_at")
        if updated_at and isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                updated_at = None

        completed_at = record.get("completed_at")
        if completed_at and isinstance(completed_at, str):
            try:
                completed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            except ValueError:
                completed_at = None

        status_str = record.get("status", "draft")
        try:
            status = NotebookStatus(status_str)
        except ValueError:
            status = NotebookStatus.DRAFT

        return NotebookResponse(
            id=record.get("id", ""),
            title=record.get("title", ""),
            description=record.get("description", ""),
            status=status,
            template_name=record.get("template_name"),
            linked_entity_ids=record.get("linked_entity_ids") or [],
            linked_alert_ids=record.get("linked_alert_ids") or [],
            tags=record.get("tags") or [],
            cell_count=record.get("cell_count", 0),
            cells=[],
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
            author=record.get("author", "user"),
        )

    def _record_to_cell(self, record: dict[str, Any]) -> NotebookCell:
        """Convert a Neo4j cell record to NotebookCell."""
        created_at = record.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(UTC)
        elif not created_at:
            created_at = datetime.now(UTC)

        updated_at = record.get("updated_at")
        if updated_at and isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                updated_at = None

        last_executed_at = record.get("last_executed_at")
        if last_executed_at and isinstance(last_executed_at, str):
            try:
                last_executed_at = datetime.fromisoformat(last_executed_at.replace("Z", "+00:00"))
            except ValueError:
                last_executed_at = None

        cell_type_str = record.get("cell_type", "markdown")
        try:
            cell_type = NotebookCellType(cell_type_str)
        except ValueError:
            cell_type = NotebookCellType.MARKDOWN

        execution_result = record.get("execution_result")
        if isinstance(execution_result, str):
            try:
                execution_result = json.loads(execution_result)
            except json.JSONDecodeError:
                execution_result = None

        return NotebookCell(
            id=record.get("id", ""),
            notebook_id=record.get("notebook_id", ""),
            cell_type=cell_type,
            content=record.get("content", ""),
            position=record.get("position", 0),
            title=record.get("title"),
            execution_result=execution_result,
            execution_count=record.get("execution_count", 0),
            last_executed_at=last_executed_at,
            linked_entity_id=record.get("linked_entity_id"),
            created_at=created_at,
            updated_at=updated_at,
        )

    def _log_change(self, notebook_id: str, change_type: str, cell_id: str | None = None, details: dict | None = None) -> None:
        """
        Log a change to the notebook for audit trail.

        Parameters
        ----------
        notebook_id:
            UUID of the notebook.
        change_type:
            Type of change.
        cell_id:
            Optional cell ID.
        details:
            Optional details dict.
        """
        now = datetime.now(UTC)
        change_id = str(uuid.uuid4())

        query = """
        CREATE (h:NotebookChangeHistory {
            id: $id,
            notebook_id: $notebook_id,
            change_type: $change_type,
            cell_id: $cell_id,
            details: $details,
            changed_at: $changed_at
        })
        """

        params = {
            "id": change_id,
            "notebook_id": notebook_id,
            "change_type": change_type,
            "cell_id": cell_id,
            "details": json.dumps(details or {}),
            "changed_at": now.isoformat(),
        }

        try:
            self.conn.run_query(query, params)
        except Exception as e:
            # Don't fail the operation if logging fails
            logger.warning(f"Failed to log notebook change: {e}")

    # ── Export Helpers ───────────────────────────────────────────────────────

    def _export_json(self, notebook: NotebookResponse) -> str:
        """Export notebook to JSON format."""
        export_data = {
            "id": notebook.id,
            "title": notebook.title,
            "description": notebook.description,
            "status": notebook.status.value,
            "template_name": notebook.template_name,
            "linked_entity_ids": notebook.linked_entity_ids,
            "linked_alert_ids": notebook.linked_alert_ids,
            "tags": notebook.tags,
            "author": notebook.author,
            "created_at": notebook.created_at.isoformat(),
            "updated_at": notebook.updated_at.isoformat() if notebook.updated_at else None,
            "completed_at": notebook.completed_at.isoformat() if notebook.completed_at else None,
            "cells": [
                {
                    "id": cell.id,
                    "cell_type": cell.cell_type.value,
                    "content": cell.content,
                    "position": cell.position,
                    "title": cell.title,
                    "execution_result": cell.execution_result,
                    "execution_count": cell.execution_count,
                    "last_executed_at": cell.last_executed_at.isoformat() if cell.last_executed_at else None,
                    "linked_entity_id": cell.linked_entity_id,
                }
                for cell in notebook.cells
            ],
        }
        return json.dumps(export_data, indent=2, ensure_ascii=False)

    def _export_markdown(self, notebook: NotebookResponse) -> str:
        """Export notebook to Markdown format."""
        lines = [
            f"# {notebook.title}",
            "",
            notebook.description,
            "",
            f"**Status:** {notebook.status.value}",
            f"**Author:** {notebook.author}",
            f"**Created:** {notebook.created_at.strftime('%Y-%m-%d %H:%M')}",
            "",
            "---",
            "",
        ]

        for cell in sorted(notebook.cells, key=lambda c: c.position):
            if cell.title:
                lines.append(f"## {cell.title}")
                lines.append("")

            if cell.cell_type == NotebookCellType.MARKDOWN:
                lines.append(cell.content)
            elif cell.cell_type == NotebookCellType.CYPHER_QUERY:
                lines.append("```cypher")
                lines.append(cell.content)
                lines.append("```")
                if cell.execution_result and cell.execution_result.get("data"):
                    lines.append("")
                    lines.append("**Results:**")
                    lines.append("")
                    data = cell.execution_result["data"]
                    if data:
                        # Table header
                        headers = list(data[0].keys())
                        lines.append("| " + " | ".join(headers) + " |")
                        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                        for row in data:
                            lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
            elif cell.cell_type in (NotebookCellType.RESULTS_TABLE, NotebookCellType.VISUALIZATION, NotebookCellType.CODE):
                lines.append(f"```{cell.cell_type.value}")
                lines.append(cell.content)
                lines.append("```")

            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _export_html(self, notebook: NotebookResponse) -> str:
        """Export notebook to HTML format."""
        html_parts = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            f"<title>{html.escape(notebook.title)}</title>",
            "<style>",
            "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }",
            "h1 { border-bottom: 2px solid #333; padding-bottom: 10px; }",
            "h2 { border-bottom: 1px solid #ddd; padding-bottom: 5px; margin-top: 30px; }",
            "pre { background: #f5f5f5; padding: 15px; border-radius: 4px; overflow-x: auto; }",
            "code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }",
            "table { border-collapse: collapse; width: 100%; margin: 15px 0; }",
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
            "th { background: #f0f0f0; }",
            ".cell { margin: 20px 0; padding: 15px; border: 1px solid #eee; border-radius: 4px; }",
            ".cell-title { font-weight: bold; margin-bottom: 10px; }",
            ".cell-type { color: #666; font-size: 0.9em; }",
            ".meta { color: #666; font-size: 0.9em; margin: 10px 0; }",
            "</style>",
            "</head>",
            "<body>",
            f"<h1>{html.escape(notebook.title)}</h1>",
            f"<p>{html.escape(notebook.description)}</p>",
            f'<div class="meta">',
            f"<p><strong>Status:</strong> {html.escape(notebook.status.value)} | ",
            f"<strong>Author:</strong> {html.escape(notebook.author)} | ",
            f"<strong>Created:</strong> {notebook.created_at.strftime('%Y-%m-%d %H:%M')}</p>",
            f"</div>",
            "<hr>",
        ]

        for cell in sorted(notebook.cells, key=lambda c: c.position):
            html_parts.append('<div class="cell">')

            if cell.title:
                html_parts.append(f'<div class="cell-title">{html.escape(cell.title)}</div>')

            html_parts.append(f'<div class="cell-type">[{cell.cell_type.value}]</div>')

            if cell.cell_type == NotebookCellType.MARKDOWN:
                html_parts.append(self._render_markdown(cell.content))
            elif cell.cell_type == NotebookCellType.CYPHER_QUERY:
                html_parts.append("<pre><code>")
                html_parts.append(html.escape(cell.content))
                html_parts.append("</code></pre>")

                if cell.execution_result and cell.execution_result.get("data"):
                    data = cell.execution_result["data"]
                    if data:
                        headers = list(data[0].keys())
                        html_parts.append("<table>")
                        html_parts.append("<tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr>")
                        for row in data:
                            html_parts.append("<tr>" + "".join(f"<td>{html.escape(str(row.get(h, '')))}</td>" for h in headers) + "</tr>")
                        html_parts.append("</table>")
            else:
                html_parts.append("<pre><code>")
                html_parts.append(html.escape(cell.content))
                html_parts.append("</code></pre>")

            html_parts.append("</div>")

        html_parts.extend(["</body>", "</html>"])

        return "\n".join(html_parts)

    # ──────────────────────────────────────────────────────────────────────────
    # Connection Discovery Integration
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_entity_ids_from_results(self, results: list[dict]) -> list[int]:
        """
        Extract Neo4j internal entity IDs from Cypher query results.

        Handles three formats returned by Neo4j Python driver:
        1. Column `id(n)` → int value
        2. Column containing a `neo4j.graph.Node` object → `.element_id` or `.id`
        3. Dict with `element_id` or `id` key (nested node data)
        """
        ids: set[int] = set()
        for row in results:
            if not isinstance(row, dict):
                continue
            for key, value in row.items():
                # Case 1: Neo4j Node object (from `RETURN n`)
                if hasattr(value, "element_id"):
                    # element_id is a string like "4:xxx:0" — try numeric id first
                    node_id = getattr(value, "id", None)
                    if isinstance(node_id, int):
                        ids.add(node_id)
                    continue

                # Case 2: Direct int/float value (from `RETURN id(n)`)
                if isinstance(value, (int, float)):
                    # Only accept as entity ID if column name suggests it's an ID
                    key_lower = key.lower()
                    if "element_id" in key_lower:
                        continue  # string ID, skip
                    if "id" in key_lower or key_lower in ("n", "c", "t", "p", "m", "b"):
                        ids.add(int(value))
                    continue

                # Case 3: Dict with embedded element_id or id (from nested node data)
                if isinstance(value, dict):
                    vid = value.get("id") or value.get("neo4j_id")
                    if isinstance(vid, (int, float)):
                        ids.add(int(vid))
                    continue

        return list(ids)

    def _get_linked_entity_ids(self, notebook_id: str, cell: Any) -> list[int]:
        """
        Get entity IDs to analyze for a CONNECTION_INSIGHT cell.

        Priority:
        1. cell.linked_entity_id (single entity → find its internal ID)
        2. Notebook's linked_entity_ids
        3. Entity IDs from other cells in this notebook
        """
        # Try cell-level linked entity
        if hasattr(cell, "linked_entity_id") and cell.linked_entity_id:
            ids = self._resolve_external_id_to_internal(cell.linked_entity_id)
            if ids:
                return ids

        # Fall back to notebook-level linked entities
        if hasattr(cell, "notebook_id"):
            nb_query = """
            MATCH (n:Notebook {id: $notebook_id})
            RETURN n.linked_entity_ids AS ids
            """
            nb_result = self.conn.run_query(nb_query, {"notebook_id": cell.notebook_id})
            if nb_result and nb_result[0].get("ids"):
                raw_ids = nb_result[0]["ids"]
                resolved: list[int] = []
                for eid in raw_ids:
                    resolved.extend(self._resolve_external_id_to_internal(eid))
                if resolved:
                    return resolved

        # Last resort: gather entity IDs from all cypher_query cells in notebook
        return self._gather_ids_from_cypher_cells(notebook_id)

    def _resolve_external_id_to_internal(self, external_id: str) -> list[int]:
        """Resolve a business ID (cf, cig, cup) to Neo4j internal IDs."""
        query = """
        MATCH (n)
        WHERE n.id = $eid OR n.cf = $eid OR n.cig = $eid OR n.cup = $eid
        RETURN id(n) AS neo4j_id
        """
        results = self.conn.run_query(query, {"eid": external_id})
        return [r["neo4j_id"] for r in results if "neo4j_id" in r]

    def _gather_ids_from_cypher_cells(self, notebook_id: str) -> list[int]:
        """Extract all entity IDs from previously executed cypher cells in the notebook."""
        query = """
        MATCH (c:NotebookCell {notebook_id: $notebook_id})
        WHERE c.cell_type = 'cypher_query' AND c.execution_result IS NOT NULL
        RETURN c.execution_result AS result
        """
        results = self.conn.run_query(query, {"notebook_id": notebook_id})
        ids: list[int] = []
        for row in results:
            try:
                exec_result = json.loads(row["result"]) if isinstance(row["result"], str) else row["result"]
                data = exec_result.get("data", [])
                ids.extend(self._extract_entity_ids_from_results(data))
            except (json.JSONDecodeError, TypeError):
                continue
        return ids

    def _discover_connections(self, entity_ids: list[int]) -> list:
        """
        Discover implicit connections between a list of Neo4j internal IDs.

        Returns a list of ImplicitConnection objects.
        """
        from paladino.etl.connection_resolver import ConnectionResolver

        resolver = ConnectionResolver(db=self.conn, llm_manager=None)

        # Create dummy EntityMatch objects for each ID
        dummy_matches = [
            EntityMatch(
                extracted_entity_id=f"auto_{eid}",
                extracted_entity_type="Company",
                matched_neo4j_id=str(eid),
                matched_neo4j_label="Company",
                match_method="exact_cf",
                confidence=1.0,
            )
            for eid in entity_ids
        ]
        resolver._matches = dummy_matches

        connections = resolver._discover_implicit_connections("notebook_auto")
        # Convert to serializable dicts
        return [c.model_dump() for c in connections]


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────

def get_notebook_service() -> NotebookService:
    """Get a NotebookService instance using the default Neo4j connection."""
    from paladino.db import Neo4jConnection
    conn = Neo4jConnection()
    return NotebookService(conn)
