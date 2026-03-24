"""
Corporate structure transformer — parse CSVs into normalised DataFrames.

The transformer accepts any CSV that passes schema detection in download.py.
It emits three DataFrames ready for CorporateLoader:

  persons_df       — Person nodes
  represents_df    — Person-[:REPRESENTS]->Company edges
  shareholding_df  — (Person|Company)-[:SHAREHOLDER_OF]->Company edges

When a file has ambiguous or missing columns the transformer soft-skips those
rows with a warning rather than raising an exception.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

import polars as pl
from loguru import logger

from paladino.etl.corporate.download import (
    SourceFile,
    _norm,
    _COMPANY_CF_VARIANTS,
    _PERSON_CF_VARIANTS,
    _SHAREHOLDERCF_VARIANTS,
    _ROLE_VARIANTS,
    _QUOTA_VARIANTS,
)


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _find_col(columns: List[str], variants: set[str]) -> Optional[str]:
    """Return the first column whose normalised name is in variants, or None."""
    for c in columns:
        if _norm(c) in variants:
            return c
    return None


def _read_csv(path, **kwargs) -> pl.DataFrame:
    """Read a CSV, auto-detecting delimiter."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        header = fh.readline()
    sep = ";" if header.count(";") > header.count(",") else ","
    return pl.read_csv(path, separator=sep, ignore_errors=True, **kwargs)


# ─────────────────────────────────────────────────────────
# Transformer
# ─────────────────────────────────────────────────────────

