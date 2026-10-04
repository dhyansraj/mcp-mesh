"""Issue #1593: ``SelfDependencyProxy`` must treat ``headers=`` the way the
remote ``UnifiedMCPProxy.__call__`` does — popped from the kwargs, never handed
to the tool as an argument. A self-call has no wire, so the per-call headers
apply as the invocation's propagated-header scope (allowlist-filtered,
dispatch-only headers scrubbed), which is what a remote callee would see.
"""

import asyncio

from _mcp_mesh.engine.self_dependency_proxy import SelfDependencyProxy
from _mcp_mesh.tracing.context import TraceContext

# Always allowlisted infra header (independent of MCP_MESH_PROPAGATE_HEADERS).
ALLOWED = "x-mesh-timeout"


def setup_function(_fn):
    TraceContext.clear_propagated_headers()


def teardown_function(_fn):
    TraceContext.clear_propagated_headers()


def test_headers_kwarg_is_not_passed_to_the_tool():
    seen = {}

    def tool(**kwargs):
        seen.update(kwargs)
        return "ok"

    proxy = SelfDependencyProxy(tool, "tool")
    assert proxy(a=1, headers={ALLOWED: "30"}) == "ok"
    assert seen == {"a": 1}


def test_headers_apply_as_the_calls_propagated_scope_and_are_restored():
    seen = {}

    def tool(a):
        seen["headers"] = dict(TraceContext.get_propagated_headers())
        return a

    TraceContext.set_propagated_headers({"x-outer": "keep"})
    proxy = SelfDependencyProxy(tool, "tool")
    proxy(
        a=1,
        headers={
            "X-Mesh-Timeout": "30",  # allowlisted, lowercased
            "x-not-allowlisted": "drop",  # filtered like the remote merge
            "x-mesh-job-id": "job-1",  # inbound-only dispatch header (#1570)
        },
    )
    assert seen["headers"]["x-mesh-timeout"] == "30"
    assert "x-not-allowlisted" not in seen["headers"]
    assert "x-mesh-job-id" not in seen["headers"]
    assert seen["headers"]["x-outer"] == "keep"
    # The outer scope is restored after the call.
    assert TraceContext.get_propagated_headers() == {"x-outer": "keep"}


def test_async_target_sees_the_scope_when_awaited():
    seen = {}

    async def tool(a):
        seen["headers"] = dict(TraceContext.get_propagated_headers())
        return a

    proxy = SelfDependencyProxy(tool, "tool")

    async def run():
        return await proxy(a=7, headers={ALLOWED: "5"})

    assert asyncio.run(run()) == 7
    assert seen["headers"][ALLOWED] == "5"


def test_no_headers_kwarg_is_unchanged():
    seen = {}

    def tool(**kwargs):
        seen.update(kwargs)
        return "ok"

    SelfDependencyProxy(tool, "tool")(a=1)
    assert seen == {"a": 1}
