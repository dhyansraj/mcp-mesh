"""A provider that needs LiteLLM and does not have it must fail at startup.

Issue #1551. ``litellm`` left the base install in 3.5.0 (#1383) and every
``_require_litellm`` call site is lazy on purpose, so a big-3-only install
stays fully functional without the package. The cost of that laziness was
that a provider declaring a LONG-TAIL model — which cannot serve a single
request without the extra — registered, reported healthy, won dependency
resolution, and raised on a *consumer's* first call.

``@mesh.llm_provider`` has the model at decoration time, so it can settle this
before the agent exists. These tests pin the four cases that matter, and two of
them are the ones easy to regress:

  * a big-3 model must NOT trigger the check — if it did, the optional
    dependency would stop being optional and #1383 would be undone;
  * a broken TRANSITIVE import (``litellm`` present, ``tokenizers`` broken)
    must propagate untouched. Relabelling it as a missing ``litellm`` sends
    the author to an install command that is already satisfied and cannot
    help, while hiding the real cause.
"""

from __future__ import annotations

import builtins
import sys
import types
from contextlib import contextmanager

import pytest

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@contextmanager
def _module_with_app(module_name: str):
    """A real ``sys.modules`` entry carrying a FastMCP ``app``.

    ``@mesh.llm_provider`` resolves the app via ``sys.modules[fn.__module__]``,
    so a decorated function needs a module that actually exists.
    """
    from fastmcp import FastMCP

    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    mod = types.ModuleType(module_name)
    mod.app = FastMCP(module_name)
    sys.modules[module_name] = mod
    snapshot = dict(DecoratorRegistry._mesh_tools)
    DecoratorRegistry._mesh_tools.clear()
    try:
        yield mod
    finally:
        sys.modules.pop(module_name, None)
        DecoratorRegistry._mesh_tools.clear()
        DecoratorRegistry._mesh_tools.update(snapshot)


def _declare_provider(mod, module_name: str, model: str, func_name: str = "provider"):
    """Apply ``@mesh.llm_provider(model=...)`` the way an agent module would."""
    import mesh

    def placeholder():
        pass

    placeholder.__name__ = func_name
    placeholder.__qualname__ = func_name
    placeholder.__module__ = module_name
    return mesh.llm_provider(model=model, capability="llm")(placeholder)


def _hide_litellm(monkeypatch):
    """Make ``import litellm`` raise exactly what an uninstalled package does.

    ``None`` in ``sys.modules`` is CPython's own "this import is blocked" hook
    and raises ``ModuleNotFoundError(name="litellm")`` — the same type and the
    same ``.name`` a real absence produces, which is what ``_require_litellm``
    branches on. Uninstalling the package in the test venv is not an option,
    and stubbing the exception by hand would let the ``.name`` drift away from
    what CPython actually sets.
    """
    monkeypatch.setitem(sys.modules, "litellm", None)


def _break_litellm_subimport(monkeypatch, missing: str = "tokenizers"):
    """``litellm`` itself is installed; something it imports is not.

    The real shape of this is an ABI-broken or half-installed transitive
    dependency: ``import litellm`` raises ``ModuleNotFoundError`` whose
    ``.name`` is the *inner* module, not ``litellm``.
    """
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "litellm":
            raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


# Long-tail models: no bundled native adapter, so every request goes through
# LiteLLM. Kept aligned with the Go table in
# src/core/cli/scaffold/model_dispatch_test.go (TestRequiresLiteLLM).
LONG_TAIL_MODELS = [
    "moonshot/kimi-k2-0905-preview",
    "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
    "databricks/anthropic.claude-3-7-sonnet",
    "cohere/command-r-plus",
    "ollama/llama3",
    "groq/llama-3.1-70b-versatile",
    "acme-llm/frobnicator-9",
    "llama-3-70b",
    "mistral-large-latest",
    "o3xyz",
]

# Big-3 models: bundled native SDK adapters, litellm never involved.
NATIVE_MODELS = [
    "anthropic/claude-sonnet-4-5",
    "openai/gpt-4o",
    "gemini/gemini-2.5-flash",
    "vertex_ai/gemini-2.5-flash",
    "claude-3-haiku",
    "gpt-4o",
    "chatgpt-4o-latest",
    "o1",
    "o3-mini",
    "gemini-3-pro-preview",
]


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------


