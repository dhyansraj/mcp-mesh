"""
Provider handler registry for vendor-specific LLM behavior.

Manages selection and instantiation of provider handlers based on vendor name.
"""

import logging
from typing import Optional

from .base_provider_handler import BaseProviderHandler
from .claude_handler import ClaudeHandler
from .gemini_handler import GeminiHandler
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
    - "gemini" -> GeminiHandler (Google AI Studio API key auth)
    - "vertex_ai" -> GeminiHandler (Vertex AI / IAM auth, same Gemini models)
    - "unknown" or others -> GenericHandler

    Note on the gemini/vertex_ai aliasing:
        Both ``gemini/<model>`` and ``vertex_ai/<model>`` route through the
        same GeminiHandler because they target the same Gemini model family on
        the other side of the wire — only the auth/transport differs (AI
        Studio API key vs GCP IAM via service account / ADC). LiteLLM handles
        the routing distinction internally based on the model prefix and the
        environment variables present (``GOOGLE_API_KEY`` vs
        ``GOOGLE_APPLICATION_CREDENTIALS`` / ``VERTEXAI_*``). Mesh-side
        prompt-shaping behavior (HINT mode with tools, STRICT mode without)
        is identical for both.

    Usage:
        handler = ProviderHandlerRegistry.get_handler("anthropic")
        request = handler.prepare_request(messages, tools, output_type)
        system_prompt = handler.format_system_prompt(base, tools, output_type)

    Extensibility:
        New handlers can be registered:
        ProviderHandlerRegistry.register("cohere", CohereHandler)
    """

    # Built-in vendor mappings.
    #
    # !! CROSS-LANGUAGE DUPLICATE (issue #1383) !!
    # ``meshctl scaffold`` re-implements this vendor -> native/LiteLLM split in
    # Go (``nativeVendorPrefixes`` in ``src/core/cli/scaffold/model_dispatch.go``)
    # so it can decide whether a generated ``requirements.txt`` needs the
    # optional ``mcp-mesh[litellm]`` pin. Any vendor added or removed here must
    # be mirrored there — a vendor that is native here but long-tail there
    # installs 30MB it never uses; the reverse ships an agent that ImportErrors
    # on its first request.
    _handlers: dict[str, type[BaseProviderHandler]] = {
        "anthropic": ClaudeHandler,
        "openai": OpenAIHandler,
        "gemini": GeminiHandler,  # Google AI Studio (GOOGLE_API_KEY)
        "vertex_ai": GeminiHandler,  # Vertex AI / IAM (same Gemini family, different auth)
    }

    # Cache of instantiated handlers (singleton per vendor)
    _instances: dict[str, BaseProviderHandler] = {}

    @classmethod
    def register(cls, vendor: str, handler_class: type[BaseProviderHandler]) -> None:
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
        logger.info(
            f"📝 Registered provider handler: {vendor} -> {handler_class.__name__}"
        )

        # Clear cached instance if it exists (force re-instantiation)
        if vendor in cls._instances:
            del cls._instances[vendor]

    @classmethod
    def get_handler(cls, vendor: str | None = None) -> BaseProviderHandler:
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
        vendor = cls._normalize_vendor(vendor)

        # Check cache first
        if vendor in cls._instances:
            logger.debug(f"🔍 Using cached handler for vendor: {vendor}")
            return cls._instances[vendor]

        # Get handler class (or fallback to Generic)
        handler_class = cls._handler_class(vendor)
        if vendor in cls._handlers:
            logger.info(f"✅ Selected {handler_class.__name__} for vendor: {vendor}")
        elif vendor != "unknown":
            logger.warning(
                f"⚠️  No specific handler for vendor '{vendor}', using GenericHandler"
            )
        else:
            logger.debug("Using GenericHandler for unknown vendor")

        # Instantiate and cache
        handler = cls._instantiate(handler_class, vendor)
        cls._instances[vendor] = handler

        logger.debug(f"🆕 Instantiated handler: {handler}")
        return handler

    @classmethod
    def probe_handler(cls, vendor: str | None = None) -> BaseProviderHandler:
        """Get a handler instance for a question asked OUTSIDE a dispatch.

        Same handler :meth:`get_handler` would return, with neither of its two
        side effects: the cache is not warmed and the "✅ Selected …" INFO line
        is not emitted. Returns the cached singleton when one already exists,
        otherwise a transient instance (handlers are stateless — per-request
        state lives in ContextVars precisely because they are cached as
        singletons — so a throwaway answers the same questions).

        Why the side effects matter (issue #1558). The selection line is the
        once-per-vendor record of *which handler will serve*, and it fires on
        cache miss — so it lands wherever the FIRST caller happens to be. A
        startup-time question that warms the cache moves that record from the
        dispatch it describes to import time, and every later dispatch takes
        the cache-hit branch and logs at DEBUG, which an operator's log does
        not capture. The #1551 startup assertion in ``mesh.helpers.llm_provider``
        is exactly such a caller.

        Same shape of reasoning as ``native_dispatch_blocker()`` vs
        ``has_native()`` in ``BaseProviderHandler``: asking a dispatch-time
        question early must not consume the dispatch-time record.
        """
        vendor = cls._normalize_vendor(vendor)
        cached = cls._instances.get(vendor)
        if cached is not None:
            return cached
        return cls._instantiate(cls._handler_class(vendor), vendor)

    @staticmethod
    def _normalize_vendor(vendor: str | None) -> str:
        """Normalize a vendor name (handles None and empty string)."""
        return (vendor or "unknown").lower().strip()

    @classmethod
    def _handler_class(cls, vendor: str) -> type[BaseProviderHandler]:
        """Handler class registered for a NORMALIZED vendor, else GenericHandler."""
        return cls._handlers.get(vendor, GenericHandler)

    @classmethod
    def _instantiate(
        cls, handler_class: type[BaseProviderHandler], vendor: str
    ) -> BaseProviderHandler:
        """Construct a handler. GenericHandler alone needs the vendor name."""
        return (
            handler_class()
            if handler_class is not GenericHandler
            else GenericHandler(vendor)
        )

    @classmethod
    def list_vendors(cls) -> dict[str, str]:
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
    def native_dispatch_vendors(cls) -> frozenset[str]:
        """The vendor prefixes that dispatch through a bundled native SDK.

        Derived, not declared: a handler ships a native adapter exactly when it
        overrides ``_native_module`` (the base returns ``None``, which is what
        keeps ``has_native()`` False and sends the vendor down the LiteLLM
        path). Reading the override rather than keeping a second list means a
        new native handler cannot be added without this set following it.

        Deliberately class-level. It answers "is a native adapter *wired up*
        for this vendor", not "would this call dispatch natively right now" —
        the latter is ``has_native()`` / ``native_dispatch_blocker()``, which
        additionally import the vendor SDK and honour ``MCP_MESH_NATIVE_LLM``.
        Callers that need a cheap, side-effect-free, env-independent verdict
        want this one; the #1551 startup assertion in
        ``mesh.helpers.llm_provider`` asks both, in that order, because a
        vendor with an adapter wired up can still fall back at runtime.

        A vendor added at runtime via ``register()`` appears here only if its
        handler actually overrides ``_native_module``; a plain
        ``BaseProviderHandler`` subclass does not, and correctly stays on the
        LiteLLM path.
        """
        return frozenset(
            vendor
            for vendor, handler_class in cls._handlers.items()
            if handler_class._native_module is not BaseProviderHandler._native_module
        )

    @classmethod
    def clear_cache(cls) -> None:
        """
        Clear cached handler instances.

        Useful for testing or when handler behavior needs to be reset.
        Next get_handler() call will create fresh instances.
        """
        cls._instances.clear()
        logger.debug("🧹 Cleared provider handler cache")
