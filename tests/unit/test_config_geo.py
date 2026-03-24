import pytest
from paladino.config import settings
from paladino.etl.geography import GeoMapper

def test_settings_load():
    # Should have default values
    assert settings.neo4j_user == "neo4j"
    assert settings.min_tender_amount == 40000.0

def test_geo_mapper_fallback():
    mapper = GeoMapper()
    assert mapper.get_istat_code("MILANO") == "015146"
    assert mapper.get_istat_code("ROMA") == "058091"
    assert mapper.get_istat_code("NonExistentCity") is None

def test_geo_mapper_normalization():
    mapper = GeoMapper()
    assert mapper.normalize_provincia("Milano") == "MI"
    assert mapper.normalize_provincia("Roma") == "RM"
    assert mapper.normalize_provincia("Generic") == "GE"
