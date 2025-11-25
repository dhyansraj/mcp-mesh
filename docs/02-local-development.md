# Local Development

> Set up a professional development environment for building MCP Mesh agents

## Overview

After running your first Hello World example, it's time to set up a proper development environment. This guide covers professional development practices, debugging techniques, and productivity tools for MCP Mesh development.

## What You'll Learn

By the end of this section, you will:

- ✅ Set up a complete local development environment
- ✅ Run the MCP Mesh registry with different database backends
- ✅ Debug agents using IDE tools and logging
- ✅ Implement hot reload for rapid development
- ✅ Write and run comprehensive tests for your agents

## Development Workflow

Here's the typical development workflow we'll establish:

```mermaid
graph LR
    A[Write Code] --> B[Hot Reload]
    B --> C[Test Locally]
    C --> D[Debug if Needed]
    D --> A
    C --> E[Run Tests]
    E --> F[Commit Changes]
```

## Section Contents

1. **[Development Environment Setup](./02-local-development/01-environment-setup.md)** - IDEs, tools, and configuration
2. **[Running Registry Locally](./02-local-development/02-local-registry.md)** - SQLite vs PostgreSQL, data persistence
3. **[Debugging Agents](./02-local-development/03-debugging.md)** - IDE debugging, logging, troubleshooting
4. **[Hot Reload and Development Workflow](./02-local-development/04-hot-reload.md)** - Automatic reloading, file watching
5. **[Testing Your Agents](./02-local-development/05-testing.md)** - Unit tests, integration tests, test coverage

## Key Development Tools

### 1. Virtual Environments

Keep your dependencies isolated:

```bash
# Create project-specific environment
python -m venv .venv
source .venv/bin/activate

# Install development dependencies
make install-dev
```

### 2. Environment Variables

Use `.env` files for configuration:

```bash
# .env
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_HTTP_PORT=8081
DATABASE_URL=postgresql://user:pass@localhost/mcp_mesh
```

### 3. Development Registry

Run registry with hot reload:

```bash
# Start registry with automatic database setup
./bin/meshctl start-registry

# PostgreSQL for production-like testing
docker run -d -p 5432:5432 \
  -e POSTGRES_DB=mcp_mesh \
  -e POSTGRES_PASSWORD=password \
  postgres:15
```

### 4. Code Quality Tools

Maintain high code quality:

```bash
# Format code
black src/ tests/

# Sort imports
isort src/ tests/

# Lint code
ruff check src/

# Type checking
mypy src/
```

## Quick Start Commands

Get started quickly with these commands:

```bash
# Clone the repository
git clone https://github.com/your-org/weather-agent
cd weather-agent

# Set up development environment
make dev-setup  # or ./scripts/setup-dev.sh

# Start all services
make dev-start  # Starts registry, database, and monitoring

# Run your agent
./bin/meshctl start examples/simple/weather_agent.py

# Run tests
make test       # All tests
make test-unit  # Unit tests only
make test-integration  # Integration tests
```

## Development Best Practices

### 1. Project Structure

Organize your agent projects consistently:

```
my-agent/
├── src/
│   ├── __init__.py
│   ├── agent.py           # Main agent code
│   ├── handlers.py        # Request handlers
│   └── utils.py          # Utility functions
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py       # pytest configuration
├── configs/
│   ├── development.yaml
│   ├── staging.yaml
│   └── production.yaml
├── scripts/
│   ├── setup-dev.sh
│   └── run-tests.sh
├── .env.example
├── requirements.txt
├── requirements-dev.txt
├── Makefile
└── README.md
```

### 2. Configuration Management

Use environment-specific configurations:

```python
# config.py
import os
from pathlib import Path

ENV = os.getenv("MCP_MESH_ENV", "development")

# Load environment-specific config
config_path = Path(f"configs/{ENV}.yaml")
```

### 3. Logging Strategy

Implement comprehensive logging:

```python
import logging
import structlog

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()
```

### 4. Error Handling

Implement robust error handling:

```python
# Import mesh decorators and handle errors gracefully
from mesh import agent, tool

@tool(
    capability="robust_service",
    dependencies=["external_service"]
)
def robust_operation(data: str, external_service=None):
    try:
        if external_service:
            result = external_service(data)
            return result
        else:
            logger.warning("External service unavailable, using fallback")
            return {"result": "fallback_data", "source": "local"}
    except Exception as e:
        logger.error(f"Operation failed: {e}")
        raise
```

## Common Development Scenarios

