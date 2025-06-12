# Mesh Integration and Health Monitoring Design

## Overview

This document defines the comprehensive mesh integration and health monitoring system for the File Agent, ensuring robust service discovery, dependency management, and operational observability within the MCP Mesh ecosystem.

## Mesh Integration Architecture

### Registry Service Integration

```python
# src/mcp_mesh_sdk/shared/registry_client.py

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from urllib.parse import urljoin
import aiohttp
from dataclasses import dataclass, asdict

from .types import HealthStatus, MeshCapability, DependencyConfig
from .exceptions import RegistryConnectionError, RegistryTimeoutError, ErrorCode

@dataclass
class AgentRegistration:
    """Agent registration information."""
    agent_id: str
    agent_name: str
    capabilities: List[MeshCapability]
    dependencies: List[str]
    endpoint: str
    security_context: Optional[str] = None
    metadata: Dict[str, Any] = None
    registered_at: datetime = None
    last_heartbeat: datetime = None
    status: str = "initializing"

@dataclass
class ServiceDiscoveryEntry:
    """Service discovery entry."""
    service_id: str
    service_name: str
    endpoint: str
    capabilities: List[str]
    health_status: str
    last_seen: datetime
    metadata: Dict[str, Any] = None

class MeshRegistryClient:
    """Enhanced registry client with full mesh integration capabilities."""

    def __init__(
        self,
        registry_url: str,
        agent_name: str,
        timeout: int = 30,
        retry_attempts: int = 3,
        heartbeat_interval: int = 30,
        enable_service_discovery: bool = True
    ):
        self.registry_url = registry_url
        self.agent_name = agent_name
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.heartbeat_interval = heartbeat_interval
        self.enable_service_discovery = enable_service_discovery

        # Internal state
        self._session: Optional[aiohttp.ClientSession] = None
        self._agent_id: Optional[str] = None
        self._registration: Optional[AgentRegistration] = None
        self._service_cache: Dict[str, ServiceDiscoveryEntry] = {}
        self._dependency_cache: Dict[str, Any] = {}
        self._cache_ttl = timedelta(minutes=5)
        self._last_cache_update = datetime.min

        # Event callbacks
        self._on_registration_success: Optional[Callable] = None
        self._on_heartbeat_success: Optional[Callable] = None
        self._on_connection_error: Optional[Callable] = None

        self.logger = logging.getLogger(f"mesh.registry.{agent_name}")

    async def initialize(self) -> None:
        """Initialize registry client and establish connection."""
        try:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                connector=aiohttp.TCPConnector(limit=10)
            )

            # Test connection
            await self._test_connection()
            self.logger.info(f"Registry client initialized for {self.agent_name}")

        except Exception as e:
            self.logger.error(f"Failed to initialize registry client: {e}")
            raise RegistryConnectionError(self.registry_url, cause=e)

    async def register_agent(
        self,
        capabilities: List[MeshCapability],
        dependencies: List[str],
        endpoint: str,
        security_context: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AgentRegistration:
        """
        Register agent with the mesh registry.

        Args:
            capabilities: List of capabilities this agent provides
            dependencies: List of service dependencies
            endpoint: Agent's network endpoint
            security_context: Security context identifier
            metadata: Additional metadata

        Returns:
            AgentRegistration object with assigned agent ID
        """
        registration_data = {
            "agent_name": self.agent_name,
            "capabilities": [asdict(cap) for cap in capabilities],
            "dependencies": dependencies,
            "endpoint": endpoint,
            "security_context": security_context,
            "metadata": metadata or {},
            "registered_at": datetime.now().isoformat()
        }

        try:
            response = await self._make_request(
                "POST",
                "/agents/register",
                data=registration_data
            )

            self._agent_id = response["agent_id"]
            self._registration = AgentRegistration(
                agent_id=self._agent_id,
                agent_name=self.agent_name,
                capabilities=capabilities,
                dependencies=dependencies,
                endpoint=endpoint,
                security_context=security_context,
                metadata=metadata,
                registered_at=datetime.fromisoformat(response["registered_at"]),
                status="registered"
            )

            self.logger.info(f"Agent registered with ID: {self._agent_id}")

            if self._on_registration_success:
                await self._on_registration_success(self._registration)

            return self._registration

        except Exception as e:
            self.logger.error(f"Failed to register agent: {e}")
            raise RegistryConnectionError(
                self.registry_url,
                details={"operation": "register_agent", "agent_name": self.agent_name}
            )

    async def send_heartbeat(self, health_status: HealthStatus) -> bool:
        """
        Send periodic heartbeat with health status.

        Args:
            health_status: Current health status of the agent

        Returns:
            True if heartbeat was successful
        """
        if not self._agent_id:
            self.logger.warning("Cannot send heartbeat: agent not registered")
            return False

        heartbeat_data = {
            "agent_id": self._agent_id,
            "health_status": health_status.dict(),
            "timestamp": datetime.now().isoformat()
        }

        try:
            response = await self._make_request(
                "POST",
                f"/agents/{self._agent_id}/heartbeat",
                data=heartbeat_data
            )

            # Process any configuration updates from registry
            if "config_updates" in response:
                await self._process_config_updates(response["config_updates"])

            # Update service discovery cache if provided
            if "service_directory" in response:
                await self._update_service_cache(response["service_directory"])

            if self._on_heartbeat_success:
                await self._on_heartbeat_success(response)

            return True

        except Exception as e:
            self.logger.warning(f"Heartbeat failed: {e}")

            if self._on_connection_error:
                await self._on_connection_error(e)

            return False

    async def discover_service(self, service_name: str) -> Optional[ServiceDiscoveryEntry]:
        """
        Discover a service by name.

        Args:
            service_name: Name of the service to discover

        Returns:
            ServiceDiscoveryEntry if found, None otherwise
        """
        # Check cache first
        if service_name in self._service_cache:
            entry = self._service_cache[service_name]
            if datetime.now() - entry.last_seen < self._cache_ttl:
                return entry

        # Query registry
        try:
            response = await self._make_request(
                "GET",
                f"/services/discover/{service_name}"
            )

            if response and "service" in response:
                service_data = response["service"]
                entry = ServiceDiscoveryEntry(
                    service_id=service_data["service_id"],
                    service_name=service_data["service_name"],
                    endpoint=service_data["endpoint"],
                    capabilities=service_data["capabilities"],
                    health_status=service_data["health_status"],
                    last_seen=datetime.fromisoformat(service_data["last_seen"]),
                    metadata=service_data.get("metadata", {})
                )

                # Cache the result
                self._service_cache[service_name] = entry
                return entry

        except Exception as e:
            self.logger.warning(f"Service discovery failed for {service_name}: {e}")

        return None

    async def get_dependency(self, dependency_name: str) -> Optional[Any]:
        """
        Retrieve dependency configuration or service endpoint.

        Args:
            dependency_name: Name of the dependency

        Returns:
            Dependency value or None if not found
        """
        # Check cache first
        cache_key = dependency_name
        if cache_key in self._dependency_cache:
            cached_entry = self._dependency_cache[cache_key]
            if datetime.now() - cached_entry["timestamp"] < self._cache_ttl:
                return cached_entry["value"]

        # Query registry
        try:
            response = await self._make_request(
                "GET",
                f"/dependencies/{dependency_name}",
                params={"agent_id": self._agent_id}
            )

            if response and "dependency" in response:
                dependency_data = response["dependency"]
                value = dependency_data["value"]

                # Cache the result
                self._dependency_cache[cache_key] = {
                    "value": value,
                    "timestamp": datetime.now(),
                    "metadata": dependency_data.get("metadata", {})
                }

                return value

        except Exception as e:
            self.logger.warning(f"Failed to get dependency {dependency_name}: {e}")

        return None

    async def update_capability_status(
        self,
        capability_name: str,
        status: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update the status of a specific capability.

        Args:
            capability_name: Name of the capability
            status: New status (active, degraded, inactive)
            metadata: Additional status metadata

        Returns:
            True if update was successful
        """
        if not self._agent_id:
            return False

        update_data = {
            "capability_name": capability_name,
            "status": status,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat()
        }

        try:
            await self._make_request(
                "PUT",
                f"/agents/{self._agent_id}/capabilities/{capability_name}",
                data=update_data
            )
            return True

        except Exception as e:
            self.logger.warning(f"Failed to update capability status: {e}")
            return False

    async def _test_connection(self) -> None:
        """Test connection to registry."""
        try:
            await self._make_request("GET", "/health")
        except Exception as e:
            raise RegistryConnectionError(
                self.registry_url,
                details={"operation": "connection_test"}
            )

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Make HTTP request to registry with retry logic."""
        if not self._session:
            await self.initialize()

        url = urljoin(self.registry_url, endpoint)

        for attempt in range(self.retry_attempts):
            try:
                kwargs = {"params": params} if params else {}

                if method.upper() == "GET":
                    async with self._session.get(url, **kwargs) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 404:
                            return None
                        else:
                            response.raise_for_status()

                else:  # POST, PUT, etc.
                    kwargs["json"] = data
                    async with self._session.request(method, url, **kwargs) as response:
                        if response.status in [200, 201]:
                            return await response.json() if response.content_length else {}
                        else:
                            response.raise_for_status()

            except asyncio.TimeoutError:
                if attempt == self.retry_attempts - 1:
                    raise RegistryTimeoutError(endpoint, self.timeout)
                await asyncio.sleep(2 ** attempt)

            except Exception as e:
                if attempt == self.retry_attempts - 1:
                    raise RegistryConnectionError(
                        self.registry_url,
                        details={"endpoint": endpoint, "method": method}
                    )
                await asyncio.sleep(2 ** attempt)

        return None

    async def _process_config_updates(self, updates: Dict[str, Any]) -> None:
        """Process configuration updates from registry."""
        self.logger.info(f"Processing config updates: {list(updates.keys())}")

        # Handle capability updates
        if "capabilities" in updates:
            capability_updates = updates["capabilities"]
            for capability_name, config in capability_updates.items():
                self.logger.info(f"Updated capability {capability_name}: {config}")

        # Handle dependency updates
        if "dependencies" in updates:
            dependency_updates = updates["dependencies"]
            for dep_name, config in dependency_updates.items():
                # Invalidate cache for updated dependencies
                if dep_name in self._dependency_cache:
                    del self._dependency_cache[dep_name]
                self.logger.info(f"Updated dependency {dep_name}: {config}")

    async def _update_service_cache(self, service_directory: List[Dict]) -> None:
        """Update local service discovery cache."""
        for service_data in service_directory:
            entry = ServiceDiscoveryEntry(
                service_id=service_data["service_id"],
                service_name=service_data["service_name"],
                endpoint=service_data["endpoint"],
                capabilities=service_data["capabilities"],
                health_status=service_data["health_status"],
                last_seen=datetime.fromisoformat(service_data["last_seen"]),
                metadata=service_data.get("metadata", {})
            )
            self._service_cache[entry.service_name] = entry

        self._last_cache_update = datetime.now()

    def set_event_callbacks(
        self,
        on_registration_success: Optional[Callable] = None,
        on_heartbeat_success: Optional[Callable] = None,
        on_connection_error: Optional[Callable] = None
    ) -> None:
        """Set event callback functions."""
        self._on_registration_success = on_registration_success
        self._on_heartbeat_success = on_heartbeat_success
        self._on_connection_error = on_connection_error

    async def cleanup(self) -> None:
        """Cleanup resources and deregister agent."""
        try:
            if self._agent_id:
                await self._make_request(
                    "DELETE",
                    f"/agents/{self._agent_id}"
                )
                self.logger.info(f"Agent {self._agent_id} deregistered")
        except Exception as e:
            self.logger.warning(f"Failed to deregister agent: {e}")

        if self._session:
            await self._session.close()
```

