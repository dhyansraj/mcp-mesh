"""Issue #1610: ``dependency_kwargs`` is TypeScript-only.

``@mesh.tool`` takes ``**kwargs`` and used to fold them verbatim into the
producer's metadata, so the documented-for-TypeScript ``dependency_kwargs``
was swallowed silently on Python: advertised to the registry as opaque
producer metadata, with no effect on any consumer. It is now dropped from the
advertised kwargs and the runtime says so with one WARNING per tool.
"""

import logging

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


class TestDependencyKwargsIgnored:
    def setup_method(self):
        _clear()

    def teardown_method(self):
        _clear()

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
        @mesh.tool(
            capability="report",
            dependency_kwargs={"x": {}},
            vendor="acme",
        )
        def report():
            return "ok"

        meta = DecoratorRegistry.get_mesh_tools()["report"].metadata
        assert meta["vendor"] == "acme"
        assert "dependency_kwargs" not in meta

    def test_warns_once_naming_the_tool(self, caplog):
        caplog.set_level(logging.WARNING, logger="mesh.decorators")

        @mesh.tool(capability="report", dependency_kwargs={"dep": {"timeout": 5}})
        def report():
            return "ok"

        found = _warnings(caplog)
        assert len(found) == 1
        assert "report" in found[0].getMessage()

    def test_warns_once_per_tool_not_once_per_process(self, caplog):
        caplog.set_level(logging.WARNING, logger="mesh.decorators")

        @mesh.tool(capability="first", dependency_kwargs={})
        def first():
            return "ok"

        @mesh.tool(capability="second", dependency_kwargs={})
        def second():
            return "ok"

        assert len(_warnings(caplog)) == 2

    def test_no_warning_without_dependency_kwargs(self, caplog):
        caplog.set_level(logging.WARNING, logger="mesh.decorators")

        @mesh.tool(capability="plain", dependencies=["dep"])
        def plain(dep: mesh.McpMeshTool = None):
            return "ok"

        assert _warnings(caplog) == []
