"""
Unit tests for ANAC data transformation.
"""

import pytest
import polars as pl
from paladino.etl.anac_transform import AnacOcdsTransformer


def test_extract_tender_basic(sample_ocds_tender):
    transformer = AnacOcdsTransformer()
    ocds_data = {"records": [{"releases": [sample_ocds_tender]}]}
    tenders_df = transformer.extract_tenders(ocds_data)
    
    assert len(tenders_df) == 1
    assert tenders_df["cig"][0] == "123"
    assert tenders_df["oggetto"][0] == "Test Tender"
    assert tenders_df["importo"][0] == 100000.0


def test_extract_company_from_award(sample_ocds_tender):
    transformer = AnacOcdsTransformer()
    ocds_data = {"records": [{"releases": [sample_ocds_tender]}]}
    companies_df = transformer.extract_companies(ocds_data)
    
    assert len(companies_df) == 1
    assert companies_df["cf"][0] == "CF123"
    assert "TEST COMPANY" in companies_df["nome_normalizzato"][0]


def test_extract_wins_relationship(sample_ocds_tender):
    transformer = AnacOcdsTransformer()
    ocds_data = {"records": [{"releases": [sample_ocds_tender]}]}
    wins_df = transformer.extract_wins(ocds_data)
    
    assert len(wins_df) == 1
    assert wins_df["company_cf"][0] == "CF123"
    assert wins_df["tender_cig"][0] == "123"
