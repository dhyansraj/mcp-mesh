"""Issue #1442: two declarations may not advertise the same MCP tool name.

``DecoratorRegistry.register_mesh_tool`` stored tools with a bare
``cls._mesh_tools[func.__name__] = decorated_func``. The advertised tool name IS
the wire name — the heartbeat ships ``func.__name__`` as the tool's
``function_name`` and a client's ``tools/call`` sends it straight back as
``params.name`` — so a second function of the same name in another module did
not shadow the first harmlessly: it replaced it, and the loser never reached
the heartbeat while still looking registered to whoever wrote it.

The guard fails at registration (i.e. at import, when the decorator fires) and
names both declaration sites. Its discriminator is the DECLARATION, not the
function object, which is what keeps it off the legitimate re-registration
paths — see ``test_dual_module_reregistration_is_not_a_collision``.
"""

import pytest

from _mcp_mesh.engine.decorator_registry import DecoratorRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    DecoratorRegistry.clear_all()
    yield
    DecoratorRegistry.clear_all()


def _metadata(capability: str) -> dict:
    return {
        "capability": capability,
        "tags": [],
        "version": "1.0.0",
        "dependencies": [],
    }


# ---------------------------------------------------------------------------
# Genuine collision
# ---------------------------------------------------------------------------


def test_two_different_functions_sharing_a_tool_name_raise():
    """Two `analyze` functions from different modules → startup error."""

    # Two genuinely separate declarations: distinct source files, distinct
    # module names — exactly the "two classes both define `analyze`" shape from
    # the issue, expressed in Python's module namespace.
    src = "def analyze(text: str) -> str:\n    return text\n"
    first = _load(src, "/agent/pkg_a/tools.py", "pkg_a.tools")["analyze"]
    second = _load(src, "/agent/pkg_b/tools.py", "pkg_b.tools")["analyze"]

    DecoratorRegistry.register_mesh_tool(first, _metadata("analyze-a"))

    with pytest.raises(ValueError) as excinfo:
        DecoratorRegistry.register_mesh_tool(second, _metadata("analyze-b"))

    message = str(excinfo.value)
    assert "'analyze'" in message, message
    assert "pkg_a.tools.analyze" in message, message
    assert "pkg_b.tools.analyze" in message, message


def test_two_same_named_methods_on_different_classes_raise():
    """The qualname case: `A.analyze` and `B.analyze` both advertise `analyze`."""

    class A:
        def analyze(self):
            return "a"

    class B:
        def analyze(self):
            return "b"

    DecoratorRegistry.register_mesh_tool(A.analyze, _metadata("a-analyze"))

    with pytest.raises(ValueError) as excinfo:
        DecoratorRegistry.register_mesh_tool(B.analyze, _metadata("b-analyze"))

    message = str(excinfo.value)
    assert "A.analyze" in message, message
    assert "B.analyze" in message, message


def test_the_first_registration_survives_a_rejected_second():
    """The winner must not be half-replaced by the raise."""

    class A:
        def analyze(self):
            return "a"

    class B:
        def analyze(self):
            return "b"

    DecoratorRegistry.register_mesh_tool(A.analyze, _metadata("a-analyze"))
    with pytest.raises(ValueError):
        DecoratorRegistry.register_mesh_tool(B.analyze, _metadata("b-analyze"))

    registered = DecoratorRegistry.get_mesh_tools()["analyze"]
    assert registered.metadata["capability"] == "a-analyze"


# ---------------------------------------------------------------------------
# Idempotent re-registration is NOT a collision (the PR #1445 regression guard)
# ---------------------------------------------------------------------------


def test_same_function_reregistered_is_tolerated():
    def greet(name: str) -> str:
        return name

    DecoratorRegistry.register_mesh_tool(greet, _metadata("greet"))
    DecoratorRegistry.register_mesh_tool(greet, _metadata("greet"))

    assert "greet" in DecoratorRegistry.get_mesh_tools()


