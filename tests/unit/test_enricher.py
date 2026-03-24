"""
Unit tests for company enricher.
"""

import pytest
from unittest.mock import MagicMock, patch
from paladino.ml.enricher import CompanyEnricher


@pytest.fixture
def mock_driver():
    return MagicMock()


@pytest.fixture
def enricher(mock_driver):
    return CompanyEnricher(driver=mock_driver)


def test_calculate_risk_score_high_risk(enricher, mock_driver):
    """Test risk score calculation for high risk scenarios."""
    stats = {
        "total_tenders": 10,
        "total_importo": 60000000.0,
        "avg_importo": 6000000.0
    }
    
    # Mock session results
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    # Mock single bidder check
    mock_res_sb = MagicMock()
    mock_res_sb.single.return_value = {"single_bidder_count": 6} # 60%
    
    # Mock buyer concentration check
    mock_res_bc = MagicMock()
    mock_res_bc.single.return_value = {"max_buyer_tenders": 8} # 80%
    
    mock_session.run.side_effect = [mock_res_sb, mock_res_bc]
    
    risk_report = enricher._compute_risk_score("CF123", stats)
    
    assert risk_report["score"] >= 0.5
    assert "high_single_bidder_rate" in risk_report["flags"]
    assert "buyer_concentration" in risk_report["flags"]
    assert "high_avg_amount" in risk_report["flags"]


def test_calculate_risk_score_low_risk(enricher, mock_driver):
    """Test risk score calculation for low risk scenarios."""
    stats = {
        "total_tenders": 5,
        "total_importo": 500000.0,
        "avg_importo": 100000.0
    }
    
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    # Mock results (low counts)
    mock_res = MagicMock()
    mock_res.single.return_value = {"single_bidder_count": 0, "max_buyer_tenders": 1}
    
    mock_session.run.return_value = mock_res
    
    risk_report = enricher._compute_risk_score("CF123", stats)
    
    assert risk_report["score"] == 0.0
    assert len(risk_report["flags"]) == 0
