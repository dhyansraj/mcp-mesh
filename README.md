# MCP Mesh SDK

[![CI/CD Pipeline](https://github.com/yourusername/mcp-mesh/actions/workflows/ci.yml/badge.svg)](https://github.com/yourusername/mcp-mesh/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/yourusername/mcp-mesh/branch/main/graph/badge.svg)](https://codecov.io/gh/yourusername/mcp-mesh)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compliance](https://img.shields.io/badge/MCP-compliant-green.svg)](https://github.com/anthropics/model-context-protocol)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A production-ready service mesh for Model Context Protocol (MCP) services built on the official Anthropic MCP Python SDK.

## Overview

This project provides a service mesh implementation that leverages the official MCP SDK to create, manage, and coordinate MCP services in a distributed environment.

## Features

- **Official MCP SDK Integration**: Built on the official Anthropic MCP Python SDK
- **Service Mesh Architecture**: Distributed service discovery and management
- **Development Tools**: Comprehensive testing, linting, and type checking
- **Production Ready**: Designed for enterprise deployment scenarios

## Quick Start

### Prerequisites

- Python 3.10 or higher
- Virtual environment (recommended)

### Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd mcp-mesh
```

2. Create and activate virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements-dev.txt
```

4. Run tests to verify setup:

```bash
pytest
```

### Development

#### Running the Example Server

```bash
python examples/simple_server.py
```

#### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=mcp_mesh_sdk

# Run specific test categories
pytest -m unit
pytest -m integration
```

#### Code Quality

```bash
# Format code
black src/ tests/

# Sort imports
isort src/ tests/

# Lint code
ruff check src/ tests/

# Type checking
mypy src/
```

## Project Structure

```
mcp-mesh/
├── src/mcp_mesh_sdk/          # Main package
│   ├── server/                # MCP server components
│   ├── client/                # MCP client components
│   ├── shared/                # Shared utilities
│   ├── tools/                 # Tool implementations
│   ├── resources/             # Resource implementations
│   └── prompts/               # Prompt implementations
├── tests/                     # Test suite
│   ├── unit/                  # Unit tests
│   ├── integration/           # Integration tests
│   └── e2e/                   # End-to-end tests
├── examples/                  # Usage examples
├── docs/                      # Documentation
└── scripts/                   # Utility scripts
```

## Architecture

This implementation follows the official MCP SDK patterns and extends them with service mesh capabilities:

- **MCP Protocol Compliance**: Full compatibility with MCP specification
- **Service Discovery**: Automatic service registration and discovery
- **Load Balancing**: Intelligent request routing
- **Health Monitoring**: Service health checks and monitoring
- **Security**: Authentication and authorization

## CI/CD Pipeline

This project uses GitHub Actions for continuous integration and deployment:

### Automated Testing

- **Multi-Python Testing**: Tests on Python 3.10, 3.11, and 3.12
- **Test Categories**: Unit, integration, and end-to-end tests run in proper order
- **MCP Compliance**: Automated MCP protocol compliance validation
- **Coverage Reporting**: Comprehensive code coverage with Codecov integration

### Code Quality

- **Linting**: Ruff and Black for code formatting
- **Type Checking**: MyPy for static type analysis
- **Security Scanning**: Bandit for security vulnerability detection
- **Import Sorting**: isort for consistent import organization

### Build and Release

- **Package Building**: Automated package building and verification
- **Release Automation**: Automated GitHub releases and PyPI publishing
- **Dependency Updates**: Weekly automated dependency updates

### Local CI Testing

Run the full CI pipeline locally:

```bash
python scripts/run_ci_tests.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run local CI tests: `python scripts/run_ci_tests.py`
5. Submit a pull request

All PRs must pass:

- ✅ Code quality checks (ruff, black, mypy)
- ✅ All test suites (unit, integration, e2e)
- ✅ MCP protocol compliance tests
- ✅ Security scans
- ✅ Build verification

## License

MIT License - see LICENSE file for details.
