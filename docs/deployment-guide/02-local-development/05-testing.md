# Testing Your Agents

> Write comprehensive tests for MCP Mesh agents including unit tests, integration tests, and dependency mocking

## Overview

Testing distributed systems requires special consideration for dependencies, network calls, and asynchronous operations. This guide covers testing strategies specific to MCP Mesh agents, including how to mock dependencies, test dependency injection, and verify distributed behavior.

We'll explore unit testing individual functions, integration testing with real dependencies, and end-to-end testing of your entire mesh.

## Key Concepts

- **Unit Testing**: Test agent functions in isolation
- **Dependency Mocking**: Mock injected dependencies for controlled testing
- **Integration Testing**: Test agents with real registry and dependencies
- **Contract Testing**: Verify agent interfaces remain stable
- **Performance Testing**: Ensure agents meet performance requirements

## Step-by-Step Guide

### Step 1: Set Up Testing Framework

Install testing dependencies:

```bash
# Core testing tools
pip install pytest pytest-asyncio pytest-cov pytest-mock

# Additional helpful tools
pip install pytest-timeout pytest-xdist httpx

# Development dependencies
pip install -e ".[test]"  # If your package has test extras
```

Create `pytest.ini` configuration:

```ini
[tool:pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --tb=short
    --strict-markers
    --cov=agents
    --cov-report=term-missing
    --cov-report=html
markers =
    unit: Unit tests (fast)
    integration: Integration tests (slower)
    e2e: End-to-end tests (slowest)
asyncio_mode = auto
```

### Step 2: Unit Test Agent Functions

Create test structure:

```python
# tests/test_weather_agent.py
import pytest
from unittest.mock import Mock, patch
from agents.weather_agent import get_weather, process_forecast

class TestWeatherAgent:
    """Unit tests for weather agent functions"""

    @pytest.fixture
    def mock_context(self):
        """Mock MCP context"""
        context = Mock()
        context.request_id = "test-123"
        return context

    def test_get_weather_success(self, mock_context):
        """Test successful weather retrieval"""
        result = get_weather(mock_context, city="London")

        assert result is not None
        assert "temperature" in result
        assert result["city"] == "London"

    def test_get_weather_invalid_city(self, mock_context):
        """Test handling of invalid city"""
        with pytest.raises(ValueError, match="Invalid city"):
            get_weather(mock_context, city="")

    @patch('agents.weather_agent.fetch_external_api')
    def test_get_weather_api_failure(self, mock_fetch, mock_context):
        """Test handling of API failures"""
        mock_fetch.side_effect = Exception("API Error")

        result = get_weather(mock_context, city="Paris")
        assert result["error"] == "Unable to fetch weather"
```

### Step 3: Test Dependency Injection

Mock injected dependencies:

```python
# tests/test_dependency_injection.py
import pytest
from unittest.mock import Mock, AsyncMock
from mcp import Context
from agents.analytics_agent import analyze_data

class TestDependencyInjection:
    """Test agents with dependency injection"""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies"""
        return {
            'DatabaseAgent_query': Mock(return_value={"count": 42}),
            'CacheAgent_get': Mock(return_value=None),
            'CacheAgent_set': Mock(return_value=True)
        }

    def test_analyze_with_all_dependencies(self, mock_dependencies):
        """Test when all dependencies are available"""
        ctx = Context()

        result = analyze_data(
            ctx,
            dataset="sales",
            **mock_dependencies
        )

        # Verify dependency calls
        mock_dependencies['DatabaseAgent_query'].assert_called_once_with("sales")
        mock_dependencies['CacheAgent_get'].assert_called_once()

        assert result["source"] == "database"
        assert result["count"] == 42

    def test_analyze_with_cache_hit(self, mock_dependencies):
        """Test when cache has data"""
        mock_dependencies['CacheAgent_get'].return_value = {"cached": True}
        ctx = Context()

        result = analyze_data(ctx, dataset="sales", **mock_dependencies)

        # Should not query database on cache hit
        mock_dependencies['DatabaseAgent_query'].assert_not_called()
        assert result["source"] == "cache"

    def test_analyze_graceful_degradation(self):
        """Test when dependencies are unavailable"""
        ctx = Context()

        # Call with no dependencies
        result = analyze_data(
            ctx,
            dataset="sales",
            DatabaseAgent_query=None,
            CacheAgent_get=None,
            CacheAgent_set=None
        )

        assert result["error"] == "No data sources available"
```

### Step 4: Integration Testing

Test with real registry and agents:

