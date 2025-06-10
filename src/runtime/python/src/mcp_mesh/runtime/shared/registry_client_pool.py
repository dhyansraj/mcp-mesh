"""
Registry Client Pool - Manages shared registry client instances.

This module provides a pool of registry clients to avoid creating multiple
clients for the same registry URL, which can lead to unclosed sessions.
"""

import asyncio
import logging
from typing import Optional
from weakref import WeakValueDictionary

from .registry_client import RegistryClient

logger = logging.getLogger(__name__)


class RegistryClientPool:
    """Manages a pool of registry clients to avoid duplicates."""

    _instance: Optional["RegistryClientPool"] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        # Use weak references so clients can be garbage collected
        self._clients: WeakValueDictionary[str, RegistryClient] = WeakValueDictionary()
        self._strong_refs: dict[str, RegistryClient] = (
            {}
        )  # Keep strong refs during shutdown

    async def get_client(
        self, url: str, timeout: int = 30, retry_attempts: int = 3
    ) -> RegistryClient:
        """Get or create a registry client for the given URL."""
        async with self._lock:
            # Check if we already have a client for this URL
            client = self._clients.get(url)
            if client is None:
                logger.debug(f"Creating new registry client for {url}")
                client = RegistryClient(url, timeout, retry_attempts)
                self._clients[url] = client
            else:
                logger.debug(f"Reusing existing registry client for {url}")

            return client

    async def close_all(self) -> None:
        """Close all registry clients in the pool."""
        async with self._lock:
            # Convert weak refs to strong refs to prevent GC during cleanup
            self._strong_refs = dict(self._clients.items())

            for url, client in self._strong_refs.items():
                try:
                    logger.debug(f"Closing registry client for {url}")
                    await client.close()
                except Exception as e:
                    logger.error(f"Error closing registry client for {url}: {e}")

            self._clients.clear()
            self._strong_refs.clear()


# Global instance
_pool = RegistryClientPool()


async def get_registry_client(
    url: str, timeout: int = 30, retry_attempts: int = 3
) -> RegistryClient:
    """Get a registry client from the global pool."""
    return await _pool.get_client(url, timeout, retry_attempts)


async def close_all_registry_clients() -> None:
    """Close all registry clients in the global pool."""
    await _pool.close_all()


# Register cleanup with graceful shutdown
try:
    from ..decorators.graceful_shutdown import register_cleanup

    def cleanup_registry_pool():
        """Cleanup function for graceful shutdown."""
        try:
            # Run async cleanup in sync context
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule cleanup as a task
                loop.create_task(close_all_registry_clients())
            else:
                # Run directly
                loop.run_until_complete(close_all_registry_clients())
        except Exception as e:
            logger.error(f"Error during registry pool cleanup: {e}")

    register_cleanup(cleanup_registry_pool)
except ImportError:
    pass  # Graceful shutdown not available
