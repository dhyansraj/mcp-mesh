# Multi-File MCP Mesh Agent Development Guide

This guide provides comprehensive best practices for developing complex, production-ready MCP Mesh agents with proper Python packaging, modular architecture, and deployment strategies.

## Table of Contents

1. [Overview](#overview)
2. [Architecture Patterns](#architecture-patterns)
3. [Project Structure](#project-structure)
4. [Development Workflow](#development-workflow)
5. [Packaging & Distribution](#packaging--distribution)
6. [Testing Strategies](#testing-strategies)
7. [Deployment Options](#deployment-options)
8. [Best Practices](#best-practices)
9. [Common Patterns](#common-patterns)
10. [Troubleshooting](#troubleshooting)

## Overview

The Data Processor Agent example demonstrates how to build complex MCP Mesh agents that go beyond simple single-file implementations. This approach is essential for:

- **Production Applications**: Real-world agents requiring complex business logic
- **Team Development**: Multiple developers working on different components
- **Code Reusability**: Shared utilities and libraries across agents
- **Maintainability**: Clear separation of concerns and modular design
- **Testing**: Comprehensive test coverage with isolated components
- **Deployment**: Flexible deployment options (local, Docker, Kubernetes)

## Architecture Patterns

### 1. Modular Package Structure

```
my_complex_agent/
├── __init__.py              # Package initialization
├── __main__.py              # Entry point for python -m execution
├── main.py                  # Main agent with MCP tools
├── pyproject.toml           # Python packaging configuration
│
├── config/                  # Configuration management
│   ├── __init__.py
│   └── settings.py          # Environment-based settings
│
├── tools/                   # Domain-specific tools
│   ├── __init__.py
│   ├── data_processing.py   # Core business logic
│   ├── external_apis.py     # External service integrations
│   └── analytics.py         # Analysis and reporting
│
├── utils/                   # Shared utilities
│   ├── __init__.py
│   ├── validation.py        # Input validation
│   ├── formatting.py        # Output formatting
│   ├── caching.py          # Performance optimization
│   └── logging.py          # Structured logging
│
└── tests/                   # Test suite
    ├── __init__.py
    ├── test_tools/
    ├── test_utils/
    └── test_integration/
```

### 2. Dependency Injection Pattern

```python
# main.py - Clean separation of concerns
from .tools import DataProcessor, APIClient, Reporter
from .utils import CacheManager, Logger
from .config import get_settings

# Initialize components
settings = get_settings()
cache = CacheManager(settings.cache_config)
logger = Logger(settings.log_config)
processor = DataProcessor(cache, logger)
api_client = APIClient(settings.api_config, logger)
reporter = Reporter(settings.report_config)

@mesh.tool(capability="data_processing")
def process_data(data: str) -> Dict[str, Any]:
    return processor.process(data)
```

### 3. Configuration Management Pattern

```python
# config/settings.py - Environment-driven configuration
from dataclasses import dataclass
from typing import Dict, Any
import os

@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = "agent_db"
    
    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        return cls(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            name=os.getenv("DB_NAME", "agent_db")
        )

@dataclass 
class Settings:
    agent_name: str = "my-agent"
    http_port: int = 9090
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    
    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            agent_name=os.getenv("AGENT_NAME", "my-agent"),
            http_port=int(os.getenv("HTTP_PORT", "9090")),
            database=DatabaseConfig.from_env()
        )
```

## Project Structure

### Essential Files

#### 1. `pyproject.toml` - Python Packaging Configuration

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "my-mcp-agent"
version = "1.0.0"
description = "Production MCP Mesh Agent"
dependencies = [
    "mcp-mesh>=0.1.0,<0.2.0",
    "fastmcp>=0.9.0",
    # Add your specific dependencies
]

[project.optional-dependencies]
dev = ["pytest", "black", "mypy", "flake8"]
prod = ["gunicorn", "prometheus-client"]

[project.scripts]
my-agent = "my_agent.__main__:main"
```

#### 2. `__main__.py` - Module Entry Point

```python
#!/usr/bin/env python3
"""Entry point for python -m my_agent execution."""

import sys
from .main import MyAgent, settings

def main():
    try:
        print(f"🚀 Starting {settings.agent_name} v{settings.version}")
        agent = MyAgent()
        # Keep running until interrupted
        import signal
        signal.pause()
    except KeyboardInterrupt:
        print("🛑 Agent stopped")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

#### 3. Flexible Import Strategy

```python
# Handle both package and standalone execution
try:
    # Relative imports for package execution
    from .config import get_settings
    from .tools import DataProcessor
    from .utils import Logger
except ImportError:
    # Direct imports for standalone execution
    from config import get_settings
    from tools import DataProcessor
    from utils import Logger
```

## Development Workflow

### 1. Local Development Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in editable mode with development dependencies
pip install -e ".[dev]"

# Install pre-commit hooks (optional)
pre-commit install
```

### 2. Code Quality Tools

```bash
# Format code
black my_agent/
isort my_agent/

# Lint code
flake8 my_agent/
mypy my_agent/

# Run tests
pytest tests/ -v --cov=my_agent
```

### 3. Running the Agent

```bash
# Method 1: Python module (recommended)
python -m my_agent

# Method 2: Direct script execution
python my_agent/main.py

# Method 3: Command line script (after pip install)
my-agent

# Method 4: With custom configuration
AGENT_NAME=custom-agent HTTP_PORT=8080 python -m my_agent
```

## Packaging & Distribution

### 1. Building Distribution Packages

```bash
# Build wheel and source distribution
python -m build

# Install built package
pip install dist/my_mcp_agent-1.0.0-py3-none-any.whl

# Upload to PyPI (production)
twine upload dist/*
```

### 2. Version Management

```python
# __init__.py - Single source of truth for version
__version__ = "1.0.0"

# pyproject.toml - Reference the version
dynamic = ["version"]

# setup.py alternative (if needed)
from setuptools import setup
from my_agent import __version__

setup(version=__version__)
```

### 3. Dependency Management

```toml
# pyproject.toml - Flexible dependency specifications
dependencies = [
    # Core MCP Mesh
    "mcp-mesh>=0.1.0,<0.2.0",
    
    # Data processing
    "pandas>=1.5.0,<3.0.0",
    "numpy>=1.21.0,<2.0.0",
    
    # Optional performance improvements
    "numba>=0.57.0; extra=='performance'",
]

[project.optional-dependencies]
all = ["my-agent[dev,performance,ml]"]
```

## Testing Strategies

### 1. Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Pytest configuration and fixtures
├── unit/                    # Unit tests for individual components
│   ├── test_config.py
│   ├── test_tools/
│   └── test_utils/
├── integration/             # Integration tests
│   ├── test_agent_startup.py
│   └── test_mcp_tools.py
└── e2e/                     # End-to-end tests
    └── test_full_workflow.py
```

### 2. Test Configuration

```python
# conftest.py - Shared test fixtures
import pytest
from my_agent.config import Settings

@pytest.fixture
def test_settings():
    """Test configuration settings."""
    return Settings(
        agent_name="test-agent",
        http_port=9999,
        cache_enabled=False,
        database_url="sqlite:///:memory:"
    )

@pytest.fixture
def agent(test_settings):
    """Agent instance for testing."""
    from my_agent.main import MyAgent
    return MyAgent(settings=test_settings)
```

### 3. Testing MCP Tools

```python
# tests/integration/test_mcp_tools.py
import pytest
from my_agent.main import app

@pytest.mark.asyncio
async def test_data_processing_tool():
    """Test data processing MCP tool."""
    # Test the tool function directly
    result = await app.tools["process_data"].call({
        "data": "test,data,csv\n1,2,3\n4,5,6"
    })
    
    assert result["success"] is True
    assert "processed_data" in result
```

## Deployment Options

### 1. Docker Deployment

```dockerfile
# Multi-stage Dockerfile
FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY my_agent/ ./my_agent/
RUN pip install build && python -m build

FROM python:3.11-slim AS runtime
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install /tmp/*.whl && rm -rf /tmp/*.whl
USER 1000:1000
EXPOSE 9090
CMD ["my-agent"]
```

### 2. Kubernetes Deployment

```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-agent
spec:
  replicas: 2
  selector:
    matchLabels:
      app: my-agent
  template:
    metadata:
      labels:
        app: my-agent
    spec:
      containers:
      - name: agent
        image: my-agent:latest
        ports:
        - containerPort: 9090
        env:
        - name: AGENT_NAME
          value: "production-agent"
        - name: HTTP_PORT
          value: "9090"
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

### 3. Docker Compose Development

```yaml
# docker-compose.yml
version: '3.8'
services:
  my-agent:
    build: .
    ports:
      - "9090:9090"
    environment:
      AGENT_NAME: dev-agent
      LOG_LEVEL: DEBUG
    volumes:
      - ./data:/app/data:ro
      - ./logs:/app/logs
    depends_on:
      - redis
      - postgres
      
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
      
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: agent_db
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: secret
    ports:
      - "5432:5432"
```

## Best Practices

### 1. Code Organization

- **Single Responsibility**: Each module has one clear purpose
- **Dependency Injection**: Pass dependencies explicitly rather than importing globally
- **Interface Segregation**: Create small, focused interfaces
- **Configuration Externalization**: All configuration via environment variables

### 2. Error Handling

```python
# utils/error_handling.py
import logging
from typing import Dict, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)

def handle_tool_errors(func):
    """Decorator for consistent MCP tool error handling."""
    @wraps(func)
    async def wrapper(*args, **kwargs) -> Dict[str, Any]:
        try:
            result = await func(*args, **kwargs)
            return {"success": True, "data": result}
        except ValidationError as e:
            logger.warning(f"Validation error in {func.__name__}: {e}")
            return {"success": False, "error": str(e), "type": "validation"}
        except ExternalServiceError as e:
            logger.error(f"External service error in {func.__name__}: {e}")
            return {"success": False, "error": str(e), "type": "external"}
        except Exception as e:
            logger.exception(f"Unexpected error in {func.__name__}")
            return {"success": False, "error": "Internal error", "type": "internal"}
    return wrapper

@app.tool()
@mesh.tool(capability="data_processing")
@handle_tool_errors
async def process_data(data: str) -> Dict[str, Any]:
    # Tool implementation
    pass
```

### 3. Logging Strategy

```python
# utils/logging.py
import logging
import json
from typing import Dict, Any

class StructuredFormatter(logging.Formatter):
    """JSON structured logging formatter."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add extra fields
        if hasattr(record, "agent_name"):
            log_data["agent_name"] = record.agent_name
            
        return json.dumps(log_data)

def setup_logging(settings: Settings):
    """Configure structured logging."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format='%(message)s'
    )
    
    # Apply structured formatter
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
```

### 4. Performance Optimization

```python
# utils/performance.py
import asyncio
import time
from functools import wraps
from typing import Dict, Any, Optional

def cache_result(ttl_seconds: int = 300):
    """Cache decorator for expensive operations."""
    cache: Dict[str, tuple] = {}
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Create cache key
            key = f"{func.__name__}:{hash(str(args) + str(kwargs))}"
            
            # Check cache
            if key in cache:
                result, timestamp = cache[key]
                if time.time() - timestamp < ttl_seconds:
                    return result
            
            # Execute and cache
            result = await func(*args, **kwargs)
            cache[key] = (result, time.time())
            
            return result
        return wrapper
    return decorator

@cache_result(ttl_seconds=600)
async def expensive_computation(data: str) -> Dict[str, Any]:
    # Expensive operation
    await asyncio.sleep(1)  # Simulate work
    return {"processed": len(data)}
```

## Common Patterns

### 1. External API Integration

```python
# tools/external_apis.py
import httpx
from typing import Dict, Any, Optional
from ..config import get_settings
from ..utils import Logger

class ExternalAPIClient:
    """Template for external API integration."""
    
    def __init__(self, settings: Settings, logger: Logger):
        self.settings = settings
        self.logger = logger
        self.client = httpx.AsyncClient(
            timeout=settings.api_timeout,
            headers={"User-Agent": f"{settings.agent_name}/1.0"}
        )
    
    async def fetch_data(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Fetch data from external API with error handling."""
        try:
            response = await self.client.get(
                f"{self.settings.api_base_url}/{endpoint}",
                params=params or {}
            )
            response.raise_for_status()
            return response.json()
            
        except httpx.TimeoutException:
            self.logger.error(f"Timeout fetching {endpoint}")
            raise ExternalServiceError("API timeout")
            
        except httpx.HTTPStatusError as e:
            self.logger.error(f"HTTP error {e.response.status_code} for {endpoint}")
            raise ExternalServiceError(f"API error: {e.response.status_code}")
```

### 2. Database Integration

```python
# tools/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from typing import Dict, Any, List

class DatabaseManager:
    """Async database operations."""
    
    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url)
        self.session_factory = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
    
    async def execute_query(self, query: str, params: Dict[str, Any] = None) -> List[Dict]:
        """Execute raw SQL query safely."""
        async with self.session_factory() as session:
            result = await session.execute(text(query), params or {})
            return [dict(row) for row in result]
```

### 3. File Processing Pipeline

```python
# tools/file_processing.py
from pathlib import Path
from typing import Dict, Any, Iterator
import tempfile

class FileProcessor:
    """Secure file processing with validation."""
    
    def __init__(self, max_file_size: int = 100 * 1024 * 1024):  # 100MB
        self.max_file_size = max_file_size
    
    def validate_file(self, file_path: Path) -> None:
        """Validate file before processing."""
        if not file_path.exists():
            raise ValueError(f"File not found: {file_path}")
            
        if file_path.stat().st_size > self.max_file_size:
            raise ValueError(f"File too large: {file_path}")
            
        # Additional security checks
        if file_path.suffix.lower() not in ['.csv', '.json', '.txt']:
            raise ValueError(f"Unsupported file type: {file_path.suffix}")
    
    async def process_file_safely(self, file_content: bytes) -> Dict[str, Any]:
        """Process file in temporary location."""
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            temp_file.write(file_content)
            temp_file.flush()
            
            temp_path = Path(temp_file.name)
            self.validate_file(temp_path)
            
            return await self._process_file(temp_path)
```

## Troubleshooting

### Common Issues and Solutions

#### 1. Import Errors

```python
# Problem: ModuleNotFoundError when running as package
# Solution: Use proper relative imports and fallback

try:
    from .config import settings
except ImportError:
    from config import settings
```

#### 2. Configuration Issues

```python
# Problem: Environment variables not loading
# Solution: Explicit environment variable handling

import os
from typing import Optional

def get_env_bool(key: str, default: bool = False) -> bool:
    """Safely parse boolean environment variables."""
    value = os.getenv(key, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')

def get_env_int(key: str, default: int) -> int:
    """Safely parse integer environment variables."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default
```

#### 3. Docker Build Issues

```dockerfile
# Problem: Large Docker images
# Solution: Multi-stage builds and .dockerignore

# Use slim base images
FROM python:3.11-slim

# Install only production dependencies
RUN pip install --no-cache-dir my-agent

# Use non-root user
USER 1000:1000
```

#### 4. Performance Issues

```python
# Problem: Slow agent startup
# Solution: Lazy loading and connection pooling

class LazyResource:
    def __init__(self, factory_func):
        self._factory = factory_func
        self._instance = None
    
    def __call__(self):
        if self._instance is None:
            self._instance = self._factory()
        return self._instance

# Usage
database = LazyResource(lambda: DatabaseManager(settings.database_url))
```

### Debugging Techniques

#### 1. Structured Logging

```python
import logging
import json

# Add context to all log messages
logger = logging.LoggerAdapter(
    logging.getLogger(__name__),
    extra={"agent_name": settings.agent_name}
)

# Log with structured data
logger.info("Processing data", extra={
    "file_size": len(data),
    "processing_time": duration,
    "success": True
})
```

#### 2. Health Checks

```python
@app.tool()
@mesh.tool(capability="monitoring")
async def health_check() -> Dict[str, Any]:
    """Comprehensive health check."""
    checks = {}
    
    # Database connectivity
    try:
        await database.execute_query("SELECT 1")
        checks["database"] = {"status": "healthy"}
    except Exception as e:
        checks["database"] = {"status": "unhealthy", "error": str(e)}
    
    # External API connectivity
    try:
        await api_client.fetch_data("health")
        checks["external_api"] = {"status": "healthy"}
    except Exception as e:
        checks["external_api"] = {"status": "unhealthy", "error": str(e)}
    
    # Overall status
    overall_healthy = all(
        check["status"] == "healthy" 
        for check in checks.values()
    )
    
    return {
        "status": "healthy" if overall_healthy else "unhealthy",
        "checks": checks,
        "timestamp": time.time()
    }
```

## Conclusion

This development guide provides a comprehensive foundation for building production-ready, multi-file MCP Mesh agents. The patterns and practices demonstrated here enable:

- **Scalable Architecture**: Modular design that grows with complexity
- **Team Collaboration**: Clear code organization and separation of concerns
- **Reliable Deployment**: Multiple deployment options with proper packaging
- **Maintainable Code**: Comprehensive testing and quality assurance
- **Production Readiness**: Error handling, logging, and monitoring

Use this guide as a starting point and adapt the patterns to your specific use cases and requirements. The Data Processor Agent example provides a working implementation of all these concepts that you can use as a reference or starting template for your own agents.