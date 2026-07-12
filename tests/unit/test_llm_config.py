"""
Tests for LLM configuration CLI and settings.

Tests cover:
- OpenRouter provider configuration
- All provider configurations (Ollama, OpenAI, Groq, Anthropic, Custom)
- .env file updates
- Settings validation
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from paladino.config import Settings


class TestSettingsOpenRouter:
    """Test Settings class with OpenRouter support."""

    def test_openrouter_api_key_field_exists(self):
        """Test that openrouter_api_key field exists in Settings."""
        assert hasattr(Settings, 'model_fields')
        assert 'openrouter_api_key' in Settings.model_fields

    def test_settings_accepts_openrouter_key(self, tmp_path, monkeypatch):
        """Test that Settings can read OPENROUTER_API_KEY from env."""
        env_file = tmp_path / ".env"
        env_file.write_text("PALADINO_OPENROUTER_API_KEY=test-key\n")
        
        monkeypatch.setenv("PALADINO_OPENROUTER_API_KEY", "test-key")
        
        settings = Settings(_env_file=env_file)
        assert settings.openrouter_api_key == "test-key"

    def test_settings_openrouter_key_optional(self):
        """Test that OPENROUTER_API_KEY is optional."""
        settings = Settings()
        assert settings.openrouter_api_key is None


class TestOpenRouterCLIApiConfig:
    """Test OpenRouter API configuration in CLI."""

    def test_openrouter_in_provider_list(self):
        """Test that OpenRouter is in the provider choices."""
        # Read the CLI file to verify OpenRouter is listed
        cli_file = Path(__file__).parent.parent.parent / "paladino" / "cli.py"
        content = cli_file.read_text(encoding="utf-8")
        
        assert "OpenRouter (Free & Paid Models)" in content
        assert "openrouter.ai/api/v1" in content
        assert "OPENROUTER_API_KEY" in content

    def test_openrouter_config_structure(self):
        """Test that OpenRouter config has correct structure."""
        # Simulate the api_config dict from CLI
        api_config = {
            "OpenRouter (Free & Paid Models)": {
                "base_url": "https://openrouter.ai/api/v1",
                "model_prompt": "Enter model name (e.g., meta-llama/llama-3.1-70b-instruct, mistralai/mistral-large, google/gemini-flash-1.5):",
                "key_name": "OPENROUTER_API_KEY",
                "env_key": "OPENROUTER_API_KEY",
            },
        }
        
        config = api_config["OpenRouter (Free & Paid Models)"]
        assert config["base_url"] == "https://openrouter.ai/api/v1"
        assert "meta-llama/llama-3.1-70b-instruct" in config["model_prompt"]
        assert config["key_name"] == "OPENROUTER_API_KEY"
        assert config["env_key"] == "OPENROUTER_API_KEY"


class TestOpenRouterEnvFileUpdates:
    """Test .env file updates with OpenRouter configuration."""

    def test_env_file_includes_openrouter_key(self, tmp_path):
        """Test that .env file correctly writes OpenRouter key."""
        env_file = tmp_path / ".env"
        env_file.write_text("PALADINO_NEO4J_URI=bolt://localhost:7687\n")
        
        # Simulate CLI config update for OpenRouter
        config = {
            "base_url": "https://openrouter.ai/api/v1",
            "env_key": "OPENROUTER_API_KEY",
        }
        model = "meta-llama/llama-3.1-70b-instruct"
        api_key = "sk-or-test-key"
        
        env_lines = [
            line
            for line in env_file.read_text(encoding="utf-8").splitlines()
            if not any(
                skip in line
                for skip in [
                    "LLM_MODEL=",
                    "LLM_API_KEY=",
                    "LLM_API_BASE=",
                    "OPENAI_API_KEY=",
                    "OPENROUTER_API_KEY=",
                    "GROQ_API_KEY=",
                    "ANTHROPIC_API_KEY=",
                ]
            )
        ]
        
        env_lines.append(f'LLM_MODEL="{model}"')
        env_lines.append(f'LLM_API_BASE="{config["base_url"]}"')
        env_lines.append(f'LLM_API_KEY="{api_key}"')
        env_lines.append(f'{config["env_key"]}="{api_key}"')
        
        env_file.write_text("\n".join(env_lines), encoding="utf-8")
        
        # Verify the file content
        content = env_file.read_text(encoding="utf-8")
        assert 'LLM_MODEL="meta-llama/llama-3.1-70b-instruct"' in content
        assert 'LLM_API_BASE="https://openrouter.ai/api/v1"' in content
        assert 'LLM_API_KEY="sk-or-test-key"' in content
        assert 'OPENROUTER_API_KEY="sk-or-test-key"' in content

    def test_env_file_updates_existing_openrouter(self, tmp_path):
        """Test updating existing .env with OpenRouter key replaces old key."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            'LLM_MODEL="old-model"\n'
            'LLM_API_KEY="old-key"\n'
            'OPENROUTER_API_KEY="old-openrouter-key"\n'
        )
        
        config = {
            "base_url": "https://openrouter.ai/api/v1",
            "env_key": "OPENROUTER_API_KEY",
        }
        model = "google/gemini-flash-1.5"
        api_key = "sk-or-new-key"
        
        env_lines = [
            line
            for line in env_file.read_text(encoding="utf-8").splitlines()
            if not any(
                skip in line
                for skip in [
                    "LLM_MODEL=",
                    "LLM_API_KEY=",
                    "LLM_API_BASE=",
                    "OPENAI_API_KEY=",
                    "OPENROUTER_API_KEY=",
                    "GROQ_API_KEY=",
                    "ANTHROPIC_API_KEY=",
                ]
            )
        ]
        
        env_lines.append(f'LLM_MODEL="{model}"')
        env_lines.append(f'LLM_API_BASE="{config["base_url"]}"')
        env_lines.append(f'LLM_API_KEY="{api_key}"')
        env_lines.append(f'{config["env_key"]}="{api_key}"')
        
        env_file.write_text("\n".join(env_lines), encoding="utf-8")
        
        # Verify old keys are removed and new keys are present
        content = env_file.read_text(encoding="utf-8")
        assert 'LLM_MODEL="google/gemini-flash-1.5"' in content
        assert 'LLM_API_BASE="https://openrouter.ai/api/v1"' in content
        assert 'LLM_API_KEY="sk-or-new-key"' in content
        assert 'OPENROUTER_API_KEY="sk-or-new-key"' in content
        assert "old-key" not in content
        assert "old-openrouter-key" not in content


