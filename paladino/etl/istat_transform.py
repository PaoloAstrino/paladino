"""
ISTAT transformation - Convert ISTAT CSV to normalized graph schema.
"""

import polars as pl
from datetime import datetime
from typing import Dict, Optional, List
from loguru import logger


class IstatTransformer:
    """Transform ISTAT CSV to normalized DataFrames."""
    
    def __init__(self, dataset_version: str = "2026-01"):
        """
        Initialize transformer.
        
        Args:
            dataset_version: Version identifier for this dataset
        """
        self.source = "ISTAT"
        self.dataset_version = dataset_version
        self.retrieval_date = datetime.now().isoformat()

    def _find_column(self, df: pl.DataFrame, candidates: List[str]) -> str:
        """Find first matching column from candidates."""
        for cand in candidates:
            # Exact match
            if cand in df.columns:
                return cand
            # Substring match (case insensitive)
            for col in df.columns:
                if cand.lower() in col.lower():
                    return col
        # If still not found, try common patterns
        raise IndexError(f"None of the candidates {candidates} found in {df.columns}")

    def transform_municipalities(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Transform municipalities from unified DataFrame.
        """
        logger.info(f"Transforming {len(df)} municipalities...")
        
        try:
            col_istat = self._find_column(df, ["Codice Comune formato alfanumerico", "COD_ISTAT"])
            col_nome = self._find_column(df, ["Denominazione in italiano", "DENOMINAZIONE"])
            col_prov = self._find_column(df, ["Sigla automobilistica", "SIGLA_PROVINCIA"])
            col_reg = self._find_column(df, ["Codice Regione", "COD_REGIONE"])
            
            # Popolazione might be missing
            try:
                col_pop = self._find_column(df, ["Popolazione", "POPOLAZIONE"])
            except IndexError:
                col_pop = None
        except IndexError as e:
            logger.error(f"Column mapping failed: {e}")
            raise e
        
        municipalities = []
        for row in df.iter_rows(named=True):
            cod_istat = str(row.get(col_istat, "")).strip()
            if not cod_istat:
                continue
                
            municipality = {
                "id": self._generate_uuid(),
                "cod_istat": cod_istat,
                "nome": str(row.get(col_nome, "")).strip(),
                "sigla_provincia": str(row.get(col_prov, "")).strip(),
                "cod_regione": str(row.get(col_reg, "")).strip(),
                "popolazione": self._parse_int(row.get(col_pop)) if col_pop else None,
                "source": self.source,
                "dataset_version": self.dataset_version,
                "retrieval_date": self.retrieval_date,
            }
            municipalities.append(municipality)
            
        result = pl.DataFrame(municipalities) if municipalities else pl.DataFrame()
        logger.info(f"Extracted {len(municipalities)} municipalities")
        return result
    
    def transform_provinces(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Extract unique provinces from unified DataFrame.
        """
        logger.info("Extracting unique provinces...")
        
        try:
            prov_code_col = self._find_column(df, ["territoriale sovracomunale", "COD_PROVINCIA"])
            prov_name_col = self._find_column(df, ["territoriale sovracomunale", "DENOMINAZIONE"])
            sigla_col = self._find_column(df, ["Sigla automobilistica", "SIGLA"])
            reg_col = self._find_column(df, ["Codice Regione", "COD_REGIONE"])
        except IndexError as e:
            logger.error(f"Column mapping failed: {e}")
            raise e
        
        unique_provinces = df.select([
            pl.col(prov_code_col).alias("cod_provincia"),
            pl.col(prov_name_col).alias("nome"),
            pl.col(sigla_col).alias("sigla"),
            pl.col(reg_col).alias("cod_regione")
        ]).unique(subset=["cod_provincia"])
        
        provinces = []
        for row in unique_provinces.iter_rows(named=True):
            if not row["cod_provincia"]:
                continue
                
            provinces.append({
                "id": self._generate_uuid(),
                "cod_provincia": str(row["cod_provincia"]).strip(),
                "nome": str(row["nome"]).strip(),
                "sigla": str(row["sigla"]).strip(),
                "cod_regione": str(row["cod_regione"]).strip(),
                "source": self.source,
            })
            
        result = pl.DataFrame(provinces) if provinces else pl.DataFrame()
        return result
    
    def transform_regions(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Extract unique regions from unified DataFrame.
        """
        logger.info("Extracting unique regions...")
        
        try:
            reg_code_col = self._find_column(df, ["Codice Regione", "COD_REGIONE"])
            reg_name_col = self._find_column(df, ["Denominazione Regione", "Denominazione regione", "DENOMINAZIONE"])
        except IndexError as e:
            logger.error(f"Column mapping failed: {e}")
            raise e
        
        unique_regions = df.select([
            pl.col(reg_code_col).alias("cod_regione"),
            pl.col(reg_name_col).alias("nome")
        ]).unique(subset=["cod_regione"])
        
        regions = []
        for row in unique_regions.iter_rows(named=True):
            if not row["cod_regione"]:
                continue
                
            regions.append({
                "id": self._generate_uuid(),
                "cod_regione": str(row["cod_regione"]).strip(),
                "nome": str(row["nome"]).strip(),
                "source": self.source,
            })
            
        return pl.DataFrame(regions) if regions else pl.DataFrame()
    
    def create_municipality_evolution(self, municipalities_df: pl.DataFrame) -> pl.DataFrame:
        """Placeholder for municipality evolution."""
        return pl.DataFrame()
    
    def _generate_uuid(self) -> str:
        import uuid
        return str(uuid.uuid4())
    
    def _parse_int(self, value) -> Optional[int]:
        """Parse integer value, handling dots and empty strings."""
        if value is None or value == "":
            return None
        
        if isinstance(value, str):
            # Remove dots (common in Italian population formatting)
            value = value.replace(".", "").replace(",", "").strip()
            
        try:
            return int(float(value)) # float handle possible .0
        except (ValueError, TypeError):
            return None