## Health Monitoring System

### Comprehensive Health Checks

```python
# src/mcp_mesh_sdk/shared/health_monitor.py

import asyncio
import psutil
import platform
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path
import logging

from .types import HealthStatus, FileAgentConfig
from .exceptions import HealthCheckError, ErrorCode

class HealthMetrics:
    """Container for health monitoring metrics."""

    def __init__(self):
        self.checks_performed = 0
        self.checks_passed = 0
        self.checks_failed = 0
        self.last_check_duration = 0.0
        self.avg_check_duration = 0.0
        self.error_count = 0
        self.warning_count = 0
        self.last_error: Optional[str] = None
        self.start_time = datetime.now()
        self.uptime = timedelta()

class FileAgentHealthMonitor:
    """Comprehensive health monitoring for File Agent."""

    def __init__(
        self,
        config: FileAgentConfig,
        registry_client: Optional[Any] = None
    ):
        self.config = config
        self.registry_client = registry_client
        self.metrics = HealthMetrics()

        # Health check components
        self._health_checks: Dict[str, Callable] = {}
        self._check_intervals: Dict[str, int] = {}
        self._last_check_times: Dict[str, datetime] = {}
        self._check_results: Dict[str, bool] = {}

        # Monitoring state
        self._monitoring_task: Optional[asyncio.Task] = None
        self._is_monitoring = False

        self.logger = logging.getLogger("file_agent.health")

        # Register default health checks
        self._register_default_checks()

    def _register_default_checks(self) -> None:
        """Register default health checks."""

        # Core system checks
        self.register_health_check("file_system_access", self._check_file_system_access, 60)
        self.register_health_check("disk_space", self._check_disk_space, 120)
        self.register_health_check("memory_usage", self._check_memory_usage, 60)
        self.register_health_check("cpu_usage", self._check_cpu_usage, 60)

        # File Agent specific checks
        self.register_health_check("base_directory", self._check_base_directory, 300)
        self.register_health_check("permissions", self._check_file_permissions, 300)
        self.register_health_check("backup_directory", self._check_backup_directory, 300)

        # Mesh integration checks
        if self.registry_client:
            self.register_health_check("registry_connection", self._check_registry_connection, 30)
            self.register_health_check("service_discovery", self._check_service_discovery, 120)

    def register_health_check(
        self,
        name: str,
        check_function: Callable,
        interval_seconds: int = 60
    ) -> None:
        """
        Register a custom health check.

        Args:
            name: Unique name for the health check
            check_function: Async function that returns bool or raises exception
            interval_seconds: How often to run this check
        """
        self._health_checks[name] = check_function
        self._check_intervals[name] = interval_seconds
        self._last_check_times[name] = datetime.min
        self._check_results[name] = True  # Assume healthy until proven otherwise

        self.logger.debug(f"Registered health check: {name} (interval: {interval_seconds}s)")

    async def start_monitoring(self) -> None:
        """Start continuous health monitoring."""
        if self._is_monitoring:
            self.logger.warning("Health monitoring already started")
            return

        self._is_monitoring = True
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())
        self.logger.info("Health monitoring started")

    async def stop_monitoring(self) -> None:
        """Stop health monitoring."""
        self._is_monitoring = False

        if self._monitoring_task and not self._monitoring_task.done():
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        self.logger.info("Health monitoring stopped")

    async def perform_health_check(self, check_name: Optional[str] = None) -> HealthStatus:
        """
        Perform health check(s) and return status.

        Args:
            check_name: Specific check to run, or None for all checks

        Returns:
            HealthStatus with results
        """
        start_time = datetime.now()

        try:
            if check_name:
                if check_name not in self._health_checks:
                    raise HealthCheckError(
                        f"Unknown health check: {check_name}",
                        ErrorCode.HEALTH_CHECK_FAILED
                    )
                checks_to_run = {check_name: self._health_checks[check_name]}
            else:
                checks_to_run = self._health_checks

            # Run health checks
            check_results = {}
            for name, check_func in checks_to_run.items():
                try:
                    result = await check_func()
                    check_results[name] = bool(result)
                    self._check_results[name] = check_results[name]

                    if check_results[name]:
                        self.metrics.checks_passed += 1
                    else:
                        self.metrics.checks_failed += 1
                        self.logger.warning(f"Health check failed: {name}")

                except Exception as e:
                    check_results[name] = False
                    self._check_results[name] = False
                    self.metrics.checks_failed += 1
                    self.metrics.error_count += 1
                    self.metrics.last_error = f"{name}: {str(e)}"
                    self.logger.error(f"Health check error in {name}: {e}")

                self.metrics.checks_performed += 1
                self._last_check_times[name] = datetime.now()

            # Calculate overall status
            all_passed = all(check_results.values())
            some_failed = any(not result for result in check_results.values())

            if all_passed:
                status = "healthy"
            elif some_failed:
                status = "degraded"
            else:
                status = "unhealthy"

            # Update metrics
            duration = (datetime.now() - start_time).total_seconds()
            self.metrics.last_check_duration = duration
            self.metrics.avg_check_duration = (
                (self.metrics.avg_check_duration * (self.metrics.checks_performed - len(check_results)) +
                 duration * len(check_results)) / self.metrics.checks_performed
            )
            self.metrics.uptime = datetime.now() - self.metrics.start_time

            return HealthStatus(
                status=status,
                agent_name=self.config.agent_name,
                capabilities=[],  # Will be filled by caller
                timestamp=datetime.now(),
                checks=check_results,
                metadata={
                    "metrics": {
                        "checks_performed": self.metrics.checks_performed,
                        "checks_passed": self.metrics.checks_passed,
                        "checks_failed": self.metrics.checks_failed,
                        "last_check_duration": self.metrics.last_check_duration,
                        "avg_check_duration": self.metrics.avg_check_duration,
                        "error_count": self.metrics.error_count,
                        "warning_count": self.metrics.warning_count,
                        "uptime_seconds": self.metrics.uptime.total_seconds()
                    },
                    "system": await self._get_system_metrics(),
                    "config": {
                        "health_check_interval": self.config.health_check_interval,
                        "security_mode": self.config.security_mode,
                        "max_file_size": self.config.max_file_size
                    }
                },
                error_count=self.metrics.error_count,
                last_error=self.metrics.last_error
            )

        except Exception as e:
            self.logger.error(f"Health check system error: {e}")
            self.metrics.error_count += 1
            self.metrics.last_error = str(e)

            return HealthStatus(
                status="unhealthy",
                agent_name=self.config.agent_name,
                timestamp=datetime.now(),
                checks={"health_system": False},
                error_count=self.metrics.error_count,
                last_error=str(e)
            )

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while self._is_monitoring:
            try:
                # Check which health checks need to run
                current_time = datetime.now()
                checks_to_run = []

                for name, interval in self._check_intervals.items():
                    last_check = self._last_check_times[name]
                    if (current_time - last_check).total_seconds() >= interval:
                        checks_to_run.append(name)

                # Run due health checks
                if checks_to_run:
                    for check_name in checks_to_run:
                        try:
                            await self.perform_health_check(check_name)
                        except Exception as e:
                            self.logger.error(f"Error in monitoring loop for {check_name}: {e}")

                # Wait before next iteration
                await asyncio.sleep(10)  # Check every 10 seconds for due checks

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(30)  # Back off on errors

    # Health check implementations
    async def _check_file_system_access(self) -> bool:
        """Test basic file system operations."""
        try:
            test_dir = Path.home() / ".mcp_mesh" / "health_check"
            test_dir.mkdir(parents=True, exist_ok=True)

            test_file = test_dir / f"health_check_{datetime.now().timestamp()}.txt"
            test_content = "health_check_test"

            # Write test file
            test_file.write_text(test_content)

            # Read test file
            read_content = test_file.read_text()

            # Clean up
            test_file.unlink()

            return read_content == test_content

        except Exception as e:
            self.logger.warning(f"File system access check failed: {e}")
            return False

    async def _check_disk_space(self) -> bool:
        """Check available disk space."""
        try:
            if self.config.base_directory:
                path = self.config.base_directory
            else:
                path = Path.home()

            stat = psutil.disk_usage(str(path))
            free_percent = (stat.free / stat.total) * 100

            # Consider unhealthy if less than 10% free space
            return free_percent > 10.0

        except Exception as e:
            self.logger.warning(f"Disk space check failed: {e}")
            return False

    async def _check_memory_usage(self) -> bool:
        """Check memory usage."""
        try:
            memory = psutil.virtual_memory()
            # Consider unhealthy if more than 90% memory used
            return memory.percent < 90.0
        except Exception:
            return True  # Non-critical check

    async def _check_cpu_usage(self) -> bool:
        """Check CPU usage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            # Consider unhealthy if more than 95% CPU used consistently
            return cpu_percent < 95.0
        except Exception:
            return True  # Non-critical check

    async def _check_base_directory(self) -> bool:
        """Check base directory accessibility."""
        if not self.config.base_directory:
            return True

        try:
            return (
                self.config.base_directory.exists() and
                self.config.base_directory.is_dir() and
                os.access(self.config.base_directory, os.R_OK | os.W_OK)
            )
        except Exception:
            return False

    async def _check_file_permissions(self) -> bool:
        """Check file operation permissions."""
        try:
            # Test read/write permissions in base directory
            if self.config.base_directory:
                test_path = self.config.base_directory
            else:
                test_path = Path.cwd()

            return os.access(test_path, os.R_OK | os.W_OK)
        except Exception:
            return False

    async def _check_backup_directory(self) -> bool:
        """Check backup directory accessibility."""
        if not self.config.enable_backups or not self.config.backup_directory:
            return True

        try:
            backup_dir = self.config.backup_directory
            if not backup_dir.exists():
                backup_dir.mkdir(parents=True, exist_ok=True)

            return backup_dir.is_dir() and os.access(backup_dir, os.R_OK | os.W_OK)
        except Exception:
            return False

    async def _check_registry_connection(self) -> bool:
        """Check mesh registry connectivity."""
        if not self.registry_client:
            return True  # No registry configured

        try:
            # Simple ping to registry
            return await self.registry_client._test_connection()
        except Exception:
            return False

    async def _check_service_discovery(self) -> bool:
        """Check service discovery functionality."""
        if not self.registry_client:
            return True

        try:
            # Try to discover a common service (auth_service if configured)
            if "auth_service" in getattr(self.config, 'dependencies', []):
                result = await self.registry_client.discover_service("auth_service")
                return result is not None
            return True
        except Exception:
            return False

    async def _get_system_metrics(self) -> Dict[str, Any]:
        """Get system metrics for health status."""
        try:
            return {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "cpu_count": psutil.cpu_count(),
                "memory_total": psutil.virtual_memory().total,
                "memory_available": psutil.virtual_memory().available,
                "disk_usage": dict(psutil.disk_usage("/")),
                "load_average": list(psutil.getloadavg()) if hasattr(psutil, 'getloadavg') else None
            }
        except Exception as e:
            return {"error": str(e)}
```

This comprehensive mesh integration and health monitoring system provides:

1. **Full Registry Integration**: Agent registration, service discovery, dependency injection
2. **Comprehensive Health Monitoring**: System, application, and mesh-specific health checks
3. **Event-Driven Architecture**: Callbacks for registration, heartbeats, and connection events
4. **Automatic Recovery**: Retry logic, graceful degradation, and error handling
5. **Rich Metrics**: Performance monitoring, error tracking, and operational insights
6. **Configurable Monitoring**: Customizable health checks with different intervals
7. **Production Ready**: Suitable for enterprise deployment with full observability

The system ensures the File Agent operates reliably within the mesh ecosystem while providing comprehensive visibility into its health and performance.
