"""
Unit tests for OpenCUP data transformation.
"""

import polars as pl
import pytest

from paladino.etl.opencup_transform import OpencupTransformer


@pytest.fixture
def transformer():
    return OpencupTransformer()


def test_transform_projects_basic(transformer):
    """Test basic project transformation."""
    df = pl.DataFrame(
        {
            "CUP": ["J12345678901234"],
            "TITOLO_PROGETTO": ["Test Project"],
            "DESCRIZIONE": ["Test Description"],
            "IMPORTO_PREVISTO": ["1000000"],
            "DATA_INIZIO": ["2024-01-01"],
            "REGIONE": ["Lombardia"],
            "FONDI_UE": ["PNRR"],
        }
    )

    result = transformer.transform(df)
    projects_df = result["projects"]

    assert len(projects_df) == 1
    assert projects_df["cup"][0] == "J12345678901234"
    assert projects_df["titolo"][0] == "Test Project"


def test_extract_funding_sources(transformer):
    """Test extraction of individual funding sources."""
    df = pl.DataFrame({"CUP": ["J1", "J2"], "FONDI_UE": ["PNRR", "FESR"]})

    result = transformer.transform(df)
    funding_df = result["funding_sources"]

    sources = set(funding_df["nome"].to_list())
    assert sources == {"PNRR", "FESR"}
