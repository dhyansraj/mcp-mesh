# @mesh_agent Decorator Specification

## Overview

The `@mesh_agent` decorator is the core innovation of MCP-Mesh, providing zero-boilerplate integration between standard MCP tools and the mesh infrastructure. It automatically handles registry registration, health monitoring, dependency injection, and configuration management.

## Decorator Signature

```python
def mesh_agent(
    capabilities: List[str],
    health_interval: int = 30,
    dependencies: Optional[List[str]] = None,
    registry_url: Optional[str] = None,
    agent_name: Optional[str] = None,
    security_context: Optional[str] = None,
    timeout: int = 30,
    retry_attempts: int = 3,
    enable_caching: bool = True,
    fallback_mode: bool = True
) -> Callable:
    """
    Decorator that integrates MCP tools with mesh infrastructure.

    Args:
        capabilities: List of capabilities this tool provides
        health_interval: Heartbeat interval in seconds (default: 30)
        dependencies: List of service dependencies to inject (default: None)
        registry_url: Registry service URL (default: from env/config)
        agent_name: Agent identifier (default: auto-generated)
        security_context: Security context for authorization (default: None)
        timeout: Network timeout in seconds (default: 30)
        retry_attempts: Number of retry attempts for registry calls (default: 3)
        enable_caching: Enable local caching of dependencies (default: True)
        fallback_mode: Enable graceful degradation mode (default: True)
    """
```

## Implementation Architecture

### Core Components

