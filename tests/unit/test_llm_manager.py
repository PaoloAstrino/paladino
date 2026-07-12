"""
Unit tests for LLM manager (Ollama integration).
"""

import json
from unittest.mock import Mock, patch

import pytest

from paladino.llm_manager import LLMManager


def test_ollama_chat_success():
    """Test successful Ollama chat call."""
    with patch("requests.post") as mock_post:
        # Mocking the actual requests.post call
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "Test response"}}
        mock_post.return_value = mock_response

        llm = LLMManager(model="llama3b")
        messages = [{"role": "user", "content": "Test question"}]

        response = llm.chat(messages)
        assert response == "Test response"


def test_ollama_classify_intent_success():
    """Test intent classification with valid response."""
    with patch("requests.post") as mock_post:
        mock_response = Mock()
        mock_response.status_code = 200
        # Return valid JSON as content string
        content = json.dumps({"template_name": "pnrr_projects", "params": {}})
        mock_response.json.return_value = {"message": {"content": content}}
        mock_post.return_value = mock_response

        llm = LLMManager(model="llama3b")
        question = "Show me PNRR projects"
        templates = ["pnrr_projects", "high_risk_companies"]

        result = llm.classify_intent(question, templates)

        assert result["template_name"] == "pnrr_projects"
        assert isinstance(result["params"], dict)


def test_ollama_classify_intent_invalid_json():
    """Test intent classification with invalid JSON response."""
    with patch("requests.post") as mock_post:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "Not JSON"}}
        mock_post.return_value = mock_response

        llm = LLMManager(model="llama3b")
        result = llm.classify_intent("Test", ["template1"])

        assert result["template_name"] is None
        assert result["params"] == {}


def test_ollama_api_failure():
    """Test handling of Ollama API failure."""
    import requests

    from paladino.errors import LLMConnectionError

    with patch("requests.post", side_effect=requests.ConnectionError("Connection refused")):
        llm = LLMManager(model="llama3b")
        with pytest.raises(LLMConnectionError):
            llm.chat([{"role": "user", "content": "Test"}])