def _load(source: str, filename: str, module_name: str):
    """Independently compile+exec `source`, as a real second import would."""
    namespace: dict = {"__name__": module_name}
    # A separate compile() per load: the same file read twice produces two
    # distinct code objects that AGREE on (co_filename, co_firstlineno). Sharing
    # one compiled object between both namespaces would make the test pass
    # trivially, whatever the discriminator.
    exec(compile(source, filename, "exec"), namespace)
    return namespace


def test_reexecuted_module_is_tolerated():
    """`importlib.reload`-style re-execution produces a NEW function object.

    Object identity would boot-fail this; the declaration identity (source
    coordinates) does not.
    """
    src = "def greet(name):\n    return name\n"
    first = _load(src, "/agent/greetings.py", "greetings")
    second = _load(src, "/agent/greetings.py", "greetings")

    assert first["greet"] is not second["greet"]
    assert first["greet"].__code__ is not second["greet"].__code__

    DecoratorRegistry.register_mesh_tool(first["greet"], _metadata("greet"))
    DecoratorRegistry.register_mesh_tool(second["greet"], _metadata("greet"))

    assert "greet" in DecoratorRegistry.get_mesh_tools()


def test_dual_module_reregistration_is_not_a_collision():
    """The `__main__.X` / `<module>.X` footgun (issue #1031) must NOT trip here.

    ``python main.py`` plus a sibling's ``from main import X`` evaluates main.py
    twice as two distinct module objects, so ``__module__`` differs (``__main__``
    vs ``main``) for the SAME declaration. That case has its own dedicated
    diagnostic in ``pipeline.mcp_startup.dual_module_check``, which explains the
    restructure-as-a-package fix; a generic "duplicate tool name" error raised
    here would pre-empt it with a much worse message.
    """
    src = "def greet(name):\n    return name\n"
    main_ns = _load(src, "/agent/main.py", "__main__")
    reimport_ns = _load(src, "/agent/main.py", "main")

    assert main_ns["greet"].__module__ == "__main__"
    assert reimport_ns["greet"].__module__ == "main"
    assert main_ns["greet"].__code__ is not reimport_ns["greet"].__code__

    DecoratorRegistry.register_mesh_tool(main_ns["greet"], _metadata("greet"))
    DecoratorRegistry.register_mesh_tool(reimport_ns["greet"], _metadata("greet"))

    assert "greet" in DecoratorRegistry.get_mesh_tools()


def test_dual_module_tolerated_even_when_the_two_loads_spell_the_path_differently():
    """The entry script and the re-import need not agree on `co_filename`.

    ``python main.py`` can report the path as given on the command line while
    the later ``import main`` reports the resolved one. Source coordinates then
    disagree for what is still ONE declaration, so the guard falls back to the
    same conservative rule ``dual_module_detection`` uses: exactly one side is
    ``__main__``, and both name the same function.
    """
    src = "def greet(name):\n    return name\n"
    main_ns = _load(src, "main.py", "__main__")
    reimport_ns = _load(src, "/agent/main.py", "main")

    assert main_ns["greet"].__code__.co_filename != (
        reimport_ns["greet"].__code__.co_filename
    )

    DecoratorRegistry.register_mesh_tool(main_ns["greet"], _metadata("greet"))
    DecoratorRegistry.register_mesh_tool(reimport_ns["greet"], _metadata("greet"))

    assert "greet" in DecoratorRegistry.get_mesh_tools()


def test_two_ordinary_modules_are_still_a_collision():
    """The dual-module tolerance must not become a blanket same-name pass.

    Neither side is ``__main__``, so this is the plain two-modules-define-
    `analyze` case the guard exists to catch.
    """
    src = "def analyze(text):\n    return text\n"
    a = _load(src, "/agent/pkg_a/tools.py", "pkg_a.tools")
    b = _load(src, "/agent/pkg_b/tools.py", "pkg_b.tools")

    DecoratorRegistry.register_mesh_tool(a["analyze"], _metadata("a"))
    with pytest.raises(ValueError, match="Duplicate MCP tool name 'analyze'"):
        DecoratorRegistry.register_mesh_tool(b["analyze"], _metadata("b"))


