"""
Session-Aware MCP Client

Routes MCP requests to appropriate agents based on session affinity
and capability routing requirements.
"""

import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional

from .mcp_client_proxy import MCPClientProxy
from .session_manager import get_session_manager

logger = logging.getLogger(__name__)


class SessionAwareMCPClient:
    """MCP client that handles session affinity routing."""

    def __init__(self, registry_client=None, redis_url: Optional[str] = None):
        self.registry_client = registry_client
        self.redis_url = redis_url
        self._session_manager = None
        self._agent_cache: dict[str, dict] = {}  # Cache of available agents
        self._cache_ttl = 300  # 5 minutes
        self._last_cache_update = 0

    async def initialize(self):
        """Initialize the session-aware client."""
        self._session_manager = await get_session_manager(self.redis_url)
        logger.info("🎯 Session-aware MCP client initialized")

    async def call_capability(
        self,
        capability: str,
        arguments: dict[str, Any],
        session_id: Optional[str] = None,
        routing_metadata: Optional[dict] = None,
    ) -> Any:
        """
        Call a capability with session affinity routing.

        Args:
            capability: The capability name to call
            arguments: Arguments for the capability
            session_id: Session ID for stateful capabilities
            routing_metadata: Additional routing metadata

        Returns:
            Result from the capability call
        """
        logger.debug(
            f"🎯 Session-aware call: capability={capability}, session={session_id}"
        )

        # Get available agents for this capability
        target_agents = await self._get_agents_for_capability(capability)
        if not target_agents:
            raise RuntimeError(f"No agents available for capability: {capability}")

        # Determine routing strategy based on capability metadata
        routing_strategy = self._determine_routing_strategy(
            target_agents[0], session_id
        )

        # Select target agent based on routing strategy
        target_agent = await self._select_target_agent(
            capability, target_agents, session_id, routing_strategy
        )

        # Create client proxy and make the call
        client = MCPClientProxy(target_agent["endpoint"], capability)

        try:
            result = await client._async_call(**arguments)

            # Update session affinity if this was a session-required call
            if session_id and routing_strategy.get("session_required"):
                await self._session_manager.update_session_access(
                    session_id, capability
                )

            logger.debug(
                f"✅ Session-aware call succeeded to {target_agent['agent_id']}"
            )
            return result

        except Exception as e:
            logger.error(
                f"❌ Session-aware call failed to {target_agent['agent_id']}: {e}"
            )

            # If session affinity call failed, try to remove bad session mapping
            if session_id and routing_strategy.get("session_required"):
                await self._handle_session_failure(
                    session_id, capability, target_agent["agent_id"]
                )

            raise

    async def _get_agents_for_capability(self, capability: str) -> list[dict]:
        """Get list of agents that provide the specified capability."""
        # Check cache first
        current_time = asyncio.get_event_loop().time()
        if current_time - self._last_cache_update > self._cache_ttl:
            await self._refresh_agent_cache()

        agents_with_capability = []
        for agent_id, agent_info in self._agent_cache.items():
            capabilities = agent_info.get("capabilities", {})
            if capability in capabilities:
                agents_with_capability.append(
                    {
                        "agent_id": agent_id,
                        "endpoint": agent_info["endpoint"],
                        "capability_metadata": capabilities[capability],
                    }
                )

        logger.debug(
            f"🔍 Found {len(agents_with_capability)} agents for capability: {capability}"
        )
        return agents_with_capability

    async def _refresh_agent_cache(self):
        """Refresh the cache of available agents and their capabilities."""
        if not self.registry_client:
            logger.warning("No registry client available for agent discovery")
            return

        try:
            # Get all agents from registry
            agents = await self.registry_client.list_agents()

            self._agent_cache.clear()
            for agent in agents:
                agent_id = agent.get("id")
                endpoint = agent.get("endpoint")

                if agent_id and endpoint:
                    # Fetch capability metadata from agent
                    try:
                        capabilities = await self._fetch_agent_metadata(endpoint)
                        self._agent_cache[agent_id] = {
                            "endpoint": endpoint,
                            "capabilities": capabilities,
                            "last_updated": asyncio.get_event_loop().time(),
                        }
                    except Exception as e:
                        logger.warning(f"Failed to fetch metadata from {agent_id}: {e}")

            self._last_cache_update = asyncio.get_event_loop().time()
            logger.debug(f"🔄 Agent cache refreshed: {len(self._agent_cache)} agents")

        except Exception as e:
            logger.error(f"❌ Failed to refresh agent cache: {e}")

    async def _fetch_agent_metadata(self, endpoint: str) -> dict:
        """Fetch capability metadata from an agent's /metadata endpoint."""
        try:
            import urllib.error
            import urllib.request

            metadata_url = f"{endpoint}/metadata"
            req = urllib.request.Request(
                metadata_url, headers={"Accept": "application/json"}
            )

            with urllib.request.urlopen(req, timeout=5.0) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("capabilities", {})

        except Exception as e:
            logger.debug(f"Failed to fetch metadata from {endpoint}: {e}")
            return {}

    def _determine_routing_strategy(
        self, agent_info: dict, session_id: Optional[str]
    ) -> dict:
        """Determine routing strategy based on capability metadata."""
        capability_metadata = agent_info.get("capability_metadata", {})

        strategy = {
            "session_required": capability_metadata.get("session_required", False),
            "stateful": capability_metadata.get("stateful", False),
            "full_mcp_access": capability_metadata.get("full_mcp_access", False),
            "streaming": capability_metadata.get("streaming", False),
            "has_session": session_id is not None,
        }

        logger.debug(f"🎯 Routing strategy: {strategy}")
        return strategy

    async def _select_target_agent(
        self,
        capability: str,
        available_agents: list[dict],
        session_id: Optional[str],
        routing_strategy: dict,
    ) -> dict:
        """Select the best target agent based on routing strategy."""

        # If session affinity is required and we have a session
        if routing_strategy.get("session_required") and session_id:
            # Check if we already have an agent for this session
            existing_agent_id = await self._session_manager.get_session_agent(
                session_id, capability
            )

            if existing_agent_id:
                # Find the existing agent in available agents
                for agent in available_agents:
                    if agent["agent_id"] == existing_agent_id:
                        logger.info(
                            f"📍 Using session affinity: {session_id} → {existing_agent_id}"
                        )
                        return agent

                # If existing agent not available, remove the session mapping
                logger.warning(
                    f"⚠️ Session agent {existing_agent_id} not available, removing mapping"
                )
                await self._session_manager.remove_session(session_id, capability)

            # No existing session or agent unavailable - create new session mapping
            selected_agent = self._select_random_agent(available_agents)
            await self._session_manager.set_session_agent(
                session_id, capability, selected_agent["agent_id"]
            )
            logger.info(
                f"🎯 New session affinity: {session_id} → {selected_agent['agent_id']}"
            )
            return selected_agent

        # For non-session capabilities, use load balancing
        selected_agent = self._select_random_agent(available_agents)
        logger.debug(f"🎯 Load-balanced selection: {selected_agent['agent_id']}")
        return selected_agent

    def _select_random_agent(self, agents: list[dict]) -> dict:
        """Select a random agent from the available list (simple load balancing)."""
        return random.choice(agents)

    async def _handle_session_failure(
        self, session_id: str, capability: str, failed_agent_id: str
    ):
        """Handle session failure by removing the session mapping."""
        logger.warning(f"💥 Session failure: {session_id} with agent {failed_agent_id}")
        await self._session_manager.remove_session(session_id, capability)

    async def get_session_stats(self) -> dict:
        """Get session statistics."""
        if self._session_manager:
            stats = await self._session_manager.get_session_stats()
            stats.update(
                {
                    "cached_agents": len(self._agent_cache),
                    "cache_age": asyncio.get_event_loop().time()
                    - self._last_cache_update,
                }
            )
            return stats
        return {"error": "Session manager not initialized"}

    async def close(self):
        """Close the client and cleanup resources."""
        if self._session_manager:
            await self._session_manager.close()
        logger.info("🔌 Session-aware MCP client closed")
