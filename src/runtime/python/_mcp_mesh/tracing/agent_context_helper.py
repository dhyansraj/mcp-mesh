"""
Agent Context Helper

Helper functions to retrieve agent metadata for distributed tracing.
Gathers agent_id, hostname, IP address, and other runtime context information.
"""

import logging
import os
import socket
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AgentContextHelper:
    """Helper class to retrieve agent runtime context for tracing."""

    _cached_context: Optional[dict[str, Any]] = None

    @classmethod
    def get_agent_context(cls) -> dict[str, Any]:
        """
        Get complete agent context information for tracing.

        Uses decorator registry's resolved configuration with proper override chain:
        env var > decorator param > defaults

        Returns:
            Dictionary containing agent_id, hostname, IP, service name, etc.
        """
        # Return cached context if available (agent context doesn't change during runtime)
        if cls._cached_context is not None:
            return cls._cached_context

        context = {}

        # Get resolved agent configuration from decorator registry
        # (includes env var > decorator param > defaults resolution)
        try:
            from ..engine.decorator_registry import DecoratorRegistry

            agent_config = DecoratorRegistry.get_resolved_agent_config()

            # Extract core configuration fields using proper resolution
            context["agent_id"] = agent_config.get("agent_id", "unknown")
            context["agent_name"] = agent_config.get("name") or os.getenv(
                "MCP_MESH_AGENT_NAME", "unknown-agent"
            )
            context["agent_hostname"] = agent_config.get("http_host", "localhost")
            context["agent_port"] = str(agent_config.get("http_port", 8080))
            context["agent_namespace"] = agent_config.get("namespace", "default")
            context["mesh_version"] = agent_config.get("version", "unknown")

        except Exception as e:
            logger.debug(
                f"Failed to get resolved agent config: {e}, falling back to env vars"
            )
            # Fallback to direct environment variable access
            context["agent_id"] = "unknown"
            context["agent_name"] = os.getenv("MCP_MESH_AGENT_NAME", "unknown-agent")
            context["agent_hostname"] = os.getenv("MCP_MESH_HTTP_HOST", "localhost")
            context["agent_port"] = os.getenv("MCP_MESH_HTTP_PORT", "8080")
            context["agent_namespace"] = os.getenv("MCP_MESH_NAMESPACE", "default")
            context["mesh_version"] = os.getenv("MCP_MESH_VERSION", "unknown")

        # Get container/environment specific information (not resolved by decorator registry)
        context["pod_ip"] = os.getenv("POD_IP", context["agent_hostname"])
        context["container_name"] = os.getenv("HOSTNAME", context["agent_hostname"])

        # Try to get actual local IP address (fallback)
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            context["agent_local_ip"] = local_ip
        except Exception:
            context["agent_local_ip"] = "127.0.0.1"

        # Build service endpoint using resolved configuration
        context["agent_endpoint"] = (
            f"http://{context['agent_hostname']}:{context['agent_port']}"
        )

        # Cache the context
        cls._cached_context = context

        return context

    @classmethod
    def get_trace_metadata(cls) -> dict[str, Any]:
        """
        Get agent metadata specifically formatted for trace storage.

        Returns subset of agent context optimized for tracing.
        """
        context = cls.get_agent_context()

        # If agent_name is unknown but we have a valid agent_id, use agent_id as agent_name
        agent_name = context["agent_name"]
        agent_id = context["agent_id"]

        if agent_name in ("unknown-agent", "unknown") and agent_id not in (
            "unknown",
            "",
        ):
            agent_name = agent_id

        # Return only the fields we want in trace data
        return {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "agent_hostname": context["agent_hostname"],
            "agent_ip": context["pod_ip"],
            "agent_port": context["agent_port"],
            "agent_namespace": context["agent_namespace"],
            "agent_endpoint": context["agent_endpoint"],
        }


# Convenience functions
def get_agent_context() -> dict[str, Any]:
    """Convenience function to get agent context."""
    return AgentContextHelper.get_agent_context()


def get_trace_metadata() -> dict[str, Any]:
    """Convenience function to get trace metadata."""
    return AgentContextHelper.get_trace_metadata()