```python
# tests/test_integration.py
import pytest
import subprocess
import time
import requests
from pathlib import Path

class TestMeshIntegration:
    """Integration tests with real agents"""

    @pytest.fixture(scope="class")
    def mesh_environment(self):
        """Start mesh environment for testing"""
        procs = []

        # Start test agents
        for agent in ["system_agent.py", "weather_agent.py"]:
            proc = subprocess.Popen([
                "mcp-mesh-dev", "start", f"agents/{agent}",
                "--registry-url", "http://localhost:18080"
            ])
            procs.append(proc)

        # Wait for agents to register
        time.sleep(5)

        yield

        # Cleanup
        for proc in procs:
            proc.terminate()
            proc.wait()

    def test_agent_discovery(self, mesh_environment):
        """Test agents can discover each other"""
        response = requests.get("http://localhost:18080/api/v1/agents")
        agents = response.json()

        agent_names = [a["name"] for a in agents]
        assert "SystemAgent" in agent_names
        assert "WeatherAgent" in agent_names

    def test_dependency_resolution(self, mesh_environment):
        """Test weather agent can use system agent"""
        response = requests.get(
            "http://localhost:8889/weather_with_timestamp?city=London"
        )

        result = response.json()
        assert "weather" in result
        assert "timestamp" in result  # From SystemAgent
        assert result["timestamp"] is not None
```

### Step 5: Create Test Utilities

Build reusable test helpers:

```python
# tests/utils.py
import asyncio
import functools
from contextlib import contextmanager
from unittest.mock import Mock

class MockRegistry:
    """Mock registry for testing"""
    def __init__(self):
        self.agents = {}

    def register(self, agent_name, capabilities, dependencies):
        self.agents[agent_name] = {
            "capabilities": capabilities,
            "dependencies": dependencies,
            "status": "healthy"
        }

    def discover(self, capability):
        for name, info in self.agents.items():
            if capability in info["capabilities"]:
                return {"name": name, "url": f"http://mock/{name}"}
        return None

@contextmanager
def mock_mesh_environment():
    """Context manager for test environment"""
    registry = MockRegistry()

    # Mock environment variables
    import os
    old_env = os.environ.copy()
    os.environ['MCP_MESH_REGISTRY_URL'] = 'http://mock-registry'
    os.environ['MCP_MESH_LOG_LEVEL'] = 'ERROR'  # Quiet logs in tests

    try:
        yield registry
    finally:
        os.environ.clear()
        os.environ.update(old_env)

def async_test(timeout=5):
    """Decorator for async test with timeout"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            async def run():
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout
                )
            return asyncio.run(run())
        return wrapper
    return decorator
```

## Configuration Options

| Option                  | Description           | Default                | Example                   |
| ----------------------- | --------------------- | ---------------------- | ------------------------- |
| `PYTEST_TIMEOUT`        | Global test timeout   | 300                    | 60                        |
| `PYTEST_WORKERS`        | Parallel test workers | auto                   | 4                         |
| `MCP_TEST_REGISTRY_URL` | Test registry URL     | http://localhost:18080 | http://test-registry:8080 |
| `MCP_TEST_ISOLATION`    | Isolate test agents   | true                   | false                     |
| `COVERAGE_THRESHOLD`    | Minimum coverage %    | 80                     | 90                        |

## Examples

### Example 1: Testing Async Agents

```python
# tests/test_async_agent.py
import pytest
import asyncio
from agents.async_processor import process_batch

@pytest.mark.asyncio
async def test_batch_processing():
    """Test async batch processing"""
    items = ["item1", "item2", "item3"]

    # Mock async dependency
    async def mock_process_item(item):
        await asyncio.sleep(0.1)  # Simulate work
        return f"processed_{item}"

    results = await process_batch(
        items,
        ProcessorAgent_process=mock_process_item
    )

    assert len(results) == 3
    assert all(r.startswith("processed_") for r in results)

@pytest.mark.asyncio
async def test_batch_processing_timeout():
    """Test timeout handling"""
    items = ["slow_item"] * 10

    async def slow_processor(item):
        await asyncio.sleep(10)  # Too slow!

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            process_batch(items, ProcessorAgent_process=slow_processor),
            timeout=1.0
        )
```

### Example 2: Contract Testing

```python
# tests/test_contracts.py
import json
from jsonschema import validate

# Define agent contract
WEATHER_AGENT_CONTRACT = {
    "type": "object",
    "properties": {
        "temperature": {"type": "number"},
        "humidity": {"type": "number", "minimum": 0, "maximum": 100},
        "city": {"type": "string"},
        "timestamp": {"type": "string", "format": "date-time"}
    },
    "required": ["temperature", "city", "timestamp"]
}

def test_weather_agent_contract():
    """Verify weather agent output matches contract"""
    from agents.weather_agent import get_weather

    result = get_weather(Mock(), city="London")

    # Validate against contract
    validate(instance=result, schema=WEATHER_AGENT_CONTRACT)

def test_contract_backwards_compatibility():
    """Ensure new changes don't break existing consumers"""
    # Test with minimal required fields
    minimal_response = {
        "temperature": 20.5,
        "city": "Paris",
        "timestamp": "2024-01-01T12:00:00Z"
    }

    validate(instance=minimal_response, schema=WEATHER_AGENT_CONTRACT)
```

