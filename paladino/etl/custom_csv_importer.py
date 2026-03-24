from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from neo4j import Driver
from loguru import logger


class CustomCSVImporter:
    """Import custom CSV datasets into core domain nodes with explicit field mapping."""

    _TARGET_TO_LABEL = {
        "company": "Company",
        "tender": "Tender",
        "project": "Project",
    }

    _TARGET_DEFAULT_KEYS = {
        "company": ["piva", "cf"],
        "tender": ["cig"],
        "project": ["cup"],
    }

    _TARGET_REQUIRED_PROPERTIES = {
        "company": [],
        "tender": ["importo"],
        "project": [],
    }

    # SECURITY FIX (SEC-009): Allowlist of valid key properties to prevent Cypher injection
    _ALLOWED_KEY_PROPERTIES = {
        "cf", "piva", "cig", "cup", "id", "nome_normalizzato",
        "codice_fiscale", "partita_iva", "ragione_sociale",
        "titolo", "oggetto", "importo", "data",
    }

    def __init__(self, driver: Driver):
        self.driver = driver

    def import_csv(
        self,
        source: str,
        target: str,
        mapping: dict[str, str],
        key_property: str | None = None,
        delimiter: str | None = None,
        dry_run: bool = False,
        max_rows: int | None = None,
    ) -> dict[str, Any]:
        target_normalized = target.strip().lower()
        if target_normalized not in self._TARGET_TO_LABEL:
            raise ValueError(f"Unsupported target: {target}")
        if not mapping:
            raise ValueError("mapping must not be empty")

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"CSV source does not exist: {source}")

        rows, headers, used_delimiter = self._read_csv(path, delimiter, max_rows=max_rows)
        self._validate_mapping(headers, mapping)
        self._validate_required_properties(target_normalized, mapping)

        effective_key = self._resolve_key_property(target_normalized, mapping, key_property)
        label = self._TARGET_TO_LABEL[target_normalized]

        if dry_run:
            return {
                "mode": "preview",
                "target": target_normalized,
                "label": label,
                "source": str(path),
                "delimiter": used_delimiter,
                "headers": headers,
                "rows_total": len(rows),
                "effective_key_property": effective_key,
                "preview": [self._map_row(row, mapping) for row in rows[:5]],
            }

        stats = self._merge_rows(
            source=str(path),
            label=label,
            rows=rows,
            mapping=mapping,
            key_property=effective_key,
        )
        stats.update(
            {
                "mode": "imported",
                "target": target_normalized,
                "label": label,
                "source": str(path),
                "delimiter": used_delimiter,
                "headers": headers,
                "rows_total": len(rows),
                "effective_key_property": effective_key,
            }
        )
        return stats

    def _read_csv(
        self,
        path: Path,
        delimiter: str | None,
        max_rows: int | None,
    ) -> tuple[list[dict[str, str]], list[str], str]:
        raw = path.read_text(encoding="utf-8-sig", errors="ignore")
        lines = raw.splitlines()
        if not lines:
            return [], [], delimiter or ","

        effective_delimiter = delimiter or self._detect_delimiter(lines)
        reader = csv.DictReader(lines, delimiter=effective_delimiter)
        rows = list(reader)
        if max_rows is not None:
            rows = rows[:max_rows]
        headers = [header.strip() for header in (reader.fieldnames or []) if header and header.strip()]
        return rows, headers, effective_delimiter

    @staticmethod
    def _detect_delimiter(lines: list[str]) -> str:
        sample = "\n".join(lines[:3])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
            return dialect.delimiter
        except csv.Error:
            return ";" if ";" in lines[0] else ","

    @staticmethod
    def _validate_mapping(headers: list[str], mapping: dict[str, str]) -> None:
        available = {h.strip() for h in headers}
        missing = sorted({column.strip() for column in mapping.values()} - available)
        if missing:
            raise ValueError(f"Mapping references unknown CSV columns: {missing}")

    def _resolve_key_property(
        self,
        target: str,
        mapping: dict[str, str],
        key_property: str | None,
    ) -> str:
        if key_property:
            if key_property not in mapping:
                raise ValueError(f"key_property '{key_property}' must be present in mapping")
            
            # SECURITY FIX (SEC-009): Validate key_property against allowlist
            if key_property not in self._ALLOWED_KEY_PROPERTIES:
                raise ValueError(
                    f"Invalid key_property '{key_property}'. "
                    f"Must be one of: {', '.join(sorted(self._ALLOWED_KEY_PROPERTIES))}"
                )
            return key_property

        for candidate in self._TARGET_DEFAULT_KEYS[target]:
            if candidate in mapping:
                return candidate

        raise ValueError(
            f"Unable to infer key_property for target '{target}'. "
            f"Provide key_property explicitly or map one of {self._TARGET_DEFAULT_KEYS[target]}"
        )

    def _validate_required_properties(self, target: str, mapping: dict[str, str]) -> None:
        required = self._TARGET_REQUIRED_PROPERTIES.get(target, [])
        missing = [prop for prop in required if prop not in mapping]
        if missing:
            raise ValueError(
                f"Missing required mapping properties for target '{target}': {missing}. "
                "Please map these fields before import."
            )

    @staticmethod
    def _map_row(row: dict[str, str], mapping: dict[str, str]) -> dict[str, Any]:
        mapped: dict[str, Any] = {}
        for graph_property, csv_column in mapping.items():
            value = (row.get(csv_column) or "").strip()
            mapped[graph_property] = value
        return mapped

    def _merge_rows(
        self,
        source: str,
        label: str,
        rows: list[dict[str, str]],
        mapping: dict[str, str],
        key_property: str,
    ) -> dict[str, int]:
        processed = 0
        skipped_missing_key = 0
        merged_nodes = 0

        # SECURITY FIX (SEC-009): key_property is now validated against allowlist
        # Safe to use in query construction since it's been validated
        query = f"""
        MERGE (n:{label} {{{key_property}: $key_value}})
        SET n += $mapped_props,
            n.id = coalesce(n.id, $node_id),
            n.source = coalesce(n.source, 'CUSTOM_CSV'),
            n.last_custom_import_at = datetime(),
            n.last_custom_import_source = $source
        RETURN n
        """

        with self.driver.session() as session:
            for row in rows:
                mapped = self._map_row(row, mapping)
                key_value = str(mapped.get(key_property, "")).strip()
                if not key_value:
                    skipped_missing_key += 1
                    continue

                result = session.run(
                    query,
                    key_value=key_value,
                    mapped_props=mapped,
                    node_id=key_value,
                    source=source,
                )
                result.consume()
                processed += 1
                merged_nodes += 1

        return {
            "rows_processed": processed,
            "rows_skipped_missing_key": skipped_missing_key,
            "nodes_merged": merged_nodes,
        }
