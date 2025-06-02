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
    SCHEMA_VERSION = 1

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
            for table_name, sql in DatabaseSchema.SCHEMA_SQL.items():
                await conn.execute(sql)

            # Create all indexes
            for index_name, sql in DatabaseSchema.INDEXES.items():
                await conn.execute(sql)

            await conn.commit()
        finally:
            await self._return_connection(conn)

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
                await conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                    (DatabaseSchema.SCHEMA_VERSION,),
                )
                await conn.commit()
        finally:
            await self._return_connection(conn)

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
