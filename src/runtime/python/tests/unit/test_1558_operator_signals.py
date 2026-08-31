"""Issue #1558 — two operator-visible signals that went silent in 3.7.0.

Neither regression broke behaviour, which is why review missed both and a full
integration run caught them. Both are the same shape: a change that quietly
removed a line an operator reads, while the code around it kept working.

  * #1552 added a three-rung annotation-resolution ladder. The last rung —
    match the annotation as written — means an UNRESOLVABLE annotation no
    longer raises out of the scan, so a broken type hint stopped being
    reported at all. The rung stays (without it a ``TYPE_CHECKING``-only
    import hard-fails at import, which is #1548 relocated); what comes back is
    the diagnostic on the way past.

  * #1555 asks ``ProviderHandlerRegistry`` for a handler at DECORATION time to
    reach ``native_dispatch_blocker()``. That warmed the instance cache, so the
    "✅ Selected <handler> for vendor: <vendor>" line — logged on a cache MISS —
    moved from the first dispatch to import time, and every dispatch after it
    took the cache-hit branch at DEBUG.

The integration tests that failed are ``uc02_tools/tc24_invalid_type_hint_warning_py``
and ``uc04_llm_integration/tc34_vertex_provider_py``. Both grep an agent log, so
the assertions below pin the same literal substrings those greps use: a
reworded message is a broken test there and must be a broken test here.
"""

import logging
import sys
import types
from contextlib import contextmanager

import pytest

from _mcp_mesh.engine import signature_analyzer
from _mcp_mesh.engine.provider_handlers import ProviderHandlerRegistry
from _mcp_mesh.engine.signature_analyzer import (
    get_llm_agent_parameter_names,
    get_mesh_agent_parameter_names,
    get_mesh_agent_positions,
)
from mesh.types import McpMeshTool

SIGNATURE_LOGGER = "_mcp_mesh.engine.signature_analyzer"
REGISTRY_LOGGER = "_mcp_mesh.engine.provider_handlers.provider_handler_registry"

#: The literal ``tc24`` greps for (``WARNING.*Failed to analyze signature for``).
TC24_SUBSTRING = "Failed to analyze signature for"

#: The literal ``tc34`` asserts on.
TC34_SUBSTRING = "GeminiHandler for vendor: vertex_ai"


# ===========================================================================
# 1. An unresolvable annotation must still be reported
# ===========================================================================


@pytest.fixture
def scan_warnings(caplog):
    """WARNING records from the signature analyzer, with the latch re-armed.

    The warning fires once per function per PROCESS, so a test that did not
    clear the latch would pass or fail depending on what ran before it.

    ``getattr`` rather than a direct reference so a build with no latch at all
    — main before this fix — fails on the missing WARNING, which is the
    regression, instead of erroring in setup on a missing private name.
    """
    latch = getattr(signature_analyzer, "_unresolved_warned", set())
    latch.clear()
    caplog.set_level(logging.WARNING, logger=SIGNATURE_LOGGER)
    yield caplog
    latch.clear()


def _warnings(caplog):
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == SIGNATURE_LOGGER and r.levelno == logging.WARNING
    ]