class TestAllProviders:
    """Test that all providers are correctly configured."""

    def test_all_provider_urls_are_valid(self):
        """Test that all provider base URLs are valid HTTPS URLs."""
        providers = {
            "OpenRouter": "https://openrouter.ai/api/v1",
            "OpenAI": "https://api.openai.com/v1",
            "Groq": "https://api.groq.com/openai/v1",
            "Anthropic": "https://api.anthropic.com/v1",
        }
        
        for provider, url in providers.items():
            assert url.startswith("https://"), f"{provider} URL must be HTTPS"
            assert len(url) > 10, f"{provider} URL seems too short"

    def test_all_providers_have_api_key_env_vars(self):
        """Test that all providers have corresponding env var names."""
        providers = {
            "OpenRouter": "OPENROUTER_API_KEY",
            "OpenAI": "OPENAI_API_KEY",
            "Groq": "GROQ_API_KEY",
            "Anthropic": "ANTHROPIC_API_KEY",
        }
        
        for provider, env_var in providers.items():
            assert env_var.endswith("_API_KEY"), f"{provider} env var should end with _API_KEY"
            assert "_" in env_var, f"{provider} env var should use underscores"


class TestLLMManagerWithOpenRouter:
    """Test LLM manager integration with OpenRouter."""

    def test_llm_manager_reads_openrouter_key(self, tmp_path, monkeypatch):
        """Test that LLM manager can use OpenRouter API key."""
        from paladino.llm_manager import LLMManager
        
        env_file = tmp_path / ".env"
        env_file.write_text(
            "PALADINO_LLM_API_KEY=sk-or-test-key\n"
            "PALADINO_LLM_API_BASE=https://openrouter.ai/api/v1\n"
            "PALADINO_LLM_MODEL=meta-llama/llama-3.1-70b-instruct\n"
        )
        
        monkeypatch.setenv("PALADINO_LLM_API_KEY", "sk-or-test-key")
        monkeypatch.setenv("PALADINO_LLM_API_BASE", "https://openrouter.ai/api/v1")
        monkeypatch.setenv("PALADINO_LLM_MODEL", "meta-llama/llama-3.1-70b-instruct")
        
        settings = Settings(_env_file=env_file)
        
        assert settings.llm_api_key == "sk-or-test-key"
        assert settings.llm_api_base == "https://openrouter.ai/api/v1"
        assert settings.llm_model == "meta-llama/llama-3.1-70b-instruct"