def test_wrapper_reregistration_is_tolerated():
    """A functools.wraps wrapper is the same declaration as what it wraps.

    ``@mesh.tool`` registers the original function and then swaps in the
    injection wrapper; a later pass registering the wrapper must not read as a
    second declaration.
    """
    import functools

    def greet(name: str) -> str:
        return name

    @functools.wraps(greet)
    def wrapper(*args, **kwargs):
        return greet(*args, **kwargs)

    DecoratorRegistry.register_mesh_tool(greet, _metadata("greet"))
    DecoratorRegistry.register_mesh_tool(wrapper, _metadata("greet"))

    assert "greet" in DecoratorRegistry.get_mesh_tools()


def test_unregistered_name_can_be_claimed_again():
    """Decoration-failure cleanup must release the name, not poison it."""

    class A:
        def analyze(self):
            return "a"

    class B:
        def analyze(self):
            return "b"

    DecoratorRegistry.register_mesh_tool(A.analyze, _metadata("a-analyze"))
    DecoratorRegistry.unregister_mesh_tool("analyze")

    DecoratorRegistry.register_mesh_tool(B.analyze, _metadata("b-analyze"))
    assert DecoratorRegistry.get_mesh_tools()["analyze"].metadata["capability"] == (
        "b-analyze"
    )


def test_clear_all_releases_claimed_names():
    class A:
        def analyze(self):
            return "a"

    class B:
        def analyze(self):
            return "b"

    DecoratorRegistry.register_mesh_tool(A.analyze, _metadata("a-analyze"))
    DecoratorRegistry.clear_all()

    DecoratorRegistry.register_mesh_tool(B.analyze, _metadata("b-analyze"))
    assert "analyze" in DecoratorRegistry.get_mesh_tools()


def test_direct_mesh_tools_manipulation_cannot_desync_the_guard():
    """`_mesh_tools` IS the claimed-name index — there is no side table.

    Several test harnesses snapshot / clear / restore `_mesh_tools` directly.
    A parallel dict would keep a name claimed that `_mesh_tools` no longer
    holds, and the guard would refuse a name nothing owns.
    """
    src = "def analyze(text):\n    return text\n"
    a = _load(src, "/agent/pkg_a/tools.py", "pkg_a.tools")["analyze"]
    b = _load(src, "/agent/pkg_b/tools.py", "pkg_b.tools")["analyze"]

    DecoratorRegistry.register_mesh_tool(a, _metadata("a"))
    DecoratorRegistry._mesh_tools.clear()

    DecoratorRegistry.register_mesh_tool(b, _metadata("b"))
    assert DecoratorRegistry.get_mesh_tools()["analyze"].metadata["capability"] == "b"


def test_collision_is_caught_after_the_wrapper_swap():
    """The stored function becomes the injection WRAPPER — still discriminates.

    `@mesh.tool` calls `update_mesh_tool_function` right after registration, so
    by the time a second declaration arrives the registry no longer holds the
    original function. Both wrapper layers use `functools.wraps`, so the guard
    unwraps back to the declaration.
    """
    import functools

    src = "def analyze(text):\n    return text\n"
    a = _load(src, "/agent/pkg_a/tools.py", "pkg_a.tools")["analyze"]
    b = _load(src, "/agent/pkg_b/tools.py", "pkg_b.tools")["analyze"]

    DecoratorRegistry.register_mesh_tool(a, _metadata("a"))

    @functools.wraps(a)
    def injection_wrapper(*args, **kwargs):
        return a(*args, **kwargs)

    DecoratorRegistry.update_mesh_tool_function("analyze", injection_wrapper)

    with pytest.raises(ValueError, match="Duplicate MCP tool name 'analyze'"):
        DecoratorRegistry.register_mesh_tool(b, _metadata("b"))


# ---------------------------------------------------------------------------
# Factory-built tools: @mesh.llm_provider (issue #227 / #1442)
# ---------------------------------------------------------------------------


def _fake_llm_provider_tool(user_func):
    """Reproduce `mesh.llm_provider`'s shape: ONE shared nested closure.

    Every provider in a process is the same `process_chat` def, renamed to the
    user's function name (the issue #227 fix). Its own source coordinates are
    therefore identical for every provider — hence the origin stamp.
    """

    async def process_chat(request):
        return await user_func(request)

    process_chat.__name__ = user_func.__name__
    process_chat.__qualname__ = user_func.__qualname__
    process_chat._mesh_declaration_origin = user_func
    return process_chat