class TestUnresolvableAnnotationIsReported:
    def test_unresolvable_annotation_warns(self, scan_warnings):
        """The tc24 agent's declaration, verbatim.

        Before #1552 this reached the scan's ``except`` and warned. After it,
        the annotation resolves to itself, matches no mesh type, and the
        parameter was skipped in silence — the user's typo reported nowhere.
        """

        def ping(value: "NonExistentType") -> str:  # noqa: F821
            return "pong"

        assert get_mesh_agent_parameter_names(ping) == []

        messages = _warnings(scan_warnings)
        assert len(messages) == 1
        assert TC24_SUBSTRING in messages[0]
        assert "NonExistentType" in messages[0]

    def test_resolvable_annotations_do_not_warn(self, scan_warnings):
        """The signal has to stay rare enough to mean something: a signature
        whose annotations all resolve must produce nothing."""

        def ok(value: str, dep: McpMeshTool = None) -> str:
            return value

        assert get_mesh_agent_parameter_names(ok) == ["dep"]
        assert _warnings(scan_warnings) == []

    def test_warns_once_per_function_across_repeated_scans(self, scan_warnings):
        """Warn-once, not warn-per-scan.

        A function is scanned several times — once per predicate at decoration
        (tool / LLM / job), then again on every dependency-resolution pass for
        the life of the process. The text never changes, so repeating it would
        turn a startup-time authoring error into recurring noise.
        """

        def ping(value: "NonExistentType") -> str:  # noqa: F821
            return "pong"

        for _ in range(3):
            get_mesh_agent_parameter_names(ping)
            get_mesh_agent_positions(ping)
            get_llm_agent_parameter_names(ping)

        assert len(_warnings(scan_warnings)) == 1

    def test_a_second_function_gets_its_own_warning(self, scan_warnings):
        """The latch is per function, not a global one-shot — two broken
        signatures are two authoring errors and each has to be reported."""

        def first(value: "MissingOne") -> str:  # noqa: F821
            return "x"

        def second(value: "MissingTwo") -> str:  # noqa: F821
            return "x"

        get_mesh_agent_parameter_names(first)
        get_mesh_agent_parameter_names(second)

        messages = _warnings(scan_warnings)
        assert len(messages) == 2
        assert any("MissingOne" in m for m in messages)
        assert any("MissingTwo" in m for m in messages)

    def test_closures_from_one_factory_each_get_a_warning(self, scan_warnings):
        """Distinct functions that share a NAME are still distinct errors.

        Every closure a factory returns has the same
        ``module.qualname`` (``…<locals>.handler``), so a name-keyed latch
        reports the first and silences the rest — under-reporting exactly the
        way this warning exists to stop. The latch is keyed on the function
        object, which ``_scan_params`` has already unwrapped to the original
        before the diagnostic sees it.
        """

        def make(missing: str):
            ns: dict = {}
            exec(  # noqa: S102 - building N same-named functions is the point
                f"def handler(value: '{missing}') -> str:\n    return 'x'\n", ns
            )
            handler = ns["handler"]
            handler.__qualname__ = "make.<locals>.handler"
            handler.__module__ = __name__
            return handler

        built = [make("MissingA"), make("MissingB"), make("MissingC")]
        assert len({f.__qualname__ for f in built}) == 1

        for fn in built:
            get_mesh_agent_parameter_names(fn)

        messages = _warnings(scan_warnings)
        assert len(messages) == 3
        for missing in ("MissingA", "MissingB", "MissingC"):
            assert any(missing in m for m in messages)

    def test_a_function_without_a_module_is_still_latched(self, scan_warnings):
        """``exec``-built functions have ``__module__`` None.

        Two of them would collide on the name key ``"None.ask"`` and report as
        one. Identity gets both halves right: a warning each, and still only
        one per function across repeated scans.
        """
        ns_a: dict = {}
        ns_b: dict = {}
        exec("def ask(value: 'MissingX') -> str:\n    return 'x'\n", ns_a)  # noqa: S102
        exec("def ask(value: 'MissingY') -> str:\n    return 'x'\n", ns_b)  # noqa: S102
        assert ns_a["ask"].__module__ is None

        for _ in range(2):
            get_mesh_agent_parameter_names(ns_a["ask"])
            get_mesh_agent_parameter_names(ns_b["ask"])

        messages = _warnings(scan_warnings)
        assert len(messages) == 2
        assert any("MissingX" in m for m in messages)
        assert any("MissingY" in m for m in messages)

    def test_unresolvable_return_annotation_warns(self, scan_warnings):
        """The return annotation is scanned too.

        ``get_type_hints`` is all-or-nothing including the return, so before
        #1552 a broken return raised out of the scan and the operator got the
        warning. It is the half that matters most: a surviving string quietly
        becomes an ``@mesh.llm`` output type and fails the Pydantic-model check
        that drives structured output, with nothing logged.
        """

        def ask(prompt: str) -> "ChatResponse":  # noqa: F821
            return "x"

        assert get_mesh_agent_parameter_names(ask) == []

        messages = _warnings(scan_warnings)
        assert len(messages) == 1
        assert TC24_SUBSTRING in messages[0]
        assert "ChatResponse" in messages[0]
        # Reads as an annotation on its own, not as a stray parameter named
        # "return".
        assert "return type: 'ChatResponse'" in messages[0]

    def test_broken_return_and_parameter_share_one_warning(self, scan_warnings):
        """One signature is one authoring error: both halves in one message,
        not a parameter warning followed by a return warning."""

        def ask(value: "MissingParam") -> "MissingReturn":  # noqa: F821
            return "x"

        get_mesh_agent_parameter_names(ask)

        messages = _warnings(scan_warnings)
        assert len(messages) == 1
        assert "MissingParam" in messages[0]
        assert "return type: 'MissingReturn'" in messages[0]

    def test_a_resolvable_return_annotation_does_not_warn(self, scan_warnings):
        """Carrying the return through the scan must not make a healthy
        signature noisy."""

        def ask(value: str) -> dict[str, int]:
            return {}

        assert get_mesh_agent_parameter_names(ask) == []
        assert _warnings(scan_warnings) == []

    def test_a_diagnostic_failure_cannot_empty_the_scan(self, scan_warnings):
        """The diagnostic is a logging call; it must not be able to become an
        outage.

        The call used to sit inside ``_scan_params``' ``try``, whose
        ``except Exception`` returns ``[]`` — so a raise from it would have
        dropped every typed DI slot on the function, injecting ``None`` where a
        dependency proxy belongs, and reported it as a signature that could not
        be analyzed. Two changes: the call moved after the ``try`` so the
        result is already final, and the diagnostic swallows its own failures.
        """

        def boom(*_args, **_kwargs):
            raise RuntimeError("diagnostic exploded")

        def ping(value: "MissingBoom", dep: McpMeshTool = None) -> str:  # noqa: F821
            return "x"

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(signature_analyzer, "describe_unresolved_annotations", boom)
            assert get_mesh_agent_parameter_names(ping) == ["dep"]
            assert get_mesh_agent_positions(ping) == [1]

        assert _warnings(scan_warnings) == []

    def test_type_checking_only_import_still_binds_and_is_reported(self, scan_warnings):
        """The #1552 rung is not being taken back.

        A ``TYPE_CHECKING``-only mesh import is the case that rung exists for:
        the parameter must still bind. It is also a degraded resolution — the
        name matched as text, not as a type — so the operator is told, once.
        """
        import __future__

        ns: dict = {}
        exec(  # noqa: S102 - PEP 563 semantics are the point of the test
            compile(
                "def ask(prompt: str, dep: McpMeshTool = None) -> str:\n"
                "    return 'x'\n",
                "<pep563>",
                "exec",
                flags=__future__.annotations.compiler_flag,
            ),
            ns,
        )

        assert get_mesh_agent_parameter_names(ns["ask"]) == ["dep"]

        messages = _warnings(scan_warnings)
        assert len(messages) == 1
        assert TC24_SUBSTRING in messages[0]
        assert "McpMeshTool" in messages[0]


