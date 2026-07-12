import os
from paladino.config import Settings, settings
from paladino.etl.geography import GeoMapper


def test_settings_load():
    # Test with settings instance (conftest sets PALADINO_NEO4J_USER=test, PALADINO_NEO4J_PASSWORD=test)
    assert settings.neo4j_user == "test"
    assert settings.neo4j_password == "test"
    assert settings.min_tender_amount == 40000.0


def test_settings_defaults():
    # Test that default values are correct when no env vars are set
    # Temporarily clear the env vars set by conftest
    old_user = os.environ.pop("PALADINO_NEO4J_USER", None)
    old_password = os.environ.pop("PALADINO_NEO4J_PASSWORD", None)
    try:
        # Settings still requires neo4j_user and neo4j_password, so set test values
        os.environ["PALADINO_NEO4J_USER"] = "neo4j"
        os.environ["PALADINO_NEO4J_PASSWORD"] = "test_password"
        fresh_settings = Settings()
        assert fresh_settings.neo4j_user == "neo4j"
        assert fresh_settings.min_tender_amount == 40000.0
    finally:
        # Restore env vars
        if old_user:
            os.environ["PALADINO_NEO4J_USER"] = old_user
        if old_password:
            os.environ["PALADINO_NEO4J_PASSWORD"] = old_password


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