class TestModelRequiresLiteLLM:
    """The Python half of a predicate ``meshctl scaffold`` also implements.

    The Go side decides whether a generated ``requirements.txt`` gets the pin;
    this side decides whether the agent is allowed to start without it. They
    must agree, or the scaffolder writes an agent that refuses to boot. The
    model tables above are the Go test's tables; the vendor halves are held
    together by TestGoNativeVendorsMatchPythonRegistry in Go.
    """

    @pytest.mark.parametrize("model", LONG_TAIL_MODELS)
    def test_long_tail_models_require_litellm(self, model):
        from mesh.helpers import _is_native_dispatch_model, _model_requires_litellm

        assert _model_requires_litellm(model) is True
        assert _is_native_dispatch_model(model) is False

    @pytest.mark.parametrize("model", NATIVE_MODELS)
    def test_native_models_do_not_require_litellm(self, model):
        from mesh.helpers import _is_native_dispatch_model, _model_requires_litellm

        assert _model_requires_litellm(model) is False
        assert _is_native_dispatch_model(model) is True

    def test_is_case_insensitive(self):
        from mesh.helpers import _model_requires_litellm

        assert _model_requires_litellm("Anthropic/Claude-Sonnet-5") is False
        assert _model_requires_litellm("VERTEX_AI/gemini-2.5-flash") is False
        assert _model_requires_litellm("Bedrock/Anthropic.Claude-3") is True

    @pytest.mark.parametrize("model", ["", "   ", None])
    def test_unset_model_is_never_reported_as_needing_litellm(self, model):
        """Nothing is known about it — refusing to start on a guess is worse
        than the lazy call-site check that still stands behind this one."""
        from mesh.helpers import _model_requires_litellm

        assert _model_requires_litellm(model) is False

    def test_vendor_half_comes_from_the_handler_registry(self):
        """Not a second vendor table: the registry is asked.

        Registering a handler with no native adapter must not make its vendor
        look native — such a handler still dispatches through LiteLLM.
        """
        from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry
        from _mcp_mesh.engine.provider_handlers.base_provider_handler import (
            BaseProviderHandler,
        )
        from mesh.helpers import _model_requires_litellm

        assert ProviderHandlerRegistry.native_dispatch_vendors() == frozenset(
            {"anthropic", "openai", "gemini", "vertex_ai"}
        )

        class PlainHandler(BaseProviderHandler):
            pass

        try:
            ProviderHandlerRegistry.register("acme", PlainHandler)
            assert "acme" not in ProviderHandlerRegistry.native_dispatch_vendors()
            assert _model_requires_litellm("acme/frobnicator-9") is True
        finally:
            ProviderHandlerRegistry._handlers.pop("acme", None)
            ProviderHandlerRegistry.clear_cache()


# ---------------------------------------------------------------------------
# The startup assertion
# ---------------------------------------------------------------------------


class TestLongTailModelWithoutLiteLLM:
    def test_decoration_raises(self, monkeypatch):
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_longtail_absent"
        with _module_with_app(module_name) as mod:
            with pytest.raises(ImportError) as exc:
                _declare_provider(mod, module_name, "moonshot/kimi-k2-0905-preview")

        message = str(exc.value)
        # The existing message quality is the point — this path must not grow
        # a second, thinner error. Copy is asserted by substring, not in full,
        # so wording can improve without breaking the test.
        assert "moonshot/kimi-k2-0905-preview" in message
        assert "mcp-mesh[litellm]" in message
        assert "requirements.txt" in message

    def test_the_message_does_not_describe_a_request(self, monkeypatch):
        """It fires before any request exists, so it must not claim one did.

        The dispatch-time wording opens "This request", and reusing it here
        would tell the author a call failed when nothing has been called —
        sending them to look at a consumer that never ran.
        """
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_longtail_subject"
        with _module_with_app(module_name) as mod:
            with pytest.raises(ImportError) as exc:
                _declare_provider(mod, module_name, "ollama/llama3")

        assert str(exc.value).startswith("This agent's LLM provider")

    def test_dispatch_time_wording_is_unchanged(self):
        """The six lazy call sites keep the copy they already had."""
        from mesh.helpers import _require_litellm

        with pytest.raises(ImportError) as exc:
            with pytest.MonkeyPatch.context() as mp:
                _hide_litellm(mp)
                _require_litellm(model="ollama/llama3", vendor="ollama")

        assert str(exc.value).startswith("This request for model 'ollama/llama3'")

    def test_no_tool_is_registered(self, monkeypatch):
        """The whole point: it must not be discoverable.

        A provider that registers and then fails on call is exactly the state
        #1551 reports — consumers resolve to it and inherit its failure.
        """
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_longtail_no_registration"
        with _module_with_app(module_name) as mod:
            with pytest.raises(ImportError):
                _declare_provider(mod, module_name, "cohere/command-r-plus")

            assert DecoratorRegistry._mesh_tools == {}

    @pytest.mark.parametrize("model", LONG_TAIL_MODELS)
    def test_every_long_tail_model_is_caught(self, monkeypatch, model):
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_longtail_matrix"
        with _module_with_app(module_name) as mod:
            with pytest.raises(ImportError):
                _declare_provider(mod, module_name, model)