# ===========================================================================
# 2. The handler-selection line must survive the startup check
# ===========================================================================


@pytest.fixture
def selection_log(caplog, monkeypatch):
    """INFO records from the handler registry, against a cold cache and the
    default dispatch environment.

    ``_instances`` is class-level and process-wide, so an earlier test that
    resolved ``vertex_ai`` would otherwise pre-warm the very cache these tests
    are about.

    ``MCP_MESH_NATIVE_LLM`` is deleted for the same reason
    ``test_llm_provider_litellm_startup_assertion`` deletes it: it is a real
    operator knob, and a developer running the suite with it exported would
    flip these vendors onto the LiteLLM path and fail the tests for a reason
    that has nothing to do with the code under test.
    """
    monkeypatch.delenv("MCP_MESH_NATIVE_LLM", raising=False)
    ProviderHandlerRegistry.clear_cache()
    caplog.set_level(logging.INFO, logger=REGISTRY_LOGGER)
    yield caplog
    ProviderHandlerRegistry.clear_cache()


def _dispatches_natively(vendor: str) -> bool:
    """Whether ``vendor`` would really dispatch through its native SDK in THIS
    process — i.e. the vendor SDK is importable and native dispatch is not
    switched off.

    Asked through ``probe_handler`` precisely because a guard must not warm the
    cache or emit the selection line these tests are about; the probe is
    verified to answer the same as ``get_handler`` below.
    """
    return (
        ProviderHandlerRegistry.probe_handler(vendor).native_dispatch_blocker() is None
    )


