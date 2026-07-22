"""Issue #1355: LLM max_iterations exhaustion is a structural signal.

The provider-managed loop marks exhaustion with a ``_mesh_stop_reason``
sibling field (buffered) or a reserved terminal control frame (streaming) —
never an English marker in ``content`` / the token stream. The delegating
``@mesh.llm`` consumer reads the signal and raises the typed
``MaxIterationsError`` so the documented contract holds on the mainline
provider-managed-loop path (previously unreachable: the managed loop returns a
terminal no-tool-calls message and the consumer exited normally on iter 1).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from _mcp_mesh.engine.llm_config import LLMConfig
from _mcp_mesh.engine.llm_errors import MaxIterationsError
from _mcp_mesh.engine.llm_stop_reason import encode_stream_end
from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent


def _make_agent(provider_proxy, *, output_type=str, max_iterations=5) -> MeshLlmAgent:
    return MeshLlmAgent(
        config=LLMConfig(
            provider={"capability": "llm", "tags": ["claude"]},
            model=None,
            max_iterations=max_iterations,
            system_prompt="Test prompt",
        ),
        filtered_tools=[],
        output_type=output_type,
        tool_proxies={},
        provider_proxy=provider_proxy,
        vendor="anthropic",
    )


class TestBufferedExhaustionRaises:
    @pytest.mark.asyncio
    async def test_stop_reason_envelope_raises_max_iterations_error(self):
        """A provider-managed exhaustion envelope (empty content +
        ``_mesh_stop_reason``) drives the buffered consumer to raise the typed
        error on iteration 1 — it must NOT be mis-parsed as a bare answer."""
        max_iterations = 7

        async def provider(request):
            return {
                "role": "assistant",
                "content": "",
                "_mesh_stop_reason": "max_iterations",
            }

        agent = _make_agent(provider, max_iterations=max_iterations)

        with pytest.raises(MaxIterationsError) as exc_info:
            await agent("hello")

        assert exc_info.value.iteration_count == max_iterations
        assert exc_info.value.max_allowed == max_iterations

    @pytest.mark.asyncio
    async def test_stop_reason_with_prior_text_still_raises(self):
        """Even when ``content`` carries prior assistant prose, the presence of
        ``_mesh_stop_reason`` takes precedence and raises — the answer channel
        is never returned on exhaustion."""

        async def provider(request):
            return {
                "role": "assistant",
                "content": "Partial reasoning so far...",
                "_mesh_stop_reason": "max_iterations",
            }

        agent = _make_agent(provider, max_iterations=3)

        with pytest.raises(MaxIterationsError):
            await agent("hello")

    @pytest.mark.asyncio
    async def test_normal_completion_without_stop_reason_returns_answer(self):
        """Absence of ``_mesh_stop_reason`` = a normal turn; the answer is
        returned, not raised."""

        async def provider(request):
            return {"role": "assistant", "content": "the answer"}

        agent = _make_agent(provider, max_iterations=3)

        result = await agent("hello")
        assert result == "the answer"


class TestStreamExhaustionRaises:
    @pytest.mark.asyncio
    async def test_terminal_frame_raises_and_is_not_forwarded(self):
        """The stream wrapper recognizes the reserved terminal control frame,
        never yields it, and raises MaxIterationsError at end-of-iteration."""
        max_iterations = 4

        async def _stream(name, request):
            yield "Hello"
            yield " world"
            yield encode_stream_end("max_iterations")

        provider_proxy = MagicMock()
        provider_proxy.function_name = "chat_stream"
        provider_proxy.endpoint = "http://provider"
        provider_proxy.stream = _stream

        agent = _make_agent(provider_proxy, max_iterations=max_iterations)

        collected: list[str] = []
        with pytest.raises(MaxIterationsError) as exc_info:
            async for chunk in agent.stream("hi"):
                collected.append(chunk)

        # Real text tokens were forwarded; the control frame never leaked.
        assert collected == ["Hello", " world"]
        assert all("Maximum tool call iterations" not in c for c in collected)
        assert exc_info.value.iteration_count == max_iterations
        assert exc_info.value.max_allowed == max_iterations


class TestBufferedFallbackExhaustionRaises:
    @pytest.mark.asyncio
    async def test_buffered_fallback_exhaustion_envelope_raises(self):
        """Degraded streaming path (issue #1355 W1): the provider advertised the
        ai.mcpmesh.stream tag but its ``_stream`` tool is unreachable, so the
        consumer degrades to the buffered sibling tool. If that buffered reply
        is itself an exhaustion envelope (empty content + ``_mesh_stop_reason``),
        the consumer must raise MaxIterationsError — not yield a silent empty
        stream."""
        max_iterations = 6

        async def _stream(name, request):
            # Simulate the streaming tool being unreachable: FastMCP surfaces an
            # unknown tool as a ToolError whose message contains "Unknown tool".
            raise RuntimeError("Unknown tool: chat_stream")
            yield  # pragma: no cover — makes this an async generator

        provider_proxy = MagicMock()
        provider_proxy.function_name = "chat_stream"
        provider_proxy.endpoint = "http://provider"
        provider_proxy.stream = _stream
        provider_proxy.call_tool_with_tracing = AsyncMock(
            return_value={
                "role": "assistant",
                "content": "",
                "_mesh_stop_reason": "max_iterations",
            }
        )

        agent = _make_agent(provider_proxy, max_iterations=max_iterations)

        collected: list[str] = []
        with pytest.raises(MaxIterationsError) as exc_info:
            async for chunk in agent.stream("hi"):
                collected.append(chunk)

        # The buffered fallback was reached (streaming tool unreachable) and the
        # exhaustion envelope raised instead of yielding nothing.
        provider_proxy.call_tool_with_tracing.assert_awaited_once()
        assert collected == []
        assert exc_info.value.iteration_count == max_iterations
        assert exc_info.value.max_allowed == max_iterations


class TestExhaustionErrorExports:
    def test_public_error_exports_import_cleanly(self):
        """Issue #1355: both errors are reachable off the top-level ``mesh``
        package via the ``__getattr__`` dispatch."""
        from mesh import MaxIterationsError as ExportedMaxIterationsError
        from mesh import ToolExecutionError as ExportedToolExecutionError

        assert ExportedMaxIterationsError is MaxIterationsError

        from _mcp_mesh.engine.llm_errors import ToolExecutionError

        assert ExportedToolExecutionError is ToolExecutionError
