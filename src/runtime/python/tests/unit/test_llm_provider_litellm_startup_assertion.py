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

The model is only half the question. A big-3 model ALSO dispatches through
LiteLLM when native dispatch is unavailable in the process —
``MCP_MESH_NATIVE_LLM`` switching it off, or the vendor SDK failing to import —
and such a provider fails on a consumer's first call for the same reason. That
half is asked at the registration site rather than inside the model predicate,
which is a cross-language duplicate that must stay environment-independent;
``TestNativeDispatchUnavailable`` below pins it.
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


@pytest.fixture(autouse=True)
def _native_dispatch_default(monkeypatch):
    """Every test starts from the default: native dispatch ON.

    ``MCP_MESH_NATIVE_LLM`` is a real operator knob, so a developer running the
    suite with it exported would otherwise flip the big-3 cases into the
    LiteLLM path and make them fail for a reason that has nothing to do with
    the code under test. Tests that want the opt-out set it themselves.
    """
    monkeypatch.delenv("MCP_MESH_NATIVE_LLM", raising=False)


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


def _disable_native_dispatch(monkeypatch, value: str = "0"):
    """The documented opt-out: force every vendor down the LiteLLM path."""
    monkeypatch.setenv("MCP_MESH_NATIVE_LLM", value)


def _hide_vendor_sdk(monkeypatch, vendor: str = "anthropic"):
    """The vendor's native SDK is not importable in this process.

    Patched at the adapter's ``is_available`` rather than by hiding the module,
    because that probe caches its result in a closure cell — a later
    ``sys.modules`` edit would not be seen. This is the state a damaged or
    hand-pruned install is in: anthropic/openai/google-genai are base
    dependencies, so it is not reachable by choosing extras.
    """
    from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry

    native = ProviderHandlerRegistry.get_handler(vendor)._native_module()
    monkeypatch.setattr(native, "is_available", lambda: False)
    return native


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
        """The six lazy call sites keep the copy they already had.

        Both shaped parameters (``subject``, ``explanation``) default to what
        the message used to hard-code, so a call site that passes neither is
        unaffected by their existence.
        """
        from mesh.helpers import _require_litellm

        with pytest.raises(ImportError) as exc:
            with pytest.MonkeyPatch.context() as mp:
                _hide_litellm(mp)
                _require_litellm(model="ollama/llama3", vendor="ollama")

        message = str(exc.value)
        assert message.startswith("This request for model 'ollama/llama3'")
        assert (
            "mcp-mesh bundles native SDK adapters for Anthropic, OpenAI and "
            "Gemini; every other vendor/model dispatches through LiteLLM."
        ) in message

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


# ---------------------------------------------------------------------------
# A big-3 model that will NOT dispatch natively
# ---------------------------------------------------------------------------


