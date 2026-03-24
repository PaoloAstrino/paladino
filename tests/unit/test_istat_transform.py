"""
Unit tests for ISTAT data transformation.
"""

import polars as pl
import pytest

from paladino.etl.istat_transform import IstatTransformer


@pytest.fixture
def transformer():
    return IstatTransformer()


def test_transform_municipalities_basic(transformer):
    """Test basic municipality transformation."""
    df = pl.DataFrame(
        {
            "COD_ISTAT": ["058091"],
            "DENOMINAZIONE": ["Milano"],
            "SIGLA_PROVINCIA": ["MI"],
            "COD_REGIONE": ["03"],
            "POPOLAZIONE": ["1350000"],
        }
    )

    result = transformer.transform_municipalities(df)

    assert len(result) == 1
    assert result["cod_istat"][0] == "058091"
    assert result["nome"][0] == "Milano"
    assert result["popolazione"][0] == 1350000


def test_transform_provinces(transformer):
    """Test province transformation."""
    df = pl.DataFrame(
        {
            "COD_PROVINCIA": ["015"],
            "DENOMINAZIONE": ["Milano"],
            "SIGLA": ["MI"],
            "COD_REGIONE": ["03"],
        }
    )

    result = transformer.transform_provinces(df)

    assert len(result) == 1
    assert result["cod_provincia"][0] == "015"
    assert result["sigla"][0] == "MI"


def test_transform_regions(transformer):
    """Test region transformation."""
    df = pl.DataFrame({"COD_REGIONE": ["03"], "DENOMINAZIONE": ["Lombardia"]})

    result = transformer.transform_regions(df)

    assert len(result) == 1
    assert result["cod_regione"][0] == "03"
    assert result["nome"][0] == "Lombardia"


def test_create_municipality_evolution(transformer):
    """Test placeholder for municipality evolution."""
    df = pl.DataFrame({"COD_ISTAT": ["058091"], "DENOMINAZIONE": ["Milano"]})

    # create_municipality_evolution is a placeholder returning empty df for now
    result = transformer.create_municipality_evolution(df)
    assert isinstance(result, pl.DataFrame)


def test_parse_population_numbers(transformer):
    """Test robust population parsing."""
    df = pl.DataFrame(
        {
            "COD_ISTAT": ["1", "2", "3"],
            "DENOMINAZIONE": ["A", "B", "C"],
            "SIGLA_PROVINCIA": ["XX", "YY", "ZZ"],
            "COD_REGIONE": ["01", "02", "03"],
            "POPOLAZIONE": ["1.500.000", "", None],
        }
    )

    result = transformer.transform_municipalities(df)
    assert len(result) == 3
    assert result["popolazione"][0] == 1500000
