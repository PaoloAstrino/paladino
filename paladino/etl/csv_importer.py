"""
Feature 5.3 — CSV / Custom Data Import
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Auto-detects the target node type from CSV headers (Company, Tender, or generic
CustomRecord), fuzzy-maps columns to known graph fields, and MERGEs rows into
Neo4j.  Reuses the column-variant sets already established in
``paladino/etl/corporate/download.py``.
"""

from __future__ import annotations

import csv
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

from paladino.db import Neo4jConnection


# ---------------------------------------------------------------------------
# String normaliser (mirrors download.py _norm)
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Lower-case and strip spaces / underscores / hyphens / dots."""
    return re.sub(r"[\s_\-\.]+", "", name.lower())


# ---------------------------------------------------------------------------
# Known column variants per semantic field
# ---------------------------------------------------------------------------

_COMPANY_CF_VARIANTS: frozenset[str] = frozenset({
    "cfazienda", "companycf", "codicefiscaleazienda", "cf",
    "aziendacf", "partitaiva", "piva", "vatnumber", "codicefiscale",
})
_COMPANY_NAME_VARIANTS: frozenset[str] = frozenset({
    "nome", "nomeazienda", "ragionesociale", "denominazione",
    "companyname", "name", "ditta",
})
_COMPANY_ATECO_VARIANTS: frozenset[str] = frozenset({
    "ateco", "codiceateco", "sectorcode", "sector", "settore",
})
_COMPANY_REGIONE_VARIANTS: frozenset[str] = frozenset({
    "regione", "region", "provincia", "province",
})

_TENDER_CIG_VARIANTS: frozenset[str] = frozenset({
    "cig", "codicecig", "tenderid", "tendercode",
})
_TENDER_OGGETTO_VARIANTS: frozenset[str] = frozenset({
    "oggetto", "oggettoappalto", "description", "descrizione",
    "titolo", "title",
})
_TENDER_IMPORTO_VARIANTS: frozenset[str] = frozenset({
    "importo", "valore", "amount", "value", "importoaggiudicazione",
    "importobase",
})
_TENDER_BUYER_VARIANTS: frozenset[str] = frozenset({
    "stazione", "stazione_appaltante", "buyername", "buyer",
    "amministrazione", "ente", "ente_appaltante",
})

# Ordered map: (semantic_field, node_type, variant_set)
_FIELD_REGISTRY: list[tuple[str, str, frozenset[str]]] = [
    ("cf",          "Company", _COMPANY_CF_VARIANTS),
    ("nome",        "Company", _COMPANY_NAME_VARIANTS),
    ("ateco",       "Company", _COMPANY_ATECO_VARIANTS),
    ("regione",     "Company", _COMPANY_REGIONE_VARIANTS),
    ("cig",         "Tender",  _TENDER_CIG_VARIANTS),
    ("oggetto",     "Tender",  _TENDER_OGGETTO_VARIANTS),
    ("importo",     "Tender",  _TENDER_IMPORTO_VARIANTS),
    ("buyer_name",  "Tender",  _TENDER_BUYER_VARIANTS),
]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FieldMap:
    """Maps one CSV column to one graph field with a confidence score."""
    csv_column: str
    graph_field: str
    node_type: str        # Company | Tender | CustomRecord
    confidence: float     # 1.0 = exact variant hit, 0.7 = partial


@dataclass
class ImportResult:
    rows_read: int = 0
    rows_merged: int = 0
    rows_created: int = 0
    rows_skipped: int = 0
    warnings: List[str] = field(default_factory=list)
    column_map_used: Dict[str, str] = field(default_factory=dict)
    node_type_detected: str = "CustomRecord"
    dry_run: bool = False
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Core importer
# ---------------------------------------------------------------------------

class CustomCSVImporter:
    """
    Import an arbitrary CSV file into the Neo4j graph.

    Parameters
    ----------
    db :
        An open :class:`~paladino.db.Neo4jConnection` (or ``None`` to open
        one automatically from environment settings).
    batch_size :
        Number of rows sent to Neo4j per transaction.
    """

    BATCH_SIZE = 500

    def __init__(
        self,
        db: Optional[Neo4jConnection] = None,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        from paladino.config import settings  # lazy to avoid circular at module load

        self.db = db or Neo4jConnection(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
        )
        self.batch_size = batch_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def import_file(
        self,
        path: Path | str,
        column_map_override: Optional[Dict[str, str]] = None,
        node_type_override: Optional[str] = None,
        dry_run: bool = False,
    ) -> ImportResult:
        """
        Read *path* and MERGE its rows into Neo4j.

        Parameters
        ----------
        path : Path or str
            Absolute path to the CSV file (UTF-8, auto-detects delimiter).
        column_map_override : dict, optional
            Explicit ``{csv_column: graph_field}`` overrides applied *after*
            auto-detection (take priority over fuzzy results).
        node_type_override : str, optional
            Force node type to ``"Company"``, ``"Tender"``, or ``"CustomRecord"``.
        dry_run : bool
            If ``True``, parse and map but do not write to Neo4j.

        Returns
        -------
        ImportResult
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        result = ImportResult(dry_run=dry_run)

        headers, rows = self._read_csv(path, result)
        if not rows:
            result.warnings.append("CSV file is empty or unreadable.")
            return result

        result.rows_read = len(rows)

        # Build column → field map
        field_maps = self._build_column_map(headers, column_map_override)
        node_type = node_type_override or self._auto_detect_node_type(field_maps)
        result.node_type_detected = node_type
        result.column_map_used = {fm.csv_column: fm.graph_field for fm in field_maps}

        if not field_maps:
            result.warnings.append(
                "No columns could be mapped to known graph fields. "
                "All rows saved as CustomRecord with raw properties."
            )

        if dry_run:
            logger.info(
                f"[dry_run] Would import {result.rows_read} rows as {node_type} "
                f"with map: {result.column_map_used}"
            )
            # Count rows that have a primary key
            pk_col = self._primary_key_column(node_type, field_maps)
            for row in rows:
                if pk_col and row.get(pk_col):
                    result.rows_merged += 1
                else:
                    result.rows_created += 1
            return result

        # Write to graph
        self._load_rows(rows, field_maps, node_type, result)
        return result

    # ------------------------------------------------------------------
    # Column mapping
    # ------------------------------------------------------------------

    def _build_column_map(
        self,
        headers: Sequence[str],
        override: Optional[Dict[str, str]],
    ) -> List[FieldMap]:
        """Return FieldMap list for matched columns (duplicates discarded)."""
        used_fields: set[str] = set()
        maps: List[FieldMap] = []

        for col in headers:
            col_norm = _norm(col)

            # 1. Explicit override wins
            if override and col in override:
                gf = override[col]
                node_type = self._field_to_node_type(gf)
                maps.append(FieldMap(col, gf, node_type, 1.0))
                used_fields.add(gf)
                continue

            # 2. Fuzzy match against registry
            for graph_field, node_type, variants in _FIELD_REGISTRY:
                if graph_field in used_fields:
                    continue
                if col_norm in variants:
                    maps.append(FieldMap(col, graph_field, node_type, 1.0))
                    used_fields.add(graph_field)
                    break
                # Partial match: col_norm starts with or ends with a variant substring
                for v in variants:
                    if col_norm.startswith(v) or col_norm.endswith(v) or v.startswith(col_norm):
                        maps.append(FieldMap(col, graph_field, node_type, 0.7))
                        used_fields.add(graph_field)
                        break
                else:
                    continue
                break

        return maps

    @staticmethod
    def _field_to_node_type(graph_field: str) -> str:
        company_fields = {"cf", "nome", "ateco", "regione"}
        tender_fields = {"cig", "oggetto", "importo", "buyer_name"}
        if graph_field in company_fields:
            return "Company"
        if graph_field in tender_fields:
            return "Tender"
        return "CustomRecord"

    @staticmethod
    def _auto_detect_node_type(field_maps: List[FieldMap]) -> str:
        company_score = sum(1 for fm in field_maps if fm.node_type == "Company")
        tender_score = sum(1 for fm in field_maps if fm.node_type == "Tender")
        if company_score == 0 and tender_score == 0:
            return "CustomRecord"
        return "Company" if company_score >= tender_score else "Tender"

    @staticmethod
    def _primary_key_column(node_type: str, field_maps: List[FieldMap]) -> Optional[str]:
        pk_field = {"Company": "cf", "Tender": "cig"}.get(node_type)
        if not pk_field:
            return None
        for fm in field_maps:
            if fm.graph_field == pk_field:
                return fm.csv_column
        return None

    # ------------------------------------------------------------------
    # CSV reading
    # ------------------------------------------------------------------

    @staticmethod
    def _read_csv(
        path: Path, result: ImportResult
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        lines = raw.splitlines()
        if not lines:
            return [], []

        sample = "\n".join(lines[:3])
        delimiter = ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","

        reader = csv.DictReader(raw.splitlines(), delimiter=delimiter)
        headers = list(reader.fieldnames or [])
        rows: List[Dict[str, Any]] = []
        for i, row in enumerate(reader):
            cleaned = {k.strip(): (v.strip() if isinstance(v, str) else v)
                       for k, v in row.items() if k is not None}
            rows.append(cleaned)
            if i > 0 and i % 50_000 == 0:
                logger.debug(f"Read {i:,} rows from {path.name}…")

        return headers, rows

    # ------------------------------------------------------------------
    # Neo4j loading
    # ------------------------------------------------------------------

    def _load_rows(
        self,
        rows: List[Dict[str, Any]],
        field_maps: List[FieldMap],
        node_type: str,
        result: ImportResult,
    ) -> None:
        pk_col = self._primary_key_column(node_type, field_maps)
        import_ts = datetime.now(timezone.utc).isoformat()

        batch: List[Dict[str, Any]] = []

        def flush(b: List[Dict[str, Any]]) -> None:
            if not b:
                return
            if node_type == "Company":
                self._merge_company_batch(b, result)
            elif node_type == "Tender":
                self._merge_tender_batch(b, result)
            else:
                self._merge_custom_batch(b, result)

        for row in rows:
            # Remap keys
            remapped: Dict[str, Any] = {}
            for fm in field_maps:
                val = row.get(fm.csv_column)
                if val is not None and val != "":
                    remapped[fm.graph_field] = val

            # Carry unmapped columns as extras
            mapped_cols = {fm.csv_column for fm in field_maps}
            extras = {
                f"_extra_{k}": v
                for k, v in row.items()
                if k not in mapped_cols and v
            }
            remapped.update(extras)
            remapped["_import_ts"] = import_ts
            remapped["_import_source"] = "custom_csv_import"

            if pk_col and not row.get(pk_col):
                # Assign synthetic import_id for generic or key-less rows
                remapped["import_id"] = f"import_{uuid.uuid4().hex[:12]}"
                result.rows_created += 1
            else:
                result.rows_merged += 1

            batch.append(remapped)

            if len(batch) >= self.batch_size:
                flush(batch)
                batch = []

        flush(batch)

    def _merge_company_batch(self, batch: List[Dict], result: ImportResult) -> None:
        query = """
        UNWIND $rows AS row
        MERGE (c:Company {cf: row.cf})
        ON CREATE SET
            c.nome_normalizzato    = row.nome,
            c.ateco                = row.ateco,
            c.regione              = row.regione,
            c.source               = ['custom_csv_import'],
            c.import_ts            = row._import_ts,
            c.risk_score           = 0.0
        ON MATCH SET
            c.nome_normalizzato    = coalesce(c.nome_normalizzato, row.nome),
            c.ateco                = coalesce(c.ateco, row.ateco),
            c.regione              = coalesce(c.regione, row.regione),
            c.source               = apoc.coll.toSet(coalesce(c.source, []) + ['custom_csv_import']),
            c.import_ts            = row._import_ts
        RETURN count(c) AS n
        """
        try:
            self.db.run_query(query, {"rows": batch})
        except Exception as exc:  # noqa: BLE001
            msg = f"Company MERGE batch error: {exc}"
            logger.warning(msg)
            result.warnings.append(msg)
            result.rows_merged -= len(batch)
            result.rows_skipped += len(batch)

    def _merge_tender_batch(self, batch: List[Dict], result: ImportResult) -> None:
        query = """
        UNWIND $rows AS row
        MERGE (t:Tender {cig: row.cig})
        ON CREATE SET
            t.oggetto              = row.oggetto,
            t.importo              = toFloat(row.importo),
            t.buyer_name           = row.buyer_name,
            t.source               = ['custom_csv_import'],
            t.import_ts            = row._import_ts
        ON MATCH SET
            t.oggetto              = coalesce(t.oggetto, row.oggetto),
            t.importo              = coalesce(t.importo, toFloat(row.importo)),
            t.buyer_name           = coalesce(t.buyer_name, row.buyer_name),
            t.source               = apoc.coll.toSet(coalesce(t.source, []) + ['custom_csv_import']),
            t.import_ts            = row._import_ts
        RETURN count(t) AS n
        """
        try:
            self.db.run_query(query, {"rows": batch})
        except Exception as exc:  # noqa: BLE001
            msg = f"Tender MERGE batch error: {exc}"
            logger.warning(msg)
            result.warnings.append(msg)
            result.rows_merged -= len(batch)
            result.rows_skipped += len(batch)

    def _merge_custom_batch(self, batch: List[Dict], result: ImportResult) -> None:
        query = """
        UNWIND $rows AS row
        MERGE (n:CustomRecord {import_id: row.import_id})
        SET n += row,
            n.source    = 'custom_csv_import',
            n.import_ts = row._import_ts
        RETURN count(n) AS n
        """
        try:
            self.db.run_query(query, {"rows": batch})
        except Exception as exc:  # noqa: BLE001
            msg = f"CustomRecord MERGE batch error: {exc}"
            logger.warning(msg)
            result.warnings.append(msg)
            result.rows_created -= len(batch)
            result.rows_skipped += len(batch)