class TestNativeDispatchUnavailable:
    """ "Needs LiteLLM" is two questions, and the model answers only one.

    A big-3 model is on the LiteLLM path whenever native dispatch is not
    actually available in the process — ``MCP_MESH_NATIVE_LLM`` switching it
    off, or the vendor SDK not importing. Such a provider fails on a
    consumer's first call for precisely the reason #1551 reports, so leaving
    it out would have left the reported bug reachable through a configuration
    the operator explicitly asked for.

    The runtime question is asked at the registration site, NOT inside
    ``_model_requires_litellm``: that predicate is a cross-language duplicate
    of the scaffolder's ``IsNativeDispatchModel``, which runs in ``meshctl``
    where this process's environment and installed SDKs do not exist. Making
    it env-dependent would make the Go/Python sync guard enforce a lie.
    """

    @pytest.mark.parametrize("flag", ["0", "false", "no", "off", "OFF", " False "])
    def test_env_opt_out_makes_a_big3_model_require_litellm(self, monkeypatch, flag):
        _disable_native_dispatch(monkeypatch, flag)
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_native_env_off"
        with _module_with_app(module_name) as mod:
            with pytest.raises(ImportError) as exc:
                _declare_provider(mod, module_name, "anthropic/claude-sonnet-4-5")

        message = str(exc.value)
        assert "anthropic/claude-sonnet-4-5" in message
        assert "mcp-mesh[litellm]" in message
        # The cause, named. Without it the message would claim this model is
        # long-tail — "every other vendor/model dispatches through LiteLLM" —
        # and send an Anthropic user looking for a typo in a model string that
        # is perfectly correct.
        assert "MCP_MESH_NATIVE_LLM" in message

    @pytest.mark.parametrize("flag", ["1", "true", "yes", "on", ""])
    def test_a_non_opt_out_value_leaves_native_dispatch_alone(self, monkeypatch, flag):
        """Only the documented opt-out set disables native dispatch.

        The negative control for the parametrization above: if any value of the
        variable counted, this check would be reading the variable's presence
        rather than its meaning.
        """
        _disable_native_dispatch(monkeypatch, flag)
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_native_env_on"
        with _module_with_app(module_name) as mod:
            assert (
                _declare_provider(mod, module_name, "anthropic/claude-sonnet-4-5")
                is not None
            )

    def test_env_opt_out_with_litellm_installed_still_starts(self, monkeypatch):
        """The opt-out is a supported configuration — it just needs the extra."""
        pytest.importorskip("litellm")
        _disable_native_dispatch(monkeypatch)
        module_name = "_test_llm_provider_native_env_off_with_litellm"
        with _module_with_app(module_name) as mod:
            assert (
                _declare_provider(mod, module_name, "anthropic/claude-sonnet-4-5")
                is not None
            )

    @pytest.mark.parametrize(
        "model,vendor",
        [
            ("anthropic/claude-sonnet-4-5", "anthropic"),
            ("openai/gpt-4o", "openai"),
            ("gemini/gemini-2.5-flash", "gemini"),
            ("claude-3-haiku", "anthropic"),
        ],
    )
    def test_env_opt_out_covers_every_native_vendor(self, monkeypatch, model, vendor):
        _disable_native_dispatch(monkeypatch)
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_native_env_off_matrix"
        with _module_with_app(module_name) as mod:
            with pytest.raises(ImportError) as exc:
                _declare_provider(mod, module_name, model)

        assert vendor in str(exc.value)

    def test_a_missing_vendor_sdk_is_covered_too(self, monkeypatch):
        """The deliberate scope decision, stated as a test.

        The check is "will this dispatch through LiteLLM", not "did the
        operator ask for LiteLLM" — so it covers an unimportable vendor SDK as
        well as the env opt-out. Both leave the provider with no dispatch path
        at all when ``litellm`` is absent, which is a first-call failure the
        decorator can see coming. The vendor SDKs are BASE dependencies
        (issue #834), so this state is a damaged install rather than a
        supported one: nobody reaches it by choosing extras, and failing at
        boot is strictly better than registering healthy and failing later.
        """
        _hide_vendor_sdk(monkeypatch, "anthropic")
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_native_sdk_missing"
        with _module_with_app(module_name) as mod:
            with pytest.raises(ImportError) as exc:
                _declare_provider(mod, module_name, "anthropic/claude-sonnet-4-5")

        message = str(exc.value)
        assert "not importable" in message
        assert "mcp-mesh[litellm]" in message
        # It must not be described as a long-tail vendor: mcp-mesh does bundle
        # an adapter for it, and that is the difference between "install the
        # extra" and "repair your install".
        assert "every other vendor/model dispatches through LiteLLM" not in message

    def test_a_missing_vendor_sdk_falls_back_when_litellm_is_present(self, monkeypatch):
        """This is the LiteLLM fallback working as designed, not a failure."""
        pytest.importorskip("litellm")
        _hide_vendor_sdk(monkeypatch, "anthropic")
        module_name = "_test_llm_provider_native_sdk_missing_with_litellm"
        with _module_with_app(module_name) as mod:
            assert (
                _declare_provider(mod, module_name, "anthropic/claude-sonnet-4-5")
                is not None
            )

    def test_an_unset_model_never_fails_even_with_native_dispatch_off(
        self, monkeypatch
    ):
        """Nothing is known about it, so there is nothing to refuse over."""
        _disable_native_dispatch(monkeypatch)
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_empty_model_env_off"
        with _module_with_app(module_name) as mod:
            assert _declare_provider(mod, module_name, "") is not None

    def test_the_optional_dependency_stays_optional_by_default(self, monkeypatch):
        """The #1383 guarantee, re-asserted against the wider check.

        With the env unset and the SDK present, the runtime question must
        return "native" and ``_require_litellm`` must not be consulted at all —
        "does not raise" is vacuous here because litellm IS installed in this
        venv.
        """
        import mesh.helpers as helpers

        calls = []
        monkeypatch.setattr(
            helpers,
            "_require_litellm",
            lambda *a, **k: calls.append(k) or object(),
        )
        _hide_litellm(monkeypatch)
        module_name = "_test_llm_provider_native_default_no_import"
        with _module_with_app(module_name) as mod:
            _declare_provider(mod, module_name, "anthropic/claude-sonnet-4-5")

        assert calls == []

    def test_the_runtime_question_does_not_burn_the_dispatch_log_latches(
        self, monkeypatch
    ):
        """Registration asks, but must not narrate.

        ``has_native()`` fires two once-per-process latches — the
        dispatch-status DEBUG record and the SDK-fallback INFO nudge — and both
        exist to mark the first *dispatch* decision. Asking it at decoration
        time would move those records away from the event they describe and
        pre-arm them under the tests that assert on them, which is why the
        startup check uses ``native_dispatch_blocker()`` instead.
        """
        from _mcp_mesh.engine.provider_handlers import claude_handler

        monkeypatch.setattr(claude_handler, "_DISPATCH_STATUS_LOGGED", False)
        native = _hide_vendor_sdk(monkeypatch, "anthropic")
        fallback_calls = []
        monkeypatch.setattr(
            native, "log_fallback_once", lambda: fallback_calls.append(1)
        )

        module_name = "_test_llm_provider_latches_untouched"
        with _module_with_app(module_name) as mod:
            _declare_provider(mod, module_name, "anthropic/claude-sonnet-4-5")

        assert claude_handler._DISPATCH_STATUS_LOGGED is False
        assert fallback_calls == []

    def test_the_dispatch_decision_still_logs(self, monkeypatch):
        """The negative control: the latches are not dead, only unasked.

        ``has_native()`` — what a real dispatch calls — must still fire both.
        """
        from _mcp_mesh.engine.provider_handlers import (
            ProviderHandlerRegistry,
            claude_handler,
        )

        monkeypatch.setattr(claude_handler, "_DISPATCH_STATUS_LOGGED", False)
        native = _hide_vendor_sdk(monkeypatch, "anthropic")
        fallback_calls = []
        monkeypatch.setattr(native, "is_fallback_logged", lambda: False)
        monkeypatch.setattr(
            native, "log_fallback_once", lambda: fallback_calls.append(1)
        )

        handler = ProviderHandlerRegistry.get_handler("anthropic")
        assert handler.has_native() is False

        assert claude_handler._DISPATCH_STATUS_LOGGED is True
        assert fallback_calls == [1]


