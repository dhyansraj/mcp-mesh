"""
Clean registry client implementation for the new multi-tool design.
"""

import logging
from datetime import datetime
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class RegistryClient:
    """Client for interacting with the MCP Mesh Registry."""

    def __init__(self, registry_url: str):
        self.url = registry_url.rstrip("/")
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()

    async def ensure_session(self):
        """Ensure aiohttp session exists."""
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def register_agent(
        self, agent_id: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Register agent with all its tools.

        Returns:
            {
                "status": "success",
                "agent_id": "...",
                "dependencies_resolved": {
                    "tool1": {"dep1": {...}},
                    "tool2": {"dep2": {...}}
                }
            }
        """
        await self.ensure_session()

        payload = {
            "agent_id": agent_id,
            "metadata": metadata,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            async with self.session.post(
                f"{self.url}/agents/register",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 201:
                    return await resp.json()
                else:
                    error = await resp.text()
                    raise Exception(f"Registration failed: {resp.status} - {error}")
        except Exception as e:
            logger.error(f"Failed to register agent: {e}")
            raise

    async def send_heartbeat(
        self, agent_id: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Send heartbeat and get dependency updates.

        Returns:
            {
                "status": "success",
                "dependencies_resolved": {...}  # Only if changed
            }
        """
        await self.ensure_session()

        payload = {"agent_id": agent_id, "metadata": metadata or {}}

        try:
            async with self.session.post(
                f"{self.url}/heartbeat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    # Agent not found, need to re-register
                    return {"status": "not_found"}
                else:
                    error = await resp.text()
                    logger.error(f"Heartbeat failed: {resp.status} - {error}")
                    return {"status": "error"}
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")
            return {"status": "error"}

    async def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """
        Get agent details with all tools and dependencies.
        Used for recovery/reconnection.

        Returns:
            {
                "agent_id": "...",
                "tools": [
                    {
                        "name": "tool1",
                        "dependencies_resolved": {...}
                    }
                ]
            }
        """
        await self.ensure_session()

        try:
            async with self.session.get(
                f"{self.url}/agents/{agent_id}", timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return None
        except Exception as e:
            logger.error(f"Failed to get agent: {e}")
            return None

    async def search_capabilities(
        self,
        capability: str,
        version: str | None = None,
        tags: list[str] | None = None,
        fuzzy: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Search for tools providing a capability.
        This is mainly for CLI/dashboard use, not runtime.

        Returns:
            {
                "capabilities": [
                    {
                        "capability": "greeting",
                        "tool_name": "greet",
                        "agent_id": "...",
                        "endpoint": "..."
                    }
                ]
            }
        """
        await self.ensure_session()

        params = {"name": capability, "fuzzy": str(fuzzy).lower()}

        if version:
            params["version"] = version
        if tags:
            params["tags"] = ",".join(tags)

        try:
            async with self.session.get(
                f"{self.url}/capabilities",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("capabilities", [])
                else:
                    return []
        except Exception as e:
            logger.error(f"Failed to search capabilities: {e}")
            return []

    async def close(self):
        """Close the client session."""
        if self.session:
            await self.session.close()
            self.session = None