def test_two_llm_providers_sharing_a_function_name_collide():
    """The collision `helpers.py`'s #227 comment is about.

    Without the origin stamp both providers resolve to the SAME nested closure
    (same file, same line), compare equal, and the second silently replaces the
    first — the guard would be inert for the exact case it was built for.
    """
    src = "async def chat(request):\n    return request\n"
    first_user = _load(src, "/agent/claude.py", "agent.claude")["chat"]
    second_user = _load(src, "/agent/gpt.py", "agent.gpt")["chat"]

    first = _fake_llm_provider_tool(first_user)
    second = _fake_llm_provider_tool(second_user)
    # The tool functions themselves are indistinguishable by source.
    assert first.__code__ is second.__code__
    assert first.__name__ == second.__name__ == "chat"

    DecoratorRegistry.register_mesh_tool(first, _metadata("llm-claude"))
    with pytest.raises(ValueError) as excinfo:
        DecoratorRegistry.register_mesh_tool(second, _metadata("llm-gpt"))

    message = str(excinfo.value)
    assert "claude.py" in message, message
    assert "gpt.py" in message, message


def test_one_llm_provider_reregistered_is_still_tolerated():
    src = "async def chat(request):\n    return request\n"
    user = _load(src, "/agent/claude.py", "agent.claude")["chat"]

    DecoratorRegistry.register_mesh_tool(
        _fake_llm_provider_tool(user), _metadata("llm-claude")
    )
    DecoratorRegistry.register_mesh_tool(
        _fake_llm_provider_tool(user), _metadata("llm-claude")
    )

    assert "chat" in DecoratorRegistry.get_mesh_tools()


def test_real_llm_provider_decorator_rejects_two_providers_named_the_same():
    """End-to-end through the real `mesh.llm_provider`, not a stand-in.

    Links the stand-in above to the shipping decorator: `helpers.py` must stamp
    the origin, or this pair is invisible to the guard.
    """
    import sys
    import types

    from fastmcp import FastMCP

    import mesh

    src = "def chat():\n    pass\n"
    modules = []
    try:
        for module_name, filename in (
            ("_t1442_provider_a", "/agent/a.py"),
            ("_t1442_provider_b", "/agent/b.py"),
        ):
            module = types.ModuleType(module_name)
            module.app = FastMCP(module_name)
            sys.modules[module_name] = module
            modules.append(module_name)

        first = _load(src, "/agent/a.py", "_t1442_provider_a")["chat"]
        second = _load(src, "/agent/b.py", "_t1442_provider_b")["chat"]

        mesh.llm_provider(
            model="anthropic/claude-3-5-haiku-20241022", capability="llm-a"
        )(first)

        with pytest.raises(ValueError) as excinfo:
            mesh.llm_provider(model="openai/gpt-4o-mini", capability="llm-b")(second)
        assert "Duplicate MCP tool name 'chat'" in str(excinfo.value)
    finally:
        for module_name in modules:
            sys.modules.pop(module_name, None)


def test_llm_provider_origin_survives_the_wrapper_layers():
    """`functools.wraps` copies `__dict__`, so the stamp reaches every layer."""
    import functools

    src = "async def chat(request):\n    return request\n"
    user = _load(src, "/agent/claude.py", "agent.claude")["chat"]
    provider = _fake_llm_provider_tool(user)

    @functools.wraps(provider)
    async def injection_wrapper(*args, **kwargs):
        return await provider(*args, **kwargs)

    assert injection_wrapper._mesh_declaration_origin is user

    other = _fake_llm_provider_tool(_load(src, "/agent/gpt.py", "agent.gpt")["chat"])
    DecoratorRegistry.register_mesh_tool(injection_wrapper, _metadata("llm-claude"))
    with pytest.raises(ValueError):
        DecoratorRegistry.register_mesh_tool(other, _metadata("llm-gpt"))


# ---------------------------------------------------------------------------
# A normal agent must not trip the guard
# ---------------------------------------------------------------------------