class TestNativeDispatchBlocker:
    """The handler-level runtime question, in isolation."""

    def test_reports_none_when_native_dispatch_will_happen(self):
        from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry

        handler = ProviderHandlerRegistry.get_handler("anthropic")
        assert handler.native_dispatch_blocker() is None

    def test_reports_the_env_opt_out(self, monkeypatch):
        from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry

        _disable_native_dispatch(monkeypatch)
        handler = ProviderHandlerRegistry.get_handler("openai")
        assert handler.native_dispatch_blocker() == "disabled-by-env"

    def test_reports_a_missing_sdk(self, monkeypatch):
        from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry

        _hide_vendor_sdk(monkeypatch, "gemini")
        handler = ProviderHandlerRegistry.get_handler("gemini")
        assert handler.native_dispatch_blocker() == "sdk-missing"

    def test_the_env_opt_out_outranks_a_missing_sdk(self, monkeypatch):
        """Same precedence ``has_native()`` has always had: an explicit
        opt-out is answered without probing the SDK at all."""
        from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry

        _disable_native_dispatch(monkeypatch)
        _hide_vendor_sdk(monkeypatch, "anthropic")
        handler = ProviderHandlerRegistry.get_handler("anthropic")
        assert handler.native_dispatch_blocker() == "disabled-by-env"

    def test_reports_a_vendor_with_no_adapter(self):
        from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry

        handler = ProviderHandlerRegistry.get_handler("cohere")
        assert handler.native_dispatch_blocker() == "no-adapter"

    def test_has_native_agrees_with_it(self, monkeypatch):
        """One verdict, two call sites — ``has_native()`` adds only logging."""
        from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry

        handler = ProviderHandlerRegistry.get_handler("openai")
        assert handler.has_native() is (handler.native_dispatch_blocker() is None)

        _disable_native_dispatch(monkeypatch)
        assert handler.has_native() is (handler.native_dispatch_blocker() is None)
        assert handler.has_native() is False