### Scenario 1: Multi-Agent Development

Develop multiple interacting agents:

```bash
# Terminal 1: Registry
./bin/meshctl start-registry

# Terminal 2: Database Agent
./bin/meshctl start examples/simple/database_agent.py

# Terminal 3: Cache Agent
./bin/meshctl start examples/simple/cache_agent.py

# Terminal 4: API Agent
./bin/meshctl start examples/simple/api_agent.py
```

### Scenario 2: Testing Integration

Test agent interactions:

```python
# tests/integration/test_weather_integration.py
import pytest
import subprocess
import requests
import time

@pytest.fixture
def test_harness():
    # Start test registry
    registry_proc = subprocess.Popen([
        "./bin/meshctl", "start-registry", "--port", "18000"
    ])
    time.sleep(2)

    # Start test agents
    weather_proc = subprocess.Popen([
        "./bin/meshctl", "start", "examples/simple/weather_agent.py"
    ], env={"MCP_MESH_REGISTRY_URL": "http://localhost:18000"})

    time.sleep(3)
    yield

    # Cleanup
    weather_proc.terminate()
    registry_proc.terminate()

def test_weather_integration(test_harness):
    response = requests.get("http://localhost:18000/agents")
    agents = response.json()
    assert any(a["name"] == "weather-agent" for a in agents)
```

### Scenario 3: Performance Profiling

Profile your agents:

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Your agent code here

profiler.disable()
stats = pstats.Stats(profiler).sort_stats('cumulative')
stats.print_stats()
```

## Development Tools Integration

### VS Code Configuration

`.vscode/launch.json`:

```json
{
  "version": "0.6.2",
  "configurations": [
    {
      "name": "Debug Agent",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/bin/meshctl",
      "args": ["start", "examples/simple/weather_agent.py"],
      "env": {
        "MCP_MESH_LOG_LEVEL": "DEBUG",
        "PYTHONDONTWRITEBYTECODE": "1"
      }
    }
  ]
}
```

### PyCharm Configuration

1. Set up Python interpreter with virtual environment
2. Configure environment variables in Run Configuration
3. Enable pytest as test runner
4. Set up code style settings

## Troubleshooting Development Issues

### Registry Connection Issues

```bash
# Check if registry is running
curl http://localhost:8000/health

# Check what's using port 8000
lsof -i :8000

# Restart with verbose logging
MCP_MESH_LOG_LEVEL=DEBUG ./bin/meshctl start-registry
```

### Agent Registration Failures

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check registration details
logger.debug("registration_attempt",
    endpoint=agent.endpoint,
    capabilities=agent.capabilities
)
```

### Dependency Resolution Problems

```bash
# List all registered agents
curl http://localhost:8000/agents | jq

# Check registry health
curl http://localhost:8000/health | jq
```

## Ready to Dive Deeper?

Now that you understand the development landscape, let's set up your environment:

[Development Environment Setup](./02-local-development/01-environment-setup.md) →

---

💡 **Pro Tip**: Use `make` commands or shell scripts to standardize common development tasks across your team.

📚 **Note**: This section focuses on Python agent development. For Go component development (like the registry), see our [Go Development Guide](../contributing/go-development.md).

## 🔧 Troubleshooting

### Common Development Issues

1. **Hot reload not working** - Check file watcher permissions and patterns
2. **IDE not recognizing imports** - Configure Python interpreter to use virtual environment
3. **Database connection errors** - Verify PostgreSQL/SQLite is running and accessible
4. **Test failures in CI but not locally** - Check for environment-specific dependencies
5. **Debugging not hitting breakpoints** - Disable hot reload when debugging

For comprehensive solutions, see our [Development Troubleshooting Guide](./02-local-development/troubleshooting.md).

## ⚠️ Known Limitations

- **Hot reload**: Some changes (decorators, imports) require manual restart
- **Windows development**: File watching may be slower than Linux/macOS
- **SQLite concurrency**: Limited write concurrency for development
- **Mock limitations**: Some MCP features hard to mock locally
- **IDE support**: Limited autocomplete for injected dependencies

## 📝 TODO

- [ ] Create development container (devcontainer) configuration
- [ ] Add Makefile generator for new projects
- [ ] Implement local service mesh visualization
- [ ] Create development proxy for remote services
- [ ] Add performance regression detection
- [ ] Support for local Kubernetes development (kind/k3s)
- [ ] Create agent scaffolding CLI tool
- [ ] Add development metrics dashboard
