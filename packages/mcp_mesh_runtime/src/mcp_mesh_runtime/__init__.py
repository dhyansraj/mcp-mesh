"""
MCP Mesh - Advanced Features for Model Context Protocol

A production-ready service mesh for Model Context Protocol (MCP) services
with advanced capabilities that extend the basic mcp-mesh-types package.

This package enhances mcp-mesh-types with:
- Advanced mesh integration and service discovery
- Health monitoring and heartbeats
- Dependency injection and service composition
- Enhanced error handling and retry logic
- Audit logging and security features
- Resource management and cleanup

AUTO-ENHANCEMENT MONKEY PATCHING:
When this package is imported, it automatically enhances the mcp_mesh.mesh_agent
decorator to provide full mesh capabilities while maintaining the single import
source principle. This ensures portability and eliminates developer confusion.
"""

import asyncio
import logging
import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar

__version__ = "0.1.0"
__author__ = "MCP Mesh Contributors"
__description__ = "Advanced MCP service mesh with full capabilities"

# Import the original mesh_agent decorator from mcp_mesh
import mcp_mesh

# Import base types from mcp-mesh-types
from mcp_mesh import (
    FileOperationError,
    PermissionDeniedError,
    SecurityValidationError,
)
from mcp_mesh import FileOperations as BaseFileOperations
from mcp_mesh import mesh_agent as _original_mesh_agent

# Enhanced exports
from .client import *

# Import decorator processor for auto-registration
from .decorator_processor import DecoratorProcessor
from .decorators import MeshAgentDecorator

# Import full mesh implementation but keep it private/internal
from .decorators.mesh_agent import _internal_mesh_agent as _full_mesh_agent

# Import shared components
from .shared import *

# Import server components only if they're available (optional dependency)
try:
    from .server import *
except ImportError:
    # Server components not available - that's fine for client-only usage
    pass

# Enhanced FileOperations with full mesh capabilities (optional)
try:
    from .tools.file_operations import FileOperations
except ImportError:
    # FileOperations not available due to missing dependencies
    FileOperations = BaseFileOperations

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)


def _enhanced_mesh_agent(
    capabilities: list[str],
    health_interval: int = 30,
    dependencies: list[str] | None = None,
    registry_url: str | None = None,
    agent_name: str | None = None,
    security_context: str | None = None,
    timeout: int = 30,
    retry_attempts: int = 3,
    enable_caching: bool = True,
    fallback_mode: bool = True,
    version: str = "1.0.0",
    description: str | None = None,
    endpoint: str | None = None,
    tags: list[str] | None = None,
    performance_profile: dict[str, float] | None = None,
    resource_requirements: dict[str, Any] | None = None,
    **metadata_kwargs: Any,
) -> Callable[[F], F]:
    """
    Enhanced mesh_agent decorator that applies both original metadata and full mesh capabilities.

    This decorator:
    1. First applies the original mcp_mesh.mesh_agent for metadata storage
    2. Then applies the full mesh implementation for enhanced capabilities
    3. Maintains compatibility with both vanilla MCP and mesh environments
    """

    def decorator(func_or_class: F) -> F:
        # Step 1: Apply original decorator for metadata storage and MCP SDK compatibility
        enhanced_target = _original_mesh_agent(
            capabilities=capabilities,
            health_interval=health_interval,
            dependencies=dependencies,
            registry_url=registry_url,
            agent_name=agent_name,
            security_context=security_context,
            timeout=timeout,
            retry_attempts=retry_attempts,
            enable_caching=enable_caching,
            fallback_mode=fallback_mode,
            version=version,
            description=description,
            endpoint=endpoint,
            tags=tags,
            performance_profile=performance_profile,
            resource_requirements=resource_requirements,
            **metadata_kwargs,
        )(func_or_class)

        # Step 2: Apply full mesh implementation for enhanced capabilities
        enhanced_target = _full_mesh_agent(
            capabilities=capabilities,
            health_interval=health_interval,
            dependencies=dependencies,
            registry_url=registry_url,
            agent_name=agent_name,
            security_context=security_context,
            timeout=timeout,
            retry_attempts=retry_attempts,
            enable_caching=enable_caching,
            fallback_mode=fallback_mode,
            version=version,
            description=description,
            endpoint=endpoint,
            tags=tags,
            performance_profile=performance_profile,
            resource_requirements=resource_requirements,
            **metadata_kwargs,
        )(enhanced_target)

        # Mark as enhanced for debugging
        enhanced_target._mesh_enhanced = True
        enhanced_target._mesh_enhancement_version = __version__

        return enhanced_target

    return decorator