def test_jobs_helper_registration_is_idempotent_across_passes():
    """`_make_helper_tools` builds FRESH closures on every call.

    The pipeline step can run more than once in a process (context restart,
    repeated pipeline execution); the three helper names must not collide with
    themselves.
    """
    from _mcp_mesh.pipeline.mcp_startup.jobs_helper_tools import _make_helper_tools

    first = _make_helper_tools("http://registry:8000")
    second = _make_helper_tools("http://registry:8000")
    assert first["__mesh_job_status"] is not second["__mesh_job_status"]

    for helpers in (first, second):
        for name, fn in helpers.items():
            DecoratorRegistry.register_mesh_tool(fn, _metadata(name))

    tools = DecoratorRegistry.get_mesh_tools()
    assert {"__mesh_job_status", "__mesh_job_result", "__mesh_job_cancel"} <= set(tools)


@pytest.mark.asyncio
async def test_jobs_helper_does_not_clobber_a_user_tool_of_the_same_name():
    """A user tool named `__mesh_job_status` must survive on BOTH surfaces.

    `_register_on_fastmcp` runs before the DecoratorRegistry registration, so
    the helper used to overwrite the user's tool on the wire and only then hit
    the guard — whose ValueError was swallowed by an `except Exception` →
    warning. Net effect: the user's tool unreachable via MCP, still advertised
    in the heartbeat.
    """
    from _mcp_mesh.pipeline.mcp_startup.jobs_helper_tools import JobsHelperToolsStep

    src = "async def __mesh_job_status(job_id):\n    return {'mine': True}\n"
    user_tool = _load(src, "/agent/main.py", "__main__")["__mesh_job_status"]
    DecoratorRegistry.register_mesh_tool(user_tool, _metadata("__mesh_job_status"))

    registered_on_fastmcp: list[str] = []

    class _FakeFastMCP:
        def tool(self, name: str, description: str = ""):
            def _decorator(fn):
                registered_on_fastmcp.append(name)
                return fn

            return _decorator

    result = await JobsHelperToolsStep().execute(
        {
            "registry_url": "http://registry:8000",
            "fastmcp_servers": {"default": _FakeFastMCP()},
        }
    )

    assert result.status.name != "FAILED", result.message
    assert "__mesh_job_status" not in registered_on_fastmcp, (
        "the contested helper must not be registered on the FastMCP server — "
        "that is what makes the user's tool unreachable"
    )
    assert {"__mesh_job_result", "__mesh_job_cancel"} <= set(
        registered_on_fastmcp
    ), "the other two helpers are uncontested and must still register"

    # The user's tool still owns the name in the heartbeat catalog.
    surviving = DecoratorRegistry.get_mesh_tools()["__mesh_job_status"]
    assert surviving.metadata.get("framework_internal") is None


@pytest.mark.asyncio
async def test_jobs_helper_step_registers_all_three_when_uncontested():
    from _mcp_mesh.pipeline.mcp_startup.jobs_helper_tools import JobsHelperToolsStep

    registered_on_fastmcp: list[str] = []

    class _FakeFastMCP:
        def tool(self, name: str, description: str = ""):
            def _decorator(fn):
                registered_on_fastmcp.append(name)
                return fn

            return _decorator

    await JobsHelperToolsStep().execute(
        {
            "registry_url": "http://registry:8000",
            "fastmcp_servers": {"default": _FakeFastMCP()},
        }
    )

    assert set(registered_on_fastmcp) == {
        "__mesh_job_status",
        "__mesh_job_result",
        "__mesh_job_cancel",
    }
    assert {"__mesh_job_status", "__mesh_job_result", "__mesh_job_cancel"} <= set(
        DecoratorRegistry.get_mesh_tools()
    )


def test_distinct_tool_names_coexist():
    def greet(name: str) -> str:
        return name

    def farewell(name: str) -> str:
        return name

    DecoratorRegistry.register_mesh_tool(greet, _metadata("greet"))
    DecoratorRegistry.register_mesh_tool(farewell, _metadata("farewell"))

    assert set(DecoratorRegistry.get_mesh_tools()) == {"greet", "farewell"}
