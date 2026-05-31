"""Routing tests for RFC #1100 Gap #1: UNPREFIXED big-3 names → native handler.

These validate the vendor-resolution chokepoint behavior used by
``@mesh.llm_provider``: a bare big-3 model name (e.g. ``gpt-4o``,
``claude-3-haiku``, ``gemini-3-pro``) must resolve to its native provider
handler and be normalized to the canonical ``vendor/<name>`` form (so the
native client's ``supports_model`` / ``_strip_prefix`` accept it and the wire
model name is unchanged), while a bare unknown name (``cohere-command``,
``llama-3``) stays on the GenericHandler/LiteLLM tail.

The helper-level inference is unit-tested in
``test_mesh_llm_agent_proxy.py``; these tests assert the resolution wiring:
inference → vendor → normalized model → handler type / supports_model.
"""

from _mcp_mesh.engine.native_clients import (
    anthropic_native,
    gemini_native,
    openai_native,
)
from _mcp_mesh.engine.provider_handlers import GenericHandler
from _mcp_mesh.engine.provider_handlers.provider_handler_registry import (
    ProviderHandlerRegistry,
)
from mesh.helpers import (
    _BIG3_VENDOR_PREFIX,
    _infer_big3_vendor_from_bare_name,
)


def _resolve(model: str) -> tuple[str, str]:
    """Reproduce the decorator's vendor-resolution chokepoint.

    Returns ``(vendor, normalized_model)`` exactly as
    ``@mesh.llm_provider`` computes them: LiteLLM detection first, then the
    Gap #1 bare-name inference + canonical-prefix normalization when the
    vendor is still ``unknown`` and the model has no ``/`` prefix.
    """
    vendor = "unknown"
    try:
        import litellm

        _, vendor, _, _ = litellm.get_llm_provider(model=model)
    except Exception:
        if "/" in model:
            vendor = model.split("/")[0]

    if vendor == "unknown" and "/" not in model:
        inferred = _infer_big3_vendor_from_bare_name(model)
        if inferred is not None:
            vendor = inferred
            model = f"{_BIG3_VENDOR_PREFIX[inferred]}{model}"

    return vendor, model


class TestBareNameNativeRouting:
    def test_bare_openai_db_name_resolves_native(self):
        # ``gpt-4o`` is in LiteLLM's DB → vendor resolves via LiteLLM (vendor
        # already "openai"); the inference branch is a no-op but the handler
        # must be the native OpenAI handler (not GenericHandler).
        vendor, model = _resolve("gpt-4o")
        assert vendor == "openai"
        handler = ProviderHandlerRegistry.get_handler(vendor)
        assert not isinstance(handler, GenericHandler)
        # ``has_native()`` is gated on the SDK being importable; assert only
        # when the openai SDK is present so the test is environment-robust.
        if openai_native.is_available():
            assert handler.has_native()

    def test_bare_anthropic_unknown_db_name_resolves_native(self):
        # ``claude-3-haiku`` is NOT in LiteLLM's DB → without Gap #1 it would
        # fall to "unknown"/GenericHandler. Inference must rescue it.
        vendor, model = _resolve("claude-3-haiku")
        assert vendor == "anthropic"
        assert model == "anthropic/claude-3-haiku"
        handler = ProviderHandlerRegistry.get_handler(vendor)
        assert not isinstance(handler, GenericHandler)
        if anthropic_native.is_available():
            assert handler.has_native()
        # Normalized model must satisfy the native client's supports_model.
        assert anthropic_native.supports_model(model)
        # Wire model is the bare name again — no double-prefixing.
        assert anthropic_native._strip_prefix(model) == "claude-3-haiku"

    def test_bare_gemini_unknown_db_name_resolves_native(self):
        vendor, model = _resolve("gemini-3-pro")
        assert vendor == "gemini"
        assert model == "gemini/gemini-3-pro"
        handler = ProviderHandlerRegistry.get_handler(vendor)
        assert not isinstance(handler, GenericHandler)
        if gemini_native.is_available():
            assert handler.has_native()
        assert gemini_native.supports_model(model)
        assert gemini_native._strip_prefix(model) == "gemini-3-pro"

    def test_bare_openai_unknown_db_name_resolves_native(self):
        # A plausible future/uncommon OpenAI name not in LiteLLM's DB.
        vendor, model = _resolve("gpt-6-turbo")
        assert vendor == "openai"
        assert model == "openai/gpt-6-turbo"
        assert openai_native.supports_model(model)
        assert openai_native._strip_prefix(model) == "gpt-6-turbo"

    def test_bare_unknown_name_stays_generic(self):
        vendor, model = _resolve("cohere-command")
        # Not a big-3 prefix → vendor stays unknown, model un-normalized.
        assert vendor == "unknown"
        assert model == "cohere-command"
        handler = ProviderHandlerRegistry.get_handler(vendor)
        assert isinstance(handler, GenericHandler)

    def test_bare_llama_name_stays_generic(self):
        vendor, model = _resolve("llama-3")
        assert vendor == "unknown"
        assert model == "llama-3"
        assert isinstance(ProviderHandlerRegistry.get_handler(vendor), GenericHandler)

    def test_already_prefixed_openai_untouched(self):
        # Explicit prefix → LiteLLM resolves it; inference never fires and the
        # model string is unchanged (no second-guessing).
        vendor, model = _resolve("openai/gpt-4o")
        assert vendor == "openai"
        assert model == "openai/gpt-4o"

    def test_already_prefixed_vertex_ai_untouched(self):
        # vertex_ai must never be collapsed to gemini by inference.
        vendor, model = _resolve("vertex_ai/gemini-pro")
        assert vendor == "vertex_ai"
        assert model == "vertex_ai/gemini-pro"
        handler = ProviderHandlerRegistry.get_handler(vendor)
        assert not isinstance(handler, GenericHandler)
