# Contributing to Paladino

Thank you for your interest in contributing to Paladino! This document provides guidelines and instructions for contributing to the project.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Community](#community)

## Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md) to help maintain a welcoming and inclusive community.

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Docker Desktop (for Neo4j)
- Git
- 16GB+ RAM recommended

### First-Time Setup

```bash
# 1. Fork the repository
# 2. Clone your fork
git clone https://github.com/YOUR_USERNAME/paladino.git
cd paladino

# 3. Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 4. Install development dependencies
pip install -e ".[dev]"

# 5. Start Neo4j
docker-compose up -d

# 6. Run tests to verify setup
pytest
```

## Development Setup

### Environment Configuration

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your credentials
# Required: NEO4J_USER, NEO4J_PASSWORD
```

### IDE Setup

We recommend using VS Code or PyCharm with the following extensions:
- **Python** (Microsoft)
- **Pylance** (type checking)
- **Black Formatter** (code formatting)
- **isort** (import sorting)

### Pre-commit Hooks (Recommended)

```bash
# Install pre-commit
pip install pre-commit

# Enable hooks
pre-commit install
```

## How to Contribute

### Ways to Contribute

1. **Bug Reports**: Open an issue using the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md)
2. **Feature Requests**: Open an issue using the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md)
3. **Documentation**: Improve README, docstrings, or add examples
4. **Code**: Fix bugs, add features, or improve performance
5. **Testing**: Add test cases or improve test coverage

### Finding Issues to Work On

Look for issues labeled:
- `good first issue` - Great for newcomers
- `help wanted` - We need community help
- `bug` - Something needs fixing

## Coding Standards

### Code Style

- **Formatter**: Black (line length: 100)
- **Linter**: Ruff
- **Type Checker**: mypy (strict mode)
- **Import Sorting**: isort

### Type Hints

**All public functions and methods must have type hints:**

```python
# ✅ Good
def get_company(cf: str) -> Optional[Dict[str, Any]]:
    """Fetch company data by Codice Fiscale."""
    ...

# ❌ Bad - missing type hints
def get_company(cf):
    ...
```

### Docstrings

Use Google-style docstrings for all public APIs:

```python
def generate_cypher(self, question: str, schema_metadata: str) -> Optional[str]:
    """
    Generate a Cypher query from natural language.

    Args:
        question: Natural language questions from user
        schema_metadata: Database schema description for context

    Returns:
        Validated Cypher query string, or None if security check fails

    Raises:
        ValueError: If question is empty
    """
```

### Security Guidelines

1. **Never hardcode secrets** - Use environment variables via `pydantic-settings`
2. **Use parameterized queries** - Never use f-strings for Cypher/SQL
3. **Validate all inputs** - Use Pydantic models for validation
4. **Fail securely** - Don't leak sensitive information in error messages

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=paladino

# Run specific test file
pytest tests/unit/test_llm_manager.py

# Run tests matching a pattern
pytest -k "test_llm"
```

### Writing Tests

```python
def test_llm_chat_success(mock_ollama):
    """Test successful LLM chat response."""
    llm = LLMManager(model="llama3b")
    response = llm.chat([{"role": "user", "content": "Test"}])

    assert response is not None
    assert isinstance(response, str)
```

### Test Categories

- **Unit Tests** (`tests/unit/`): Test individual components in isolation
- **Integration Tests** (`tests/integration/`): Test component interactions
- **End-to-End Tests** (`tests/e2e/`): Test full workflows

## Submitting Changes

### Pull Request Process

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following our coding standards

3. **Run tests** and ensure they all pass:
   ```bash
   pytest
   ```

4. **Run linters and type checker**:
   ```bash
   ruff check paladino/
   mypy paladino/
   ```

5. **Update documentation** if needed (README, docstrings, etc.)

6. **Commit your changes** with clear messages:
   ```bash
   git commit -m "feat: add new feature X

   - Description of what was added
   - Why it was needed
   - Any breaking changes"
   ```

7. **Push and open a PR**:
   ```bash
   git push origin feature/your-feature-name
   ```

### Pull Request Template

When opening a PR, please fill out the [PR template](.github/PULL_REQUEST_TEMPLATE.md):

- Describe your changes
- Link related issues
- Add screenshots if UI changes
- Check all boxes in the checklist

### Code Review

All PRs require:
- ✅ At least 1 approval from a maintainer
- ✅ All CI checks passing
- ✅ No unresolved comments

## Release Process

Releases follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (1.0.0): Breaking changes
- **MINOR** (0.2.0): New features (backward compatible)
- **PATCH** (0.1.1): Bug fixes (backward compatible)

## Community

### Getting Help

- **Documentation**: [README.md](README.md), [docs/](docs/)
- **Issues**: [GitHub Issues](../../issues)
- **Discussions**: [GitHub Discussions](../../discussions)

### Communication

- Use GitHub Issues for bug reports and feature requests
- Use GitHub Discussions for questions and general discussion
- Be respectful and follow the [Code of Conduct](CODE_OF_CONDUCT.md)

---

Thank you for contributing to Paladino! 🛡️
