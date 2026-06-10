"""Issue #1162 MED-2: iteration count must be call-local, not instance state.

In non-template mode a single cached ``MeshLlmAgent`` instance is injected
into every invocation of a ``@mesh.llm`` tool, so two concurrent ``__call__``s
share the same object. Before the fix, ``__call__`` reset and incremented
``self._iteration_count`` — one call's reset zeroed the other's mid-loop
counter (loop could exceed ``max_iterations``, the runaway-LLM-spend defense)
or combined increments tripped ``MaxIterationsError`` prematurely.

These tests run two concurrent calls against ONE agent instance with a slow
async provider stub that counts model invocations and force-yields so the
calls genuinely interleave.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from _mcp_mesh.engine.llm_config import LLMConfig
from _mcp_mesh.engine.llm_errors import MaxIterationsError
from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent


def _make_agent(provider_proxy, max_iterations: int) -> MeshLlmAgent:
    tool_proxy = MagicMock()
    tool_proxy.call_tool = AsyncMock(return_value="ok")
    return MeshLlmAgent(
        config=LLMConfig(
            provider={"capability": "llm", "tags": ["claude"]},
            model=None,
            max_iterations=max_iterations,
            system_prompt="Test prompt",
        ),
        filtered_tools=[],
        output_type=str,
        tool_proxies={"noop_tool": tool_proxy},
        provider_proxy=provider_proxy,
        vendor="anthropic",
    )


def _tool_call_message(call_id: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "noop_tool", "arguments": "{}"},
            }
        ],
    }


class TestConcurrentCallIterationIsolation:
    @pytest.mark.asyncio
    async def test_concurrent_calls_each_respect_own_max_iterations(self):
        """Two interleaved calls that never reach a final response must EACH
        run exactly max_iterations model invocations, then raise
        MaxIterationsError reporting their own count — no cross-talk."""
        max_iterations = 3
        invocations = 0

        async def provider(request):
            nonlocal invocations
            invocations += 1
            # Force a yield so the two concurrent loops interleave.
            await asyncio.sleep(0.001)
            return _tool_call_message(f"call_{invocations}")

        agent = _make_agent(provider, max_iterations)

        results = await asyncio.gather(
            agent("call A"), agent("call B"), return_exceptions=True
        )

        # Both calls must hit the iteration ceiling — independently.
        assert all(isinstance(r, MaxIterationsError) for r in results), results
        for r in results:
            assert r.iteration_count == max_iterations
            assert r.max_allowed == max_iterations

        # Exactly max_iterations model invocations per call. A shared
        # instance-level counter would exit both loops after a COMBINED
        # max_iterations increments (premature) or let one loop run past
        # the ceiling after the other call's reset.
        assert invocations == 2 * max_iterations

    @pytest.mark.asyncio
    async def test_concurrent_calls_do_not_trip_max_iterations_prematurely(self):
        """Two concurrent calls that each legitimately need 2 iterations
        (tool call, then final answer) must BOTH succeed with
        max_iterations=2 — combined increments on a shared counter would
        raise MaxIterationsError before either call finished."""

        async def provider(request):
            await asyncio.sleep(0.001)
            messages = request["messages"]
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if not has_tool_result:
                return _tool_call_message("call_1")
            return {"role": "assistant", "content": "done"}

        agent = _make_agent(provider, max_iterations=2)

        result_a, result_b = await asyncio.gather(agent("call A"), agent("call B"))

        assert result_a == "done"
        assert result_b == "done"