# Monkey patch mcp_mesh.mesh_agent with enhanced version
def _schedule_auto_decorator_processing():
    """
    Schedule automatic decorator processing for agent self-registration.

    This function ensures that when mcp_mesh_runtime is imported in any process
    (CLI subprocess, K8s pod, etc.), decorators are automatically processed
    and agents self-register with the mesh registry.
    """
    # Check if auto-processing is disabled
    auto_process = os.getenv("MCP_MESH_AUTO_PROCESS", "true").lower() in (
        "true",
        "1",
        "yes",
        "on",
    )

    if not auto_process:
        logger.info("MCP Mesh auto-processing disabled via MCP_MESH_AUTO_PROCESS")
        return

    # Schedule decorator processing to run after current execution context
    # This allows imports to complete before processing decorators
    def run_delayed_processing():
        """Run decorator processing in a separate thread after a short delay."""
        import time

        # Short delay to ensure all imports are complete
        time.sleep(0.1)

        # Run the async processing in a new event loop
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_auto_process_decorators())
            loop.close()
        except Exception as e:
            logger.debug(f"Auto decorator processing completed with result: {e}")
        finally:
            # Clean up the event loop
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass

    # Start the processing in a daemon thread so it doesn't block shutdown
    processing_thread = threading.Thread(
        target=run_delayed_processing, name="MCP_Mesh_Auto_Processor", daemon=True
    )
    processing_thread.start()

    logger.debug("Scheduled automatic decorator processing")


async def _auto_process_decorators():
    """
    Automatically process mesh decorators for agent self-registration.

    This function runs when mcp_mesh_runtime is imported and processes
    any @mesh_agent decorators found in the current process, registering
    them with the mesh registry.
    """
    try:
        # Get registry URL from environment
        registry_url = os.getenv("MCP_MESH_REGISTRY_URL")

        if not registry_url:
            logger.debug("No MCP_MESH_REGISTRY_URL found, skipping auto-processing")
            return

        logger.debug(f"Auto-processing decorators for registry: {registry_url}")

        # Create processor and process decorators
        processor = DecoratorProcessor(registry_url)
        results = await processor.process_all_decorators()

        if results.get("total_successful", 0) > 0:
            logger.info(
                f"Auto-registered {results['total_successful']} mesh agents with registry"
            )
        elif results.get("total_processed", 0) > 0:
            logger.warning(
                f"Auto-processing completed: {results['total_successful']}/{results['total_processed']} successful"
            )
        else:
            logger.debug("No mesh decorators found for auto-processing")

    except Exception as e:
        # Don't fail the import process if auto-processing fails
        logger.debug(f"Auto decorator processing failed (non-fatal): {e}")


def _apply_auto_enhancement():
    """Apply auto-enhancement monkey patching to mcp_mesh.mesh_agent."""

    # Check environment variable for control (default: enabled)
    auto_enhance = os.getenv("MCP_MESH_AUTO_ENHANCE", "true").lower() in (
        "true",
        "1",
        "yes",
        "on",
    )

    if not auto_enhance:
        logger.info("MCP Mesh auto-enhancement disabled via MCP_MESH_AUTO_ENHANCE")
        return

    # Store reference to original for debugging
    _enhanced_mesh_agent._original_decorator = _original_mesh_agent

    # Replace the mesh_agent in mcp_mesh module
    mcp_mesh.mesh_agent = _enhanced_mesh_agent
    mcp_mesh.decorators.mesh_agent = _enhanced_mesh_agent

    # Also update the import in the main package namespace
    if hasattr(mcp_mesh, "__all__") and "mesh_agent" in mcp_mesh.__all__:
        # mesh_agent is already in __all__, just update the reference
        pass

    logger.info(
        f"MCP Mesh auto-enhancement applied - mcp_mesh.mesh_agent enhanced with v{__version__}"
    )

    # Schedule automatic decorator processing
    _schedule_auto_decorator_processing()


# Apply auto-enhancement when this module is imported
_apply_auto_enhancement()

# DO NOT export mesh_agent from this module - use mcp_mesh.mesh_agent instead
# mesh_agent = _enhanced_mesh_agent  # REMOVED - use mcp_mesh.mesh_agent

__all__ = [
    "__version__",
    "__author__",
    "__description__",
    # "mesh_agent",  # REMOVED - use mcp_mesh.mesh_agent instead
    "MeshAgentDecorator",
    "FileOperations",
    "BaseFileOperations",
    "FileOperationError",
    "SecurityValidationError",
    "PermissionDeniedError",
]