class TestNativeModelWithoutLiteLLM:
    @pytest.mark.parametrize("model", NATIVE_MODELS)
    def test_decoration_succeeds(self, monkeypatch, model):
        """#1383's guarantee: a big-3 install works with no litellm at all."""
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_native_absent"
        with _module_with_app(module_name) as mod:
            decorated = _declare_provider(mod, module_name, model)
            assert decorated is not None

    @pytest.mark.parametrize("model", NATIVE_MODELS)
    def test_the_check_is_never_reached(self, monkeypatch, model):
        """Not merely "does not raise" — must not consult litellm at all.

        ``_require_litellm`` would succeed in this venv (litellm IS installed
        here), so a gate that ran it and passed would look identical to a gate
        that skipped it, and would ship an agent that breaks the moment the
        extra is genuinely absent.
        """
        import mesh.helpers as helpers

        calls = []

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError(
                f"_require_litellm was consulted for native model {model!r}"
            )

        monkeypatch.setattr(helpers, "_require_litellm", spy)
        module_name = "_test_llm_provider_native_no_import"
        with _module_with_app(module_name) as mod:
            _declare_provider(mod, module_name, model)

        assert calls == []

    def test_the_check_is_reached_for_a_long_tail_model(self, monkeypatch):
        """The negative control for the test above: the spy is wired to a gate
        that really does fire, so ``calls == []`` there means something."""
        import mesh.helpers as helpers

        calls = []

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return object()

        monkeypatch.setattr(helpers, "_require_litellm", spy)
        module_name = "_test_llm_provider_longtail_spy"
        with _module_with_app(module_name) as mod:
            _declare_provider(mod, module_name, "cohere/command-r-plus")

        assert len(calls) == 1
        assert calls[0]["model"] == "cohere/command-r-plus"
        # The resolved vendor is passed through to the message so it can name
        # what it could not dispatch. Not asserted exactly: litellm resolves
        # this one to "cohere_chat" while prefix extraction yields "cohere",
        # and which of the two you get depends on whether litellm is present.
        assert calls[0]["vendor"].startswith("cohere")


class TestLongTailModelWithLiteLLMInstalled:
    @pytest.mark.parametrize("model", ["cohere/command-r-plus", "ollama/llama3"])
    def test_decoration_succeeds(self, model):
        """litellm present is the supported configuration — nothing changes."""
        pytest.importorskip("litellm")
        module_name = "_test_llm_provider_longtail_present"
        with _module_with_app(module_name) as mod:
            decorated = _declare_provider(mod, module_name, model)
            assert decorated is not None


class TestVendorProbeIsBestEffort:
    """Vendor detection must never be what stops a provider from being built.

    Found while building the matrix above, and present before the startup
    assertion existed: ``litellm.get_llm_provider`` reports an unresolvable
    bare name as ``litellm.BadRequestError`` — an ``openai.APIStatusError``
    subclass, so not a ``ValueError`` — which fell outside the ``except``
    tuple and crashed decoration. It hit exactly the names RFC #1100 Gap #1
    added the bare-name inference FOR, and only when litellm was installed:
    without it, the ``ModuleNotFoundError`` was caught and the inference ran.
    """

    @pytest.mark.parametrize("model", ["claude-3-haiku", "gemini-3-pro"])
    def test_bare_big3_name_litellm_cannot_resolve(self, model):
        pytest.importorskip("litellm")
        module_name = "_test_llm_provider_bare_big3_probe"
        with _module_with_app(module_name) as mod:
            assert _declare_provider(mod, module_name, model) is not None

    def test_a_raising_probe_falls_back_instead_of_crashing(self, monkeypatch):
        """Any probe failure, not just the one observed."""
        import litellm

        def boom(*args, **kwargs):
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(litellm, "get_llm_provider", boom)
        module_name = "_test_llm_provider_probe_raises"
        with _module_with_app(module_name) as mod:
            assert (
                _declare_provider(mod, module_name, "anthropic/claude-sonnet-4-5")
                is not None
            )

    def test_the_fallback_still_reaches_the_startup_assertion(self, monkeypatch):
        """A crashing probe must not become a way to skip the #1551 gate."""
        import litellm

        def boom(*args, **kwargs):
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(litellm, "get_llm_provider", boom)
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_probe_raises_longtail"
        with _module_with_app(module_name) as mod:
            with pytest.raises(ImportError):
                _declare_provider(mod, module_name, "cohere/command-r-plus")


class TestBrokenTransitiveImport:
    """``litellm`` is installed; one of ITS imports is broken.

    ``_require_litellm`` branches on ``e.name != "litellm"`` for exactly this,
    and moving the check to startup is where that distinction is easiest to
    lose — a naive ``try: import litellm / except ImportError: raise <install
    litellm>`` at decoration time reports a broken ``tokenizers`` as a missing
    extra that is in fact already installed.
    """

    def test_the_real_cause_propagates_for_a_long_tail_model(self, monkeypatch):
        _break_litellm_subimport(monkeypatch)
        module_name = "_test_llm_provider_transitive_longtail"
        with _module_with_app(module_name) as mod:
            with pytest.raises(ModuleNotFoundError) as exc:
                _declare_provider(mod, module_name, "cohere/command-r-plus")

        assert exc.value.name == "tokenizers"
        assert "tokenizers" in str(exc.value)
        assert "mcp-mesh[litellm]" not in str(exc.value)

    def test_a_native_model_is_unaffected(self, monkeypatch):
        """Big-3 dispatch does not need litellm, so a broken litellm tree must
        not stop the agent from starting."""
        _break_litellm_subimport(monkeypatch)
        module_name = "_test_llm_provider_transitive_native"
        with _module_with_app(module_name) as mod:
            decorated = _declare_provider(
                mod, module_name, "anthropic/claude-sonnet-4-5"
            )
            assert decorated is not None
