"""MCP Mesh - Python runtime for Model Context Protocol service mesh."""

import os
import sys

# Type alias for mesh agent proxy injections - use Any for Pydantic compatibility
from typing import Any

# Import all the existing exports
from .agent_selection import (
    AgentHealthInfo,
    AgentSelectionProtocol,
    AgentSelectionResult,
    HealthMonitoringProtocol,
    HealthStatus,
    SelectionAlgorithm,
    SelectionAlgorithmProtocol,
    SelectionCriteria,
    SelectionState,
    SelectionWeights,
    WeightUpdateRequest,
    WeightUpdateResult,
)
from .configuration import (
    ConfigurationError,
    ConfigurationProvider,
    DatabaseConfig,
    DatabaseType,
    EnvironmentConfigProvider,
    InvalidConfigurationError,
    LogLevel,
    MissingConfigurationError,
    MonitoringConfig,
    PerformanceConfig,
    RegistryConfig,
    RegistryMode,
    SecurityConfig,
    SecurityMode,
    ServerConfig,
    ServiceDiscoveryConfig,
)
from .decorator_registry import (
    DecoratedFunction,
    DecoratorRegistry,
    clear_decorator_registry,
    get_all_mesh_agents,
    get_decorator_stats,
)
from .fallback import (
    DependencyResolver,
    FallbackChainInterface,
    FallbackConfiguration,
    FallbackMetrics,
    FallbackMode,
    FallbackMonitor,
    FallbackReason,
    FallbackResult,
    LocalInstanceResolver,
    RemoteProxyResolver,
)
from .lifecycle import (
    AgentInfo,
    DeregistrationResult,
    DrainResult,
    HealthTransitionTrigger,
    LifecycleConfiguration,
    LifecycleEvent,
    LifecycleEventData,
    LifecycleEventProtocol,
    LifecycleProtocol,
    LifecycleStatus,
    LifecycleTransition,
    RegistrationResult,
)
from .method_metadata import (
    MethodMetadata,
    MethodType,
    ParameterKind,
    ParameterMetadata,
    ServiceContract,
)
from .service_discovery import (
    AgentMatch,
    CapabilityHierarchy,
    CapabilityMatchingProtocol,
    CapabilityMetadata,
    CapabilityQuery,
    CompatibilityScore,
    MatchingStrategy,
    MeshAgentMetadata,
    QueryOperator,
    Requirements,
    ServiceDiscoveryProtocol,
)
from .service_proxy import (
    MeshServiceProxyInterface,
    ProxyGenerationError,
    RemoteInvocationError,
    ServiceContractError,
    ServiceProxyProtocol,
)

# Old mesh_agent decorator has been replaced by mesh.tool and mesh.agent
# Import mesh.tool and mesh.agent instead
from .shared.exceptions import PermissionDeniedError, SecurityValidationError
from .types import McpMeshAgent
from .unified_dependencies import (
    DependencyAnalyzer,
    DependencyContext,
    DependencyList,
    DependencyMap,
    DependencyPattern,
    DependencyResolutionResult,
    DependencySpecification,
    DependencyValidationError,
    DependencyValidator,
    UnifiedDependencyResolver,
    ValidationResult,
)
from .versioning import (
    AgentVersionInfo,
    DeploymentInfo,
    DeploymentResult,
    DeploymentStatus,
    RollbackInfo,
    SemanticVersion,
    VersionComparisonProtocol,
    VersioningProtocol,
)

__version__ = "0.1.1"

# Store reference to runtime processor if initialized
_runtime_processor = None


