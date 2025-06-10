"""Agent versioning implementation for MCP Mesh."""

import re
from datetime import datetime

import aiosqlite

from mcp_mesh import (
    AgentVersionInfo,
    DeploymentInfo,
    DeploymentResult,
    DeploymentStatus,
    SemanticVersion,
    VersionComparisonProtocol,
    VersioningProtocol,
)


class VersionParser:
    """Parser for semantic version strings."""

    VERSION_PATTERN = re.compile(
        r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
        r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
        r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
        r"(?:\+(?P<build>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
    )

    @classmethod
    def parse(cls, version_string: str) -> SemanticVersion:
        """Parse a semantic version string."""
        match = cls.VERSION_PATTERN.match(version_string)
        if not match:
            raise ValueError(f"Invalid semantic version: {version_string}")

        return SemanticVersion(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=match.group("prerelease"),
            build=match.group("build"),
        )


class VersionComparison:
    """Version comparison utilities."""

    @staticmethod
    def compare_versions(
        version1: str | SemanticVersion, version2: str | SemanticVersion
    ) -> int:
        """Compare two versions. Returns -1 if v1 < v2, 0 if equal, 1 if v1 > v2."""
        v1 = (
            version1
            if isinstance(version1, SemanticVersion)
            else VersionParser.parse(version1)
        )
        v2 = (
            version2
            if isinstance(version2, SemanticVersion)
            else VersionParser.parse(version2)
        )

        if v1 < v2:
            return -1
        elif v1 == v2:
            return 0
        else:
            return 1

    @staticmethod
    def is_compatible(
        required_version: str | SemanticVersion,
        available_version: str | SemanticVersion,
    ) -> bool:
        """Check if versions are compatible based on semantic versioning rules."""
        req = (
            required_version
            if isinstance(required_version, SemanticVersion)
            else VersionParser.parse(required_version)
        )
        avail = (
            available_version
            if isinstance(available_version, SemanticVersion)
            else VersionParser.parse(available_version)
        )

        # Same major version and available version >= required version
        return req.major == avail.major and avail >= req

    @staticmethod
    def get_latest_version(
        versions: list[str | SemanticVersion],
    ) -> SemanticVersion | None:
        """Get the latest version from a list of versions."""
        if not versions:
            return None

        parsed_versions = []
        for v in versions:
            if isinstance(v, str):
                parsed_versions.append(VersionParser.parse(v))
            else:
                parsed_versions.append(v)

        return max(parsed_versions)


