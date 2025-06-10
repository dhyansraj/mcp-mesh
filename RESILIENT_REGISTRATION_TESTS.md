# Resilient Registration Tests

This document describes the unit and integration tests for the resilient registration feature.

## Feature Overview

The resilient registration feature ensures that:

1. Agents can start and work in standalone mode when the registry is unavailable
2. Health monitoring continues regardless of registration success
3. Agents automatically register when the registry becomes available
4. Failed registrations are retried during heartbeat cycles

## Unit Tests (`tests/unit/test_resilient_registration.py`)

### Test Cases

1. **`test_health_monitor_starts_when_registration_fails`**

   - Verifies health monitoring starts even if initial registration fails
   - Confirms agent returns `True` for standalone mode
   - Ensures agent is NOT marked as processed (allowing retry)

2. **`test_registration_retry_on_heartbeat`**

   - Tests that failed registrations are retried during heartbeat
   - Simulates registry coming online after initial failure
   - Verifies successful late registration

3. **`test_health_monitor_continues_after_registration`**

   - Confirms health monitoring continues after successful registration
   - Verifies periodic heartbeats are sent

4. **`test_multiple_agents_resilient_registration`**

   - Tests multiple agents can work in standalone mode
   - All health monitors start despite registration failures

5. **`test_dependency_injection_after_late_registration`**
   - Verifies dependency injection is set up after late registration
   - Tests the complete flow from failure to successful registration with dependencies

### Running Unit Tests

```bash
.venv/bin/pytest tests/unit/test_resilient_registration.py -v
```

## Integration Tests (`tests/integration/test_resilient_simple.py`)

### Test Cases

1. **`test_standalone_mode_basic`**

   - Tests agent works without registry
   - Verifies health monitor starts
   - Confirms function still executes

2. **`test_auto_connect_when_registry_starts`**

   - Starts agent without registry
   - Starts registry mid-test
   - Verifies automatic registration

3. **`test_health_monitor_continues_without_registry`**

   - Confirms heartbeat attempts continue when registry is down
   - Counts heartbeat attempts to verify continuous monitoring

4. **`test_multiple_agents_resilient`**
   - Tests multiple agents with dependencies
   - Verifies all work in standalone mode
   - Shows graceful degradation

### Running Integration Tests

```bash
.venv/bin/pytest tests/integration/test_resilient_simple.py -v
```

## Key Testing Patterns

### Mocking Registry Failures

```python
processor.mesh_agent_processor.registry_client.post = AsyncMock(
    return_value=MagicMock(
        status=500,
        json=AsyncMock(return_value={"error": "Connection failed"})
    )
)
```

### Simulating Registry Coming Online

```python
async def mock_post(*args, **kwargs):
    nonlocal call_count
    call_count += 1
    if call_count == 1:
        # First call fails
        return MagicMock(status=500, ...)
    else:
        # Subsequent calls succeed
        return MagicMock(status=201, ...)
```

### Testing Health Monitor Lifecycle

```python
# Wait for health monitor to start
assert len(processor.mesh_agent_processor._health_tasks) == 1

# Verify task is running
task = processor.mesh_agent_processor._health_tasks["agent_name"]
assert not task.done()

# Clean up properly
task.cancel()
try:
    await task
except asyncio.CancelledError:
    pass
```

## Test Coverage

The tests cover:

- ✅ Standalone operation without registry
- ✅ Health monitoring continuation
- ✅ Automatic registration on registry availability
- ✅ Registration retry logic
- ✅ Multiple agent coordination
- ✅ Dependency injection after late registration

## Common Issues and Solutions

1. **Timing Issues**: Use appropriate delays for heartbeat cycles
2. **Task Cleanup**: Always cancel and await health monitoring tasks
3. **Registry Process**: Ensure registry is properly terminated in tests
4. **Decorator Registry**: Clear between tests to avoid interference
