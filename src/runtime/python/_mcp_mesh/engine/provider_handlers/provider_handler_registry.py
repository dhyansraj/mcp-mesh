"""
Provider handler registry for vendor-specific LLM behavior.

Manages selection and instantiation of provider handlers based on vendor name.
"""

import logging
from typing import Dict, Optional, Type

from .base_provider_handler import BaseProviderHandler
from .claude_handler import ClaudeHandler
from .generic_handler import GenericHandler
from .openai_handler import OpenAIHandler

logger = logging.getLogger(__name__)


class ProviderHandlerRegistry:
    """
    Registry for provider-specific handlers.

    Manages mapping from vendor names to handler classes and provides
    handler selection logic. Handlers customize LLM API calls for
    optimal performance with each vendor.

    Vendor Mapping:
    - "anthropic" -> ClaudeHandler
    - "openai" -> OpenAIHandler
    - "unknown" or others -> GenericHandler

    Usage:
        handler = ProviderHandlerRegistry.get_handler("anthropic")
        request = handler.prepare_request(messages, tools, output_type)
        system_prompt = handler.format_system_prompt(base, tools, output_type)

    Extensibility:
        New handlers can be registered:
        ProviderHandlerRegistry.register("cohere", CohereHandler)
    """

    # Built-in vendor mappings
    _handlers: Dict[str, Type[BaseProviderHandler]] = {
        "anthropic": ClaudeHandler,
        "openai": OpenAIHandler,
    }

    # Cache of instantiated handlers (singleton per vendor)
    _instances: Dict[str, BaseProviderHandler] = {}

    @classmethod
    def register(cls, vendor: str, handler_class: Type[BaseProviderHandler]) -> None:
        """
        Register a custom provider handler.

        Allows runtime registration of new handlers without modifying registry code.

        Args:
            vendor: Vendor name (e.g., "cohere", "gemini", "together")
            handler_class: Handler class (must subclass BaseProviderHandler)

        Raises:
            TypeError: If handler_class doesn't subclass BaseProviderHandler

        Example:
            class CohereHandler(BaseProviderHandler):
                ...

            ProviderHandlerRegistry.register("cohere", CohereHandler)
        """
        if not issubclass(handler_class, BaseProviderHandler):
            raise TypeError(
                f"Handler class must subclass BaseProviderHandler, got {handler_class}"
            )

        cls._handlers[vendor] = handler_class
        logger.info(f"📝 Registered provider handler: {vendor} -> {handler_class.__name__}")

        # Clear cached instance if it exists (force re-instantiation)
        if vendor in cls._instances:
            del cls._instances[vendor]

    @classmethod
    def get_handler(cls, vendor: Optional[str] = None) -> BaseProviderHandler:
        """
        Get provider handler for vendor.

        Selection Logic:
        1. If vendor matches registered handler -> use that handler
        2. If vendor is None or "unknown" -> use GenericHandler
        3. If vendor unknown -> use GenericHandler with warning

        Handlers are cached (singleton per vendor) for performance.

        Args:
            vendor: Vendor name from LLM provider registration
                   (e.g., "anthropic", "openai", "google")

        Returns:
            Provider handler instance for the vendor

        Example:
            # Get Claude handler
            handler = ProviderHandlerRegistry.get_handler("anthropic")

            # Get OpenAI handler
            handler = ProviderHandlerRegistry.get_handler("openai")

            # Get generic fallback
            handler = ProviderHandlerRegistry.get_handler("unknown")
        """
        # Normalize vendor name (handle None, empty string)
        vendor = (vendor or "unknown").lower().strip()

        # Check cache first
        if vendor in cls._instances:
            logger.debug(f"🔍 Using cached handler for vendor: {vendor}")
            return cls._instances[vendor]

        # Get handler class (or fallback to Generic)
        if vendor in cls._handlers:
            handler_class = cls._handlers[vendor]
            logger.info(
                f"✅ Selected {handler_class.__name__} for vendor: {vendor}"
            )
        else:
            handler_class = GenericHandler
            if vendor != "unknown":
                logger.warning(
                    f"⚠️  No specific handler for vendor '{vendor}', using GenericHandler"
                )
            else:
                logger.debug("Using GenericHandler for unknown vendor")

        # Instantiate and cache
        handler = handler_class() if handler_class != GenericHandler else GenericHandler(vendor)
        cls._instances[vendor] = handler

        logger.debug(f"🆕 Instantiated handler: {handler}")
        return handler

    @classmethod
    def list_vendors(cls) -> Dict[str, str]:
        """
        List all registered vendors and their handlers.

        Returns:
            Dictionary mapping vendor name -> handler class name

        Example:
            vendors = ProviderHandlerRegistry.list_vendors()
            # {'anthropic': 'ClaudeHandler', 'openai': 'OpenAIHandler'}
        """
        return {
            vendor: handler_class.__name__
            for vendor, handler_class in cls._handlers.items()
        }

    @classmethod
    def clear_cache(cls) -> None:
        """
        Clear cached handler instances.

        Useful for testing or when handler behavior needs to be reset.
        Next get_handler() call will create fresh instances.
        """
        cls._instances.clear()
        logger.debug("🧹 Cleared provider handler cache")
