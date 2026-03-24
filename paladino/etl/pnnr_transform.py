"""
PNRR transformation - Convert PNRR Soggetti and Subappaltatori CSV to normalized graph schema.
"""

import uuid
from datetime import datetime

import polars as pl
from loguru import logger


class PnnrTransformer:
    """Transform PNRR CSVs to normalized DataFrames."""

    def __init__(self, dataset_version: str = "2026-01"):
        """
        Initialize transformer.

        Args:
            dataset_version: Version identifier for this dataset
        """
        self.source = "PNRR_ItaliaDomani"
        self.dataset_version = dataset_version
        self.retrieval_date = datetime.now().isoformat()

    def transform_soggetti(self, df: pl.DataFrame) -> dict[str, pl.DataFrame]:
        """
        Transform PNRR Soggetti DataFrame.
        """
        logger.info(f"Transforming {len(df)} PNRR soggetti")

        # 1. Extract Companies/Entities
        companies = (
            df.select(
                [
                    pl.col("Codice Fiscale Soggetto").cast(pl.String).alias("cf"),
                    pl.col("Denominazione").cast(pl.String).alias("nome_originale"),
                    pl.col("Descrizione Forma Giuridica").cast(pl.String).alias("forma_giuridica"),
                    pl.col("Codice ATECO").cast(pl.String).alias("ateco"),
                ]
            )
            .filter(pl.col("cf").is_not_null() & (pl.col("cf").str.strip_chars() != ""))
            .unique(subset=["cf"])
        )

        # Add metadata
        companies = companies.with_columns(
            [
                pl.lit(str(uuid.uuid4())).alias("id"),
                pl.col("nome_originale").str.to_uppercase().alias("nome_normalizzato"),
                pl.lit(None).alias("piva"),
                pl.lit([self.source]).alias("source"),
                pl.lit(self.dataset_version).alias("dataset_version"),
                pl.lit(self.retrieval_date).alias("retrieval_date"),
                pl.lit(1.0).alias("confidence"),
            ]
        )

        # 2. Extract Relationships to Projects
        involvement = df.select(
            [
                pl.col("Codice Fiscale Soggetto").cast(pl.String).alias("company_cf"),
                pl.col("CUP").cast(pl.String).alias("project_cup"),
                pl.col("Descrizione del Ruolo del Soggetto").cast(pl.String).alias("role"),
                pl.col("Codice Univoco Submisura").cast(pl.String).alias("submisura_code"),
                pl.col("Descrizione Submisura").cast(pl.String).alias("submisura_desc"),
            ]
        ).filter(
            pl.col("company_cf").is_not_null() & (pl.col("company_cf").str.strip_chars() != "")
        )

        involvement = involvement.with_columns(
            [
                pl.lit(self.source).alias("source"),
                pl.lit(self.retrieval_date).alias("date"),
                pl.lit(1.0).alias("confidence"),
            ]
        )

        return {"companies": companies, "involvement": involvement}

    def transform_subappaltatori(self, df: pl.DataFrame) -> dict[str, pl.DataFrame]:
        """
        Transform PNRR Subappaltatori DataFrame.
        """
        logger.info(f"Transforming {len(df)} PNRR subappaltatori")

        # 1. Extract Sub-contractors (Companies)
        sub_companies = (
            df.select(
                [
                    pl.col("Codice Fiscale/P.IVA Sub-Appaltatore").cast(pl.String).alias("cf"),
                    pl.col("Denominazione Sub-Appaltatore").cast(pl.String).alias("nome_originale"),
                    pl.col("Descrizione Forma Giuridica Sub-Appaltatore")
                    .cast(pl.String)
                    .alias("forma_giuridica"),
                    pl.col("Codice ATECO Sub-Appaltatore").cast(pl.String).alias("ateco"),
                ]
            )
            .filter(pl.col("cf").is_not_null() & (pl.col("cf").str.strip_chars() != ""))
            .unique(subset=["cf"])
        )

        sub_companies = sub_companies.with_columns(
            [
                pl.lit(str(uuid.uuid4())).alias("id"),
                pl.col("nome_originale").str.to_uppercase().alias("nome_normalizzato"),
                pl.lit(None).alias("piva"),
                pl.lit([self.source]).alias("source"),
                pl.lit(self.dataset_version).alias("dataset_version"),
                pl.lit(self.retrieval_date).alias("retrieval_date"),
                pl.lit(1.0).alias("confidence"),
            ]
        )

        # 2. Extract Relationships to Tenders (CIG) — used for both
        #    SUB_CONTRACTOR_ON (company→tender) and the later SUBCONTRACTS_TO
        #    (winner-company→subcontractor-company) steps.
        #
        # NOTE: The CSV is semicolon-delimited.  Column names verified against
        # PNRR_Subappaltatori_Gare.csv as of October 2025 extraction.
        sub_to_tender = df.select(
            [
                pl.col("Codice Fiscale/P.IVA Sub-Appaltatore").cast(pl.String).alias("sub_cf"),
                pl.col("CIG").cast(pl.String).alias("tender_cig"),
                pl.col("CUP").cast(pl.String).alias("project_cup"),
                pl.col("Descrizione Ruolo Soggetto Correlato").cast(pl.String).alias("role"),
                pl.col("Codice ATECO Sub-Appaltatore").cast(pl.String).alias("ateco"),
                pl.col("Data di Estrazione").cast(pl.String).alias("data_estrazione"),
            ]
        ).filter(
            pl.col("tender_cig").is_not_null()
            & (pl.col("tender_cig") != "")
            & pl.col("sub_cf").is_not_null()
            & (pl.col("sub_cf").str.strip_chars() != "")
        )

        sub_to_tender = sub_to_tender.with_columns(
            [
                pl.lit(self.source).alias("source"),
                pl.lit(self.retrieval_date).alias("date"),
                pl.lit(1.0).alias("confidence"),
            ]
        )

        return {
            "companies": sub_companies,
            "sub_contracts": sub_to_tender,  # sub_cf → tender CIG (SUB_CONTRACTOR_ON)
        }