class DatabaseVersionManager:
    """Database-backed version management."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path

    async def initialize_db(self, db=None):
        """Initialize the versioning database schema."""
        if db is None:
            async with aiosqlite.connect(self.db_path) as db:
                await self._create_tables(db)
        else:
            await self._create_tables(db)

    async def _create_tables(self, db):
        """Create database tables."""
        await db.execute(
            """
                CREATE TABLE IF NOT EXISTS agent_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    major INTEGER NOT NULL,
                    minor INTEGER NOT NULL,
                    patch INTEGER NOT NULL,
                    prerelease TEXT,
                    build_metadata TEXT,
                    created_at TIMESTAMP NOT NULL,
                    created_by TEXT NOT NULL,
                    description TEXT,
                    changelog TEXT,
                    metadata TEXT,
                    UNIQUE(agent_id, major, minor, patch, prerelease)
                )
            """
        )

        await db.execute(
            """
                CREATE TABLE IF NOT EXISTS deployments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deployment_id TEXT UNIQUE NOT NULL,
                    agent_id TEXT NOT NULL,
                    major INTEGER NOT NULL,
                    minor INTEGER NOT NULL,
                    patch INTEGER NOT NULL,
                    prerelease TEXT,
                    status TEXT NOT NULL,
                    deployed_at TIMESTAMP NOT NULL,
                    deployed_by TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    rollback_major INTEGER,
                    rollback_minor INTEGER,
                    rollback_patch INTEGER,
                    rollback_prerelease TEXT,
                    error_message TEXT,
                    metadata TEXT
                )
            """
        )

        await db.execute(
            """
                CREATE TABLE IF NOT EXISTS rollbacks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rollback_id TEXT UNIQUE NOT NULL,
                    agent_id TEXT NOT NULL,
                    from_major INTEGER NOT NULL,
                    from_minor INTEGER NOT NULL,
                    from_patch INTEGER NOT NULL,
                    from_prerelease TEXT,
                    to_major INTEGER NOT NULL,
                    to_minor INTEGER NOT NULL,
                    to_patch INTEGER NOT NULL,
                    to_prerelease TEXT,
                    initiated_at TIMESTAMP NOT NULL,
                    initiated_by TEXT NOT NULL,
                    reason TEXT,
                    status TEXT NOT NULL
                )
            """
        )

        await db.commit()

    def _version_to_dict(self, version: SemanticVersion) -> dict[str, int | str | None]:
        """Convert SemanticVersion to database dictionary."""
        return {
            "major": version.major,
            "minor": version.minor,
            "patch": version.patch,
            "prerelease": version.prerelease,
        }

    def _dict_to_version(self, data: dict[str, int | str | None]) -> SemanticVersion:
        """Convert database dictionary to SemanticVersion."""
        return SemanticVersion(
            major=data["major"],
            minor=data["minor"],
            patch=data["patch"],
            prerelease=data["prerelease"],
        )


class AgentVersionManager(VersioningProtocol, VersionComparisonProtocol):
    """Complete agent versioning manager."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_manager = DatabaseVersionManager(db_path)
        self.comparison = VersionComparison()

    async def initialize(self):
        """Initialize the version manager."""
        await self.db_manager.initialize_db()

    def parse_version(self, version_string: str) -> SemanticVersion:
        """Parse a version string into a SemanticVersion."""
        return VersionParser.parse(version_string)

    def compare_versions(
        self,
        version1: str | SemanticVersion,
        version2: str | SemanticVersion,
    ) -> int:
        """Compare two versions. Returns -1, 0, or 1."""
        return self.comparison.compare_versions(version1, version2)

    def is_compatible(
        self,
        required_version: str | SemanticVersion,
        available_version: str | SemanticVersion,
    ) -> bool:
        """Check if versions are compatible based on semantic versioning rules."""
        return self.comparison.is_compatible(required_version, available_version)

    def get_latest_version(
        self, versions: list[str | SemanticVersion]
    ) -> SemanticVersion | None:
        """Get the latest version from a list of versions."""
        return self.comparison.get_latest_version(versions)

    async def get_agent_versions(self, agent_id: str) -> list[AgentVersionInfo]:
        """Get all versions for an agent."""
        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await self.db_manager.initialize_db(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM agent_versions
                WHERE agent_id = ?
                ORDER BY major DESC, minor DESC, patch DESC, created_at DESC
            """,
                (agent_id,),
            )
            rows = await cursor.fetchall()

            versions = []
            for row in rows:
                version = SemanticVersion(
                    major=row["major"],
                    minor=row["minor"],
                    patch=row["patch"],
                    prerelease=row["prerelease"],
                    build=row["build_metadata"],
                )

                versions.append(
                    AgentVersionInfo(
                        agent_id=row["agent_id"],
                        version=version,
                        created_at=datetime.fromisoformat(row["created_at"]),
                        created_by=row["created_by"],
                        description=row["description"],
                        changelog=row["changelog"],
                        metadata=eval(row["metadata"]) if row["metadata"] else None,
                    )
                )

            return versions

    async def get_agent_version(
        self, agent_id: str, version: str | SemanticVersion
    ) -> AgentVersionInfo | None:
        """Get specific version information for an agent."""
        if isinstance(version, str):
            version = self.parse_version(version)

        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await self.db_manager.initialize_db(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM agent_versions
                WHERE agent_id = ? AND major = ? AND minor = ? AND patch = ? AND prerelease = ?
            """,
                (
                    agent_id,
                    version.major,
                    version.minor,
                    version.patch,
                    version.prerelease,
                ),
            )
            row = await cursor.fetchone()

            if not row:
                return None

            version_obj = SemanticVersion(
                major=row["major"],
                minor=row["minor"],
                patch=row["patch"],
                prerelease=row["prerelease"],
                build=row["build_metadata"],
            )

            return AgentVersionInfo(
                agent_id=row["agent_id"],
                version=version_obj,
                created_at=datetime.fromisoformat(row["created_at"]),
                created_by=row["created_by"],
                description=row["description"],
                changelog=row["changelog"],
                metadata=eval(row["metadata"]) if row["metadata"] else None,
            )

    async def create_agent_version(
        self,
        agent_id: str,
        version: str | SemanticVersion,
        description: str | None = None,
        changelog: str | None = None,
        metadata: dict[str, str] | None = None,
        created_by: str = "system",
    ) -> AgentVersionInfo:
        """Create a new agent version."""
        if isinstance(version, str):
            version = self.parse_version(version)

        created_at = datetime.now()

        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await self.db_manager.initialize_db(db)
            await db.execute(
                """
                INSERT INTO agent_versions
                (agent_id, major, minor, patch, prerelease, build_metadata, created_at, created_by, description, changelog, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    agent_id,
                    version.major,
                    version.minor,
                    version.patch,
                    version.prerelease,
                    version.build,
                    created_at.isoformat(),
                    created_by,
                    description,
                    changelog,
                    str(metadata) if metadata else None,
                ),
            )
            await db.commit()

        return AgentVersionInfo(
            agent_id=agent_id,
            version=version,
            created_at=created_at,
            created_by=created_by,
            description=description,
            changelog=changelog,
            metadata=metadata,
        )

    async def deploy_agent_version(
        self,
        agent_id: str,
        version: str | SemanticVersion,
        environment: str = "production",
        deployed_by: str = "system",
    ) -> DeploymentResult:
        """Deploy a specific agent version."""
        if isinstance(version, str):
            version = self.parse_version(version)

        # Check if version exists
        version_info = await self.get_agent_version(agent_id, version)
        if not version_info:
            return DeploymentResult(
                success=False,
                error_message=f"Version {version} not found for agent {agent_id}",
            )

        deployment_id = (
            f"{agent_id}-{version}-{environment}-{int(datetime.now().timestamp())}"
        )
        deployed_at = datetime.now()

        try:
            async with aiosqlite.connect(self.db_manager.db_path) as db:
                await self.db_manager.initialize_db(db)
                # Mark previous deployments as deprecated for this environment
                await db.execute(
                    """
                    UPDATE deployments
                    SET status = ?
                    WHERE agent_id = ? AND environment = ? AND status = ?
                """,
                    (
                        DeploymentStatus.DEPRECATED.value,
                        agent_id,
                        environment,
                        DeploymentStatus.ACTIVE.value,
                    ),
                )

                # Create new deployment
                await db.execute(
                    """
                    INSERT INTO deployments
                    (deployment_id, agent_id, major, minor, patch, prerelease, status, deployed_at, deployed_by, environment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        deployment_id,
                        agent_id,
                        version.major,
                        version.minor,
                        version.patch,
                        version.prerelease,
                        DeploymentStatus.ACTIVE.value,
                        deployed_at.isoformat(),
                        deployed_by,
                        environment,
                    ),
                )
                await db.commit()

            deployment_info = DeploymentInfo(
                deployment_id=deployment_id,
                agent_id=agent_id,
                version=version,
                status=DeploymentStatus.ACTIVE,
                deployed_at=deployed_at,
                deployed_by=deployed_by,
                environment=environment,
            )

            return DeploymentResult(
                success=True,
                deployment_id=deployment_id,
                deployment_info=deployment_info,
            )

        except Exception as e:
            return DeploymentResult(success=False, error_message=str(e))

    async def get_deployment_history(self, agent_id: str) -> list[DeploymentInfo]:
        """Get deployment history for an agent."""
        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await self.db_manager.initialize_db(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM deployments
                WHERE agent_id = ?
                ORDER BY deployed_at DESC
            """,
                (agent_id,),
            )
            rows = await cursor.fetchall()

            deployments = []
            for row in rows:
                version = SemanticVersion(
                    major=row["major"],
                    minor=row["minor"],
                    patch=row["patch"],
                    prerelease=row["prerelease"],
                )

                rollback_version = None
                if row["rollback_major"] is not None:
                    rollback_version = SemanticVersion(
                        major=row["rollback_major"],
                        minor=row["rollback_minor"],
                        patch=row["rollback_patch"],
                        prerelease=row["rollback_prerelease"],
                    )

                deployments.append(
                    DeploymentInfo(
                        deployment_id=row["deployment_id"],
                        agent_id=row["agent_id"],
                        version=version,
                        status=DeploymentStatus(row["status"]),
                        deployed_at=datetime.fromisoformat(row["deployed_at"]),
                        deployed_by=row["deployed_by"],
                        environment=row["environment"],
                        rollback_version=rollback_version,
                        error_message=row["error_message"],
                        metadata=eval(row["metadata"]) if row["metadata"] else None,
                    )
                )

            return deployments

    async def get_active_deployment(
        self, agent_id: str, environment: str = "production"
    ) -> DeploymentInfo | None:
        """Get the currently active deployment for an agent."""
        async with aiosqlite.connect(self.db_manager.db_path) as db:
            await self.db_manager.initialize_db(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM deployments
                WHERE agent_id = ? AND environment = ? AND status = ?
                ORDER BY deployed_at DESC
                LIMIT 1
            """,
                (agent_id, environment, DeploymentStatus.ACTIVE.value),
            )
            row = await cursor.fetchone()

            if not row:
                return None

            version = SemanticVersion(
                major=row["major"],
                minor=row["minor"],
                patch=row["patch"],
                prerelease=row["prerelease"],
            )

            return DeploymentInfo(
                deployment_id=row["deployment_id"],
                agent_id=row["agent_id"],
                version=version,
                status=DeploymentStatus(row["status"]),
                deployed_at=datetime.fromisoformat(row["deployed_at"]),
                deployed_by=row["deployed_by"],
                environment=row["environment"],
                error_message=row["error_message"],
                metadata=eval(row["metadata"]) if row["metadata"] else None,
            )

    async def rollback_deployment(
        self,
        agent_id: str,
        to_version: str | SemanticVersion,
        reason: str | None = None,
        environment: str = "production",
        initiated_by: str = "system",
    ) -> DeploymentResult:
        """Rollback to a previous agent version."""
        if isinstance(to_version, str):
            to_version = self.parse_version(to_version)

        # Get current deployment
        current_deployment = await self.get_active_deployment(agent_id, environment)
        if not current_deployment:
            return DeploymentResult(
                success=False,
                error_message=f"No active deployment found for agent {agent_id} in {environment}",
            )

        # Check if target version exists
        target_version_info = await self.get_agent_version(agent_id, to_version)
        if not target_version_info:
            return DeploymentResult(
                success=False,
                error_message=f"Target version {to_version} not found for agent {agent_id}",
            )

        try:
            # Create rollback record
            rollback_id = (
                f"rb-{agent_id}-{to_version}-{int(datetime.now().timestamp())}"
            )
            initiated_at = datetime.now()

            async with aiosqlite.connect(self.db_manager.db_path) as db:
                await self.db_manager.initialize_db(db)
                # Record the rollback
                await db.execute(
                    """
                    INSERT INTO rollbacks
                    (rollback_id, agent_id, from_major, from_minor, from_patch, from_prerelease,
                     to_major, to_minor, to_patch, to_prerelease, initiated_at, initiated_by, reason, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        rollback_id,
                        agent_id,
                        current_deployment.version.major,
                        current_deployment.version.minor,
                        current_deployment.version.patch,
                        current_deployment.version.prerelease,
                        to_version.major,
                        to_version.minor,
                        to_version.patch,
                        to_version.prerelease,
                        initiated_at.isoformat(),
                        initiated_by,
                        reason,
                        DeploymentStatus.ACTIVE.value,
                    ),
                )

                # Mark current deployment as rolled back
                await db.execute(
                    """
                    UPDATE deployments
                    SET status = ?, rollback_major = ?, rollback_minor = ?, rollback_patch = ?, rollback_prerelease = ?
                    WHERE deployment_id = ?
                """,
                    (
                        DeploymentStatus.ROLLED_BACK.value,
                        to_version.major,
                        to_version.minor,
                        to_version.patch,
                        to_version.prerelease,
                        current_deployment.deployment_id,
                    ),
                )

                await db.commit()

            # Deploy the rollback version
            return await self.deploy_agent_version(
                agent_id, to_version, environment, initiated_by
            )

        except Exception as e:
            return DeploymentResult(
                success=False, error_message=f"Rollback failed: {str(e)}"
            )
