# Contributing Guidelines

Welcome to the MCP Mesh SDK project! This document provides comprehensive guidelines for contributing to the project, ensuring high-quality contributions that align with project standards.

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Setup](#development-setup)
4. [Contribution Workflow](#contribution-workflow)
5. [Coding Standards](#coding-standards)
6. [Testing Requirements](#testing-requirements)
7. [Documentation Requirements](#documentation-requirements)
8. [Pull Request Process](#pull-request-process)
9. [Issue Guidelines](#issue-guidelines)
10. [Release Process](#release-process)

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for all contributors, regardless of experience level, gender, gender identity and expression, sexual orientation, disability, personal appearance, body size, race, ethnicity, age, religion, or nationality.

### Expected Behavior

- **Be respectful**: Treat all community members with respect and kindness
- **Be collaborative**: Work together to improve the project
- **Be patient**: Help newcomers and be understanding of different skill levels
- **Be constructive**: Provide helpful feedback and suggestions
- **Be professional**: Maintain professional communication in all interactions

### Unacceptable Behavior

- Harassment, discrimination, or offensive comments
- Personal attacks or insults
- Trolling or deliberately disruptive behavior
- Publishing private information without consent
- Any conduct that would be inappropriate in a professional setting

### Enforcement

Project maintainers have the right and responsibility to remove, edit, or reject contributions that do not align with this Code of Conduct. Report unacceptable behavior to the project maintainers.

## Getting Started

### Prerequisites

Before contributing, ensure you have:

- **Python 3.10+**: Required for development
- **Git**: For version control
- **GitHub account**: For submitting contributions
- **Basic understanding of**: Python, async programming, MCP protocol

### Project Overview

The MCP Mesh SDK provides:

- Zero-boilerplate mesh integration for MCP services
- Comprehensive file operations with security
- Service discovery and dependency injection
- Health monitoring and error handling

### Key Technologies

- **Python 3.10+**: Modern Python with type hints
- **AsyncIO**: Asynchronous programming
- **MCP SDK**: Official Anthropic MCP SDK
- **pytest**: Testing framework
- **Black/isort**: Code formatting
- **MyPy**: Static type checking

## Development Setup

### Local Environment Setup

1. **Fork and Clone Repository**

   ```bash
   # Fork on GitHub, then clone your fork
   git clone https://github.com/YOUR_USERNAME/mcp-mesh.git
   cd mcp-mesh

   # Add upstream remote
   git remote add upstream https://github.com/ORIGINAL_OWNER/mcp-mesh.git
   ```

2. **Create Virtual Environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install Development Dependencies**

   ```bash
   pip install -r requirements-dev.txt
   pip install -e .  # Install in editable mode
   ```

4. **Install Pre-commit Hooks**

   ```bash
   pre-commit install
   ```

5. **Verify Setup**

   ```bash
   # Run basic tests
   pytest tests/unit/test_runner_simple.py -v

   # Check code quality
   black --check src/ tests/
   mypy src/
   ruff check src/ tests/
   ```

### IDE Configuration

#### Recommended VS Code Extensions

- **Python**: Python language support
- **Python Docstring Generator**: Auto-generate docstrings
- **GitLens**: Enhanced Git integration
- **Test Explorer**: Test discovery and running
- **Error Lens**: Inline error highlighting

#### Recommended Settings

```json
{
  "python.defaultInterpreterPath": "./.venv/bin/python",
  "python.formatting.provider": "black",
  "python.linting.mypyEnabled": true,
  "python.testing.pytestEnabled": true,
  "files.trimTrailingWhitespace": true,
  "files.insertFinalNewline": true
}
```

## Contribution Workflow

### Git Workflow

We use **Git Flow** with the following branches:

- **`main`**: Production-ready code
- **`develop`**: Integration branch for new features
- **`feature/*`**: Feature development branches
- **`release/*`**: Release preparation branches
- **`hotfix/*`**: Emergency fixes for production

### Contribution Process

1. **Create Feature Branch**

   ```bash
   git checkout develop
   git pull upstream develop
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**

   - Write code following project standards
   - Add or update tests
   - Update documentation
   - Run local validation

3. **Commit Changes**

   ```bash
   git add .
   git commit -m "feat(component): add new functionality"
   ```

4. **Push and Create PR**
   ```bash
   git push origin feature/your-feature-name
   # Create pull request on GitHub
   ```

### Commit Message Guidelines

Follow **Conventional Commits** specification:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

#### Commit Types

- **`feat`**: New feature
- **`fix`**: Bug fix
- **`docs`**: Documentation changes
- **`style`**: Code style changes (formatting, semicolons, etc.)
- **`refactor`**: Code refactoring without functionality changes
- **`test`**: Adding or updating tests
- **`chore`**: Maintenance tasks (dependencies, build, etc.)
- **`perf`**: Performance improvements
- **`ci`**: CI/CD changes

#### Examples

```bash
feat(mesh-agent): add automatic retry mechanism
fix(file-ops): resolve path traversal vulnerability
docs(api): update decorator documentation
test(integration): add mesh registry connection tests
refactor(exceptions): simplify error hierarchy
chore(deps): update development dependencies
```

## Coding Standards

### Python Style Guidelines

#### Code Formatting

- **Black**: Automatic code formatting (line length: 88)
- **isort**: Import sorting and organization
- **Consistent style**: Follow existing code patterns

```python
# Good: Proper formatting and structure
@mesh_agent(
    capabilities=["file_operations"],
    dependencies=["auth_service", "audit_logger"],
    health_interval=30,
    fallback_mode=True
)
async def secure_file_operation(
    path: str,
    operation: str,
    auth_service: Optional[str] = None,
    audit_logger: Optional[str] = None
) -> Dict[str, Any]:
    """
    Perform secure file operation with mesh integration.

    Args:
        path: File path for operation
        operation: Type of operation (read, write, list)
        auth_service: Authentication service (injected)
        audit_logger: Audit logging service (injected)

    Returns:
        Operation result with metadata

    Raises:
        SecurityValidationError: If security validation fails
        FileOperationError: If file operation fails
    """
    # Implementation here
    pass
```

#### Type Hints

- **Comprehensive typing**: Use type hints for all functions
- **Generic types**: Use appropriate generic types
- **Optional types**: Explicitly mark optional parameters

```python
from typing import Dict, List, Optional, Union, Any, Callable, Awaitable

# Good: Comprehensive type hints
async def process_files(
    file_paths: List[str],
    processor: Callable[[str], Awaitable[str]],
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Union[str, Exception]]:
    """Process multiple files with given processor function."""
    results: Dict[str, Union[str, Exception]] = {}
    # Implementation
    return results
```

#### Error Handling

- **Specific exceptions**: Use specific exception types
- **MCP compliance**: Return MCP-compliant error responses
- **Comprehensive logging**: Log errors with context

```python
# Good: Specific error handling
try:
    result = await file_ops.read_file(path)
    return result
except FileNotFoundError as e:
    logger.warning(f"File not found: {path}")
    return e.to_mcp_response()
except SecurityValidationError as e:
    logger.security_warning(f"Security violation: {e}")
    return e.to_mcp_response()
except Exception as e:
    logger.error(f"Unexpected error reading {path}: {e}")
    return FileOperationError(
        str(e),
        file_path=path,
        operation="read",
        code=MCPErrorCode.INTERNAL_ERROR
    ).to_mcp_response()
```

#### Documentation Standards

````python
class FileOperations:
    """
    Core file operations with mesh integration.

    This class provides secure file system operations with automatic
    mesh integration, health monitoring, and comprehensive error handling.

    The class uses the @mesh_agent decorator to automatically integrate
    with the service mesh, providing dependency injection, health monitoring,
    and service registration capabilities.

    Example:
        ```python
        # Basic usage
        file_ops = FileOperations(base_directory="/safe/path")
        content = await file_ops.read_file("document.txt")

        # With dependency injection
        @mesh_agent(dependencies=["auth_service"])
        async def secure_read(path: str, auth_service=None):
            if auth_service:
                # Use injected auth service
                pass
            return await file_ops.read_file(path)
        ```

    Attributes:
        base_directory: Optional base directory constraint for security
        max_file_size: Maximum file size in bytes (default: 10MB)
        allowed_extensions: Set of allowed file extensions

    Note:
        All file operations include comprehensive security validation,
        automatic retry logic, and audit logging when configured.
    """

    def __init__(
        self,
        base_directory: Optional[str] = None,
        max_file_size: int = 10 * 1024 * 1024
    ) -> None:
        """
        Initialize file operations with security constraints.

        Args:
            base_directory: Optional base directory for operations.
                If provided, all operations are restricted to this directory
                and its subdirectories for security.
            max_file_size: Maximum file size in bytes. Files larger than
                this limit will raise FileTooLargeError.

        Raises:
            ValueError: If base_directory is invalid or inaccessible.
        """
        pass
````

### Security Guidelines

#### Input Validation

```python
# Good: Comprehensive input validation
async def validate_file_path(self, path: str) -> Path:
    """Validate and sanitize file path."""
    if not isinstance(path, str):
        raise TypeError("Path must be a string")

    if not path.strip():
        raise ValueError("Path cannot be empty")

    if '..' in path:
        raise PathTraversalError(f"Path traversal detected: {path}")

    # Additional validation...
    return Path(path).resolve()
```

#### Secure Defaults

```python
# Good: Secure defaults
@mesh_agent(
    capabilities=["file_operations"],
    security_context="restricted_file_access",  # Explicit security context
    fallback_mode=False,  # Fail securely if mesh unavailable
    timeout=30  # Reasonable timeout
)
async def secure_operation():
    pass
```

## Testing Requirements

### Test Categories

#### Unit Tests

- **Fast execution**: < 100ms per test
- **Isolated**: Mock external dependencies
- **Comprehensive**: Cover all code paths
- **Clear naming**: Descriptive test names

```python
class TestMeshAgentDecorator:
    """Unit tests for mesh agent decorator."""

    @pytest.fixture
    def mock_registry(self):
        """Mock registry client for testing."""
        with patch('mcp_mesh_sdk.shared.registry_client.RegistryClient') as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_decorator_metadata_storage(self):
        """Test that decorator stores metadata correctly."""
        @mesh_agent(capabilities=["test_capability"])
        async def test_function():
            return "test_result"

        # Verify metadata is stored
        assert hasattr(test_function, '_mesh_agent_metadata')
        metadata = test_function._mesh_agent_metadata
        assert metadata['capabilities'] == ["test_capability"]

        # Verify function still works
        result = await test_function()
        assert result == "test_result"

    @pytest.mark.asyncio
    async def test_dependency_injection_with_cache(self, mock_registry):
        """Test dependency injection with caching."""
        # Setup mock
        mock_registry.return_value.get_dependency.return_value = "mock_service"

        @mesh_agent(
            capabilities=["test"],
            dependencies=["test_service"],
            enable_caching=True
        )
        async def test_function(test_service=None):
            return test_service

        # First call should query registry
        result1 = await test_function()
        assert result1 == "mock_service"
        mock_registry.return_value.get_dependency.assert_called_once()

        # Second call should use cache
        mock_registry.return_value.get_dependency.reset_mock()
        result2 = await test_function()
        assert result2 == "mock_service"
        mock_registry.return_value.get_dependency.assert_not_called()
```

#### Integration Tests

- **Real dependencies**: Use actual services when possible
- **Environment setup**: Proper test environment configuration
- **Cleanup**: Ensure proper cleanup after tests

```python
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
    async def test_complete_workflow(self, file_ops, tmp_path):
        """Test complete file operation workflow."""
        # Test data
        test_file = tmp_path / "test_document.txt"
        test_content = "Hello, World!\nThis is a test file."

        # Write file
        write_result = await file_ops.write_file(
            str(test_file),
            test_content,
            create_backup=False
        )
        assert write_result is True
        assert test_file.exists()

        # Read file
        read_content = await file_ops.read_file(str(test_file))
        assert read_content == test_content

        # List directory
        files = await file_ops.list_directory(
            str(tmp_path),
            include_details=True
        )
        assert len(files) == 1
        assert files[0]["name"] == "test_document.txt"
        assert files[0]["type"] == "file"
```

#### End-to-End Tests

- **Full system**: Test complete workflows
- **Real scenarios**: Simulate actual usage patterns
- **Performance**: Include performance validation

### Test Coverage Requirements

- **Minimum coverage**: 85% overall
- **Critical paths**: 95% coverage for security-related code
- **New code**: 90% coverage for all new contributions

```bash
# Run tests with coverage
pytest --cov=mcp_mesh_sdk --cov-report=html --cov-report=term-missing

# View coverage report
open htmlcov/index.html
```

## Documentation Requirements

### API Documentation

- **Comprehensive docstrings**: All public APIs must have detailed docstrings
- **Type information**: Include type hints in documentation
- **Examples**: Provide usage examples for complex APIs
- **Error documentation**: Document all possible exceptions

### User Documentation

- **Getting started guides**: Clear setup and usage instructions
- **Tutorials**: Step-by-step tutorials for common use cases
- **API reference**: Complete API reference documentation
- **Architecture docs**: System design and architecture documentation

### Code Comments

```python
# Good: Helpful comments for complex logic
async def _calculate_retry_delay(self, attempt: int, config: RetryConfig) -> float:
    """Calculate retry delay based on strategy."""
    base_delay = config.initial_delay_ms / 1000.0

    # Apply backoff strategy
    if config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
        # Exponential backoff: delay = base * (multiplier ^ attempt)
        delay = base_delay * (config.backoff_multiplier ** attempt)
    elif config.strategy == RetryStrategy.LINEAR_BACKOFF:
        # Linear backoff: delay = base * (attempt + 1)
        delay = base_delay * (attempt + 1)
    else:
        # Fixed delay: always use base delay
        delay = base_delay

    # Ensure delay doesn't exceed maximum
    delay = min(delay, config.max_delay_ms / 1000.0)

    # Add jitter to prevent thundering herd if enabled
    if config.jitter:
        jitter_factor = random.uniform(0.8, 1.2)
        delay *= jitter_factor

    return delay
```

## Pull Request Process

### PR Requirements

Before submitting a pull request, ensure:

- [ ] **Code quality**: All linting and formatting checks pass
- [ ] **Tests**: All tests pass, including new tests for new functionality
- [ ] **Coverage**: Test coverage meets minimum requirements
- [ ] **Documentation**: API documentation is updated
- [ ] **Changelog**: Significant changes are noted in changelog
- [ ] **Breaking changes**: Breaking changes are clearly documented

### PR Template

```markdown
## Description

Brief description of the changes and their purpose.

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Code refactoring

## Testing

- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] E2E tests pass (if applicable)
- [ ] New tests added for new functionality
- [ ] Manual testing performed

## Documentation

- [ ] API documentation updated
- [ ] User documentation updated
- [ ] Code comments added where necessary
- [ ] Breaking changes documented

## Checklist

- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] No console.log or debug statements
- [ ] No sensitive information exposed
- [ ] Performance implications considered

## Related Issues

Fixes #(issue number)

## Screenshots/Examples

Include any relevant screenshots or code examples.

## Additional Notes

Any additional information that reviewers should know.
```

### Review Process

1. **Automated Checks**: All CI/CD checks must pass
2. **Self Review**: Author should review their own PR first
3. **Peer Review**: At least one approving review from maintainer
4. **Address Feedback**: Respond to all review comments
5. **Final Approval**: All discussions resolved before merge

### Merge Requirements

- ✅ All CI checks passing
- ✅ At least one approving review
- ✅ All conversations resolved
- ✅ Branch up to date with target branch
- ✅ No merge conflicts

## Issue Guidelines

### Bug Reports

Use the bug report template:

```markdown
## Bug Description

A clear and concise description of what the bug is.

## Environment

- OS: [e.g., Ubuntu 20.04, Windows 10, macOS 12]
- Python: [e.g., 3.10.5]
- MCP Mesh SDK: [e.g., 2.1.0]
- Other relevant versions

## Steps to Reproduce

1. Step one
2. Step two
3. Step three
4. See error

## Expected Behavior

A clear description of what you expected to happen.

## Actual Behavior

A clear description of what actually happened.

## Error Messages/Logs
```

Paste error messages or relevant logs here

```

## Additional Context
Add any other context about the problem here.

## Possible Solution
If you have ideas about what might be causing the issue or how to fix it.
```

### Feature Requests

Use the feature request template:

```markdown
## Feature Description

A clear and concise description of the feature you'd like to see.

## Use Case

Describe the use case or problem this feature would solve.

## Proposed Solution

Describe how you envision this feature working.

## Alternatives Considered

Describe any alternative solutions or features you've considered.

## Additional Context

Add any other context, mockups, or examples about the feature request.

## Implementation Notes

If you have ideas about how this could be implemented.
```

### Issue Labels

- **`bug`**: Something isn't working
- **`enhancement`**: New feature or request
- **`documentation`**: Improvements or additions to documentation
- **`good first issue`**: Good for newcomers
- **`help wanted`**: Extra attention is needed
- **`priority:high`**: High priority issue
- **`priority:low`**: Low priority issue
- **`needs:investigation`**: Requires further investigation
- **`needs:reproduction`**: Unable to reproduce the issue

## Release Process

### Version Management

We follow **Semantic Versioning** (SemVer):

- **MAJOR.MINOR.PATCH** (e.g., 2.1.3)
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

### Release Workflow

1. **Feature Freeze**: Stop accepting new features for release
2. **Release Branch**: Create release branch from develop
3. **Testing**: Comprehensive testing of release candidate
4. **Documentation**: Update changelog and documentation
5. **Version Bump**: Update version numbers
6. **Release**: Tag and publish release
7. **Post-Release**: Merge back to develop and main

### Changelog Guidelines

```markdown
## [2.1.0] - 2024-01-15

### Added

- New @mesh_agent decorator with enhanced dependency injection
- File operations with comprehensive security validation
- Automatic retry mechanisms with configurable strategies
- Health monitoring and status reporting

### Changed

- Improved error handling with MCP-compliant responses
- Enhanced performance with intelligent caching
- Updated documentation with comprehensive examples

### Fixed

- Fixed path traversal vulnerability in file operations
- Resolved memory leak in dependency caching
- Fixed race condition in health monitoring

### Deprecated

- Old registry client interface (will be removed in v3.0.0)

### Security

- Added comprehensive input validation
- Implemented audit logging for security events
- Enhanced authentication and authorization
```

## Getting Help

### Resources

- **Documentation**: Check the docs/ directory
- **Examples**: Review example code in examples/
- **Issues**: Search existing GitHub issues
- **Discussions**: Use GitHub Discussions for questions

### Community

- **Be patient**: Maintainers are volunteers
- **Be specific**: Provide detailed information in questions
- **Be helpful**: Help others when you can
- **Follow up**: Update issues with additional information

### Contact

For questions about contributing:

1. Check existing documentation
2. Search GitHub issues
3. Create a new issue with the "question" label
4. Join community discussions

---

Thank you for contributing to the MCP Mesh SDK! Your contributions help make this project better for everyone.