class CorporateTransformer:
    """
    Transform corporate-structure CSV files into graph-ready DataFrames.

    Usage::

        from paladino.etl.corporate.download import CorporateSourceDiscovery
        from paladino.etl.corporate.transform import CorporateTransformer

        discovery = CorporateSourceDiscovery()
        result    = discovery.discover()
        tf        = CorporateTransformer()
        data      = tf.transform_all(result.local_files)
        # data["persons_df"], data["represents_df"], data["shareholding_df"]
    """

    SOURCE_TAG = "corporate_csv"

    def __init__(self, dataset_version: str = "2026-02") -> None:
        self.dataset_version = dataset_version
        self.retrieval_date  = datetime.now().isoformat()

    # ── public interface ─────────────────────────────────

    def transform_all(
        self,
        source_files: List[SourceFile],
    ) -> Dict[str, pl.DataFrame]:
        """
        Process all files from a discovery run.

        Returns a dict with keys:
          ``persons_df``, ``represents_df``, ``shareholding_df``

        Always returns the dict even when all frames are empty.
        """
        all_persons:     List[pl.DataFrame] = []
        all_represents:  List[pl.DataFrame] = []
        all_shareholder: List[pl.DataFrame] = []

        for sf in source_files:
            if sf.schema_type == "unknown":
                logger.warning(
                    f"Skipping '{sf.path.name}' (unknown schema). "
                    "Check that it has cf_azienda + cf_persona + ruolo columns."
                )
                continue

            logger.info(f"Transforming {sf.path.name}  [{sf.schema_type}]  ≈{sf.row_estimate:,} rows")
            try:
                df = _read_csv(sf.path)
                if df.is_empty():
                    logger.warning(f"'{sf.path.name}' is empty — skipping.")
                    continue

                if sf.schema_type in ("directors", "generic"):
                    ps, rs = self._transform_directors(df, sf.path.name)
                    all_persons.append(ps)
                    all_represents.append(rs)

                if sf.schema_type in ("shareholders", "generic"):
                    sh = self._transform_shareholders(df, sf.path.name)
                    all_shareholder.append(sh)

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    f"Failed to transform '{sf.path.name}': {exc}\n"
                    "The file will be skipped — fix the format and re-run."
                )

        def _vstack(frames: List[pl.DataFrame], schema: dict) -> pl.DataFrame:
            valid = [f for f in frames if not f.is_empty()]
            if not valid:
                return pl.DataFrame(schema=schema)
            return pl.concat(valid, how="diagonal").unique()

        persons_schema = {
            "cf": pl.Utf8, "nome": pl.Utf8, "cognome": pl.Utf8,
            "id": pl.Utf8, "source": pl.Utf8, "dataset_version": pl.Utf8,
        }
        represents_schema = {
            "person_cf": pl.Utf8, "company_cf": pl.Utf8, "ruolo": pl.Utf8,
            "data_inizio": pl.Utf8, "data_fine": pl.Utf8, "source": pl.Utf8,
        }
        shareholding_schema = {
            "source_cf": pl.Utf8, "company_cf": pl.Utf8, "quota": pl.Float64,
            "data_rilevazione": pl.Utf8, "source": pl.Utf8,
        }

        return {
            "persons_df":      _vstack(all_persons,     persons_schema),
            "represents_df":   _vstack(all_represents,  represents_schema),
            "shareholding_df": _vstack(all_shareholder, shareholding_schema),
        }

    # ── private helpers ──────────────────────────────────

    def _transform_directors(
        self,
        df: pl.DataFrame,
        filename: str,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Parse director / board-member CSV into persons + represents frames."""
        cols = df.columns

        col_company_cf = _find_col(cols, _COMPANY_CF_VARIANTS)
        col_person_cf  = _find_col(cols, _PERSON_CF_VARIANTS)
        col_role       = _find_col(cols, _ROLE_VARIANTS)

        if not all([col_company_cf, col_person_cf, col_role]):
            logger.warning(
                f"'{filename}': directors schema detected but required columns missing "
                f"(company_cf={col_company_cf}, person_cf={col_person_cf}, role={col_role}). "
                "Returning empty frames."
            )
            return pl.DataFrame(), pl.DataFrame()

        # Optional columns
        col_nome    = next((c for c in cols if _norm(c) == "nome"),    None)
        col_cognome = next((c for c in cols if _norm(c) == "cognome"), None)
        col_start   = next((c for c in cols if _norm(c) in {"datainizio", "datastart", "inizio"}), None)
        col_end     = next((c for c in cols if _norm(c) in {"datafine",   "dataend",  "fine"}),    None)

        # Clean CFs
        df = df.filter(
            pl.col(col_person_cf).is_not_null() &
            (pl.col(col_person_cf).cast(pl.Utf8).str.strip_chars() != "")
        )

        # Build persons
        person_cols = [
            pl.col(col_person_cf).cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("cf"),
            (pl.col(col_nome).cast(pl.Utf8).str.strip_chars()
             if col_nome else pl.lit("")).alias("nome"),
            (pl.col(col_cognome).cast(pl.Utf8).str.strip_chars()
             if col_cognome else pl.lit("")).alias("cognome"),
        ]
        persons = (
            df.select(person_cols)
            .unique(subset=["cf"])
            .with_columns([
                pl.Series("id", [str(uuid.uuid4()) for _ in range(len(df.select(person_cols).unique(subset=["cf"])))]),
                pl.lit(self.SOURCE_TAG).alias("source"),
                pl.lit(self.dataset_version).alias("dataset_version"),
            ])
        )

        # Build represents
        represents_cols = [
            pl.col(col_person_cf).cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("person_cf"),
            pl.col(col_company_cf).cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("company_cf"),
            pl.col(col_role).cast(pl.Utf8).str.strip_chars().alias("ruolo"),
            (pl.col(col_start).cast(pl.Utf8) if col_start else pl.lit(None)).alias("data_inizio"),
            (pl.col(col_end).cast(pl.Utf8)   if col_end   else pl.lit(None)).alias("data_fine"),
            pl.lit(self.SOURCE_TAG).alias("source"),
        ]
        represents = (
            df.select(represents_cols)
            .filter(
                pl.col("company_cf").is_not_null() &
                (pl.col("company_cf").str.strip_chars() != "")
            )
        )

        logger.info(
            f"  ↳ directors: {len(persons)} persons, {len(represents)} REPRESENTS edges"
        )
        return persons, represents

    def _transform_shareholders(
        self,
        df: pl.DataFrame,
        filename: str,
    ) -> pl.DataFrame:
        """Parse shareholder CSV into a shareholding frame."""
        cols = df.columns

        col_shareholder = _find_col(cols, _SHAREHOLDERCF_VARIANTS)
        col_company_cf  = _find_col(cols, _COMPANY_CF_VARIANTS)
        col_quota       = _find_col(cols, _QUOTA_VARIANTS)

        if not all([col_shareholder, col_company_cf, col_quota]):
            logger.warning(
                f"'{filename}': shareholders schema detected but required columns missing "
                f"(shareholder={col_shareholder}, company_cf={col_company_cf}, quota={col_quota}). "
                "Returning empty frame."
            )
            return pl.DataFrame()

        col_date = next(
            (c for c in cols if _norm(c) in {"datarilevazione", "data", "date"}), None
        )

        df = df.filter(
            pl.col(col_shareholder).is_not_null() &
            (pl.col(col_shareholder).cast(pl.Utf8).str.strip_chars() != "") &
            pl.col(col_company_cf).is_not_null() &
            (pl.col(col_company_cf).cast(pl.Utf8).str.strip_chars() != "")
        )

        shareholding_cols = [
            pl.col(col_shareholder).cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("source_cf"),
            pl.col(col_company_cf).cast(pl.Utf8).str.strip_chars().str.to_uppercase().alias("company_cf"),
            pl.col(col_quota).cast(pl.Float64).clip(0.0, 100.0).alias("quota"),
            (pl.col(col_date).cast(pl.Utf8) if col_date else pl.lit(self.retrieval_date)).alias("data_rilevazione"),
            pl.lit(self.SOURCE_TAG).alias("source"),
        ]
        shareholding = df.select(shareholding_cols)

        logger.info(f"  ↳ shareholders: {len(shareholding)} SHAREHOLDER_OF edges")
        return shareholding
