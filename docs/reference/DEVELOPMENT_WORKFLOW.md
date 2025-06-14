# Development Workflow Documentation

This document outlines the complete development workflow for the MCP Mesh SDK, from initial setup to production deployment.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Development Environment Setup](#development-environment-setup)
3. [Code Development Workflow](#code-development-workflow)
4. [Testing Procedures](#testing-procedures)
5. [Code Review Process](#code-review-process)
6. [Release Management](#release-management)
7. [Troubleshooting](#troubleshooting)

## Getting Started

### Prerequisites

Before starting development, ensure you have:

- **Python 3.10+**: Required for modern type hints and language features
- **Git**: For version control
- **Virtual Environment Manager**: `venv`, `conda`, or `virtualenv`
- **Code Editor**: VS Code, PyCharm, or similar with Python support

### Initial Setup

1. **Clone the Repository**

   ```bash
   git clone <repository-url>
   cd mcp-mesh
   ```

2. **Create Virtual Environment**

   ```bash
   # Using venv
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate

   # Using conda
   conda create -n mcp-mesh python=3.10
   conda activate mcp-mesh
   ```

3. **Install Dependencies**

   ```bash
   # Development dependencies (includes everything)
   pip install -r requirements-dev.txt

   # Or install in editable mode
   pip install -e .[dev]
   ```

4. **Install Pre-commit Hooks**

   ```bash
   pre-commit install
   ```

5. **Verify Installation**

   ```bash
   # Run tests to verify setup
   pytest src/runtime/python/tests/unit/test_mesh_decorators.py -v

   # Check code quality tools
   black --check src/ tests/
   mypy src/
   ruff check src/ tests/
   ```

## Development Environment Setup

### IDE Configuration

#### VS Code Setup

Create `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": "./.venv/bin/python",
  "python.formatting.provider": "black",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": false,
  "python.linting.flake8Enabled": false,
  "python.linting.mypyEnabled": true,
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests"],
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.pyc": true,
    ".mypy_cache": true,
    ".pytest_cache": true,
    "htmlcov": true
  }
}
```

Create `.vscode/launch.json` for debugging:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Current File",
      "type": "python",
      "request": "launch",
      "program": "${file}",
      "console": "integratedTerminal",
      "justMyCode": true
    },
    {
      "name": "Python: Run Tests",
      "type": "python",
      "request": "launch",
      "module": "pytest",
      "args": ["tests/unit/", "-v"],
      "console": "integratedTerminal",
      "justMyCode": false
    }
  ]
}
```

#### PyCharm Setup

1. **Configure Interpreter**: Point to virtual environment
2. **Enable Type Checking**: Enable mypy integration
3. **Configure Code Style**: Import Black configuration
4. **Setup Run Configurations**: Create test runners

### Environment Variables

Create `.env` file for local development:

```bash
# Service Registry Configuration
MESH_REGISTRY_URL=http://localhost:8080
AGENT_NAME=dev-agent
HEALTH_INTERVAL=30
FALLBACK_MODE=true

# Development Settings
LOG_LEVEL=DEBUG
ENABLE_DEBUG_LOGS=true

# Test Configuration
TEST_BASE_DIRECTORY=/tmp/mcp_mesh_test
TEST_TIMEOUT=30
```

Load environment variables:

```bash
# Using python-dotenv
pip install python-dotenv

# In your code
from dotenv import load_dotenv
load_dotenv()
```

## Code Development Workflow

### Git Workflow

We follow the **Git Flow** branching strategy:

```
main                    # Production-ready code
├── develop            # Integration branch
├── feature/feature-name   # Feature development
├── release/version    # Release preparation
└── hotfix/fix-name    # Emergency fixes
```

#### Creating Feature Branches

```bash
# Start from develop branch
git checkout develop
git pull origin develop

# Create feature branch
git checkout -b feature/mesh-agent-enhancement

# Work on your feature...
# Commit changes regularly
git add .
git commit -m "feat: add dependency caching to mesh agent"

# Push feature branch
git push -u origin feature/mesh-agent-enhancement
```

#### Commit Message Convention

Follow **Conventional Commits** specification:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Types:**

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**

```bash
feat(mesh-agent): add automatic retry mechanism
fix(file-ops): resolve path traversal vulnerability
docs(api): update mesh agent decorator documentation
test(integration): add mesh registry connection tests
```

### Development Process

#### 1. Create Feature Branch

```bash
git checkout develop
git pull origin develop
git checkout -b feature/your-feature-name
```

#### 2. Write Code

Follow these principles:

- **Write tests first**: TDD approach when possible
- **Small, focused commits**: Each commit should represent a logical unit
- **Document as you go**: Update docstrings and comments
- **Follow type hints**: Use comprehensive type annotations

#### 3. Run Local Validation

Before committing, run the full validation suite:

```bash
# Format code
black src/ tests/
isort src/ tests/

# Type checking
mypy src/

# Linting
ruff check src/ tests/

# Run tests
pytest tests/unit/ -v
pytest tests/integration/ -v

# Or run the full CI pipeline locally
python scripts/run_ci_tests.py
```

#### 4. Commit and Push

```bash
git add .
git commit -m "feat(component): add new functionality"
git push -u origin feature/your-feature-name
```

#### 5. Create Pull Request

Create a pull request with:

- **Clear title**: Descriptive summary of changes
- **Detailed description**: What, why, and how
- **Test coverage**: Describe testing approach
- **Breaking changes**: Note any breaking changes

### Code Style Guidelines

#### Python Code Style

```python
# Good: Clear function with type hints and docstring
@mesh_agent(capabilities=["file_read"], dependencies=["auth_service"])
async def read_secure_file(
    path: str,
    encoding: str = "utf-8",
    auth_service: Optional[str] = None
) -> str:
    """
    Read file with security validation and audit logging.

    Args:
        path: File path to read
        encoding: File encoding (default: utf-8)
        auth_service: Authentication service (injected by mesh)

    Returns:
        File contents as string

    Raises:
        FileNotFoundError: If file not found
        SecurityValidationError: If security validation fails
    """
    # Implementation here
    pass
```

#### Documentation Style

````python
class FileOperations:
    """
    Core file operations with mesh integration.

    This class provides secure file system operations with automatic
    mesh integration, health monitoring, and comprehensive error handling.

    Example:
        ```python
        file_ops = FileOperations(base_directory="/safe/path")
        content = await file_ops.read_file("document.txt")
        ```

    Attributes:
        base_directory: Optional base directory constraint
        max_file_size: Maximum file size in bytes
    """
````

#### Error Handling Style

```python
# Good: Specific exception handling with proper MCP responses
try:
    content = await file_ops.read_file(path)
except FileNotFoundError as e:
    return e.to_mcp_response()
except SecurityValidationError as e:
    logger.security_warning(f"Security violation: {e}")
    return e.to_mcp_response()
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    return FileOperationError(
        str(e),
        code=MCPErrorCode.INTERNAL_ERROR
    ).to_mcp_response()
```

## Testing Procedures

### Test Categories

#### Unit Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/test_mesh_agent_decorator.py -v

# Run with coverage
pytest tests/unit/ --cov=mcp_mesh_sdk --cov-report=html
```

#### Integration Tests

```bash
# Run integration tests (requires services)
pytest tests/integration/ -v

# Run specific integration test
pytest tests/integration/test_file_operations_integration.py -v
```

#### End-to-End Tests

```bash
# Run E2E tests (full system)
pytest tests/e2e/ -v -s
```

### Test Writing Guidelines

#### Unit Test Structure

```python
import pytest
from mcp_mesh_sdk.decorators.mesh_agent import mesh_agent

class TestMeshAgentDecorator:
    """Test suite for mesh agent decorator."""

    @pytest.fixture
    def mock_registry(self):
        """Mock registry for testing."""
        # Setup mock
        yield mock
        # Cleanup

    @pytest.mark.asyncio
    async def test_decorator_applies_correctly(self):
        """Test that decorator applies metadata correctly."""
        @mesh_agent(capabilities=["test"])
        async def test_func():
            return "test"

        # Verify decorator metadata
        assert hasattr(test_func, '_mesh_agent_metadata')
        assert test_func._mesh_agent_metadata['capabilities'] == ["test"]

        # Verify function still works
        result = await test_func()
        assert result == "test"

    @pytest.mark.asyncio
    async def test_dependency_injection(self, mock_registry):
        """Test dependency injection functionality."""
        # Test implementation
        pass
```

#### Integration Test Structure

```python
import pytest
from mcp_mesh_sdk.tools.file_operations import FileOperations

class TestFileOperationsIntegration:
    """Integration tests for file operations."""

    @pytest.fixture
    async def file_ops(self, tmp_path):
        """File operations instance for testing."""
        ops = FileOperations(base_directory=tmp_path)
        yield ops
        await ops.cleanup()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_complete_file_workflow(self, file_ops, tmp_path):
        """Test complete file operation workflow."""
        test_file = tmp_path / "test.txt"
        test_content = "Hello, World!"

        # Write file
        result = await file_ops.write_file(str(test_file), test_content)
        assert result is True

        # Read file
        content = await file_ops.read_file(str(test_file))
        assert content == test_content

        # List directory
        files = await file_ops.list_directory(str(tmp_path))
        assert "test.txt" in files
```

### Test Configuration

#### `conftest.py` Setup

```python
import pytest
import tempfile
import asyncio
from pathlib import Path

@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def temp_directory():
    """Create temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)

@pytest.fixture
async def mock_mesh_registry():
    """Mock mesh registry for testing."""
    # Implementation
    yield mock_registry
```

### Performance Testing

```python
import time
import pytest

class TestPerformance:
    """Performance tests for critical operations."""

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_file_read_performance(self, large_test_file):
        """Test file read performance for large files."""
        start_time = time.time()

        content = await file_ops.read_file(str(large_test_file))

        duration = time.time() - start_time
        assert duration < 5.0  # Should complete in under 5 seconds
        assert len(content) > 0

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, file_ops):
        """Test performance under concurrent load."""
        tasks = []
        for i in range(10):
            task = file_ops.write_file(f"test_{i}.txt", f"content {i}")
            tasks.append(task)

        start_time = time.time()
        results = await asyncio.gather(*tasks)
        duration = time.time() - start_time

        assert all(results)
        assert duration < 2.0  # Should complete all operations quickly
```

## Code Review Process

### Pull Request Guidelines

#### PR Description Template

```markdown
## Description

Brief description of the changes and their purpose.

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Testing

- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] New tests added for new functionality
- [ ] Manual testing performed

## Checklist

- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Code is commented where necessary
- [ ] Documentation updated
- [ ] No breaking changes (or breaking changes documented)

## Screenshots/Examples

Include any relevant screenshots or code examples.
```

#### Review Checklist

**Code Quality:**

- [ ] Code follows project style guidelines
- [ ] Proper error handling implemented
- [ ] Type hints are comprehensive
- [ ] Docstrings are complete and accurate

**Security:**

- [ ] Input validation is present
- [ ] No sensitive data exposed
- [ ] Security best practices followed
- [ ] Path traversal protection in place

**Testing:**

- [ ] Adequate test coverage
- [ ] Tests are meaningful and comprehensive
- [ ] Integration tests added where appropriate
- [ ] Performance implications considered

**Documentation:**

- [ ] API documentation updated
- [ ] Usage examples provided
- [ ] Breaking changes documented
- [ ] Architecture docs updated if needed

### Review Process

1. **Author Self-Review**

   - Review your own PR before requesting review
   - Ensure all CI checks pass
   - Verify test coverage is adequate

2. **Automated Checks**

   - All CI/CD pipeline checks must pass
   - Code coverage must meet minimum threshold
   - Security scans must pass

3. **Peer Review**

   - At least one approving review required
   - Address all review comments
   - Re-request review after changes

4. **Merge Requirements**
   - All discussions resolved
   - All CI checks passing
   - Up-to-date with target branch

## Release Management

### Versioning Strategy

We follow **Semantic Versioning** (SemVer):

- **MAJOR.MINOR.PATCH** (e.g., 2.1.3)
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

#### Version Bumping

```bash
# Install version management tool
pip install bump2version

# Patch release (bug fixes)
bump2version patch

# Minor release (new features)
bump2version minor

# Major release (breaking changes)
bump2version major
```

### Release Process

#### 1. Prepare Release Branch

```bash
git checkout develop
git pull origin develop
git checkout -b release/v2.1.0
```

#### 2. Update Version and Changelog

```bash
# Update version in pyproject.toml and __init__.py
bump2version minor

# Update CHANGELOG.md with release notes
# Include all changes since last release
```

#### 3. Run Full Test Suite

```bash
# Run comprehensive tests
python scripts/run_ci_tests.py

# Run performance tests
pytest tests/ -m performance

# Manual testing of critical features
```

#### 4. Create Release PR

```bash
git push -u origin release/v2.1.0
# Create PR: release/v2.1.0 → main
```

#### 5. Deploy and Tag

After PR approval:

```bash
git checkout main
git pull origin main
git tag v2.1.0
git push origin v2.1.0

# Deploy to PyPI (automated via CI)
```

#### 6. Post-Release Tasks

```bash
# Merge main back to develop
git checkout develop
git merge main
git push origin develop

# Update documentation
# Announce release
```

### Hotfix Process

For critical production fixes:

```bash
# Create hotfix branch from main
git checkout main
git checkout -b hotfix/critical-security-fix

# Make minimal fix
# Test thoroughly
# Create PR: hotfix/critical-security-fix → main

# After merge, also merge to develop
git checkout develop
git merge main
```

## Troubleshooting

### Common Development Issues

#### Environment Setup Issues

**Problem**: Import errors after installation

```bash
# Solution: Verify virtual environment and installation
which python
pip list | grep mcp-mesh-sdk
pip install -e .[dev]  # Reinstall in editable mode
```

**Problem**: Pre-commit hooks failing

```bash
# Solution: Update and reinstall hooks
pre-commit clean
pre-commit install
pre-commit run --all-files
```

#### Testing Issues

**Problem**: Tests failing with import errors

```bash
# Solution: Check PYTHONPATH and test discovery
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
pytest tests/unit/ --collect-only  # Check test discovery
```

**Problem**: Integration tests failing

```bash
# Solution: Check test dependencies and services
docker-compose up -d  # Start required services
pytest tests/integration/ -v -s  # Run with verbose output
```

#### Code Quality Issues

**Problem**: MyPy type checking errors

```bash
# Solution: Add type hints and check configuration
mypy src/ --show-error-codes
# Add missing type hints
# Update mypy configuration in pyproject.toml
```

**Problem**: Black formatting conflicts

```bash
# Solution: Run formatters in correct order
black src/ tests/
isort src/ tests/
# Commit formatting changes separately
```

### Performance Debugging

#### Profiling Code

```python
import cProfile
import pstats

# Profile a function
profiler = cProfile.Profile()
profiler.enable()

# Your code here
await file_ops.read_file("large_file.txt")

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative').print_stats(10)
```

#### Memory Usage

```python
import tracemalloc

# Start tracing
tracemalloc.start()

# Your code here
await file_ops.read_file("large_file.txt")

# Get memory usage
current, peak = tracemalloc.get_traced_memory()
print(f"Current memory usage: {current / 1024 / 1024:.1f} MB")
print(f"Peak memory usage: {peak / 1024 / 1024:.1f} MB")
tracemalloc.stop()
```

### Getting Help

1. **Check documentation**: Review relevant documentation files
2. **Search issues**: Look for similar issues in GitHub
3. **Run diagnostics**: Use provided diagnostic tools
4. **Create issue**: If problem persists, create detailed issue

#### Issue Template

```markdown
## Bug Description

Brief description of the issue.

## Environment

- OS: [e.g., Ubuntu 20.04]
- Python: [e.g., 3.10.5]
- MCP Mesh SDK: [e.g., 2.1.0]

## Steps to Reproduce

1. Step one
2. Step two
3. Error occurs

## Expected Behavior

What should happen.

## Actual Behavior

What actually happens.

## Logs/Error Messages
```

Include relevant logs or error messages

```

## Additional Context
Any other relevant information.
```

This development workflow ensures consistent, high-quality development practices while maintaining project standards and facilitating collaboration.
