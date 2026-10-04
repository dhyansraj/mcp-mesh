"""Issue #1610: ``dependency_kwargs`` is TypeScript-only.

Every mesh decorator that takes ``**kwargs`` used to fold them verbatim into
something real: advertised producer / route / surface metadata, or (for
``@mesh.llm`` and ``mesh.llm_provider``) model parameters sent to the vendor.
So the documented-for-TypeScript ``dependency_kwargs`` was swallowed silently
on Python. It is now dropped before it reaches any of those, and the runtime
says so with one WARNING per decorated target.
"""

import logging
import sys
import types

import pytest

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from mesh import decorators

WARNING_TEXT = "dependency_kwargs is not supported by the Python runtime and is ignored"


def _clear():
    DecoratorRegistry.clear_all()
    decorators._DEPENDENCY_KWARGS_WARNED.clear()
    from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

    clear_debounce_coordinator()


def _warnings(caplog):
    return [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and WARNING_TEXT in r.getMessage()
    ]


@pytest.fixture(autouse=True)
def _isolate(caplog):
    _clear()
    caplog.set_level(logging.WARNING, logger="mesh.decorators")
    yield
    _clear()


class TestToolDependencyKwargs:
    def test_not_advertised_as_producer_metadata(self):
        @mesh.tool(
            capability="report",
            dependencies=["slow_service"],
            dependency_kwargs={"slow_service": {"timeout": 60}},
        )
        def report(slow_service: mesh.McpMeshTool = None):
            return "ok"

        meta = DecoratorRegistry.get_mesh_tools()["report"].metadata
        assert "dependency_kwargs" not in meta

    def test_other_kwargs_still_reach_metadata(self):
        @mesh.tool(capability="report", dependency_kwargs={"x": {}}, vendor="acme")
        def report():
            return "ok"

        meta = DecoratorRegistry.get_mesh_tools()["report"].metadata
        assert meta["vendor"] == "acme"
        assert "dependency_kwargs" not in meta

    def test_warns_once_naming_the_tool(self, caplog):
        @mesh.tool(capability="report", dependency_kwargs={"dep": {"timeout": 5}})
        def report():
            return "ok"

        found = _warnings(caplog)
        assert len(found) == 1
        assert "@mesh.tool 'report'" in found[0].getMessage()

    def test_warns_once_per_tool_not_once_per_process(self, caplog):
        @mesh.tool(capability="first", dependency_kwargs={})
        def first():
            return "ok"

        @mesh.tool(capability="second", dependency_kwargs={})
        def second():
            return "ok"

        assert len(_warnings(caplog)) == 2

    def test_no_warning_without_dependency_kwargs(self, caplog):
        @mesh.tool(capability="plain", dependencies=["dep"])
        def plain(dep: mesh.McpMeshTool = None):
            return "ok"

        assert _warnings(caplog) == []


class TestOtherDecorators:
    def test_route(self, caplog):
        @mesh.route(dependencies=["weather-api"], dependency_kwargs={"weather-api": {}})
        async def handler(weather: mesh.McpMeshTool = None):
            return "ok"

        assert "dependency_kwargs" not in handler._mesh_route_metadata
        found = _warnings(caplog)
        assert len(found) == 1 and "@mesh.route 'handler'" in found[0].getMessage()

    def test_a2a(self, caplog):
        @mesh.a2a(path="/agents/foo", dependency_kwargs={})
        def f():
            pass

        meta = DecoratorRegistry.get_all_by_type("mesh_a2a")["f"].metadata
        assert "dependency_kwargs" not in meta
        assert len(_warnings(caplog)) == 1

    def test_agent(self, caplog):
        @mesh.agent(name="kw-agent", dependency_kwargs={})
        class KwAgent:
            pass

        meta = DecoratorRegistry.get_mesh_agents()["KwAgent"].metadata
        assert "dependency_kwargs" not in meta
        found = _warnings(caplog)
        assert len(found) == 1 and "@mesh.agent 'KwAgent'" in found[0].getMessage()

    def test_llm_does_not_forward_it_as_a_model_param(self, caplog):
        @mesh.llm(provider={"capability": "llm"}, dependency_kwargs={}, temperature=0.2)
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
            return llm(message)

        (agent_data,) = DecoratorRegistry.get_mesh_llm_agents().values()
        assert "dependency_kwargs" not in agent_data.config
        assert agent_data.config["temperature"] == 0.2
        found = _warnings(caplog)
        assert len(found) == 1 and "@mesh.llm 'chat'" in found[0].getMessage()

    def test_llm_provider_does_not_forward_it_to_the_vendor(self, caplog):
        from mesh import helpers

        real = helpers.llm_provider

        module = types.ModuleType("_t1610_provider")
        from fastmcp import FastMCP

        module.app = FastMCP("_t1610_provider")
        sys.modules["_t1610_provider"] = module
        try:
            namespace: dict = {"__name__": "_t1610_provider"}
            exec(compile("def chat():\n    pass\n", "/agent/t1610.py", "exec"), namespace)
            chat = namespace["chat"]

            decorator = real(
                model="anthropic/claude-3-5-haiku-20241022",
                capability="llm",
                dependency_kwargs={"x": {}},
                max_tokens=64,
            )
            # The decorator closes over the remaining litellm kwargs; prove the
            # key is gone from them before any provider call could use it.
            cells = [c.cell_contents for c in (decorator.__closure__ or ())]
            litellm_kwargs = [c for c in cells if isinstance(c, dict) and "max_tokens" in c]
            assert litellm_kwargs and "dependency_kwargs" not in litellm_kwargs[0]
            decorator(chat)
        finally:
            sys.modules.pop("_t1610_provider", None)

        found = _warnings(caplog)
        assert len(found) == 1 and "@mesh.llm_provider 'chat'" in found[0].getMessage()
