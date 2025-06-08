"""
SQLite Database Schema and Operations for MCP Mesh Registry

Provides persistent storage for agent metadata, capabilities, and health status
following the Kubernetes API server pattern with ETCD-style versioning.
"""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import BaseModel

from .models import AgentCapability, AgentRegistration


class DatabaseConfig(BaseModel):
    """Database configuration settings."""

    database_path: str = "mcp_mesh_registry.db"
    connection_timeout: int = 30
    busy_timeout: int = 5000
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    cache_size: int = 10000
    enable_foreign_keys: bool = True


class DatabaseSchema:
    """SQLite schema definitions for the MCP Mesh Registry."""

    # Core schema version for migrations
    SCHEMA_VERSION = 2

    SCHEMA_SQL = {
        "schema_version": """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """,
        "agents": """
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                namespace TEXT NOT NULL DEFAULT 'default',
                endpoint TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',

                -- Kubernetes-style metadata
                labels TEXT DEFAULT '{}',  -- JSON
                annotations TEXT DEFAULT '{}',  -- JSON

                -- Timestamps and versioning
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                resource_version TEXT NOT NULL,
                last_heartbeat TIMESTAMP,

                -- Health configuration
                health_interval INTEGER DEFAULT 30,

                -- Configuration and security
                config TEXT DEFAULT '{}',  -- JSON
                security_context TEXT,
                dependencies TEXT DEFAULT '[]',  -- JSON array

                -- Indexes for discovery
                UNIQUE(name, namespace)
            );
        """,
        "capabilities": """
            CREATE TABLE IF NOT EXISTS capabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                version TEXT DEFAULT '1.0.0',
                parameters_schema TEXT,  -- JSON
                security_requirements TEXT,  -- JSON array

                -- Timestamps
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                UNIQUE(agent_id, name)
            );
        """,
        "agent_health": """
            CREATE TABLE IF NOT EXISTS agent_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                status TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- Health details
                checks TEXT DEFAULT '{}',  -- JSON object
                errors TEXT DEFAULT '[]',  -- JSON array
                uptime_seconds INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}',  -- JSON

                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );
        """,
        "registry_events": """
            CREATE TABLE IF NOT EXISTS registry_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,  -- ADDED, MODIFIED, DELETED
                agent_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resource_version TEXT NOT NULL,
                data TEXT,  -- JSON snapshot

                -- Event metadata
                source TEXT DEFAULT 'registry',
                metadata TEXT DEFAULT '{}'  -- JSON
            );
        """,
        "service_contracts": """
            CREATE TABLE IF NOT EXISTS service_contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                service_version TEXT NOT NULL DEFAULT '1.0.0',
                description TEXT,
                contract_version TEXT NOT NULL DEFAULT '1.0.0',
                compatibility_level TEXT NOT NULL DEFAULT 'strict',

                -- Contract metadata
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                UNIQUE(agent_id, service_name, service_version)
            );
        """,
        "method_metadata": """
            CREATE TABLE IF NOT EXISTS method_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id INTEGER NOT NULL,
                method_name TEXT NOT NULL,
                signature_data TEXT NOT NULL,  -- JSON serialized inspect.Signature
                return_type TEXT,
                is_async BOOLEAN DEFAULT FALSE,
                method_type TEXT DEFAULT 'function',

                -- Method documentation and versioning
                docstring TEXT,
                service_version TEXT DEFAULT '1.0.0',
                stability_level TEXT DEFAULT 'stable',
                deprecation_warning TEXT,

                -- Performance metadata
                expected_complexity TEXT DEFAULT 'O(1)',
                timeout_hint INTEGER DEFAULT 30,
                resource_requirements TEXT DEFAULT '{}',  -- JSON

                -- Timestamps
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (contract_id) REFERENCES service_contracts(id) ON DELETE CASCADE,
                UNIQUE(contract_id, method_name)
            );
        """,
        "method_parameters": """
            CREATE TABLE IF NOT EXISTS method_parameters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method_id INTEGER NOT NULL,
                parameter_name TEXT NOT NULL,
                parameter_type TEXT NOT NULL,
                parameter_kind TEXT NOT NULL,
                default_value TEXT,  -- JSON serialized
                annotation TEXT,  -- JSON serialized
                has_default BOOLEAN DEFAULT FALSE,
                is_optional BOOLEAN DEFAULT FALSE,
                position INTEGER NOT NULL,

                FOREIGN KEY (method_id) REFERENCES method_metadata(id) ON DELETE CASCADE,
                UNIQUE(method_id, parameter_name)
            );
        """,
        "method_capabilities": """
            CREATE TABLE IF NOT EXISTS method_capabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method_id INTEGER NOT NULL,
                capability_name TEXT NOT NULL,

                -- Link to agent capabilities for validation
                capability_id INTEGER,

                FOREIGN KEY (method_id) REFERENCES method_metadata(id) ON DELETE CASCADE,
                FOREIGN KEY (capability_id) REFERENCES capabilities(id) ON DELETE SET NULL,
                UNIQUE(method_id, capability_name)
            );
        """,
        "capability_method_mapping": """
            CREATE TABLE IF NOT EXISTS capability_method_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capability_id INTEGER NOT NULL,
                method_id INTEGER NOT NULL,
                mapping_type TEXT DEFAULT 'direct',  -- direct, derived, composite
                priority INTEGER DEFAULT 0,

                -- Mapping metadata
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (capability_id) REFERENCES capabilities(id) ON DELETE CASCADE,
                FOREIGN KEY (method_id) REFERENCES method_metadata(id) ON DELETE CASCADE,
                UNIQUE(capability_id, method_id)
            );
        """,
    }

    INDEXES = {
        # Agent discovery optimization
        "idx_agents_namespace": "CREATE INDEX IF NOT EXISTS idx_agents_namespace ON agents(namespace);",
        "idx_agents_status": "CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);",
        "idx_agents_updated": "CREATE INDEX IF NOT EXISTS idx_agents_updated ON agents(updated_at);",
        "idx_agents_heartbeat": "CREATE INDEX IF NOT EXISTS idx_agents_heartbeat ON agents(last_heartbeat);",
        # Capability discovery optimization
        "idx_capabilities_name": "CREATE INDEX IF NOT EXISTS idx_capabilities_name ON capabilities(name);",
        "idx_capabilities_agent": "CREATE INDEX IF NOT EXISTS idx_capabilities_agent ON capabilities(agent_id);",
        "idx_capabilities_composite": "CREATE INDEX IF NOT EXISTS idx_capabilities_composite ON capabilities(name, agent_id);",
        # Health monitoring optimization
        "idx_health_agent": "CREATE INDEX IF NOT EXISTS idx_health_agent ON agent_health(agent_id);",
        "idx_health_timestamp": "CREATE INDEX IF NOT EXISTS idx_health_timestamp ON agent_health(timestamp);",
        "idx_health_status": "CREATE INDEX IF NOT EXISTS idx_health_status ON agent_health(agent_id, timestamp);",
        # Event history optimization
        "idx_events_agent": "CREATE INDEX IF NOT EXISTS idx_events_agent ON registry_events(agent_id);",
        "idx_events_timestamp": "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON registry_events(timestamp);",
        "idx_events_type": "CREATE INDEX IF NOT EXISTS idx_events_type ON registry_events(event_type, timestamp);",
        # Service contract optimization
        "idx_contracts_agent": "CREATE INDEX IF NOT EXISTS idx_contracts_agent ON service_contracts(agent_id);",
        "idx_contracts_service": "CREATE INDEX IF NOT EXISTS idx_contracts_service ON service_contracts(service_name, service_version);",
        "idx_contracts_composite": "CREATE INDEX IF NOT EXISTS idx_contracts_composite ON service_contracts(agent_id, service_name);",
        # Method metadata optimization
        "idx_methods_contract": "CREATE INDEX IF NOT EXISTS idx_methods_contract ON method_metadata(contract_id);",
        "idx_methods_name": "CREATE INDEX IF NOT EXISTS idx_methods_name ON method_metadata(method_name);",
        "idx_methods_composite": "CREATE INDEX IF NOT EXISTS idx_methods_composite ON method_metadata(contract_id, method_name);",
        "idx_methods_stability": "CREATE INDEX IF NOT EXISTS idx_methods_stability ON method_metadata(stability_level);",
        # Parameter optimization
        "idx_parameters_method": "CREATE INDEX IF NOT EXISTS idx_parameters_method ON method_parameters(method_id);",
        "idx_parameters_type": "CREATE INDEX IF NOT EXISTS idx_parameters_type ON method_parameters(parameter_type);",
        "idx_parameters_position": "CREATE INDEX IF NOT EXISTS idx_parameters_position ON method_parameters(method_id, position);",
        # Method capabilities optimization
        "idx_method_caps_method": "CREATE INDEX IF NOT EXISTS idx_method_caps_method ON method_capabilities(method_id);",
        "idx_method_caps_capability": "CREATE INDEX IF NOT EXISTS idx_method_caps_capability ON method_capabilities(capability_name);",
        "idx_method_caps_composite": "CREATE INDEX IF NOT EXISTS idx_method_caps_composite ON method_capabilities(capability_name, method_id);",
        # Capability-method mapping optimization
        "idx_cap_mapping_capability": "CREATE INDEX IF NOT EXISTS idx_cap_mapping_capability ON capability_method_mapping(capability_id);",
        "idx_cap_mapping_method": "CREATE INDEX IF NOT EXISTS idx_cap_mapping_method ON capability_method_mapping(method_id);",
        "idx_cap_mapping_type": "CREATE INDEX IF NOT EXISTS idx_cap_mapping_type ON capability_method_mapping(mapping_type);",
        "idx_cap_mapping_priority": "CREATE INDEX IF NOT EXISTS idx_cap_mapping_priority ON capability_method_mapping(capability_id, priority);",
    }


