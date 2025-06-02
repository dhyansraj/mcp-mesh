# Registry API Patterns and Usage Guide

This document provides comprehensive guidance on using the MCP Mesh Registry Service, including API patterns, best practices, and integration examples.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [API Endpoints](#api-endpoints)
- [Usage Patterns](#usage-patterns)
- [Integration Examples](#integration-examples)
- [Best Practices](#best-practices)
- [Error Handling](#error-handling)
- [Performance Optimization](#performance-optimization)

## Overview

The MCP Mesh Registry Service implements a **Kubernetes API Server pattern** with a **pull-based architecture**. It serves as a centralized service discovery and registration system for MCP agents while maintaining no persistent connections to the agents themselves.

### Key Characteristics

- **Passive/Pull-Based**: Registry never initiates connections to agents
- **Kubernetes-style**: Similar to etcd + kube-apiserver for service discovery
- **Timer-Based Health**: Health monitoring through passive timestamp checking
- **RESTful API**: Standard HTTP endpoints with extensive filtering capabilities
- **MCP Protocol**: Native MCP endpoint for tool-based interactions

## Architecture

```
┌─────────────┐    ┌─────────────────────┐    ┌─────────────┐
│   Agent A   │    │   Registry Service  │    │   Agent B   │
│             │    │                     │    │             │
│ ┌─────────┐ │    │ ┌─────────────────┐ │    │ ┌─────────┐ │
│ │ Service │ │    │ │   REST API      │ │    │ │ Service │ │
│ │Discovery│◄┼────┼►│   /agents       │◄┼────┼►│Discovery│ │
│ │ Client  │ │    │ │   /capabilities │ │    │ │ Client  │ │
│ └─────────┘ │    │ │   /heartbeat    │ │    │ └─────────┘ │
│             │    │ └─────────────────┘ │    │             │
│ ┌─────────┐ │    │ ┌─────────────────┐ │    │ ┌─────────┐ │
│ │Heartbeat│ │    │ │   MCP Endpoint  │ │    │ │Heartbeat│ │
│ │ Client  │◄┼────┼►│   /mcp/tools    │◄┼────┼►│ Client  │ │
│ └─────────┘ │    │ └─────────────────┘ │    │ └─────────┘ │
└─────────────┘    └─────────────────────┘    └─────────────┘
                            │
                   ┌─────────────────┐
                   │ Health Monitor  │
                   │ (Timer-based)   │
                   └─────────────────┘
```

### Pull-Based Benefits

1. **Scalability**: Registry doesn't need to maintain connections to thousands of agents
2. **Resilience**: Agents can restart/reconnect without registry awareness
3. **Simplicity**: No complex connection management or state synchronization
4. **Kubernetes-style**: Familiar patterns for container orchestration users

## API Endpoints

### Core Endpoints

#### Agent Registration (MCP)

```http
POST /mcp/tools/register_agent
Content-Type: application/json

{
  "registration_data": {
    "id": "my-agent-001",
    "name": "My Service Agent",
    "namespace": "production",
    "agent_type": "service_agent",
    "endpoint": "http://localhost:8001/mcp",
    "capabilities": [
      {
        "name": "process_data",
        "description": "Process incoming data",
        "category": "data_processing",
        "version": "1.2.0",
        "stability": "stable",
        "tags": ["data", "processing", "async"]
      }
    ],
    "labels": {
      "env": "production",
      "team": "data",
      "zone": "us-west-2a"
    },
    "security_context": "standard",
    "health_interval": 30.0
  }
}
```

#### Heartbeat Updates

```http
POST /heartbeat
Content-Type: application/json

{
  "agent_id": "my-agent-001",
  "status": "healthy",
  "metadata": {
    "load": "0.65",
    "memory_usage": "78%"
  }
}
```

#### Service Discovery

```http
GET /agents?namespace=production&capability_category=data_processing&status=healthy
```

#### Capability Search

```http
GET /capabilities?tags=data&stability=stable&fuzzy_match=true
```

### Advanced Filtering

#### Label Selectors (Kubernetes-style)

```http
GET /agents?label_selector=env=production,team=data
GET /agents?label_selector=criticality=high
```

#### Version Constraints (Semantic Versioning)

```http
GET /agents?version_constraint=>1.0.0        # Greater than 1.0.0
GET /agents?version_constraint=~1.2.0        # Compatible with 1.2.x
GET /agents?version_constraint=^1.0.0        # Compatible with 1.x.x
```

#### Fuzzy Matching

```http
GET /capabilities?name=process&fuzzy_match=true
GET /agents?capability=data&fuzzy_match=true
```

#### Complex Queries

```http
GET /capabilities?category=data_processing&stability=stable&agent_status=healthy&include_deprecated=false
```

## Usage Patterns

### 1. Agent Registration Pattern

**Agent Startup Sequence:**

```python
async def register_with_registry():
    registration_data = {
        "id": f"{SERVICE_NAME}-{instance_id}",
        "name": SERVICE_NAME,
        "namespace": NAMESPACE,
        "agent_type": "service_agent",
        "endpoint": f"http://{HOST}:{PORT}/mcp",
        "capabilities": get_capabilities(),
        "labels": get_labels(),
        "security_context": SECURITY_CONTEXT,
        "health_interval": HEALTH_INTERVAL
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{REGISTRY_URL}/mcp/tools/register_agent",
            json={"registration_data": registration_data}
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                logger.info(f"Registered with registry: {result['agent_id']}")
                return True
            else:
                logger.error(f"Registration failed: {resp.status}")
                return False
```

### 2. Heartbeat Pattern

**Periodic Health Updates:**

```python
async def heartbeat_loop():
    while running:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{REGISTRY_URL}/heartbeat",
                    json={
                        "agent_id": AGENT_ID,
                        "status": "healthy",
                        "metadata": {
                            "load": get_system_load(),
                            "memory": get_memory_usage(),
                            "active_connections": get_connection_count()
                        }
                    }
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"Heartbeat failed: {resp.status}")
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")

        await asyncio.sleep(HEALTH_INTERVAL)
```

### 3. Service Discovery Pattern

**Finding Services by Capability:**

```python
async def find_data_processors():
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{REGISTRY_URL}/agents",
            params={
                "capability_category": "data_processing",
                "status": "healthy",
                "label_selector": "env=production"
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return [agent for agent in data["agents"]]
            return []

async def find_specific_capability():
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{REGISTRY_URL}/capabilities",
            params={
                "name": "transform_data",
                "stability": "stable",
                "agent_status": "healthy"
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["capabilities"]
            return []
```

### 4. Load Balancing Pattern

**Distribute Requests Across Healthy Agents:**

```python
import random

async def get_load_balanced_agent(capability_name: str):
    agents = await find_agents_with_capability(capability_name)

    if not agents:
        raise ServiceUnavailableError(f"No agents found with capability: {capability_name}")

    # Filter by health and load
    healthy_agents = [
        agent for agent in agents
        if agent["status"] == "healthy"
    ]

    if not healthy_agents:
        raise ServiceUnavailableError("No healthy agents available")

    # Simple random selection (can be enhanced with load-aware selection)
    return random.choice(healthy_agents)

async def find_agents_with_capability(capability_name: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{REGISTRY_URL}/capabilities",
            params={"name": capability_name, "agent_status": "healthy"}
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                # Group by agent_id to get unique agents
                agents_by_id = {}
                for cap in data["capabilities"]:
                    agent_id = cap["agent_id"]
                    if agent_id not in agents_by_id:
                        agents_by_id[agent_id] = {
                            "id": agent_id,
                            "name": cap["agent_name"],
                            "endpoint": cap["agent_endpoint"],
                            "capabilities": []
                        }
                    agents_by_id[agent_id]["capabilities"].append(cap)

                return list(agents_by_id.values())
            return []
```

### 5. Circuit Breaker Pattern

**Handle Registry Unavailability:**

```python
class RegistryClient:
    def __init__(self, registry_url: str):
        self.registry_url = registry_url
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30,
            expected_exception=aiohttp.ClientError
        )
        self.cache = {}
        self.cache_ttl = 60  # 60 seconds

    async def find_agents(self, **params):
        cache_key = json.dumps(params, sort_keys=True)

        # Check cache first
        if cache_key in self.cache:
            cached_result, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached_result

        # Try registry with circuit breaker
        try:
            async with self.circuit_breaker:
                result = await self._query_registry("/agents", params)
                self.cache[cache_key] = (result, time.time())
                return result
        except CircuitBreakerOpenError:
            # Fallback to cache even if stale
            if cache_key in self.cache:
                cached_result, _ = self.cache[cache_key]
                logger.warning("Registry unavailable, using stale cache")
                return cached_result
            raise ServiceUnavailableError("Registry unavailable and no cached data")

    async def _query_registry(self, endpoint: str, params: dict):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.registry_url}{endpoint}",
                params=params
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
```

## Integration Examples

### 1. FastMCP Agent Integration

```python
from fastmcp import FastMCP
import asyncio
import aiohttp

class MyAgent:
    def __init__(self):
        self.mcp = FastMCP("My Agent")
        self.agent_id = None
        self.registry_url = "http://localhost:8000"
        self.running = False

    async def start(self):
        # Register capabilities
        @self.mcp.tool()
        async def process_data(data: str) -> str:
            """Process incoming data."""
            return f"Processed: {data}"

        # Register with registry
        await self.register_with_registry()

        # Start heartbeat
        self.running = True
        asyncio.create_task(self.heartbeat_loop())

        # Start MCP server
        await self.mcp.run(transport="stdio")

    async def register_with_registry(self):
        registration_data = {
            "id": "my-agent-001",
            "name": "My Processing Agent",
            "namespace": "production",
            "agent_type": "processing_agent",
            "endpoint": "stdio://my-agent",  # For stdio transport
            "capabilities": [
                {
                    "name": "process_data",
                    "description": "Process incoming data",
                    "category": "data_processing",
                    "version": "1.0.0",
                    "stability": "stable",
                    "tags": ["data", "processing"]
                }
            ],
            "labels": {"env": "production", "team": "data"},
            "security_context": "standard",
            "health_interval": 30.0
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.registry_url}/mcp/tools/register_agent",
                json={"registration_data": registration_data}
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    self.agent_id = result["agent_id"]
                    print(f"Registered: {self.agent_id}")

    async def heartbeat_loop(self):
        while self.running:
            if self.agent_id:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{self.registry_url}/heartbeat",
                            json={"agent_id": self.agent_id}
                        ) as resp:
                            if resp.status != 200:
                                print(f"Heartbeat failed: {resp.status}")
                except Exception as e:
                    print(f"Heartbeat error: {e}")

            await asyncio.sleep(30)

if __name__ == "__main__":
    agent = MyAgent()
    asyncio.run(agent.start())
```

### 2. Client Service Discovery

```python
class ServiceClient:
    def __init__(self, registry_url: str):
        self.registry_url = registry_url
        self.agent_cache = {}

    async def call_service(self, capability: str, **kwargs):
        # Find agent with capability
        agent = await self.find_agent_with_capability(capability)

        if not agent:
            raise ServiceUnavailableError(f"No agent found with capability: {capability}")

        # Make MCP call to agent
        return await self.invoke_mcp_tool(agent["endpoint"], capability, **kwargs)

    async def find_agent_with_capability(self, capability: str):
        cache_key = f"capability:{capability}"

        # Check cache (with TTL)
        if cache_key in self.agent_cache:
            agent, timestamp = self.agent_cache[cache_key]
            if time.time() - timestamp < 30:  # 30 second cache
                return agent

        # Query registry
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.registry_url}/capabilities",
                params={
                    "name": capability,
                    "agent_status": "healthy",
                    "stability": "stable"
                }
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data["capabilities"]:
                        cap = data["capabilities"][0]
                        agent = {
                            "id": cap["agent_id"],
                            "endpoint": cap["agent_endpoint"]
                        }
                        self.agent_cache[cache_key] = (agent, time.time())
                        return agent

        return None

    async def invoke_mcp_tool(self, endpoint: str, tool_name: str, **kwargs):
        # Implementation depends on MCP client library
        # This is a simplified example
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{endpoint}/invoke",
                json={
                    "tool": tool_name,
                    "arguments": kwargs
                }
            ) as resp:
                return await resp.json()
```

## Best Practices

### 1. Agent Design

**Health Interval Guidelines:**

- **Critical services**: 10-15 seconds
- **Standard services**: 30 seconds
- **Background services**: 60 seconds
- **Development/testing**: 5 seconds

**Capability Design:**

```python
{
    "name": "clear_descriptive_name",  # Use clear, descriptive names
    "description": "Detailed description of what this capability does",
    "category": "logical_grouping",    # Group related capabilities
    "version": "1.2.3",               # Use semantic versioning
    "stability": "stable",            # Be honest about stability
    "tags": ["searchable", "keywords"], # Add searchable tags
    "input_schema": {                 # Always include schemas
        "type": "object",
        "properties": {...},
        "required": [...]
    }
}
```

**Labels Best Practices:**

```python
{
    "env": "production",           # Environment (prod/staging/dev)
    "team": "platform",           # Owning team
    "zone": "us-west-2a",         # Deployment zone
    "criticality": "high",        # Business criticality
    "version": "1.2.3",          # Application version
    "component": "api-server"     # Component type
}
```

### 2. Service Discovery

**Query Optimization:**

- Use specific queries rather than broad searches
- Combine filters to reduce result sets
- Cache discovery results with appropriate TTL
- Use fuzzy matching sparingly (performance cost)

**Example - Good Query:**

```python
# Specific, filtered query
params = {
    "capability_category": "data_processing",
    "status": "healthy",
    "label_selector": "env=production,team=data",
    "stability": "stable"
}
```

**Example - Poor Query:**

```python
# Overly broad query
params = {
    "fuzzy_match": True,
    "capability": "*"  # Don't do this
}
```

### 3. Error Handling

**Graceful Degradation:**

```python
async def resilient_service_call(capability: str, **kwargs):
    try:
        # Try primary approach
        return await call_service_via_registry(capability, **kwargs)
    except RegistryUnavailableError:
        # Fallback to cached agents
        return await call_service_via_cache(capability, **kwargs)
    except ServiceUnavailableError:
        # Fallback to default behavior
        return await fallback_implementation(**kwargs)
```

**Retry Logic:**

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
async def register_with_retry():
    return await register_with_registry()
```

### 4. Performance Optimization

**Connection Pooling:**

```python
# Reuse HTTP session for multiple requests
class RegistryClient:
    def __init__(self, registry_url: str):
        self.registry_url = registry_url
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
```

**Caching Strategy:**

```python
# Multi-level caching
class CachedRegistryClient:
    def __init__(self):
        self.memory_cache = {}      # Fast, short TTL
        self.persistent_cache = {}  # Slower, longer TTL

    async def find_agents(self, query):
        # L1: Memory cache (5 seconds)
        result = self.memory_cache.get(query)
        if result and time.time() - result[1] < 5:
            return result[0]

        # L2: Persistent cache (30 seconds)
        result = self.persistent_cache.get(query)
        if result and time.time() - result[1] < 30:
            self.memory_cache[query] = result
            return result[0]

        # L3: Registry
        data = await self.query_registry(query)
        timestamp = time.time()
        self.memory_cache[query] = (data, timestamp)
        self.persistent_cache[query] = (data, timestamp)
        return data
```

## Error Handling

### Common Error Scenarios

#### 1. Registry Unavailable

```python
class RegistryUnavailableError(Exception):
    pass

async def handle_registry_down():
    try:
        await register_with_registry()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Registry unavailable: {e}")
        # Use cached discovery data
        # Continue with reduced functionality
        # Alert monitoring system
```

#### 2. Agent Not Found

```python
# HTTP 404 from registry
{
    "detail": "Agent my-agent-001 not found"
}

# Handle in client
if response.status == 404:
    logger.warning(f"Agent {agent_id} not found in registry")
    # Remove from local cache
    # Try alternative agents
    # Graceful degradation
```

#### 3. Validation Errors

```python
# HTTP 400 from registry
{
    "status": "error",
    "error": "Validation failed: 'id' field is required"
}

# Handle in agent
if response.status == 400:
    result = await response.json()
    logger.error(f"Registration validation failed: {result['error']}")
    # Fix registration data
    # Retry with corrected data
```

### Error Recovery Strategies

#### Exponential Backoff

```python
async def register_with_backoff():
    max_retries = 5
    base_delay = 1

    for attempt in range(max_retries):
        try:
            return await register_with_registry()
        except Exception as e:
            if attempt == max_retries - 1:
                raise

            delay = base_delay * (2 ** attempt)
            logger.warning(f"Registration failed (attempt {attempt + 1}), retrying in {delay}s: {e}")
            await asyncio.sleep(delay)
```

#### Circuit Breaker Implementation

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    async def __aenter__(self):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitBreakerOpenError("Circuit breaker is OPEN")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            # Success
            self.failure_count = 0
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
        else:
            # Failure
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
```

## Performance Optimization

### Registry Configuration

**Database Optimization:**

```python
# Registry server configuration
registry_config = {
    "cache_ttl": 30,              # Response cache TTL
    "max_cache_size": 10000,      # Maximum cached entries
    "database_pool_size": 20,     # Database connection pool
    "query_timeout": 5.0,         # Query timeout seconds
    "health_check_interval": 60,  # Health check frequency
}
```

**Monitoring and Metrics:**

```python
# Monitor registry performance
async def check_registry_health():
    async with aiohttp.ClientSession() as session:
        # Check response time
        start_time = time.time()
        async with session.get(f"{registry_url}/health") as resp:
            response_time = time.time() - start_time

            if response_time > 1.0:
                logger.warning(f"Slow registry response: {response_time:.2f}s")

            # Check registry metrics
            async with session.get(f"{registry_url}/metrics") as metrics_resp:
                if metrics_resp.status == 200:
                    metrics = await metrics_resp.json()

                    if metrics["total_agents"] > 10000:
                        logger.info("Large registry detected, consider scaling")

                    if metrics["memory_usage_mb"] > 1000:
                        logger.warning("High registry memory usage")
```

### Client Optimization

**Batch Operations:**

```python
async def batch_discovery(queries: List[dict]):
    """Perform multiple discovery queries concurrently."""
    async with aiohttp.ClientSession() as session:
        tasks = []
        for query in queries:
            task = session.get(f"{registry_url}/agents", params=query)
            tasks.append(task)

        responses = await asyncio.gather(*tasks)
        results = []

        for response in responses:
            if response.status == 200:
                data = await response.json()
                results.append(data["agents"])
            else:
                results.append([])

        return results
```

**Connection Management:**

```python
# Configure client session for optimal performance
connector = aiohttp.TCPConnector(
    limit=100,              # Total connection pool size
    limit_per_host=30,      # Connections per host
    ttl_dns_cache=300,      # DNS cache TTL
    use_dns_cache=True,     # Enable DNS caching
    keepalive_timeout=30    # Keep-alive timeout
)

session = aiohttp.ClientSession(
    connector=connector,
    timeout=aiohttp.ClientTimeout(total=10),
    headers={"User-Agent": "mcp-mesh-client/1.0"}
)
```

This comprehensive guide provides the foundation for effectively using the MCP Mesh Registry Service in production environments while following best practices for scalability, reliability, and performance.
