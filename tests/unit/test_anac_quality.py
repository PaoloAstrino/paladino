"""
Unit tests for ANAC quality validator.
"""

import pytest
import polars as pl
from paladino.etl.anac_quality import AnacQualityValidator


@pytest.fixture
def validator():
    return AnacQualityValidator()


def test_validate_high_quality_data(validator):
    """Test validation of high quality data."""
    df = pl.DataFrame({
        "cig": ["Z1234567890", "Z0987654321"],
        "importo": [100000.0, 500000.0],
        "data_aggiudicazione": ["2024-01-15", "2024-02-20"]
    })
    
    report = validator.validate(df, context="tenders")
    
    assert report["quality_score"] == 1.0
    assert report["pass"] is True
    assert len(report["issues"]) == 0


def test_validate_low_quality_data(validator):
    """Test validation of low quality data."""
    df = pl.DataFrame({
        "cig": [None, "Z0987654321"],  # Missing CIG (critical)
        "importo": [100000.0, 5.0],      # Out of range (medium)
        "data_aggiudicazione": ["2024-01-15", "invalid-date"] # Invalid format (medium)
    })
    
    report = validator.validate(df, context="tenders")
    
    assert report["quality_score"] < 1.0
    assert report["pass"] is False
    assert any(i["type"] == "missing_value" for i in report["issues"])
    assert any(i["type"] == "out_of_range" for i in report["issues"])
    assert any(i["type"] == "invalid_date_format" for i in report["issues"])


def test_validate_empty_dataframe(validator):
    """Test validation of empty DataFrame."""
    df = pl.DataFrame()
    
    report = validator.validate(df, context="tenders")
    
    assert report["total_records"] == 0
    assert report["pass"] is False # Missing columns are critical


def test_check_duplicates(validator):
    """Test detection of duplicate CIGs."""
    df = pl.DataFrame({
        "cig": ["DUP123", "DUP123"],
        "importo": [100000.0, 100000.0]
    })
    
    report = validator.validate(df, context="tenders")
    
    assert any(i["type"] == "duplicate_cig" for i in report["issues"])
    assert report["quality_score"] < 1.0