```python
# src/mcp_mesh_sdk/decorators/mesh_agent.py

import asyncio
import functools
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union
from datetime import datetime, timedelta

from ..shared.registry_client import RegistryClient
from ..shared.types import HealthStatus, DependencyConfig
from ..shared.exceptions import MeshAgentError, RegistryConnectionError

F = TypeVar('F', bound=Callable[..., Any])

class MeshAgentDecorator:
    """Core decorator implementation for mesh agent integration."""

    def __init__(
        self,
        capabilities: List[str],
        health_interval: int = 30,
        dependencies: Optional[List[str]] = None,
        registry_url: Optional[str] = None,
        agent_name: Optional[str] = None,
        security_context: Optional[str] = None,
        timeout: int = 30,
        retry_attempts: int = 3,
        enable_caching: bool = True,
        fallback_mode: bool = True
    ):
        self.capabilities = capabilities
        self.health_interval = health_interval
        self.dependencies = dependencies or []
        self.registry_url = registry_url
        self.agent_name = agent_name
        self.security_context = security_context
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.enable_caching = enable_caching
        self.fallback_mode = fallback_mode

        # Internal state
        self._registry_client: Optional[RegistryClient] = None
        self._health_task: Optional[asyncio.Task] = None
        self._dependency_cache: Dict[str, Any] = {}
        self._last_health_check: Optional[datetime] = None
        self._initialization_lock = asyncio.Lock()
        self._initialized = False

        self.logger = logging.getLogger(f"mesh_agent.{self.agent_name or 'unknown'}")

    def __call__(self, func: F) -> F:
        """Apply the decorator to a function."""

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Initialize mesh integration on first call
            if not self._initialized:
                await self._initialize()

            # Inject dependencies into kwargs
            injected_kwargs = await self._inject_dependencies(kwargs)

            # Execute the original function
            try:
                result = await func(*args, **injected_kwargs)
                await self._record_success()
                return result
            except Exception as e:
                await self._record_failure(e)
                raise

        # Store metadata on the wrapper function
        wrapper._mesh_agent_metadata = {
            "capabilities": self.capabilities,
            "dependencies": self.dependencies,
            "decorator_instance": self
        }

        return wrapper

    async def _initialize(self) -> None:
        """Initialize mesh integration components."""
        async with self._initialization_lock:
            if self._initialized:
                return

            try:
                # Initialize registry client
                self._registry_client = RegistryClient(
                    url=self.registry_url,
                    timeout=self.timeout,
                    retry_attempts=self.retry_attempts
                )

                # Register capabilities with registry
                await self._register_capabilities()

                # Start health monitoring task
                self._health_task = asyncio.create_task(self._health_monitor())

                self._initialized = True
                self.logger.info(f"Mesh agent initialized with capabilities: {self.capabilities}")

            except Exception as e:
                if self.fallback_mode:
                    self.logger.warning(f"Mesh initialization failed, running in fallback mode: {e}")
                    self._initialized = True  # Allow function to work without mesh
                else:
                    raise MeshAgentError(f"Failed to initialize mesh agent: {e}")

    async def _register_capabilities(self) -> None:
        """Register agent capabilities with the mesh registry."""
        if not self._registry_client:
            return

        try:
            await self._registry_client.register_agent(
                agent_name=self.agent_name,
                capabilities=self.capabilities,
                dependencies=self.dependencies,
                security_context=self.security_context
            )
        except RegistryConnectionError as e:
            if not self.fallback_mode:
                raise
            self.logger.warning(f"Failed to register capabilities: {e}")

    async def _inject_dependencies(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Inject dependency values into function kwargs."""
        if not self.dependencies or not self._registry_client:
            return kwargs

        injected_kwargs = kwargs.copy()

        for dependency in self.dependencies:
            # Check cache first
            if self.enable_caching and dependency in self._dependency_cache:
                cache_entry = self._dependency_cache[dependency]
                if not self._is_cache_expired(cache_entry):
                    injected_kwargs[dependency] = cache_entry["value"]
                    continue

            # Fetch from registry
            try:
                dependency_value = await self._registry_client.get_dependency(dependency)

                # Cache the result
                if self.enable_caching:
                    self._dependency_cache[dependency] = {
                        "value": dependency_value,
                        "timestamp": datetime.now(),
                        "ttl": timedelta(minutes=5)  # 5-minute cache TTL
                    }

                injected_kwargs[dependency] = dependency_value

            except Exception as e:
                if self.fallback_mode:
                    self.logger.warning(f"Failed to inject dependency {dependency}: {e}")
                    # Don't inject the dependency, let function handle missing parameter
                else:
                    raise MeshAgentError(f"Failed to inject dependency {dependency}: {e}")

        return injected_kwargs

    async def _health_monitor(self) -> None:
        """Background task for periodic health monitoring."""
        while True:
            try:
                await asyncio.sleep(self.health_interval)
                await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Health monitor error: {e}")

    async def _send_heartbeat(self) -> None:
        """Send heartbeat to registry with current health status."""
        if not self._registry_client:
            return

        try:
            health_status = HealthStatus(
                agent_name=self.agent_name,
                status="healthy",
                capabilities=self.capabilities,
                timestamp=datetime.now(),
                metadata={
                    "last_health_check": self._last_health_check,
                    "dependency_cache_size": len(self._dependency_cache)
                }
            )

            await self._registry_client.send_heartbeat(health_status)
            self._last_health_check = datetime.now()

        except Exception as e:
            self.logger.warning(f"Failed to send heartbeat: {e}")

    def _is_cache_expired(self, cache_entry: Dict[str, Any]) -> bool:
        """Check if a cache entry has expired."""
        return datetime.now() - cache_entry["timestamp"] > cache_entry["ttl"]

    async def _record_success(self) -> None:
        """Record successful function execution."""
        # Could send metrics to registry or monitoring system
        pass

    async def _record_failure(self, error: Exception) -> None:
        """Record failed function execution."""
        self.logger.error(f"Function execution failed: {error}")
        # Could send error metrics to registry or monitoring system

    async def cleanup(self) -> None:
        """Cleanup resources when decorator is no longer needed."""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        if self._registry_client:
            await self._registry_client.close()

# Public decorator function
def mesh_agent(
    capabilities: List[str],
    health_interval: int = 30,
    dependencies: Optional[List[str]] = None,
    registry_url: Optional[str] = None,
    agent_name: Optional[str] = None,
    security_context: Optional[str] = None,
    timeout: int = 30,
    retry_attempts: int = 3,
    enable_caching: bool = True,
    fallback_mode: bool = True
) -> Callable[[F], F]:
    """
    Decorator that integrates MCP tools with mesh infrastructure.

    This decorator automatically handles:
    - Registry registration of capabilities
    - Periodic health monitoring
    - Dependency injection
    - Error handling and fallback modes
    - Caching of dependency values
    """
    decorator = MeshAgentDecorator(
        capabilities=capabilities,
        health_interval=health_interval,
        dependencies=dependencies,
        registry_url=registry_url,
        agent_name=agent_name,
        security_context=security_context,
        timeout=timeout,
        retry_attempts=retry_attempts,
        enable_caching=enable_caching,
        fallback_mode=fallback_mode
    )
    return decorator
```

## Registry Client Implementation