def initialize_runtime():
    """Initialize the MCP Mesh runtime processor."""
    global _runtime_processor

    if _runtime_processor is not None:
        return  # Already initialized

    try:
        from .engine.fastmcp_integration import patch_fastmcp
        from .engine.processor import DecoratorProcessor

        # Patch FastMCP FIRST before any decorators are used
        patch_fastmcp()

        # Create and start the processor
        _runtime_processor = DecoratorProcessor()
        _runtime_processor.start()

        # Enhance the new mesh decorators
        try:
            import mesh.decorators

            if hasattr(mesh.decorators, "_enhance_mesh_decorators"):
                mesh.decorators._enhance_mesh_decorators(_runtime_processor)
        except ImportError:
            # mesh module not available - skip enhancement
            pass

        sys.stderr.write("MCP Mesh runtime initialized\n")
    except Exception as e:
        # Log but don't fail - allows graceful degradation
        sys.stderr.write(f"MCP Mesh runtime initialization failed: {e}\n")


# Auto-initialize runtime if enabled
if os.getenv("MCP_MESH_ENABLED", "true").lower() == "true":
    initialize_runtime()


__all__ = [
    # mesh_agent has been removed - use mesh.tool and mesh.agent instead
    "McpMeshAgent",
    "initialize_runtime",
    "DecoratedFunction",
    "DecoratorRegistry",
    "clear_decorator_registry",
    "get_all_mesh_agents",
    "get_decorator_stats",
    "SecurityValidationError",
    "PermissionDeniedError",
    # Fallback chain (CRITICAL FEATURE)
    "FallbackChainInterface",
    "FallbackConfiguration",
    "FallbackMetrics",
    "FallbackMode",
    "FallbackMonitor",
    "FallbackReason",
    "FallbackResult",
    "DependencyResolver",
    "RemoteProxyResolver",
    "LocalInstanceResolver",
    "CapabilityMetadata",
    "CapabilityQuery",
    "AgentInfo",
    "AgentMatch",
    "CompatibilityScore",
    "Requirements",
    "ServiceDiscoveryProtocol",
    "CapabilityMatchingProtocol",
    "MeshAgentMetadata",
    "CapabilityHierarchy",
    "QueryOperator",
    "MatchingStrategy",
    "DeploymentStatus",
    "SemanticVersion",
    "AgentVersionInfo",
    "DeploymentInfo",
    "DeploymentResult",
    "RollbackInfo",
    "VersioningProtocol",
    "VersionComparisonProtocol",
    "LifecycleEvent",
    "LifecycleStatus",
    "RegistrationResult",
    "DeregistrationResult",
    "DrainResult",
    "LifecycleEventData",
    "LifecycleTransition",
    "LifecycleProtocol",
    "LifecycleEventProtocol",
    "HealthTransitionTrigger",
    "LifecycleConfiguration",
    "SelectionAlgorithm",
    "HealthStatus",
    "SelectionCriteria",
    "SelectionWeights",
    "AgentSelectionResult",
    "AgentHealthInfo",
    "WeightUpdateRequest",
    "WeightUpdateResult",
    "SelectionState",
    "AgentSelectionProtocol",
    "SelectionAlgorithmProtocol",
    "HealthMonitoringProtocol",
    "LogLevel",
    "DatabaseType",
    "SecurityMode",
    "RegistryMode",
    "ServerConfig",
    "DatabaseConfig",
    "SecurityConfig",
    "ServiceDiscoveryConfig",
    "MonitoringConfig",
    "PerformanceConfig",
    "RegistryConfig",
    "ConfigurationProvider",
    "EnvironmentConfigProvider",
    "ConfigurationError",
    "MissingConfigurationError",
    "InvalidConfigurationError",
    "MethodMetadata",
    "MethodType",
    "ParameterKind",
    "ParameterMetadata",
    "ServiceContract",
    "MeshServiceProxyInterface",
    "ServiceProxyProtocol",
    "ProxyGenerationError",
    "RemoteInvocationError",
    "ServiceContractError",
    # Unified dependencies (CRITICAL FEATURE)
    "DependencyPattern",
    "DependencySpecification",
    "DependencyResolutionResult",
    "UnifiedDependencyResolver",
    "DependencyValidator",
    "DependencyValidationError",
    "ValidationResult",
    "DependencyAnalyzer",
    "DependencyList",
    "DependencyMap",
    "DependencyContext",
]
