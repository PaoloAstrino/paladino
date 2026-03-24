import pytest
from paladino.etl.normalizer import CompanyNormalizer

def test_normalize_basic():
    assert CompanyNormalizer.normalize("Rossi S.R.L.") == "ROSSI"
    assert CompanyNormalizer.normalize("Rossi Srl") == "ROSSI"
    assert CompanyNormalizer.normalize("Rossi SPA") == "ROSSI"

def test_normalize_accents():
    assert CompanyNormalizer.normalize("Società Caffè") == "SOCIETA CAFFE"

def test_normalize_messy():
    assert CompanyNormalizer.normalize("  Rossi   &   Figli   S.n.c.  ") == "ROSSI FIGLI"

def test_normalize_multiple_suffixes():
    assert CompanyNormalizer.normalize("Cooperativa Edile S.C.A.R.L.") == "COOPERATIVA EDILE"
    assert CompanyNormalizer.normalize("Grande Impresa S.R.L. S.P.A.") == "GRANDE IMPRESA"

def test_get_core_name():
    assert CompanyNormalizer.get_core_name("Rossi & Bianchi S.r.l.") == "ROSSIBIANCHI"

def test_normalize_legal_forms_in_middle():
    # It should only remove from the end (usually)
    # But if it's in the middle, it might be tricky. 
    # Current implementation uses greedy removal from end.
    assert CompanyNormalizer.normalize("SRL ROSSI") == "SRL ROSSI"
