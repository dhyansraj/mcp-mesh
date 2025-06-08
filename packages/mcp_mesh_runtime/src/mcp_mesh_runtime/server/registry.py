"""
Registry Service - Central MCP Server for Service Mesh Management

Follows Kubernetes API server pattern with PASSIVE pull-based architecture.
Agents call registry; registry does NOT call agents.

Architecture:
- FastMCP server providing RESTful API endpoints
- ETCD-style storage for agent registrations and capabilities
- Resource versioning and watch capabilities
- Health monitoring through agent heartbeats
- Capability-based service discovery
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastmcp import FastMCP
from mcp_mesh import SecurityValidationError

from ..shared.lifecycle_manager import LifecycleManager
from ..tools.contract_tools import ContractTools
from ..tools.lifecycle_tools import LifecycleTools
from .database import DatabaseConfig, RegistryDatabase
from .models import (
    AgentRegistration,
    CapabilitySearchQuery,
    HealthConfiguration,
    HealthStatus,
    RegistryMetrics,
    ServiceDiscoveryQuery,
)


class RegistryStorage:
    """ETCD-style storage for registry data with versioning and watches."""

    def __init__(self, database_config: DatabaseConfig | None = None):
        # Legacy in-memory storage for backward compatibility
        self._agents: dict[str, AgentRegistration] = {}
        self._capability_index: dict[str, set[str]] = {}  # capability -> agent_ids
        self._namespace_index: dict[str, set[str]] = {}  # namespace -> agent_ids
        self._watchers: list[asyncio.Queue] = []
        self._global_version = 0

        # New persistent database storage
        self.database = RegistryDatabase(database_config)
        self._database_enabled = True

        # Response caching
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl: int = 30  # seconds
        self._cache_timestamps: dict[str, datetime] = {}

        # Health monitoring configuration and metrics
        self.health_config = HealthConfiguration()
        self.metrics = RegistryMetrics()
        self._service_start_time = datetime.now(timezone.utc)

    async def initialize(self) -> None:
        """Initialize the storage system including database."""
        if self._database_enabled:
            await self.database.initialize()
            # Load existing agents from database into memory cache
            await self._load_from_database()

    async def close(self) -> None:
        """Close storage connections."""
        if self._database_enabled:
            await self.database.close()

    async def _load_from_database(self) -> None:
        """Load agents from database into memory cache for fast access."""
        try:
            agents = await self.database.list_agents()
            for agent in agents:
                self._agents[agent.id] = agent
                self._update_capability_index(agent)
                self._update_namespace_index(agent)
        except Exception as e:
            print(f"Warning: Failed to load from database: {e}")

    async def register_agent(
        self, registration: AgentRegistration
    ) -> AgentRegistration:
        """Register or update an agent."""
        existing = self._agents.get(registration.id)

        # Configure type-specific timeout thresholds
        registration.timeout_threshold = self.health_config.get_timeout_threshold(
            registration.agent_type
        )
        registration.eviction_threshold = self.health_config.get_eviction_threshold(
            registration.agent_type
        )

        # Update resource version and timestamp
        registration.updated_at = datetime.now(timezone.utc)
        registration.resource_version = str(int(time.time() * 1000))

        # Store in database first (for durability)
        if self._database_enabled:
            try:
                await self.database.register_agent(registration)
            except Exception as e:
                print(f"Database error during registration: {e}")
                # Continue with in-memory storage as fallback

        # Store in memory cache
        self._agents[registration.id] = registration

        # Update indexes
        self._update_capability_index(registration)
        self._update_namespace_index(registration)

        # Increment global version
        self._global_version += 1

        # Invalidate cache on changes
        self._invalidate_cache()

        # Update metrics
        if not existing:
            self.metrics.registrations_processed += 1
            self._update_metrics()

        # Notify watchers
        event_type = "MODIFIED" if existing else "ADDED"
        await self._notify_watchers(event_type, registration)

        return registration

    async def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent."""
        if agent_id not in self._agents:
            return False

        registration = self._agents[agent_id]

        # Remove from database first
        if self._database_enabled:
            try:
                await self.database.unregister_agent(agent_id)
            except Exception as e:
                print(f"Database error during unregistration: {e}")

        # Remove from memory
        del self._agents[agent_id]

        # Clean up indexes
        self._cleanup_capability_index(registration)
        self._cleanup_namespace_index(registration)

        # Increment global version
        self._global_version += 1

        # Invalidate cache on changes
        self._invalidate_cache()

        # Update metrics
        self._update_metrics()

        # Notify watchers
        await self._notify_watchers("DELETED", registration)

        return True

    async def get_agent(self, agent_id: str) -> AgentRegistration | None:
        """Get agent by ID."""
        return self._agents.get(agent_id)

    async def list_agents(
        self, query: ServiceDiscoveryQuery | None = None
    ) -> list[AgentRegistration]:
        """List agents with optional filtering."""
        # Check cache first for complex queries
        if query:
            cache_key = self._get_cache_key("agents_list", query.dict())
            cached = self._get_cached_response(cache_key)
            if cached:
                return [
                    AgentRegistration(**agent_data) for agent_data in cached["agents"]
                ]

        agents = list(self._agents.values())

        if not query:
            return agents

        # Filter by capabilities
        if query.capabilities:
            capability_agents = set()
            for cap in query.capabilities:
                if query.fuzzy_match:
                    # Fuzzy matching for capabilities
                    for agent in agents:
                        for agent_cap in agent.capabilities:
                            if self._fuzzy_match_capability(cap, agent_cap.name):
                                capability_agents.add(agent.id)
                else:
                    capability_agents.update(self._capability_index.get(cap, set()))
            agents = [a for a in agents if a.id in capability_agents]

        # Filter by capability metadata
        if (
            query.capability_category
            or query.capability_stability
            or query.capability_tags
        ):
            filtered_agents = []
            for agent in agents:
                for cap in agent.capabilities:
                    if (
                        query.capability_category
                        and cap.category != query.capability_category
                    ):
                        continue
                    if (
                        query.capability_stability
                        and cap.stability != query.capability_stability
                    ):
                        continue
                    if query.capability_tags:
                        if not any(tag in cap.tags for tag in query.capability_tags):
                            continue
                    filtered_agents.append(agent)
                    break  # Found matching capability, include agent
            agents = filtered_agents

        # Filter by version constraints
        if query.version_constraint:
            filtered_agents = []
            for agent in agents:
                for cap in agent.capabilities:
                    if self._match_version_constraint(
                        cap.version, query.version_constraint
                    ):
                        filtered_agents.append(agent)
                        break  # Found compatible capability, include agent
            agents = filtered_agents

        # Filter by namespace
        if query.namespace:
            agents = [a for a in agents if a.namespace == query.namespace]

        # Filter by status
        if query.status:
            agents = [a for a in agents if a.status == query.status]

        # Filter by labels
        if query.labels:
            agents = [
                a
                for a in agents
                if all(a.labels.get(k) == v for k, v in query.labels.items())
            ]

        # Cache the result if query was provided
        if query:
            result = {
                "agents": [agent.dict() for agent in agents],
                "count": len(agents),
            }
            self._set_cached_response(cache_key, result)

        return agents

    async def update_heartbeat(self, agent_id: str) -> bool:
        """Update agent heartbeat timestamp."""
        if agent_id not in self._agents:
            return False

        # Update in database first
        if self._database_enabled:
            try:
                db_success = await self.database.update_heartbeat(agent_id)
                if not db_success:
                    return False
            except Exception as e:
                print(f"Database error during heartbeat update: {e}")

        # Update in memory
        agent = self._agents[agent_id]
        agent.last_heartbeat = datetime.now(timezone.utc)
        agent.status = "healthy"
        agent.updated_at = datetime.now(timezone.utc)
        agent.resource_version = str(int(time.time() * 1000))

        # Increment global version
        self._global_version += 1

        # Update metrics
        self.metrics.heartbeats_processed += 1

        # Notify watchers
        await self._notify_watchers("MODIFIED", agent)

        return True

    def _get_cache_key(self, prefix: str, params: dict[str, Any]) -> str:
        """Generate cache key from parameters."""
        import hashlib
        import json

        param_str = json.dumps(params, sort_keys=True, default=str)
        hash_obj = hashlib.md5(param_str.encode())
        return f"{prefix}:{hash_obj.hexdigest()}"

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self._cache_timestamps:
            return False

        cache_time = self._cache_timestamps[cache_key]
        now = datetime.now(timezone.utc)
        return (now - cache_time).total_seconds() < self._cache_ttl

    def _get_cached_response(self, cache_key: str) -> dict[str, Any] | None:
        """Get cached response if valid."""
        if self._is_cache_valid(cache_key):
            return self._cache.get(cache_key)
        return None

    def _set_cached_response(self, cache_key: str, response: dict[str, Any]) -> None:
        """Cache response data."""
        self._cache[cache_key] = response
        self._cache_timestamps[cache_key] = datetime.now(timezone.utc)

    def _invalidate_cache(self) -> None:
        """Invalidate all cached responses."""
        self._cache.clear()
        self._cache_timestamps.clear()

    def _fuzzy_match_capability(
        self, query: str, capability_name: str, threshold: float = 0.7
    ) -> bool:
        """Perform fuzzy matching on capability names."""
        if not query or not capability_name:
            return False

        query_lower = query.lower()
        name_lower = capability_name.lower()

        # Exact match
        if query_lower == name_lower:
            return True

        # Substring match
        if query_lower in name_lower:
            return True

        # Simple Levenshtein distance ratio
        def levenshtein_ratio(s1: str, s2: str) -> float:
            """Calculate Levenshtein distance ratio."""
            len1, len2 = len(s1), len(s2)
            if len1 == 0:
                return float(len2)
            if len2 == 0:
                return float(len1)

            matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]

            for i in range(len1 + 1):
                matrix[i][0] = i
            for j in range(len2 + 1):
                matrix[0][j] = j

            for i in range(1, len1 + 1):
                for j in range(1, len2 + 1):
                    cost = 0 if s1[i - 1] == s2[j - 1] else 1
                    matrix[i][j] = min(
                        matrix[i - 1][j] + 1,  # deletion
                        matrix[i][j - 1] + 1,  # insertion
                        matrix[i - 1][j - 1] + cost,  # substitution
                    )

            distance = matrix[len1][len2]
            max_len = max(len1, len2)
            return 1.0 - (distance / max_len) if max_len > 0 else 0.0

        return levenshtein_ratio(query_lower, name_lower) >= threshold

    def _match_version_constraint(self, version: str, constraint: str) -> bool:
        """Check if version matches constraint."""
        if not constraint:
            return True

        # Simple version constraint matching
        # Support: ">=1.0.0", "~1.2.0", "^1.0.0", "=1.0.0"
        constraint = constraint.strip()

        if constraint.startswith(">="):
            return self._compare_versions(version, constraint[2:]) >= 0
        elif constraint.startswith(">"):
            return self._compare_versions(version, constraint[1:]) > 0
        elif constraint.startswith("<="):
            return self._compare_versions(version, constraint[2:]) <= 0
        elif constraint.startswith("<"):
            return self._compare_versions(version, constraint[1:]) < 0
        elif constraint.startswith("="):
            return version == constraint[1:]
        elif constraint.startswith("~"):
            # Compatible within patch level
            target = constraint[1:]
            return self._is_compatible_patch(version, target)
        elif constraint.startswith("^"):
            # Compatible within minor level
            target = constraint[1:]
            return self._is_compatible_minor(version, target)
        else:
            return version == constraint

    def _compare_versions(self, v1: str, v2: str) -> int:
        """Compare two semantic versions."""

        def parse_version(v):
            parts = v.split("-")[0].split(".")  # Remove pre-release suffix
            return [int(x) for x in parts]

        try:
            parts1 = parse_version(v1)
            parts2 = parse_version(v2)

            # Pad with zeros to same length
            max_len = max(len(parts1), len(parts2))
            parts1.extend([0] * (max_len - len(parts1)))
            parts2.extend([0] * (max_len - len(parts2)))

            for p1, p2 in zip(parts1, parts2, strict=False):
                if p1 < p2:
                    return -1
                elif p1 > p2:
                    return 1
            return 0
        except (ValueError, IndexError):
            return 0  # Invalid versions are considered equal

    def _is_compatible_patch(self, version: str, target: str) -> bool:
        """Check if version is compatible within patch level."""
        try:
            v_parts = version.split(".")
            t_parts = target.split(".")
            return (
                v_parts[0] == t_parts[0]
                and v_parts[1] == t_parts[1]
                and int(v_parts[2]) >= int(t_parts[2])
            )
        except (ValueError, IndexError):
            return False

    def _is_compatible_minor(self, version: str, target: str) -> bool:
        """Check if version is compatible within minor level."""
        try:
            v_parts = version.split(".")
            t_parts = target.split(".")
            return v_parts[0] == t_parts[0] and int(v_parts[1]) >= int(t_parts[1])
        except (ValueError, IndexError):
            return False

    async def search_capabilities(
        self, query: CapabilitySearchQuery
    ) -> list[dict[str, Any]]:
        """Search capabilities with enhanced filtering and fuzzy matching."""
        # Check cache first
        cache_key = self._get_cache_key("capabilities_search", query.dict())
        cached = self._get_cached_response(cache_key)
        if cached:
            return cached["capabilities"]

        # Get all agents
        agents = await self.list_agents()
        capabilities = []

        for agent in agents:
            # Filter by agent status and namespace first
            if query.agent_status and agent.status != query.agent_status:
                continue
            if query.agent_namespace and agent.namespace != query.agent_namespace:
                continue

            for cap in agent.capabilities:
                # Skip deprecated capabilities unless explicitly requested
                if cap.stability == "deprecated" and not query.include_deprecated:
                    continue

                # Apply filters
                if query.name:
                    if query.fuzzy_match:
                        if not self._fuzzy_match_capability(query.name, cap.name):
                            continue
                    else:
                        if query.name.lower() not in cap.name.lower():
                            continue

                if query.description_contains and cap.description:
                    if (
                        query.description_contains.lower()
                        not in cap.description.lower()
                    ):
                        continue

                if query.category and cap.category != query.category:
                    continue

                if query.stability and cap.stability != query.stability:
                    continue

                if query.tags:
                    if not any(tag in cap.tags for tag in query.tags):
                        continue

                if query.version_constraint:
                    if not self._match_version_constraint(
                        cap.version, query.version_constraint
                    ):
                        continue

                # Build capability response
                cap_dict = cap.dict()
                cap_dict.update(
                    {
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "agent_namespace": agent.namespace,
                        "agent_status": agent.status,
                        "agent_endpoint": agent.endpoint,
                    }
                )
                capabilities.append(cap_dict)

        # Cache the result
        result = {"capabilities": capabilities, "count": len(capabilities)}
        self._set_cached_response(cache_key, result)

        return capabilities

    async def get_agent_health(self, agent_id: str) -> HealthStatus | None:
        """Get health status for a specific agent."""
        agent = self._agents.get(agent_id)
        if not agent:
            return None

        current_time = datetime.now(timezone.utc)
        time_since_heartbeat = None
        next_heartbeat_expected = None
        is_expired = False
        message = None

        if agent.last_heartbeat:
            time_since_heartbeat = (current_time - agent.last_heartbeat).total_seconds()
            next_heartbeat_expected = agent.last_heartbeat + timedelta(
                seconds=agent.health_interval
            )

            if time_since_heartbeat > agent.eviction_threshold:
                is_expired = True
                message = (
                    f"Agent expired - no heartbeat for {time_since_heartbeat:.1f}s"
                )
            elif time_since_heartbeat > agent.timeout_threshold:
                message = (
                    f"Agent degraded - no heartbeat for {time_since_heartbeat:.1f}s"
                )
            else:
                message = (
                    f"Agent healthy - last heartbeat {time_since_heartbeat:.1f}s ago"
                )
        else:
            message = "No heartbeat received yet"

        return HealthStatus(
            agent_id=agent_id,
            status=agent.status,
            last_heartbeat=agent.last_heartbeat,
            next_heartbeat_expected=next_heartbeat_expected,
            time_since_heartbeat=time_since_heartbeat,
            timeout_threshold=agent.timeout_threshold,
            eviction_threshold=agent.eviction_threshold,
            is_expired=is_expired,
            message=message,
        )

    async def get_registry_metrics(self) -> RegistryMetrics:
        """Get current registry metrics."""
        self._update_metrics()
        return self.metrics

    async def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format."""
        self._update_metrics()

        prometheus_metrics = []

        # Agent status metrics
        prometheus_metrics.extend(
            [
                "# HELP mcp_registry_agents_total Total number of registered agents",
                "# TYPE mcp_registry_agents_total gauge",
                f"mcp_registry_agents_total {self.metrics.total_agents}",
                "",
                "# HELP mcp_registry_agents_by_status Number of agents by status",
                "# TYPE mcp_registry_agents_by_status gauge",
                f'mcp_registry_agents_by_status{{status="healthy"}} {self.metrics.healthy_agents}',
                f'mcp_registry_agents_by_status{{status="degraded"}} {self.metrics.degraded_agents}',
                f'mcp_registry_agents_by_status{{status="expired"}} {self.metrics.expired_agents}',
                f'mcp_registry_agents_by_status{{status="offline"}} {self.metrics.offline_agents}',
                f'mcp_registry_agents_by_status{{status="pending"}} {self.metrics.pending_agents}',
                "",
                "# HELP mcp_registry_capabilities_total Total number of capabilities",
                "# TYPE mcp_registry_capabilities_total gauge",
                f"mcp_registry_capabilities_total {self.metrics.total_capabilities}",
                "",
                "# HELP mcp_registry_capability_types_unique Number of unique capability types",
                "# TYPE mcp_registry_capability_types_unique gauge",
                f"mcp_registry_capability_types_unique {self.metrics.unique_capability_types}",
                "",
                "# HELP mcp_registry_uptime_seconds Registry uptime in seconds",
                "# TYPE mcp_registry_uptime_seconds counter",
                f"mcp_registry_uptime_seconds {self.metrics.uptime_seconds}",
                "",
                "# HELP mcp_registry_heartbeats_processed_total Total heartbeats processed",
                "# TYPE mcp_registry_heartbeats_processed_total counter",
                f"mcp_registry_heartbeats_processed_total {self.metrics.heartbeats_processed}",
                "",
                "# HELP mcp_registry_registrations_processed_total Total registrations processed",
                "# TYPE mcp_registry_registrations_processed_total counter",
                f"mcp_registry_registrations_processed_total {self.metrics.registrations_processed}",
                "",
            ]
        )

        return "\n".join(prometheus_metrics)

    async def check_agent_health_and_evict_expired(self) -> list[str]:
        """Check agent health and evict expired agents. Returns list of evicted agent IDs."""
        current_time = datetime.now(timezone.utc)
        evicted_agents = []
        agents_to_update = []

        for agent_id, agent in self._agents.items():
            if not agent.last_heartbeat:
                continue

            time_since_heartbeat = (current_time - agent.last_heartbeat).total_seconds()

            # Check if agent should be evicted
            if time_since_heartbeat > agent.eviction_threshold:
                if agent.status != "expired":
                    agent.status = "expired"
                    agent.updated_at = current_time
                    agent.resource_version = str(int(time.time() * 1000))
                    agents_to_update.append(agent)
                    evicted_agents.append(agent_id)

            # Check if agent should be marked as degraded
            elif time_since_heartbeat > agent.timeout_threshold:
                if agent.status == "healthy":
                    agent.status = "degraded"
                    agent.updated_at = current_time
                    agent.resource_version = str(int(time.time() * 1000))
                    agents_to_update.append(agent)

        # Update database and notify watchers for changed agents
        for agent in agents_to_update:
            if self._database_enabled:
                try:
                    await self.database.register_agent(agent)
                except Exception as e:
                    print(f"Database error during health status update: {e}")

            await self._notify_watchers("MODIFIED", agent)

        # Update metrics
        self._update_metrics()

        return evicted_agents

    def _update_metrics(self):
        """Update registry metrics."""
        current_time = datetime.now(timezone.utc)

        # Count agents by status
        status_counts = {
            "healthy": 0,
            "degraded": 0,
            "expired": 0,
            "offline": 0,
            "pending": 0,
        }
        total_capabilities = 0
        capability_types = set()

        for agent in self._agents.values():
            status_counts[agent.status] = status_counts.get(agent.status, 0) + 1
            total_capabilities += len(agent.capabilities)
            for cap in agent.capabilities:
                capability_types.add(cap.name)

        # Update metrics
        self.metrics.total_agents = len(self._agents)
        self.metrics.healthy_agents = status_counts["healthy"]
        self.metrics.degraded_agents = status_counts["degraded"]
        self.metrics.expired_agents = status_counts["expired"]
        self.metrics.offline_agents = status_counts["offline"]
        self.metrics.pending_agents = status_counts["pending"]
        self.metrics.total_capabilities = total_capabilities
        self.metrics.unique_capability_types = len(capability_types)
        self.metrics.uptime_seconds = (
            current_time - self._service_start_time
        ).total_seconds()
        self.metrics.last_updated = current_time

    def _update_capability_index(self, registration: AgentRegistration):
        """Update capability index for an agent."""
        for cap in registration.capabilities:
            if cap.name not in self._capability_index:
                self._capability_index[cap.name] = set()
            self._capability_index[cap.name].add(registration.id)

    def _cleanup_capability_index(self, registration: AgentRegistration):
        """Clean up capability index for an agent."""
        for cap in registration.capabilities:
            if cap.name in self._capability_index:
                self._capability_index[cap.name].discard(registration.id)
                if not self._capability_index[cap.name]:
                    del self._capability_index[cap.name]

    def _update_namespace_index(self, registration: AgentRegistration):
        """Update namespace index for an agent."""
        if registration.namespace not in self._namespace_index:
            self._namespace_index[registration.namespace] = set()
        self._namespace_index[registration.namespace].add(registration.id)

    def _cleanup_namespace_index(self, registration: AgentRegistration):
        """Clean up namespace index for an agent."""
        if registration.namespace in self._namespace_index:
            self._namespace_index[registration.namespace].discard(registration.id)
            if not self._namespace_index[registration.namespace]:
                del self._namespace_index[registration.namespace]

    async def _notify_watchers(self, event_type: str, registration: AgentRegistration):
        """Notify all watchers of registry changes."""
        event = {
            "type": event_type,
            "object": registration.model_dump(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Send to all watchers
        for watcher_queue in self._watchers[
            :
        ]:  # Copy to avoid modification during iteration
            try:
                await watcher_queue.put(event)
            except asyncio.QueueFull:
                # Remove full watchers
                self._watchers.remove(watcher_queue)

    def create_watcher(self) -> asyncio.Queue:
        """Create a new watcher queue for registry events."""
        queue = asyncio.Queue(maxsize=100)
        self._watchers.append(queue)
        return queue


class RegistryService:
    """
    Registry Service - Central service mesh coordinator

    Implements Kubernetes API server pattern:
    - RESTful API for agent registration/discovery
    - Resource versioning and conflict detection
    - Watch streams for real-time updates
    - PASSIVE architecture - only responds to agent requests
    """

    def __init__(
        self,
        name: str = "mcp-mesh-registry",
        database_config: DatabaseConfig | None = None,
    ):
        self.app = FastMCP(name)
        self.storage = RegistryStorage(database_config)
        self._health_check_task: asyncio.Task | None = None
        self._initialized = False

        # Initialize lifecycle management
        self.lifecycle_manager = LifecycleManager(self.storage)
        self.lifecycle_tools = LifecycleTools(self.lifecycle_manager)

        # Initialize contract management
        self.contract_tools = ContractTools(self.storage.database)

        # Initialize agent selection
        from ..shared.agent_selection import AgentSelector
        from ..tools.selection_tools import SelectionTools

        self.agent_selector = AgentSelector()
        self.selection_tools = SelectionTools(self.agent_selector)

        # Register tools following the pattern
        self._register_tools()

    async def initialize(self) -> None:
        """Initialize the registry service and storage."""
        if not self._initialized:
            await self.storage.initialize()

            # Create a minimal registry client interface for the selector
            class RegistryClientInterface:
                def __init__(self, storage):
                    self.storage = storage

                async def get_all_agents(self):
                    agents = await self.storage.list_agents()
                    return [agent.model_dump() for agent in agents]

                async def get_agent(self, agent_id: str):
                    agent = await self.storage.get_agent(agent_id)
                    return agent.model_dump() if agent else None

            # Set the registry client for the selector
            registry_client = RegistryClientInterface(self.storage)
            self.agent_selector.set_registry_client(registry_client)
            self.selection_tools.set_registry_client(registry_client)

            self._initialized = True

    async def close(self) -> None:
        """Close the registry service and storage."""
        await self.stop_health_monitoring()
        await self.storage.close()
        self._initialized = False

    def _register_tools(self):
        """Register all registry tools using FastMCP."""

        @self.app.tool(
            name="register_agent", description="Register agent with the service mesh"
        )
        async def register_agent(registration_data: dict) -> dict:
            """Register or update an agent in the service mesh."""
            try:
                registration = AgentRegistration(**registration_data)

                # Validate security context if provided
                if registration.security_context:
                    await self._validate_security_context(registration)

                registered = await self.storage.register_agent(registration)

                return {
                    "status": "success",
                    "agent_id": registered.id,
                    "resource_version": registered.resource_version,
                    "message": f"Agent {registered.name} registered successfully",
                }

            except Exception as e:
                return {
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to register agent",
                }

        @self.app.tool(
            name="unregister_agent", description="Unregister agent from service mesh"
        )
        async def unregister_agent(agent_id: str) -> dict:
            """Unregister an agent from the service mesh."""
            try:
                success = await self.storage.unregister_agent(agent_id)

                if success:
                    return {
                        "status": "success",
                        "message": f"Agent {agent_id} unregistered successfully",
                    }
                else:
                    return {"status": "error", "message": f"Agent {agent_id} not found"}

            except Exception as e:
                return {
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to unregister agent",
                }

        @self.app.tool(
            name="discover_services", description="Discover available services"
        )
        async def discover_services(query: dict = None) -> dict:
            """Discover services based on capabilities and labels."""
            try:
                discovery_query = ServiceDiscoveryQuery(**(query or {}))
                agents = await self.storage.list_agents(discovery_query)

                return {
                    "status": "success",
                    "agents": [agent.model_dump() for agent in agents],
                    "count": len(agents),
                }

            except Exception as e:
                return {
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to discover services",
                }

        @self.app.tool(name="heartbeat", description="Send agent heartbeat")
        async def heartbeat(agent_id: str) -> dict:
            """Process agent heartbeat."""
            try:
                success = await self.storage.update_heartbeat(agent_id)

                if success:
                    return {
                        "status": "success",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "message": "Heartbeat recorded",
                    }
                else:
                    return {"status": "error", "message": f"Agent {agent_id} not found"}

            except Exception as e:
                return {
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to process heartbeat",
                }

        @self.app.tool(
            name="get_agent_status", description="Get agent status and details"
        )
        async def get_agent_status(agent_id: str) -> dict:
            """Get detailed status of a specific agent."""
            try:
                agent = await self.storage.get_agent(agent_id)

                if agent:
                    return {"status": "success", "agent": agent.model_dump()}
                else:
                    return {"status": "error", "message": f"Agent {agent_id} not found"}

            except Exception as e:
                return {
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to get agent status",
                }

        # Lifecycle Management Tools
        @self.app.tool(
            name="lifecycle_register_agent",
            description="Register agent with lifecycle management",
        )
        async def lifecycle_register_agent(agent_info: dict) -> dict:
            """Register agent using lifecycle management system."""
            return await self.lifecycle_tools.register_agent(agent_info)

        @self.app.tool(
            name="lifecycle_deregister_agent",
            description="Deregister agent with lifecycle management",
        )
        async def lifecycle_deregister_agent(
            agent_id: str, graceful: bool = True
        ) -> dict:
            """Deregister agent using lifecycle management system."""
            return await self.lifecycle_tools.deregister_agent(agent_id, graceful)

        @self.app.tool(
            name="lifecycle_drain_agent", description="Drain agent from selection pool"
        )
        async def lifecycle_drain_agent(agent_id: str) -> dict:
            """Drain agent using lifecycle management system."""
            return await self.lifecycle_tools.drain_agent(agent_id)

        @self.app.tool(
            name="get_agent_lifecycle_status", description="Get agent lifecycle status"
        )
        async def get_agent_lifecycle_status(agent_id: str) -> dict:
            """Get agent lifecycle status."""
            return await self.lifecycle_tools.get_agent_lifecycle_status(agent_id)

        @self.app.tool(
            name="list_agents_by_lifecycle_status",
            description="List agents by lifecycle status",
        )
        async def list_agents_by_lifecycle_status(status: str) -> dict:
            """List agents by lifecycle status."""
            return await self.lifecycle_tools.list_agents_by_lifecycle_status(status)

        # Agent Selection Tools
        @self.app.tool(
            name="select_agent",
            description="Select an agent based on capability and selection criteria",
        )
        async def select_agent(
            capability: str,
            algorithm: str = "health_aware",
            requirements: dict = None,
            exclude_unhealthy: bool = True,
            exclude_draining: bool = True,
            min_health_score: float = 0.7,
            max_load_threshold: float = 0.8,
            prefer_local: bool = False,
            session_affinity: str = None,
        ) -> dict:
            """Select an agent using intelligent selection algorithms."""
            return await self.selection_tools.select_agent(
                capability=capability,
                algorithm=algorithm,
                requirements=requirements,
                exclude_unhealthy=exclude_unhealthy,
                exclude_draining=exclude_draining,
                min_health_score=min_health_score,
                max_load_threshold=max_load_threshold,
                prefer_local=prefer_local,
                session_affinity=session_affinity,
            )

        @self.app.tool(
            name="get_agent_health",
            description="Get health status for a specific agent",
        )
        async def get_agent_health(agent_id: str) -> dict:
            """Get detailed health information for an agent."""
            return await self.selection_tools.get_agent_health(agent_id)

        @self.app.tool(
            name="update_selection_weights",
            description="Update selection weights for an agent",
        )
        async def update_selection_weights(
            agent_id: str,
            weights: dict,
            reason: str = "Manual weight update",
            apply_globally: bool = False,
            expires_at: str = None,
        ) -> dict:
            """Update selection weights for intelligent agent selection."""
            return await self.selection_tools.update_selection_weights(
                agent_id=agent_id,
                weights=weights,
                reason=reason,
                apply_globally=apply_globally,
                expires_at=expires_at,
            )

        @self.app.tool(
            name="get_available_agents",
            description="Get list of available agents for a capability",
        )
        async def get_available_agents(
            capability: str,
            min_health_score: float = 0.0,
            max_load_threshold: float = 1.0,
            exclude_unhealthy: bool = False,
            exclude_draining: bool = False,
        ) -> dict:
            """Get list of available agents for a specific capability."""
            return await self.selection_tools.get_available_agents(
                capability=capability,
                min_health_score=min_health_score,
                max_load_threshold=max_load_threshold,
                exclude_unhealthy=exclude_unhealthy,
                exclude_draining=exclude_draining,
            )

        @self.app.tool(
            name="get_selection_stats",
            description="Get selection statistics and current state",
        )
        async def get_selection_stats() -> dict:
            """Get statistics about agent selection operations."""
            return await self.selection_tools.get_selection_stats()

        # Service Contract Management Tools
        @self.app.tool(
            name="store_service_contract",
            description="Store a service contract for an agent class",
        )
        async def store_service_contract(
            class_name: str, method_metadata_dict: dict
        ) -> dict:
            """Store a service contract with method metadata."""
            try:
                # Convert dict back to MethodMetadata object
                import inspect

                from mcp_mesh import (
                    MethodMetadata,
                    MethodType,
                )

                # Reconstruct MethodMetadata from dictionary
                metadata = MethodMetadata(
                    method_name=method_metadata_dict["method_name"],
                    signature=inspect.signature(
                        lambda: None
                    ),  # Placeholder, would need proper reconstruction
                    capabilities=method_metadata_dict.get("capabilities", []),
                    return_type=eval(
                        method_metadata_dict.get("return_type", "type(None)")
                    ),
                    parameters=method_metadata_dict.get("parameters", {}),
                    type_hints=method_metadata_dict.get("type_hints", {}),
                    method_type=MethodType(
                        method_metadata_dict.get("method_type", "function")
                    ),
                    is_async=method_metadata_dict.get("is_async", False),
                    docstring=method_metadata_dict.get("docstring", ""),
                    service_version=method_metadata_dict.get(
                        "service_version", "1.0.0"
                    ),
                    stability_level=method_metadata_dict.get(
                        "stability_level", "stable"
                    ),
                    deprecation_warning=method_metadata_dict.get(
                        "deprecation_warning", ""
                    ),
                    expected_complexity=method_metadata_dict.get(
                        "expected_complexity", "O(1)"
                    ),
                    resource_requirements=method_metadata_dict.get(
                        "resource_requirements", {}
                    ),
                    timeout_hint=method_metadata_dict.get("timeout_hint", 30),
                )

                # Create a dummy class type for the class name
                class_type = type(class_name, (), {})

                result = await self.contract_tools.store_service_contract(
                    class_type, metadata
                )
                return result.to_dict()

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "message": "Failed to store service contract",
                }

        @self.app.tool(
            name="get_service_contract",
            description="Retrieve a service contract for a class",
        )
        async def get_service_contract(class_name: str) -> dict:
            """Retrieve a service contract for a class."""
            try:
                class_type = type(class_name, (), {})
                contract = await self.contract_tools.get_service_contract(class_type)

                if contract:
                    return {
                        "success": True,
                        "contract": contract.to_dict(),
                        "message": f"Retrieved contract for {class_name}",
                    }
                else:
                    return {
                        "success": False,
                        "contract": None,
                        "message": f"No contract found for {class_name}",
                    }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "message": "Failed to retrieve service contract",
                }

        @self.app.tool(
            name="validate_contract_compatibility",
            description="Validate contract compatibility and signature consistency",
        )
        async def validate_contract_compatibility(contract_dict: dict) -> dict:
            """Validate a service contract for compatibility."""
            try:
                from mcp_mesh import (
                    ServiceContract,
                )

                # Reconstruct ServiceContract from dictionary
                # This is a simplified reconstruction - in production would need full deserialization
                contract = ServiceContract(
                    service_name=contract_dict["service_name"],
                    service_version=contract_dict.get("service_version", "1.0.0"),
                    description=contract_dict.get("description", ""),
                    contract_version=contract_dict.get("contract_version", "1.0.0"),
                    compatibility_level=contract_dict.get(
                        "compatibility_level", "strict"
                    ),
                )

                result = await self.contract_tools.validate_contract_compatibility(
                    contract
                )
                return result.to_dict()

            except Exception as e:
                return {
                    "is_valid": False,
                    "issues": [str(e)],
                    "compatibility_score": 0.0,
                    "error": "Failed to validate contract",
                }

        @self.app.tool(
            name="find_contracts_by_capability",
            description="Find contracts that provide a specific capability",
        )
        async def find_contracts_by_capability(capability_name: str) -> dict:
            """Find all contracts that provide a specific capability."""
            try:
                contracts = await self.contract_tools.find_contracts_by_capability(
                    capability_name
                )
                return {
                    "success": True,
                    "contracts": contracts,
                    "count": len(contracts),
                    "capability": capability_name,
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "message": f"Failed to find contracts for capability {capability_name}",
                }

        @self.app.tool(
            name="get_contract_compatibility_info",
            description="Get contract compatibility information for version checking",
        )
        async def get_contract_compatibility_info(
            service_name: str, version_constraint: str = None
        ) -> dict:
            """Get contract compatibility information."""
            try:
                info = await self.contract_tools.get_contract_compatibility_info(
                    service_name, version_constraint
                )
                return {
                    "success": True,
                    "compatibility_info": info,
                    "service_name": service_name,
                    "version_constraint": version_constraint,
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "message": f"Failed to get compatibility info for {service_name}",
                }

        @self.app.tool(
            name="get_contract_performance_metrics",
            description="Get performance metrics for contract operations",
        )
        async def get_contract_performance_metrics() -> dict:
            """Get performance metrics for contract operations."""
            try:
                metrics = await self.contract_tools.get_performance_metrics()
                return {
                    "success": True,
                    "metrics": metrics,
                    "message": "Performance metrics retrieved successfully",
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "message": "Failed to retrieve performance metrics",
                }

    async def _validate_security_context(self, registration: AgentRegistration):
        """Validate security context for agent registration."""
        # Basic security validation - extend as needed
        if registration.security_context == "high_security":
            # Require specific capabilities for high security context
            required_caps = {"authentication", "authorization", "audit"}
            agent_caps = {cap.name for cap in registration.capabilities}

            if not required_caps.issubset(agent_caps):
                missing = required_caps - agent_caps
                raise SecurityValidationError(
                    f"High security context requires capabilities: {missing}"
                )

    async def start_health_monitoring(self):
        """Start background health monitoring task."""
        if self._health_check_task is None:
            self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def stop_health_monitoring(self):
        """Stop background health monitoring task."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

    async def _health_check_loop(self):
        """Background task to monitor agent health using timer-based approach."""
        while True:
            try:
                # Use configurable check interval
                check_interval = self.storage.health_config.check_interval
                await asyncio.sleep(check_interval)

                # Perform passive timer-based health check
                evicted_agents = (
                    await self.storage.check_agent_health_and_evict_expired()
                )

                if evicted_agents:
                    print(
                        f"Health monitor: Marked {len(evicted_agents)} agents as expired"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but continue monitoring
                print(f"Error in health check loop: {e}")

    async def _database_health_check(self):
        """Database-backed health monitoring."""
        try:
            # Find agents that haven't sent heartbeat within timeout
            unhealthy_agent_ids = await self.storage.database.get_unhealthy_agents(
                timeout_seconds=60
            )

            if unhealthy_agent_ids:
                # Mark agents as unhealthy in database
                marked_count = await self.storage.database.mark_agents_unhealthy(
                    unhealthy_agent_ids
                )
                print(f"Marked {marked_count} agents as unhealthy")

                # Update memory cache
                for agent_id in unhealthy_agent_ids:
                    if agent_id in self.storage._agents:
                        agent = self.storage._agents[agent_id]
                        if agent.status != "unhealthy":
                            agent.status = "unhealthy"
                            agent.updated_at = datetime.now(timezone.utc)
                            agent.resource_version = str(int(time.time() * 1000))

                            # Notify watchers
                            await self.storage._notify_watchers("MODIFIED", agent)

        except Exception as e:
            print(f"Database health check error: {e}")
            # Fallback to memory-based health check
            await self._memory_health_check()

    async def _memory_health_check(self):
        """Memory-based health monitoring (fallback)."""
        current_time = datetime.now(timezone.utc)
        agents = await self.storage.list_agents()

        for agent in agents:
            if agent.last_heartbeat:
                time_since_heartbeat = (
                    current_time - agent.last_heartbeat
                ).total_seconds()

                # Mark as unhealthy if heartbeat is overdue
                if time_since_heartbeat > agent.health_interval * 2:
                    if agent.status != "unhealthy":
                        agent.status = "unhealthy"
                        agent.updated_at = current_time
                        agent.resource_version = str(int(time.time() * 1000))

                        # Update in storage
                        await self.storage.register_agent(agent)

    def get_app(self) -> FastMCP:
        """Get the FastMCP application instance."""
        return self.app


# Main application factory
def create_registry_app() -> FastMCP:
    """Create and configure the registry service application."""
    registry = RegistryService()
    return registry.get_app()


# Entry point for running the registry service
async def main():
    """Main entry point for the registry service."""
    registry = RegistryService()

    try:
        # Initialize registry and storage
        await registry.initialize()

        # Start health monitoring
        await registry.start_health_monitoring()

        # In a real deployment, you would run this with a proper ASGI server
        print("🚀 MCP Mesh Registry Service starting...")
        print("Registry follows Kubernetes API server pattern")
        print("Agents will register and discover services through this registry")
        print("✅ Database persistence enabled")

        # Keep the service running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("Shutting down registry service...")
    finally:
        await registry.close()


if __name__ == "__main__":
    asyncio.run(main())
