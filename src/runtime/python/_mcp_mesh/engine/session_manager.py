"""
Session Manager for MCP Mesh

Handles session affinity routing by tracking which agent instances
handle which sessions for stateful and session-required capabilities.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages session affinity for stateful capabilities."""

    def __init__(self, redis_url: Optional[str] = None, ttl_hours: int = 24):
        self.redis_url = redis_url
        self.session_ttl = timedelta(hours=ttl_hours)

        # In-memory fallback if Redis not available
        self._local_sessions: dict[str, dict] = {}
        self._redis_client = None
        self._redis_available = False

        logger.debug(
            f"🎯 SessionManager initialized with TTL={ttl_hours}h, Redis={redis_url}"
        )

    async def initialize(self):
        """Initialize Redis connection if available."""
        if self.redis_url:
            try:
                import redis.asyncio as redis

                self._redis_client = redis.from_url(self.redis_url)

                # Test connection
                await self._redis_client.ping()
                self._redis_available = True
                logger.info(f"✅ Redis session storage connected: {self.redis_url}")

            except ImportError:
                logger.warning(
                    "📦 Redis library not available, using in-memory session storage"
                )
                self._redis_available = False
            except Exception as e:
                logger.warning(
                    f"❌ Redis connection failed: {e}, using in-memory storage"
                )
                self._redis_available = False
        else:
            logger.info("🧠 Using in-memory session storage (no Redis configured)")

    async def get_session_agent(
        self, session_id: str, capability: str
    ) -> Optional[str]:
        """Get the agent ID that should handle this session."""
        session_key = f"session:{session_id}:{capability}"

        if self._redis_available:
            try:
                data = await self._redis_client.get(session_key)
                if data:
                    session_info = json.loads(data)
                    # Check if session hasn't expired
                    created_at = datetime.fromisoformat(session_info["created_at"])
                    if datetime.now() - created_at < self.session_ttl:
                        agent_id = session_info["agent_id"]
                        logger.debug(
                            f"📍 Session affinity found: {session_id} → {agent_id}"
                        )
                        return agent_id
                    else:
                        # Session expired, clean it up
                        await self._redis_client.delete(session_key)
                        logger.debug(f"🕐 Session expired and cleaned: {session_id}")
                        return None
            except Exception as e:
                logger.warning(f"❌ Redis session lookup failed: {e}")
                # Fall through to local storage

        # Fallback to local storage
        if session_key in self._local_sessions:
            session_info = self._local_sessions[session_key]
            created_at = datetime.fromisoformat(session_info["created_at"])
            if datetime.now() - created_at < self.session_ttl:
                agent_id = session_info["agent_id"]
                logger.debug(
                    f"📍 Local session affinity found: {session_id} → {agent_id}"
                )
                return agent_id
            else:
                # Session expired
                del self._local_sessions[session_key]
                logger.debug(f"🕐 Local session expired and cleaned: {session_id}")

        return None

    async def set_session_agent(
        self, session_id: str, capability: str, agent_id: str
    ) -> bool:
        """Set the agent that should handle this session."""
        session_key = f"session:{session_id}:{capability}"
        session_info = {
            "agent_id": agent_id,
            "capability": capability,
            "created_at": datetime.now().isoformat(),
            "last_accessed": datetime.now().isoformat(),
        }

        if self._redis_available:
            try:
                # Store in Redis with TTL
                ttl_seconds = int(self.session_ttl.total_seconds())
                await self._redis_client.setex(
                    session_key, ttl_seconds, json.dumps(session_info)
                )
                logger.info(
                    f"🎯 Session affinity set in Redis: {session_id} → {agent_id}"
                )
                return True
            except Exception as e:
                logger.warning(f"❌ Redis session storage failed: {e}")
                # Fall through to local storage

        # Store locally as fallback
        self._local_sessions[session_key] = session_info
        logger.info(f"🎯 Session affinity set locally: {session_id} → {agent_id}")
        return True

    async def update_session_access(self, session_id: str, capability: str) -> bool:
        """Update last access time for session (extends TTL)."""
        session_key = f"session:{session_id}:{capability}"

        if self._redis_available:
            try:
                data = await self._redis_client.get(session_key)
                if data:
                    session_info = json.loads(data)
                    session_info["last_accessed"] = datetime.now().isoformat()

                    ttl_seconds = int(self.session_ttl.total_seconds())
                    await self._redis_client.setex(
                        session_key, ttl_seconds, json.dumps(session_info)
                    )
                    logger.debug(f"🔄 Session access updated in Redis: {session_id}")
                    return True
            except Exception as e:
                logger.warning(f"❌ Redis session update failed: {e}")

        # Update local storage
        if session_key in self._local_sessions:
            self._local_sessions[session_key][
                "last_accessed"
            ] = datetime.now().isoformat()
            logger.debug(f"🔄 Session access updated locally: {session_id}")
            return True

        return False

    async def remove_session(self, session_id: str, capability: str = None) -> bool:
        """Remove session affinity."""
        if capability:
            session_keys = [f"session:{session_id}:{capability}"]
        else:
            # Remove all sessions for this session_id
            session_keys = []
            if self._redis_available:
                try:
                    pattern = f"session:{session_id}:*"
                    keys = await self._redis_client.keys(pattern)
                    session_keys.extend(keys)
                except Exception as e:
                    logger.warning(f"❌ Redis session removal scan failed: {e}")

            # Add local keys
            local_keys = [
                k
                for k in self._local_sessions.keys()
                if k.startswith(f"session:{session_id}:")
            ]
            session_keys.extend(local_keys)

        removed_count = 0
        for session_key in session_keys:
            # Remove from Redis
            if self._redis_available:
                try:
                    deleted = await self._redis_client.delete(session_key)
                    if deleted:
                        removed_count += 1
                except Exception as e:
                    logger.warning(
                        f"❌ Redis session removal failed for {session_key}: {e}"
                    )

            # Remove from local storage
            if session_key in self._local_sessions:
                del self._local_sessions[session_key]
                removed_count += 1

        if removed_count > 0:
            logger.info(f"🗑️ Removed {removed_count} session(s) for {session_id}")
            return True

        return False

    async def get_session_stats(self) -> dict:
        """Get session statistics."""
        stats = {
            "redis_available": self._redis_available,
            "local_sessions": len(self._local_sessions),
            "redis_sessions": 0,
            "session_ttl_hours": self.session_ttl.total_seconds() / 3600,
        }

        if self._redis_available:
            try:
                keys = await self._redis_client.keys("session:*")
                stats["redis_sessions"] = len(keys)
            except Exception as e:
                logger.warning(f"❌ Redis stats collection failed: {e}")

        return stats

    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions from local storage."""
        expired_keys = []
        now = datetime.now()

        for session_key, session_info in self._local_sessions.items():
            created_at = datetime.fromisoformat(session_info["created_at"])
            if now - created_at > self.session_ttl:
                expired_keys.append(session_key)

        for key in expired_keys:
            del self._local_sessions[key]

        if expired_keys:
            logger.info(f"🧹 Cleaned up {len(expired_keys)} expired local sessions")

        return len(expired_keys)

    async def close(self):
        """Close Redis connection."""
        if self._redis_client:
            try:
                await self._redis_client.close()
                logger.debug("🔌 Redis connection closed")
            except Exception as e:
                logger.warning(f"❌ Error closing Redis connection: {e}")


# Global session manager instance
_session_manager: Optional[SessionManager] = None


async def get_session_manager(redis_url: Optional[str] = None) -> SessionManager:
    """Get or create the global session manager."""
    global _session_manager

    if _session_manager is None:
        _session_manager = SessionManager(redis_url=redis_url)
        await _session_manager.initialize()

    return _session_manager


async def close_session_manager():
    """Close the global session manager."""
    global _session_manager

    if _session_manager:
        await _session_manager.close()
        _session_manager = None
