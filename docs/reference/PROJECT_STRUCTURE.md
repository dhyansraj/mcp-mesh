# Project Structure Documentation

This document provides a comprehensive overview of the MCP Mesh SDK project structure, explaining the purpose and contents of each directory and file.

## Overview

The MCP Mesh SDK is organized as a modern Python project with clear separation of concerns, following industry best practices for SDK development, testing, and documentation.

## Root Directory Structure

```
mcp-mesh/
├── .github/                    # GitHub configuration
│   └── workflows/             # CI/CD workflows
├── docs/                      # Project documentation
├── examples/                  # Usage examples and demos
├── src/                       # Source code
│   └── mcp_mesh_sdk/         # Main package
├── tests/                     # Test suite
│   ├── unit/                 # Unit tests
│   ├── integration/          # Integration tests
│   └── e2e/                  # End-to-end tests
├── scripts/                   # Utility scripts
├── project_plan/             # Project planning documents
├── pyproject.toml            # Project configuration
├── requirements*.txt         # Dependencies
└── README.md                 # Main project documentation
```

## Detailed Directory Structure

### Source Code (`src/mcp_mesh_sdk/`)

The main package follows the standard Python package structure with clear module organization:

```
src/mcp_mesh_sdk/
├── __init__.py               # Package initialization and public API
├── client/                   # MCP client components
│   ├── __init__.py
│   └── test_client.py       # Client implementation
├── decorators/               # Core decorators
│   ├── __init__.py
│   └── mesh_agent.py        # @mesh_agent decorator
├── prompts/                  # MCP prompt implementations
│   └── __init__.py
├── resources/                # MCP resource implementations
│   └── __init__.py
├── server/                   # MCP server components
│   ├── __init__.py
│   ├── hello_world.py       # Example server
│   └── simple_hello.py      # Simple server implementation
├── shared/                   # Shared utilities and types
│   ├── __init__.py
│   ├── exceptions.py        # Custom exception classes
│   ├── registry_client.py   # Service registry client
│   └── types.py             # Type definitions
└── tools/                    # MCP tool implementations
    ├── __init__.py
    └── file_operations.py    # File operations tool
```

#### Module Purposes

##### `decorators/`

- **`mesh_agent.py`**: Core decorator implementation that provides zero-boilerplate mesh integration
- Handles service registration, dependency injection, health monitoring, and error handling

##### `tools/`

- **`file_operations.py`**: Comprehensive file operations with security, retry logic, and mesh integration
- Implements read, write, and list operations with automatic backup and audit logging

##### `shared/`

- **`exceptions.py`**: MCP-compliant exception classes with proper error codes
- **`registry_client.py`**: Client for service registry communication
- **`types.py`**: Type definitions for health status, retry configuration, and file operations

##### `server/` and `client/`

- Server and client implementations for MCP protocol
- Example implementations and test utilities

##### `resources/` and `prompts/`

- MCP resource and prompt implementations
- Extensible framework for custom resources and prompts

### Test Suite (`tests/`)

Comprehensive test coverage organized by test type:

```
tests/
├── __init__.py
├── conftest.py                          # Pytest configuration and fixtures
├── unit/                                # Unit tests (fast, isolated)
│   ├── __init__.py
│   ├── test_file_operations.py          # File operations unit tests
│   ├── test_file_operations_enhanced.py # Enhanced file operations tests
│   ├── test_mesh_agent_decorator.py     # Decorator unit tests
│   ├── test_mesh_agent_enhanced.py      # Enhanced decorator tests
│   ├── test_mock_integration.py         # Mock integration tests
│   ├── test_performance.py              # Performance unit tests
│   ├── test_runner_simple.py            # Simple test runner
│   ├── test_security_validation.py      # Security validation tests
│   ├── test_security_validation_enhanced.py # Enhanced security tests
│   └── test_server.py                   # Server unit tests
├── integration/                         # Integration tests (with dependencies)
│   ├── __init__.py
│   ├── test_comprehensive_file_agent_suite.py # Comprehensive file agent tests
│   ├── test_end_to_end_workflows.py     # End-to-end workflow tests
│   ├── test_file_operations_integration.py # File operations integration
│   ├── test_mcp_protocol_compliance.py  # MCP protocol compliance tests
│   ├── test_mesh_integration.py         # Mesh integration tests
│   └── test_performance_load.py         # Performance and load tests
└── e2e/                                 # End-to-end tests (full system)
    └── __init__.py
```

#### Test Categories

1. **Unit Tests**: Fast, isolated tests that mock external dependencies
2. **Integration Tests**: Tests that verify component interaction with real dependencies
3. **End-to-End Tests**: Full system tests that verify complete workflows

### Documentation (`docs/`)

Comprehensive documentation covering all aspects of the project:

```
docs/
├── ERROR_HANDLING_TYPES.md              # Error handling documentation
├── FILE_AGENT_ARCHITECTURE.md           # File agent architecture details
├── FILE_AGENT_COMPLETE_DESIGN.md        # Complete file agent design
├── MCP_PROTOCOL_INTEGRATION.md          # MCP protocol integration guide
├── MESH_AGENT_DECORATOR_SPEC.md         # Mesh agent decorator specification
├── MESH_INTEGRATION_HEALTH.md           # Health monitoring documentation
├── PROJECT_STRUCTURE.md                 # This document
├── DEVELOPMENT_WORKFLOW.md              # Development workflow guide
├── ARCHITECTURE_OVERVIEW.md             # System architecture overview
├── CONTRIBUTING.md                      # Contributing guidelines
└── MAINTENANCE_OPERATIONS.md            # Maintenance and operations guide
```

### Examples (`examples/`)

Practical examples demonstrating SDK usage:

```
examples/
├── fastmcp_integration_example.py       # FastMCP integration example
├── file_agent_example.py               # File agent usage example
├── file_operations_fastmcp.py          # File operations with FastMCP
└── simple_server.py                    # Simple MCP server example
```

### Scripts (`scripts/`)

Utility scripts for development and CI/CD:

```
scripts/
└── run_ci_tests.py                     # CI test runner script
```

### Project Planning (`project_plan/`)

Project planning and design documents:

```
project_plan/
├── DECORATOR_PATTERN_GUIDE.md          # Decorator pattern implementation guide
├── TIMELINE_ASSESSMENT.md              # Project timeline assessment
└── wk1_day1/                          # Week 1, Day 1 planning
    ├── acceptance_criteria.md           # Acceptance criteria
    ├── requirements.md                  # Requirements specification
    └── tasks.md                        # Task breakdown
```

## File Organization Patterns

### Module Naming Conventions

- **Underscores for separators**: Use `snake_case` for module and file names
- **Descriptive names**: Module names clearly indicate their purpose
- **Logical grouping**: Related functionality is grouped in the same module

### Package Organization

- **Single responsibility**: Each module has a clear, single responsibility
- **Dependency direction**: Dependencies flow from concrete to abstract
- **Interface segregation**: Public APIs are clearly separated from internal implementations

### Import Structure

- **Relative imports within package**: Use relative imports for intra-package dependencies
- **Absolute imports for external**: Use absolute imports for external dependencies
- **Public API through `__init__.py`**: Main package API is exposed through `__init__.py`

## Configuration Files

### `pyproject.toml`

Central configuration file containing:

- **Project metadata**: Name, version, description, authors
- **Dependencies**: Runtime and development dependencies
- **Tool configurations**: Black, isort, mypy, ruff, pytest settings
- **Build system**: Hatchling build backend configuration

### Requirements Files

- **`requirements.txt`**: Core runtime dependencies
- **`requirements-dev.txt`**: Development dependencies
- **`requirements-prod.txt`**: Production-only dependencies

### CI/CD Configuration

- **`.github/workflows/`**: GitHub Actions workflows
- **`.pre-commit-config.yaml`**: Pre-commit hooks configuration
- **`codecov.yml`**: Code coverage configuration

## Security Considerations

### File Organization Security

- **Sensitive data exclusion**: No sensitive data in version control
- **Proper `.gitignore`**: Comprehensive gitignore patterns
- **Secure defaults**: Default configurations prioritize security

### Code Organization Security

- **Input validation**: All external inputs are validated at module boundaries
- **Error handling**: Comprehensive error handling prevents information leakage
- **Dependency isolation**: External dependencies are isolated and properly managed

## Extensibility

### Adding New Components

1. **Tools**: Add new MCP tools in `src/mcp_mesh_sdk/tools/`
2. **Resources**: Add new MCP resources in `src/mcp_mesh_sdk/resources/`
3. **Prompts**: Add new MCP prompts in `src/mcp_mesh_sdk/prompts/`
4. **Decorators**: Add new decorators in `src/mcp_mesh_sdk/decorators/`

### Testing New Components

1. **Unit tests**: Add in `tests/unit/test_[component].py`
2. **Integration tests**: Add in `tests/integration/test_[component]_integration.py`
3. **Examples**: Add usage examples in `examples/[component]_example.py`

### Documentation

1. **API documentation**: Update docstrings and type hints
2. **Usage examples**: Add examples and tutorials
3. **Architecture docs**: Update design documents as needed

## Maintenance

### Regular Maintenance Tasks

1. **Dependency updates**: Regular updates of dependencies
2. **Documentation updates**: Keep documentation in sync with code
3. **Test coverage**: Maintain high test coverage
4. **Performance monitoring**: Regular performance testing

### Code Quality

1. **Automated formatting**: Black and isort for consistent formatting
2. **Type checking**: MyPy for static type analysis
3. **Linting**: Ruff for code quality checks
4. **Testing**: Comprehensive test suite with pytest

This structure provides a solid foundation for the MCP Mesh SDK, ensuring maintainability, extensibility, and clear separation of concerns while following Python best practices.