class RegistryDatabase:
    """
    SQLite database operations for MCP Mesh Registry.

    Provides ACID transactions, connection pooling, and optimized queries
    for agent registration, capability discovery, and health monitoring.
    """

    def __init__(self, config: DatabaseConfig | None = None):
        self.config = config or DatabaseConfig()
        self.db_path = Path(self.config.database_path)
        self._connection_pool: list[aiosqlite.Connection] = []
        self._pool_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize database schema and connection pool."""
        if self._initialized:
            return

        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        await self._create_schema()
        await self._apply_migrations()

        self._initialized = True

    async def close(self) -> None:
        """Close all database connections."""
        async with self._pool_lock:
            for conn in self._connection_pool:
                await conn.close()
            self._connection_pool.clear()
        self._initialized = False

    async def _get_connection(self) -> aiosqlite.Connection:
        """Get a database connection from the pool."""
        async with self._pool_lock:
            if self._connection_pool:
                return self._connection_pool.pop()

        # Create new connection
        conn = await aiosqlite.connect(
            str(self.db_path), timeout=self.config.connection_timeout
        )

        # Configure connection
        await conn.execute(f"PRAGMA busy_timeout = {self.config.busy_timeout}")
        await conn.execute(f"PRAGMA journal_mode = {self.config.journal_mode}")
        await conn.execute(f"PRAGMA synchronous = {self.config.synchronous}")
        await conn.execute(f"PRAGMA cache_size = -{self.config.cache_size}")

        if self.config.enable_foreign_keys:
            await conn.execute("PRAGMA foreign_keys = ON")

        return conn

    async def _return_connection(self, conn: aiosqlite.Connection) -> None:
        """Return a connection to the pool."""
        async with self._pool_lock:
            if len(self._connection_pool) < 10:  # Pool size limit
                self._connection_pool.append(conn)
            else:
                await conn.close()

    async def _create_schema(self) -> None:
        """Create database schema."""
        conn = await self._get_connection()
        try:
            # Create all tables
            for _table_name, sql in DatabaseSchema.SCHEMA_SQL.items():
                await conn.execute(sql)

            # Create all indexes
            for _index_name, sql in DatabaseSchema.INDEXES.items():
                await conn.execute(sql)

            await conn.commit()
        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def _apply_migrations(self) -> None:
        """Apply database migrations."""
        conn = await self._get_connection()
        try:
            # Check current schema version
            async with conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                current_version = row[0] if row else 0

            # Apply migrations if needed
            if current_version < DatabaseSchema.SCHEMA_VERSION:
                await self._apply_schema_migrations(conn, current_version)
                await conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                    (DatabaseSchema.SCHEMA_VERSION,),
                )
                await conn.commit()
        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def _apply_schema_migrations(
        self, conn: aiosqlite.Connection, from_version: int
    ) -> None:
        """Apply schema migrations from specific version."""
        if from_version < 2:
            # Migration from v1 to v2: Add service contract tables
            migration_tables = [
                "service_contracts",
                "method_metadata",
                "method_parameters",
                "method_capabilities",
                "capability_method_mapping",
            ]

            for table_name in migration_tables:
                if table_name in DatabaseSchema.SCHEMA_SQL:
                    await conn.execute(DatabaseSchema.SCHEMA_SQL[table_name])

            # Add new indexes for service contract tables
            migration_indexes = [
                "idx_contracts_agent",
                "idx_contracts_service",
                "idx_contracts_composite",
                "idx_methods_contract",
                "idx_methods_name",
                "idx_methods_composite",
                "idx_methods_stability",
                "idx_parameters_method",
                "idx_parameters_type",
                "idx_parameters_position",
                "idx_method_caps_method",
                "idx_method_caps_capability",
                "idx_method_caps_composite",
                "idx_cap_mapping_capability",
                "idx_cap_mapping_method",
                "idx_cap_mapping_type",
                "idx_cap_mapping_priority",
            ]

            for index_name in migration_indexes:
                if index_name in DatabaseSchema.INDEXES:
                    await conn.execute(DatabaseSchema.INDEXES[index_name])

    # Agent Management Operations

    async def register_agent(
        self, registration: AgentRegistration
    ) -> AgentRegistration:
        """Register or update an agent in the database."""
        conn = await self._get_connection()
        try:
            await conn.execute("BEGIN TRANSACTION")

            # Insert or update agent record
            await conn.execute(
                """
                INSERT OR REPLACE INTO agents (
                    id, name, namespace, endpoint, status,
                    labels, annotations, created_at, updated_at, resource_version,
                    last_heartbeat, health_interval, config, security_context, dependencies
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    registration.id,
                    registration.name,
                    registration.namespace,
                    registration.endpoint,
                    registration.status,
                    str(registration.labels),
                    str(registration.annotations),
                    registration.created_at.isoformat(),
                    registration.updated_at.isoformat(),
                    registration.resource_version,
                    (
                        registration.last_heartbeat.isoformat()
                        if registration.last_heartbeat
                        else None
                    ),
                    registration.health_interval,
                    str(registration.config),
                    registration.security_context,
                    str(registration.dependencies),
                ),
            )

            # Clear existing capabilities
            await conn.execute(
                "DELETE FROM capabilities WHERE agent_id = ?", (registration.id,)
            )

            # Insert capabilities
            for cap in registration.capabilities:
                await conn.execute(
                    """
                    INSERT INTO capabilities (
                        agent_id, name, description, version, parameters_schema, security_requirements
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        registration.id,
                        cap.name,
                        cap.description,
                        cap.version,
                        str(cap.parameters_schema) if cap.parameters_schema else None,
                        (
                            str(cap.security_requirements)
                            if cap.security_requirements
                            else None
                        ),
                    ),
                )

            # Record event
            await self._record_event(conn, "MODIFIED", registration)

            await conn.commit()
            return registration

        except Exception:
            await conn.rollback()
            raise
        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent from the database."""
        conn = await self._get_connection()
        try:
            # Get agent data for event recording
            async with conn.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return False

            await conn.execute("BEGIN TRANSACTION")

            # Delete agent (cascades to capabilities and health)
            await conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))

            # Record deletion event
            await conn.execute(
                """
                INSERT INTO registry_events (event_type, agent_id, resource_version, data)
                VALUES (?, ?, ?, ?)
            """,
                ("DELETED", agent_id, str(int(time.time() * 1000)), "{}"),
            )

            await conn.commit()
            return True

        except Exception:
            await conn.rollback()
            raise
        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def get_agent(self, agent_id: str) -> AgentRegistration | None:
        """Retrieve an agent by ID."""
        conn = await self._get_connection()
        try:
            async with conn.execute(
                """
                SELECT id, name, namespace, endpoint, status, labels, annotations,
                       created_at, updated_at, resource_version, last_heartbeat,
                       health_interval, config, security_context, dependencies
                FROM agents WHERE id = ?
            """,
                (agent_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None

            # Get capabilities
            capabilities = await self._get_agent_capabilities(conn, agent_id)

            return self._build_agent_registration(row, capabilities)

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def list_agents(
        self,
        namespace: str | None = None,
        status: str | None = None,
        capabilities: list[str] | None = None,
        labels: dict[str, str] | None = None,
    ) -> list[AgentRegistration]:
        """List agents with optional filtering."""
        conn = await self._get_connection()
        try:
            # Build dynamic query
            where_conditions = []
            params = []

            if namespace:
                where_conditions.append("namespace = ?")
                params.append(namespace)

            if status:
                where_conditions.append("status = ?")
                params.append(status)

            # Capability filtering via JOIN
            if capabilities:
                cap_conditions = " OR ".join(["c.name = ?"] * len(capabilities))
                where_conditions.append(
                    f"""
                    id IN (
                        SELECT DISTINCT agent_id FROM capabilities c
                        WHERE {cap_conditions}
                    )
                """
                )
                params.extend(capabilities)

            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

            async with conn.execute(
                f"""
                SELECT DISTINCT id, name, namespace, endpoint, status, labels, annotations,
                       created_at, updated_at, resource_version, last_heartbeat,
                       health_interval, config, security_context, dependencies
                FROM agents WHERE {where_clause}
                ORDER BY updated_at DESC
            """,
                params,
            ) as cursor:
                rows = await cursor.fetchall()

            # Build agent registrations with capabilities
            agents = []
            for row in rows:
                agent_id = row[0]
                capabilities = await self._get_agent_capabilities(conn, agent_id)
                agent = self._build_agent_registration(row, capabilities)

                # Apply label filtering if specified
                if labels and not all(
                    agent.labels.get(k) == v for k, v in labels.items()
                ):
                    continue

                agents.append(agent)

            return agents

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def update_heartbeat(self, agent_id: str) -> bool:
        """Update agent heartbeat timestamp."""
        conn = await self._get_connection()
        try:
            current_time = datetime.now(timezone.utc)
            resource_version = str(int(time.time() * 1000))

            async with conn.execute(
                """
                UPDATE agents
                SET last_heartbeat = ?, status = 'healthy', updated_at = ?, resource_version = ?
                WHERE id = ?
            """,
                (
                    current_time.isoformat(),
                    current_time.isoformat(),
                    resource_version,
                    agent_id,
                ),
            ) as cursor:
                if cursor.rowcount == 0:
                    return False

            # Record health event
            await conn.execute(
                """
                INSERT INTO agent_health (agent_id, status, timestamp, metadata)
                VALUES (?, 'healthy', ?, '{"source": "heartbeat"}')
            """,
                (agent_id, current_time.isoformat()),
            )

            await conn.commit()
            return True

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    # Health Monitoring Operations

    async def get_unhealthy_agents(self, timeout_seconds: int = 60) -> list[str]:
        """Get agents that haven't sent heartbeat within timeout."""
        conn = await self._get_connection()
        try:
            cutoff_time = datetime.now(timezone.utc).timestamp() - timeout_seconds

            async with conn.execute(
                """
                SELECT id FROM agents
                WHERE status = 'healthy'
                AND (last_heartbeat IS NULL OR datetime(last_heartbeat) < datetime(?, 'unixepoch'))
            """,
                (cutoff_time,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def mark_agents_unhealthy(self, agent_ids: list[str]) -> int:
        """Mark multiple agents as unhealthy."""
        if not agent_ids:
            return 0

        conn = await self._get_connection()
        try:
            current_time = datetime.now(timezone.utc)
            resource_version = str(int(time.time() * 1000))

            # Update agents status
            placeholders = ",".join(["?"] * len(agent_ids))
            await conn.execute(
                f"""
                UPDATE agents
                SET status = 'unhealthy', updated_at = ?, resource_version = ?
                WHERE id IN ({placeholders})
            """,
                [current_time.isoformat(), resource_version] + agent_ids,
            )

            # Record health events
            for agent_id in agent_ids:
                await conn.execute(
                    """
                    INSERT INTO agent_health (agent_id, status, timestamp, metadata)
                    VALUES (?, 'unhealthy', ?, '{"source": "timeout"}')
                """,
                    (agent_id, current_time.isoformat()),
                )

            await conn.commit()
            return len(agent_ids)

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    # Capability Discovery Operations

    async def find_agents_by_capability(self, capability_name: str) -> set[str]:
        """Find agent IDs that provide a specific capability."""
        conn = await self._get_connection()
        try:
            async with conn.execute(
                """
                SELECT DISTINCT agent_id FROM capabilities
                WHERE name = ? AND agent_id IN (
                    SELECT id FROM agents WHERE status = 'healthy'
                )
            """,
                (capability_name,),
            ) as cursor:
                rows = await cursor.fetchall()
                return {row[0] for row in rows}

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def get_capability_index(self) -> dict[str, set[str]]:
        """Get complete capability to agent mapping."""
        conn = await self._get_connection()
        try:
            async with conn.execute(
                """
                SELECT c.name, c.agent_id
                FROM capabilities c
                JOIN agents a ON c.agent_id = a.id
                WHERE a.status = 'healthy'
            """
            ) as cursor:
                rows = await cursor.fetchall()

            index = {}
            for capability_name, agent_id in rows:
                if capability_name not in index:
                    index[capability_name] = set()
                index[capability_name].add(agent_id)

            return index

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    # Helper Methods

    async def _get_agent_capabilities(
        self, conn: aiosqlite.Connection, agent_id: str
    ) -> list[AgentCapability]:
        """Get capabilities for an agent."""
        async with conn.execute(
            """
            SELECT name, description, version, parameters_schema, security_requirements
            FROM capabilities WHERE agent_id = ?
        """,
            (agent_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        capabilities = []
        for row in rows:
            capabilities.append(
                AgentCapability(
                    name=row[0],
                    description=row[1],
                    version=row[2] or "1.0.0",
                    parameters_schema=eval(row[3]) if row[3] else None,
                    security_requirements=eval(row[4]) if row[4] else None,
                )
            )

        return capabilities

    def _build_agent_registration(
        self, row: tuple, capabilities: list[AgentCapability]
    ) -> AgentRegistration:
        """Build AgentRegistration from database row."""
        return AgentRegistration(
            id=row[0],
            name=row[1],
            namespace=row[2],
            endpoint=row[3],
            status=row[4],
            labels=eval(row[5]) if row[5] else {},
            annotations=eval(row[6]) if row[6] else {},
            created_at=datetime.fromisoformat(row[7]),
            updated_at=datetime.fromisoformat(row[8]),
            resource_version=row[9],
            last_heartbeat=datetime.fromisoformat(row[10]) if row[10] else None,
            health_interval=row[11],
            config=eval(row[12]) if row[12] else {},
            security_context=row[13],
            dependencies=eval(row[14]) if row[14] else [],
            capabilities=capabilities,
        )

    async def _record_event(
        self,
        conn: aiosqlite.Connection,
        event_type: str,
        registration: AgentRegistration,
    ) -> None:
        """Record a registry event."""
        await conn.execute(
            """
            INSERT INTO registry_events (event_type, agent_id, resource_version, data)
            VALUES (?, ?, ?, ?)
        """,
            (
                event_type,
                registration.id,
                registration.resource_version,
                registration.model_dump_json(),
            ),
        )

    # Statistics and Monitoring

    async def get_database_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        conn = await self._get_connection()
        try:
            stats = {}

            # Agent counts
            async with conn.execute(
                "SELECT status, COUNT(*) FROM agents GROUP BY status"
            ) as cursor:
                stats["agents_by_status"] = dict(await cursor.fetchall())

            # Capability counts
            async with conn.execute(
                "SELECT COUNT(DISTINCT name) FROM capabilities"
            ) as cursor:
                row = await cursor.fetchone()
                stats["unique_capabilities"] = row[0] if row else 0

            # Health events in last hour
            one_hour_ago = datetime.now(timezone.utc).timestamp() - 3600
            async with conn.execute(
                """
                SELECT COUNT(*) FROM agent_health
                WHERE datetime(timestamp) > datetime(?, 'unixepoch')
            """,
                (one_hour_ago,),
            ) as cursor:
                row = await cursor.fetchone()
                stats["health_events_last_hour"] = row[0] if row else 0

            # Database size
            async with conn.execute(
                "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"
            ) as cursor:
                row = await cursor.fetchone()
                stats["database_size_bytes"] = row[0] if row else 0

            return stats

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    # Service Contract Operations

    async def store_service_contract(self, agent_id: str, contract) -> int:
        """Store a service contract for an agent and return contract ID."""

        conn = await self._get_connection()
        try:
            await conn.execute("BEGIN TRANSACTION")

            # Insert or update service contract
            async with conn.execute(
                """
                INSERT OR REPLACE INTO service_contracts (
                    agent_id, service_name, service_version, description,
                    contract_version, compatibility_level, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    contract.service_name,
                    contract.service_version,
                    contract.description,
                    contract.contract_version,
                    contract.compatibility_level,
                    datetime.now(timezone.utc).isoformat(),
                ),
            ) as cursor:
                contract_id = cursor.lastrowid

            # Get contract_id if this was an update
            if not contract_id:
                async with conn.execute(
                    "SELECT id FROM service_contracts WHERE agent_id = ? AND service_name = ? AND service_version = ?",
                    (agent_id, contract.service_name, contract.service_version),
                ) as cursor:
                    row = await cursor.fetchone()
                    contract_id = row[0] if row else None

            if not contract_id:
                raise RuntimeError("Failed to get contract ID")

            # Clear existing method metadata for this contract
            await conn.execute(
                "DELETE FROM method_metadata WHERE contract_id = ?", (contract_id,)
            )

            # Store method metadata
            for _method_name, method_metadata in contract.methods.items():
                await self._store_method_metadata(conn, contract_id, method_metadata)

            await conn.commit()
            return contract_id

        except Exception:
            await conn.rollback()
            raise
        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def _store_method_metadata(
        self, conn: aiosqlite.Connection, contract_id: int, method
    ) -> int:
        """Store method metadata and return method ID."""
        import json

        # Serialize signature data
        signature_data = json.dumps(
            {
                "parameters": {
                    name: {
                        "annotation": str(param.annotation),
                        "default": (
                            str(param.default) if param.default != param.empty else None
                        ),
                        "kind": param.kind.name,
                    }
                    for name, param in method.signature.parameters.items()
                },
                "return_annotation": str(method.signature.return_annotation),
            }
        )

        # Insert method metadata
        async with conn.execute(
            """
            INSERT INTO method_metadata (
                contract_id, method_name, signature_data, return_type, is_async,
                method_type, docstring, service_version, stability_level,
                deprecation_warning, expected_complexity, timeout_hint,
                resource_requirements, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contract_id,
                method.method_name,
                signature_data,
                self._serialize_type(method.return_type),
                method.is_async,
                method.method_type.value,
                method.docstring,
                method.service_version,
                method.stability_level,
                method.deprecation_warning,
                method.expected_complexity,
                method.timeout_hint,
                json.dumps(method.resource_requirements),
                datetime.now(timezone.utc).isoformat(),
            ),
        ) as cursor:
            method_id = cursor.lastrowid

        if not method_id:
            raise RuntimeError("Failed to get method ID")

        # Store method parameters
        position = 0
        for param_name, param_metadata in method.parameter_metadata.items():
            await conn.execute(
                """
                INSERT INTO method_parameters (
                    method_id, parameter_name, parameter_type, parameter_kind,
                    default_value, annotation, has_default, is_optional, position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    method_id,
                    param_name,
                    self._serialize_type(param_metadata.type_hint),
                    param_metadata.kind.value,
                    (
                        json.dumps(param_metadata.default)
                        if param_metadata.has_default
                        else None
                    ),
                    self._serialize_type(param_metadata.annotation),
                    param_metadata.has_default,
                    param_metadata.is_optional,
                    position,
                ),
            )
            position += 1

        # Store method capabilities
        for capability in method.capabilities:
            # Try to link to existing capability
            async with conn.execute(
                "SELECT id FROM capabilities WHERE name = ?", (capability,)
            ) as cursor:
                row = await cursor.fetchone()
                capability_id = row[0] if row else None

            await conn.execute(
                """
                INSERT INTO method_capabilities (
                    method_id, capability_name, capability_id
                ) VALUES (?, ?, ?)
                """,
                (method_id, capability, capability_id),
            )

        return method_id

    async def get_service_contract(self, agent_id: str, service_name: str):
        """Retrieve a service contract for an agent."""
        import inspect
        import json

        from mcp_mesh import (
            MethodMetadata,
            MethodType,
            ServiceContract,
        )

        conn = await self._get_connection()
        try:
            # Get contract basic info
            async with conn.execute(
                """
                SELECT id, service_name, service_version, description, contract_version, compatibility_level
                FROM service_contracts
                WHERE agent_id = ? AND service_name = ?
                """,
                (agent_id, service_name),
            ) as cursor:
                contract_row = await cursor.fetchone()
                if not contract_row:
                    return None

            (
                contract_id,
                service_name,
                service_version,
                description,
                contract_version,
                compatibility_level,
            ) = contract_row

            # Get methods for this contract
            async with conn.execute(
                """
                SELECT id, method_name, signature_data, return_type, is_async, method_type,
                       docstring, service_version, stability_level, deprecation_warning,
                       expected_complexity, timeout_hint, resource_requirements
                FROM method_metadata WHERE contract_id = ?
                """,
                (contract_id,),
            ) as cursor:
                method_rows = await cursor.fetchall()

            # Build methods dictionary
            methods = {}
            contract_capabilities = []

            for method_row in method_rows:
                method_id = method_row[0]
                method_name = method_row[1]

                # Get method parameters
                parameters = await self._get_method_parameters(conn, method_id)

                # Get method capabilities
                capabilities = await self._get_method_capabilities(conn, method_id)
                contract_capabilities.extend(capabilities)

                # Reconstruct signature
                signature_data = json.loads(method_row[2])
                sig_params = []
                for param_name, param_info in signature_data["parameters"].items():
                    param_metadata = parameters.get(param_name)
                    if param_metadata:
                        param = inspect.Parameter(
                            name=param_name,
                            kind=getattr(inspect.Parameter, param_info["kind"]),
                            default=(
                                inspect.Parameter.empty
                                if not param_metadata.has_default
                                else param_metadata.default
                            ),
                            annotation=param_metadata.type_hint,
                        )
                        sig_params.append(param)

                signature = inspect.Signature(parameters=sig_params)

                # Create MethodMetadata
                method_metadata = MethodMetadata(
                    method_name=method_name,
                    signature=signature,
                    capabilities=capabilities,
                    return_type=(
                        self._deserialize_type(method_row[3])
                        if method_row[3]
                        else type(None)
                    ),
                    parameters={name: pm.type_hint for name, pm in parameters.items()},
                    type_hints={name: pm.type_hint for name, pm in parameters.items()},
                    parameter_metadata=parameters,
                    method_type=MethodType(method_row[5]),
                    is_async=bool(method_row[4]),
                    docstring=method_row[6] or "",
                    service_version=method_row[7] or "1.0.0",
                    stability_level=method_row[8] or "stable",
                    deprecation_warning=method_row[9] or "",
                    expected_complexity=method_row[10] or "O(1)",
                    timeout_hint=method_row[11] or 30,
                    resource_requirements=(
                        json.loads(method_row[12]) if method_row[12] else {}
                    ),
                )

                methods[method_name] = method_metadata

            # Create ServiceContract
            return ServiceContract(
                service_name=service_name,
                service_version=service_version,
                methods=methods,
                capabilities=list(set(contract_capabilities)),
                description=description or "",
                contract_version=contract_version,
                compatibility_level=compatibility_level,
            )

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def _get_method_parameters(self, conn: aiosqlite.Connection, method_id: int):
        """Get parameters for a method."""
        import inspect
        import json

        from mcp_mesh import ParameterKind, ParameterMetadata

        async with conn.execute(
            """
            SELECT parameter_name, parameter_type, parameter_kind, default_value,
                   annotation, has_default, is_optional
            FROM method_parameters
            WHERE method_id = ?
            ORDER BY position
            """,
            (method_id,),
        ) as cursor:
            param_rows = await cursor.fetchall()

        parameters = {}
        for row in param_rows:
            (
                param_name,
                param_type,
                param_kind,
                default_value,
                annotation,
                has_default,
                is_optional,
            ) = row

            parameters[param_name] = ParameterMetadata(
                name=param_name,
                type_hint=(
                    self._deserialize_type(param_type) if param_type else type(None)
                ),
                kind=ParameterKind(param_kind),
                default=(
                    json.loads(default_value)
                    if default_value
                    else inspect.Parameter.empty
                ),
                annotation=(
                    self._deserialize_type(annotation)
                    if annotation
                    else inspect.Parameter.empty
                ),
                has_default=bool(has_default),
                is_optional=bool(is_optional),
            )

        return parameters

    async def _get_method_capabilities(
        self, conn: aiosqlite.Connection, method_id: int
    ) -> list[str]:
        """Get capabilities for a method."""
        async with conn.execute(
            "SELECT capability_name FROM method_capabilities WHERE method_id = ?",
            (method_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        return [row[0] for row in rows]

    async def find_methods_by_capability(
        self, capability_name: str, agent_status: str = "healthy"
    ) -> list[dict]:
        """Find methods that provide a specific capability."""
        conn = await self._get_connection()
        try:
            async with conn.execute(
                """
                SELECT DISTINCT
                    a.id as agent_id, a.name as agent_name, a.endpoint,
                    sc.service_name, sc.service_version,
                    mm.method_name, mm.stability_level, mm.timeout_hint
                FROM method_capabilities mc
                JOIN method_metadata mm ON mc.method_id = mm.id
                JOIN service_contracts sc ON mm.contract_id = sc.id
                JOIN agents a ON sc.agent_id = a.id
                WHERE mc.capability_name = ? AND a.status = ?
                ORDER BY mm.stability_level DESC, a.updated_at DESC
                """,
                (capability_name, agent_status),
            ) as cursor:
                rows = await cursor.fetchall()

            results = []
            for row in rows:
                results.append(
                    {
                        "agent_id": row[0],
                        "agent_name": row[1],
                        "endpoint": row[2],
                        "service_name": row[3],
                        "service_version": row[4],
                        "method_name": row[5],
                        "stability_level": row[6],
                        "timeout_hint": row[7],
                    }
                )

            return results

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def update_capability_method_mapping(
        self,
        capability_id: int,
        method_id: int,
        mapping_type: str = "direct",
        priority: int = 0,
    ) -> None:
        """Create or update capability-to-method mapping."""
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT OR REPLACE INTO capability_method_mapping (
                    capability_id, method_id, mapping_type, priority, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    capability_id,
                    method_id,
                    mapping_type,
                    priority,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await conn.commit()

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown

    async def get_contract_compatibility_info(
        self, service_name: str, version_constraint: str | None = None
    ) -> list[dict]:
        """Get contract compatibility information for version checking."""
        conn = await self._get_connection()
        try:
            query = """
                SELECT DISTINCT
                    sc.agent_id, sc.service_name, sc.service_version,
                    sc.contract_version, sc.compatibility_level,
                    a.name as agent_name, a.status
                FROM service_contracts sc
                JOIN agents a ON sc.agent_id = a.id
                WHERE sc.service_name = ?
            """
            params = [service_name]

            if version_constraint:
                # Simple version filtering - can be enhanced with proper semver logic
                query += " AND sc.service_version = ?"
                params.append(version_constraint)

            query += " ORDER BY sc.service_version DESC"

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()

            results = []
            for row in rows:
                results.append(
                    {
                        "agent_id": row[0],
                        "service_name": row[1],
                        "service_version": row[2],
                        "contract_version": row[3],
                        "compatibility_level": row[4],
                        "agent_name": row[5],
                        "agent_status": row[6],
                    }
                )

            return results

        finally:
            await self._return_connection(conn)

    def _serialize_type(self, type_obj) -> str:
        """Safely serialize a type object to string."""
        if type_obj is None or type_obj == type(None):
            return "NoneType"
        elif hasattr(type_obj, "__name__"):
            return type_obj.__name__
        else:
            return str(type_obj)

    def _deserialize_type(self, type_str: str):
        """Safely deserialize a type string back to type object."""
        if not type_str or type_str == "NoneType":
            return type(None)

        # Handle basic built-in types
        type_mapping = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bytes": bytes,
            "Any": type(None),  # Fallback for Any type
        }

        return type_mapping.get(type_str, str)  # Default to str if unknown