```python
# src/mcp_mesh_sdk/shared/registry_client.py

import aiohttp
import asyncio
import json
from typing import Any, Dict, List, Optional
from datetime import datetime

from .types import HealthStatus
from .exceptions import RegistryConnectionError, RegistryTimeoutError

class RegistryClient:
    """Client for communicating with the mesh registry service."""

    def __init__(
        self,
        url: Optional[str] = None,
        timeout: int = 30,
        retry_attempts: int = 3
    ):
        self.url = url or self._get_registry_url_from_env()
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if not self._session:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def register_agent(
        self,
        agent_name: str,
        capabilities: List[str],
        dependencies: List[str],
        security_context: Optional[str] = None
    ) -> bool:
        """Register agent with the registry."""
        payload = {
            "agent_name": agent_name,
            "capabilities": capabilities,
            "dependencies": dependencies,
            "security_context": security_context,
            "timestamp": datetime.now().isoformat()
        }

        return await self._make_request("POST", "/agents/register", payload)

    async def send_heartbeat(self, health_status: HealthStatus) -> bool:
        """Send periodic heartbeat to registry."""
        payload = health_status.dict()
        return await self._make_request("POST", "/agents/heartbeat", payload)

    async def get_dependency(self, dependency_name: str) -> Any:
        """Retrieve dependency configuration from registry."""
        response = await self._make_request("GET", f"/dependencies/{dependency_name}")
        return response.get("value") if response else None

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Make HTTP request to registry with retry logic."""
        session = await self._get_session()
        url = f"{self.url}{endpoint}"

        for attempt in range(self.retry_attempts):
            try:
                if method == "GET":
                    async with session.get(url) as response:
                        if response.status == 200:
                            return await response.json()
                        else:
                            raise RegistryConnectionError(f"Registry returned {response.status}")

                elif method == "POST":
                    async with session.post(url, json=payload) as response:
                        if response.status in [200, 201]:
                            return await response.json() if response.content_length else {}
                        else:
                            raise RegistryConnectionError(f"Registry returned {response.status}")

            except asyncio.TimeoutError:
                if attempt == self.retry_attempts - 1:
                    raise RegistryTimeoutError(f"Registry request timed out after {self.retry_attempts} attempts")
            except Exception as e:
                if attempt == self.retry_attempts - 1:
                    raise RegistryConnectionError(f"Failed to connect to registry: {e}")

            # Exponential backoff
            await asyncio.sleep(2 ** attempt)

        return None

    def _get_registry_url_from_env(self) -> str:
        """Get registry URL from environment variables."""
        import os
        return os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8080")

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
```

## Integration with File Agent

```python
# Example usage in File Agent
from mcp_mesh_sdk.decorators import mesh_agent
from mcp.server.fastmcp import FastMCP

class FileAgent:
    def __init__(self):
        self.app = FastMCP(name="file-agent")
        self._setup_tools()

    def _setup_tools(self):

        @mesh_agent(
            capabilities=["file_read"],
            dependencies=["auth_service", "audit_logger"],
            health_interval=30,
            security_context="file_operations"
        )
        @self.app.tool()
        async def read_file(
            path: str,
            encoding: str = "utf-8",
            auth_service: str = None,  # Injected by decorator
            audit_logger: Any = None   # Injected by decorator
        ) -> str:
            """Read file contents with security validation."""
            # Decorator automatically:
            # 1. Registers "file_read" capability with registry
            # 2. Injects auth_service and audit_logger from dependencies
            # 3. Sends periodic heartbeats
            # 4. Handles registry connection failures gracefully

            # Validate authentication
            if auth_service and not await self._validate_auth(auth_service):
                raise PermissionError("Authentication failed")

            # Log the operation
            if audit_logger:
                await audit_logger.log_operation("file_read", {"path": path})

            # Perform the file operation
            return await self._read_file_safely(path, encoding)
```

## Configuration and Environment

```python
# Environment variables for mesh configuration
MCP_MESH_REGISTRY_URL=http://localhost:8080
MCP_MESH_AGENT_NAME=file-agent-01
MCP_MESH_HEALTH_INTERVAL=30
MCP_MESH_FALLBACK_MODE=true
MCP_MESH_ENABLE_CACHING=true
```

## Benefits and Features

### Zero Boilerplate

- Single decorator replaces dozens of lines of mesh integration code
- Works with existing `@app.tool()` decorators seamlessly
- No changes required to function signatures (except for dependency injection)

### Automatic Capabilities

- **Registry Registration**: Capabilities automatically registered on first function call
- **Health Monitoring**: Background heartbeat task with configurable intervals
- **Dependency Injection**: Services injected as keyword arguments
- **Error Handling**: Graceful degradation when registry unavailable

### Production Ready

- **Caching**: Local caching of dependency values with TTL
- **Retry Logic**: Exponential backoff for registry communication
- **Fallback Mode**: Functions work independently when mesh unavailable
- **Monitoring**: Built-in success/failure tracking and logging

This decorator implementation provides the foundation for seamless mesh integration while maintaining the simplicity and power that makes MCP-Mesh unique.
