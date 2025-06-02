"""Agent versioning types and interfaces for MCP Mesh."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class DeploymentStatus(Enum):
    """Status of an agent deployment."""

    PENDING = "pending"
    DEPLOYING = "deploying"
    ACTIVE = "active"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    DEPRECATED = "deprecated"


@dataclass
class SemanticVersion:
    """Semantic version following MAJOR.MINOR.PATCH format."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None

    def __str__(self) -> str:
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            version += f"-{self.prerelease}"
        if self.build:
            version += f"+{self.build}"
        return version

    def __eq__(self, other) -> bool:
        if not isinstance(other, SemanticVersion):
            return False
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
            and self.prerelease == other.prerelease
        )

    def __lt__(self, other) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented

        # Compare major.minor.patch
        if (self.major, self.minor, self.patch) != (
            other.major,
            other.minor,
            other.patch,
        ):
            return (self.major, self.minor, self.patch) < (
                other.major,
                other.minor,
                other.patch,
            )

        # Handle prerelease comparison
        if self.prerelease is None and other.prerelease is None:
            return False
        if self.prerelease is None:
            return False  # Normal version > prerelease
        if other.prerelease is None:
            return True  # Prerelease < normal version

        return self.prerelease < other.prerelease

    def __le__(self, other) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return self < other or self == other

    def __gt__(self, other) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return not (self <= other)

    def __ge__(self, other) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return not (self < other)


@dataclass
class AgentVersionInfo:
    """Information about a specific agent version."""

    agent_id: str
    version: SemanticVersion
    created_at: datetime
    created_by: str
    description: str | None = None
    changelog: str | None = None
    metadata: dict[str, str] | None = None

    @property
    def version_string(self) -> str:
        """Get the version as a string."""
        return str(self.version)


@dataclass
class DeploymentInfo:
    """Information about an agent deployment."""

    deployment_id: str
    agent_id: str
    version: SemanticVersion
    status: DeploymentStatus
    deployed_at: datetime
    deployed_by: str
    environment: str
    rollback_version: SemanticVersion | None = None
    error_message: str | None = None
    metadata: dict[str, str] | None = None

    @property
    def version_string(self) -> str:
        """Get the version as a string."""
        return str(self.version)


@dataclass
class DeploymentResult:
    """Result of a deployment operation."""

    success: bool
    deployment_id: str | None = None
    error_message: str | None = None
    deployment_info: DeploymentInfo | None = None


@dataclass
class RollbackInfo:
    """Information about a rollback operation."""

    rollback_id: str
    agent_id: str
    from_version: SemanticVersion
    to_version: SemanticVersion
    initiated_at: datetime
    initiated_by: str
    reason: str | None = None
    status: DeploymentStatus = DeploymentStatus.PENDING


class VersioningProtocol(Protocol):
    """Protocol for agent versioning operations."""

    async def get_agent_versions(self, agent_id: str) -> list[AgentVersionInfo]:
        """Get all versions for an agent."""
        ...

    async def get_agent_version(
        self, agent_id: str, version: str | SemanticVersion
    ) -> AgentVersionInfo | None:
        """Get specific version information for an agent."""
        ...

    async def create_agent_version(
        self,
        agent_id: str,
        version: str | SemanticVersion,
        description: str | None = None,
        changelog: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AgentVersionInfo:
        """Create a new agent version."""
        ...

    async def deploy_agent_version(
        self,
        agent_id: str,
        version: str | SemanticVersion,
        environment: str = "production",
    ) -> DeploymentResult:
        """Deploy a specific agent version."""
        ...

    async def get_deployment_history(self, agent_id: str) -> list[DeploymentInfo]:
        """Get deployment history for an agent."""
        ...

    async def get_active_deployment(
        self, agent_id: str, environment: str = "production"
    ) -> DeploymentInfo | None:
        """Get the currently active deployment for an agent."""
        ...

    async def rollback_deployment(
        self,
        agent_id: str,
        to_version: str | SemanticVersion,
        reason: str | None = None,
        environment: str = "production",
    ) -> DeploymentResult:
        """Rollback to a previous agent version."""
        ...


class VersionComparisonProtocol(Protocol):
    """Protocol for version comparison operations."""

    def parse_version(self, version_string: str) -> SemanticVersion:
        """Parse a version string into a SemanticVersion."""
        ...

    def compare_versions(
        self,
        version1: str | SemanticVersion,
        version2: str | SemanticVersion,
    ) -> int:
        """Compare two versions. Returns -1, 0, or 1."""
        ...

    def is_compatible(
        self,
        required_version: str | SemanticVersion,
        available_version: str | SemanticVersion,
    ) -> bool:
        """Check if versions are compatible based on semantic versioning rules."""
        ...

    def get_latest_version(
        self, versions: list[str | SemanticVersion]
    ) -> SemanticVersion | None:
        """Get the latest version from a list of versions."""
        ...
