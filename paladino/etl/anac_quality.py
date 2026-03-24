"""
Data quality validation for ANAC data.
"""

import polars as pl
from typing import Dict, List
from loguru import logger


class AnacQualityValidator:
    """Validate data quality for ANAC datasets."""
    
    # Critical fields that must be present
    CRITICAL_FIELDS = {
        "tenders": ["cig", "importo"],
        "companies": ["cf"],
        "wins": ["company_cf", "tender_cig", "importo"],
    }
    
    # Valid value ranges
    VALID_RANGES = {
        "importo": (40_000, 1_000_000_000),  # 40k to 1B EUR
    }
    
    def __init__(self):
        self.issues = []
    
    def validate(self, df: pl.DataFrame, context: str) -> Dict:
        """
        Validate a DataFrame.
        
        Args:
            df: DataFrame to validate
            context: Context name (e.g., "tenders", "companies")
            
        Returns:
            Quality report dictionary
        """
        self.issues = []
        
        logger.info(f"Validating {context} ({len(df)} records)")
        
        # Check critical fields
        self._check_missing_values(df, context)
        
        # Check value ranges
        self._check_value_ranges(df)
        
        # Check date formats
        self._check_date_formats(df)
        
        # Check duplicates
        self._check_duplicates(df, context)
        
        # Generate report
        report = self._generate_report(df, context)
        
        if report["quality_score"] < 0.85:
            logger.warning(f"{context} quality score: {report['quality_score']:.2%}")
        else:
            logger.success(f"{context} quality score: {report['quality_score']:.2%}")
        
        return report
    
    def _check_missing_values(self, df: pl.DataFrame, context: str):
        """Check for missing critical values."""
        critical_fields = self.CRITICAL_FIELDS.get(context, [])
        
        for field in critical_fields:
            if field not in df.columns:
                self.issues.append({
                    "type": "missing_column",
                    "field": field,
                    "severity": "critical",
                    "count": len(df),
                })
                continue
            
            missing = df[field].null_count()
            if missing > 0:
                self.issues.append({
                    "type": "missing_value",
                    "field": field,
                    "count": missing,
                    "percentage": missing / len(df) * 100,
                    "severity": "critical" if missing > len(df) * 0.01 else "warning",
                })
    
    def _check_value_ranges(self, df: pl.DataFrame):
        """Check for out-of-range values."""
        for field, (min_val, max_val) in self.VALID_RANGES.items():
            if field not in df.columns:
                continue
            
            out_of_range = df.filter(
                (pl.col(field) < min_val) | (pl.col(field) > max_val)
            ).height
            
            if out_of_range > 0:
                self.issues.append({
                    "type": "out_of_range",
                    "field": field,
                    "count": out_of_range,
                    "range": f"{min_val:,} - {max_val:,}",
                    "severity": "medium",
                })
    
    def _check_date_formats(self, df: pl.DataFrame):
        """Check date field formats."""
        date_fields = [col for col in df.columns if col.startswith("data_")]
        
        for field in date_fields:
            if field not in df.columns:
                continue
            
            # Count non-null, non-ISO dates
            invalid = df.filter(
                pl.col(field).is_not_null() & 
                ~pl.col(field).cast(pl.String).str.contains(r"^\d{4}-\d{2}-\d{2}")
            ).height
            
            if invalid > 0:
                self.issues.append({
                    "type": "invalid_date_format",
                    "field": field,
                    "count": invalid,
                    "severity": "medium",
                })
    
    def _check_duplicates(self, df: pl.DataFrame, context: str):
        """Check for duplicate records."""
        if context == "tenders" and "cig" in df.columns:
            duplicates = df.group_by("cig").agg(pl.count()).filter(pl.col("count") > 1).height
            
            if duplicates > 0:
                self.issues.append({
                    "type": "duplicate_cig",
                    "count": duplicates,
                    "severity": "high",
                })
        
        elif context == "companies" and "cf" in df.columns:
            duplicates = df.group_by("cf").agg(pl.count()).filter(pl.col("count") > 1).height
            
            if duplicates > 0:
                self.issues.append({
                    "type": "duplicate_cf",
                    "count": duplicates,
                    "severity": "high",
                })
    
    def _generate_report(self, df: pl.DataFrame, context: str) -> Dict:
        """Generate quality report."""
        critical_issues = [i for i in self.issues if i.get("severity") == "critical"]
        high_issues = [i for i in self.issues if i.get("severity") == "high"]
        
        # Calculate quality score
        penalty = len(critical_issues) * 0.1 + len(high_issues) * 0.05
        quality_score = max(0.0, 1.0 - penalty)
        
        return {
            "context": context,
            "total_records": len(df),
            "issues": self.issues,
            "critical_count": len(critical_issues),
            "high_count": len(high_issues),
            "quality_score": quality_score,
            "pass": len(critical_issues) == 0,
        }