## Best Practices

1. **Test Pyramid**: Many unit tests, fewer integration tests, minimal E2E tests
2. **Mock External Services**: Never call real APIs in unit tests
3. **Test Edge Cases**: Empty inputs, null dependencies, timeouts
4. **Use Fixtures**: Share common test setup with pytest fixtures
5. **Parallel Testing**: Use pytest-xdist for faster test runs

## Common Pitfalls

### Pitfall 1: Testing with Real Dependencies

**Problem**: Tests fail when external services are down

**Solution**: Always mock external dependencies:

```python
# Bad: Depends on real service
def test_weather():
    result = get_weather("London")  # Calls real API!

# Good: Mocked service
@patch('requests.get')
def test_weather(mock_get):
    mock_get.return_value.json.return_value = {"temp": 20}
    result = get_weather("London")
```

### Pitfall 2: Shared State Between Tests

**Problem**: Tests pass individually but fail when run together

**Solution**: Ensure test isolation:

```python
@pytest.fixture(autouse=True)
def reset_state():
    """Reset any global state before each test"""
    from agents.cache import clear_cache
    clear_cache()
    yield
    clear_cache()  # Cleanup after test
```

## Testing

### Performance Test Example

```python
# tests/test_performance.py
import time
import pytest
from agents.processor import batch_process

@pytest.mark.benchmark
def test_processing_performance():
    """Ensure processing meets performance requirements"""
    large_dataset = list(range(10000))

    start = time.time()
    results = batch_process(large_dataset)
    duration = time.time() - start

    assert len(results) == 10000
    assert duration < 1.0  # Must process in under 1 second

    # Calculate throughput
    throughput = len(results) / duration
    assert throughput > 5000  # At least 5000 items/second
```

### Load Test Example

```python
# tests/test_load.py
import concurrent.futures
import requests

def test_agent_under_load():
    """Test agent handles concurrent requests"""
    url = "http://localhost:8888/process"
    num_requests = 100

    def make_request(i):
        response = requests.post(url, json={"id": i})
        return response.status_code == 200

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(make_request, range(num_requests)))

    success_rate = sum(results) / len(results)
    assert success_rate >= 0.95  # 95% success rate under load
```

## Monitoring and Debugging

### Test Metrics to Track

```bash
# Coverage report
pytest --cov=agents --cov-report=html
# Open htmlcov/index.html

# Test duration analysis
pytest --durations=10

# Failed test debugging
pytest -vvs --tb=long --pdb-trace
```

### Debugging Test Failures

- **Verbose Output**: Use `-vvs` for detailed output
- **Drop to Debugger**: Use `--pdb` to debug failures
- **Capture Logs**: Use `--log-cli-level=DEBUG` to see logs

## 🔧 Troubleshooting

### Issue 1: Import Errors in Tests

**Symptoms**: `ModuleNotFoundError` when running tests

**Cause**: Python path not configured correctly

**Solution**:

```bash
# Add to pytest.ini
[tool:pytest]
pythonpath = .

# Or set PYTHONPATH
export PYTHONPATH=$PYTHONPATH:.
```

### Issue 2: Async Test Hangs

**Symptoms**: Test never completes, hangs forever

**Cause**: Missing await or event loop issues

**Solution**:

```python
# Use pytest-asyncio properly
@pytest.mark.asyncio
async def test_async():
    result = await async_function()  # Don't forget await!

# Or use pytest-timeout
@pytest.mark.timeout(5)
async def test_with_timeout():
    await potentially_hanging_function()
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Registry Mocking**: Full registry behavior is complex to mock
- **Timing Issues**: Integration tests may have race conditions
- **Resource Cleanup**: Ensure all processes are terminated after tests

## 📝 TODO

- [ ] Add mutation testing support
- [ ] Create test data generators
- [ ] Add visual test result dashboard
- [ ] Support for behavior-driven testing (BDD)

## Summary

You now have comprehensive testing strategies for MCP Mesh agents:

Key takeaways:

- 🔑 Unit tests with mocked dependencies for fast feedback
- 🔑 Integration tests with real agents for confidence
- 🔑 Test utilities and fixtures for maintainable tests
- 🔑 Performance and load testing for production readiness

## Next Steps

You've completed the local development section! Consider exploring Docker deployment next.

Continue to [Docker Deployment](../03-docker-deployment.md) →

---

💡 **Tip**: Run tests in watch mode during development: `ptw -- -v` (requires pytest-watch)

📚 **Reference**: [Pytest Documentation](https://docs.pytest.org/)

🧪 **Try It**: Write a test that verifies your agent gracefully handles all dependencies being unavailable
