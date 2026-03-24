"""
OpenCUP transformation - Convert OpenCUP CSV to normalized graph schema.
"""

from datetime import datetime

import polars as pl
from loguru import logger


class OpencupTransformer:
    """Transform OpenCUP CSV to normalized DataFrames."""

    # Expected OpenCUP CSV columns (may vary by actual API)
    COLUMN_MAPPING = {
        "CUP": "cup",
        "DESCRIZIONE_SINTETICA_CUP": "titolo",
        "TITOLO_PROGETTO": "titolo",
        "DESCRIZIONE": "descrizione",
        "COSTO_PROGETTO": "importo_previsto",
        "IMPORTO_PREVISTO": "importo_previsto",
        "FINANZIAMENTO_PROGETTO": "importo_finanziato",
        "IMPORTO_FINANZIATO": "importo_finanziato",
        "STATO_PROGETTO": "stato",
        "SETTORE_INTERVENTO": "settore",
        "SETTORE": "settore",
        "SOTTOSETTORE_INTERVENTO": "sottosettore",
        "NATURA_INTERVENTO": "categoria",
        "STRUMENTO_PROGRAMMAZIONE": "fondi_comunitari",
        "FONDI_UE": "fondi_comunitari",
        "DATA_INIZIO": "data_inizio",
        "DATA_FINE": "data_fine",
        "REGIONE": "regione",
        "PROVINCIA": "provincia",
    }

    def __init__(self, dataset_version: str = "2026-01"):
        """
        Initialize transformer.

        Args:
            dataset_version: Version identifier for this dataset
        """
        self.source = "OpenCUP"
        self.dataset_version = dataset_version
        self.retrieval_date = datetime.now().isoformat()

    def transform(self, df: pl.DataFrame) -> dict[str, pl.DataFrame]:
        """
        Transform OpenCUP DataFrame.

        Args:
            df: Raw OpenCUP DataFrame

        Returns:
            Dictionary of DataFrames: projects, funding_sources
        """
        logger.info(f"Transforming {len(df)} OpenCUP projects")

        # Normalize column names
        df = self._normalize_columns(df)

        return {
            "projects": self.extract_projects(df),
            "funding_sources": self.extract_funding_sources(df),
        }

    def transform_projects(self, df: pl.DataFrame) -> pl.DataFrame:
        """Alias for extract_projects to support unit tests."""
        df = self._normalize_columns(df)
        return self.extract_projects(df)

    def _normalize_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        """Normalize column names to standard schema."""
        # Try to map known columns
        rename_map = {}

        for col in df.columns:
            col_upper = col.upper()
            if col_upper in self.COLUMN_MAPPING:
                rename_map[col] = self.COLUMN_MAPPING[col_upper]

        if rename_map:
            df = df.rename(rename_map)

        return df

    def extract_projects(self, df: pl.DataFrame) -> pl.DataFrame:
        """Extract project nodes from OpenCUP data using Polars columnar ops."""
        if df.is_empty():
            return pl.DataFrame()

        import uuid

        # Ensure we have a cup column
        if "cup" not in df.columns:
            logger.error("No 'cup' column found in DataFrame")
            return pl.DataFrame()

        # Filter out rows with no CUP
        df = df.filter(pl.col("cup").is_not_null() & (pl.col("cup") != ""))

        # Transform using columnar operations
        count = len(df)
        ids = [str(uuid.uuid4()) for _ in range(count)]

        # Helper to ensure columns exist before select
        available_cols = set(df.columns)

        cols = [pl.Series(name="id", values=ids)]
        cols.append(pl.col("cup"))

        if "titolo" in available_cols:
            cols.append(pl.col("titolo").fill_null("").alias("titolo"))
        else:
            cols.append(pl.lit("").alias("titolo"))

        if "descrizione" in available_cols:
            cols.append(pl.col("descrizione").fill_null("").alias("descrizione"))
        else:
            cols.append(pl.lit("").alias("descrizione"))

        if "importo_previsto" in available_cols:
            cols.append(pl.col("importo_previsto").cast(pl.Float64, strict=False).fill_null(0.0))
        else:
            cols.append(pl.lit(0.0).alias("importo_previsto"))

        if "importo_finanziato" in available_cols:
            cols.append(pl.col("importo_finanziato").cast(pl.Float64, strict=False).fill_null(0.0))
        else:
            cols.append(pl.lit(0.0).alias("importo_finanziato"))

        if "data_inizio" in available_cols:
            cols.append(pl.col("data_inizio"))
        else:
            cols.append(pl.lit(None).alias("data_inizio"))

        if "data_fine" in available_cols:
            cols.append(pl.col("data_fine"))
        else:
            cols.append(pl.lit(None).alias("data_fine"))

        if "stato" in available_cols:
            cols.append(pl.col("stato").fill_null("Unknown"))
        else:
            cols.append(pl.lit("Unknown").alias("stato"))

        if "regione" in available_cols:
            cols.append(pl.col("regione").fill_null("").alias("regione"))
        else:
            cols.append(pl.lit("").alias("regione"))

        if "provincia" in available_cols:
            cols.append(pl.col("provincia").fill_null("").alias("provincia"))
        else:
            cols.append(pl.lit("").alias("provincia"))

        if "settore" in available_cols:
            cols.append(pl.col("settore").fill_null("N/A"))
        else:
            cols.append(pl.lit("N/A").alias("settore"))

        if "fondi_comunitari" in available_cols:
            # Handle comma-separated strings into real lists
            cols.append(
                pl.col("fondi_comunitari")
                .fill_null("")
                .map_elements(
                    lambda x: [f.strip() for f in str(x).split(",") if f.strip()]
                    if isinstance(x, str)
                    else (x if isinstance(x, list) else []),
                    return_dtype=pl.List(pl.String),
                )
                .alias("fondi_comunitari")
            )
        else:
            cols.append(pl.lit([]).alias("fondi_comunitari"))

        cols.extend(
            [
                pl.lit(self.source).alias("source"),
                pl.lit(self.dataset_version).alias("dataset_version"),
                pl.lit(self.retrieval_date).alias("retrieval_date"),
                pl.lit(1.0).alias("confidence"),
            ]
        )

        project_df = df.select(cols)

        logger.info(f"Extracted {len(project_df)} projects")
        return project_df

    def extract_funding_sources(self, df: pl.DataFrame) -> pl.DataFrame:
        """Extract funding source nodes from OpenCUP data."""
        if "fondi_comunitari" not in df.columns:
            return pl.DataFrame()

        # Get unique funding sources from the lists
        all_fondi = []
        for row in df.select("fondi_comunitari").iter_rows():
            fondi_list = row[0]
            if isinstance(fondi_list, list):
                all_fondi.extend(fondi_list)
            elif fondi_list:
                all_fondi.append(str(fondi_list))

        unique_fondi = sorted(list(set([f.strip() for f in all_fondi if f])))

        if not unique_fondi:
            return pl.DataFrame()

        import uuid

        funding_sources = []
        for fondo in unique_fondi:
            funding_sources.append(
                {
                    "id": str(uuid.uuid4()),
                    "nome": fondo,
                    "tipo": self._classify_funding_type(fondo),
                    "source": self.source,
                }
            )

        return pl.DataFrame(funding_sources)

    def _classify_funding_type(self, fondo: str) -> str:
        """Classify funding source type."""
        if not fondo:
            return "Altro"
        fondo_upper = str(fondo).upper()

        if "PNRR" in fondo_upper:
            return "PNRR"
        elif "FESR" in fondo_upper or "FEDER" in fondo_upper:
            return "FESR"
        elif "FSE" in fondo_upper:
            return "FSE"
        elif "PON" in fondo_upper:
            return "PON"
        else:
            return "Altro"