def _selection_lines(caplog):
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == REGISTRY_LOGGER
        and r.levelno == logging.INFO
        and "Selected" in r.getMessage()
    ]


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


class TestSelectionLineSurvivesStartupCheck:
    def test_startup_check_does_not_consume_the_selection_line(self, selection_log):
        """The #1555 caller, asked directly.

        ``_native_dispatch_fallback_reason`` runs at decoration time. Its
        verdict must be unchanged and its cost must be invisible: the record of
        which handler serves ``vertex_ai`` belongs to the first dispatch.

        The verdict is asserted against this process's actual dispatch state
        rather than pinned to ``None``: whether ``vertex_ai`` dispatches
        natively depends on ``google-genai`` being importable, which is a
        property of the install, not of this change. The selection-line
        assertions below hold either way, and they are what the test is for.
        """
        from mesh.helpers import _native_dispatch_fallback_reason

        reason = _native_dispatch_fallback_reason("vertex_ai")
        assert _selection_lines(selection_log) == []

        if _dispatches_natively("vertex_ai"):
            assert reason is None
        else:
            assert reason is not None and "LiteLLM" in reason

        ProviderHandlerRegistry.get_handler("vertex_ai")
        assert [TC34_SUBSTRING in line for line in _selection_lines(selection_log)] == [
            True
        ]

    def test_selection_line_logged_once_after_provider_declaration(self, selection_log):
        """The tc34 path end to end: declare the provider, then dispatch.

        Declaration is where #1555 warmed the cache; the two dispatches after
        it stand in for a served request and a second one. Exactly one
        selection line — the signal is restored without becoming per-call
        noise.

        The declaration is allowed to raise: with ``google-genai`` absent this
        provider falls back to LiteLLM, and the #1551 startup assertion refuses
        the declaration when LiteLLM is not installed either. That verdict is
        the sibling test file's subject; here it is irrelevant, because the
        assertion — declaration emits no selection line — holds whether the
        decorator returns or raises, and the ``probe_handler`` call that could
        have emitted one happens before either outcome.
        """
        import mesh

        module_name = "test_1558_vertex_provider_module"
        with _module_with_app(module_name) as mod:

            def provider():
                pass

            provider.__module__ = module_name
            mod.provider = provider
            try:
                mesh.llm_provider(model="vertex_ai/gemini-2.5-flash", capability="llm")(
                    provider
                )
            except ImportError:
                pass

            assert _selection_lines(selection_log) == []

            ProviderHandlerRegistry.get_handler("vertex_ai")
            ProviderHandlerRegistry.get_handler("vertex_ai")

        lines = _selection_lines(selection_log)
        assert len(lines) == 1
        assert TC34_SUBSTRING in lines[0]

    def test_probe_returns_the_cached_instance_when_one_exists(self, selection_log):
        """A probe after a dispatch must not build a second handler: handlers
        are cached singletons and callers compare identity in places."""
        dispatch_handler = ProviderHandlerRegistry.get_handler("vertex_ai")
        assert ProviderHandlerRegistry.probe_handler("vertex_ai") is dispatch_handler
        assert len(_selection_lines(selection_log)) == 1

    @pytest.mark.parametrize(
        "vendor",
        [
            "anthropic",
            "openai",
            "gemini",
            "vertex_ai",
            # Unregistered / unnormalized vendors: the only branch where
            # ``_instantiate`` passes the vendor string to the constructor, so
            # the only place probe and dispatch could disagree about ``.vendor``.
            "moonshot",
            "acme-llm",
            None,
            "",
            "   ",
            "VERTEX_AI",
            " Anthropic ",
        ],
    )
    def test_probe_resolves_the_same_handler_as_dispatch(self, selection_log, vendor):
        """Silence must not have been bought with a different answer.

        Both sides are resolved from a COLD cache, so the probe returns its
        transient instance rather than the singleton the dispatch just cached —
        comparing a warmed probe against the dispatch that warmed it is
        comparing an object with itself, which would not notice a divergence.
        """
        ProviderHandlerRegistry.clear_cache()
        probed = ProviderHandlerRegistry.probe_handler(vendor)

        ProviderHandlerRegistry.clear_cache()
        dispatched = ProviderHandlerRegistry.get_handler(vendor)

        assert probed is not dispatched
        assert type(probed) is type(dispatched)
        assert probed.vendor == dispatched.vendor
