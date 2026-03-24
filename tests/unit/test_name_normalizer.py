"""
Unit tests for company name normalization.
"""

import pytest

from paladino.ml.name_normalizer import CompanyNameNormalizer


@pytest.fixture
def normalizer():
    return CompanyNameNormalizer()


def test_remove_srl(normalizer):
    """Test removal of S.R.L. suffix."""
    assert normalizer.normalize("Acme S.r.l.") == "ACME"
    assert normalizer.normalize("Acme SRL") == "ACME"
    assert normalizer.normalize("Acme S.R.L.S.") == "ACME"


def test_remove_spa(normalizer):
    """Test removal of S.P.A. suffix."""
    assert normalizer.normalize("Beta S.p.A.") == "BETA"
    assert normalizer.normalize("Beta SPA") == "BETA"


def test_remove_cooperativa(normalizer):
    """Test removal of cooperative suffixes."""
    assert normalizer.normalize("Gamma Cooperativa") == "GAMMA"
    assert normalizer.normalize("Delta Soc. Coop.") == "DELTA"


def test_uppercase_conversion(normalizer):
    """Test uppercase conversion."""
    assert normalizer.normalize("acme costruzioni") == "ACME COSTRUZIONI"


def test_punctuation_removal(normalizer):
    """Test punctuation removal."""
    # A.C.M.E. dots are removed, & is replaced by space then collapsed
    assert normalizer.normalize("A.C.M.E. & Co.") == "ACME CO"


def test_multiple_spaces_collapsed(normalizer):
    """Test multiple spaces are collapsed."""
    assert normalizer.normalize("ACME    COSTRUZIONI") == "ACME COSTRUZIONI"


def test_aggressive_normalization(normalizer):
    """Test aggressive normalization with abbreviations."""
    result = normalizer.normalize_aggressive("Acme Costruzioni Generale S.r.l.")

    # ACME COSTR GEN
    assert "ACME" in result
    assert "COSTR" in result  # Abbreviation
    assert "GEN" in result  # Abbreviation
    assert "SRL" not in result  # Removed


def test_core_name_extraction(normalizer):
    """Test core name extraction (first 3 words)."""
    result = normalizer.extract_core_name("Acme Costruzioni Generale Italiana S.r.l.")

    # Should take first 3 significant words
    assert result == "ACME COSTRUZIONI GENERALE"


def test_core_name_short_input(normalizer):
    """Test core name with input shorter than 3 words."""
    result = normalizer.extract_core_name("Acme S.r.l.")

    assert result == "ACME"
