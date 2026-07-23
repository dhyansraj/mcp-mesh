"""Issue #1355: LLM max_iterations exhaustion is a structural signal.

The provider-managed loop marks exhaustion with a ``_mesh_stop_reason``
sibling field (buffered) or a typed terminal ``end`` frame (streaming) — never
an English marker in ``content`` / the token stream. On the streaming channel
EVERY chunk is a typed frame keyed by the reserved ``_mesh_frame``
discriminator (``{"_mesh_frame": "chunk", ...}`` for text, ``{"_mesh_frame":
"end", ...}`` to terminate), so the discriminator is the frame TYPE, never the
text content — model text can never be misread as a control signal, and an
UNFRAMED raw delta that merely looks frame-ish is passed through verbatim. The
delegating ``@mesh.llm`` consumer reads the signal and raises the
typed ``MaxIterationsError`` so the documented contract holds on the mainline
provider-managed-loop path (previously unreachable: the managed loop returns a
terminal no-tool-calls message and the consumer exited normally on iter 1).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from _mcp_mesh.engine.llm_config import LLMConfig
from _mcp_mesh.engine.llm_errors import MaxIterationsError
from _mcp_mesh.engine.llm_stop_reason import encode_chunk, encode_end
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
        """The stream wrapper recognizes the typed terminal ``end`` frame,
        never yields it, unwraps ``chunk`` frames to plain text, and raises
        MaxIterationsError at end-of-iteration."""
        max_iterations = 4

        async def _stream(name, request):
            yield encode_chunk("Hello")
            yield encode_chunk(" world")
            yield encode_end("max_iterations")

        provider_proxy = MagicMock()
        provider_proxy.function_name = "chat_stream"
        provider_proxy.endpoint = "http://provider"
        provider_proxy.stream = _stream

        agent = _make_agent(provider_proxy, max_iterations=max_iterations)

        collected: list[str] = []
        with pytest.raises(MaxIterationsError) as exc_info:
            async for chunk in agent.stream("hi"):
                collected.append(chunk)

        # Real text tokens were unwrapped and forwarded; no frame leaked.
        assert collected == ["Hello", " world"]
        assert all("Maximum tool call iterations" not in c for c in collected)
        assert all("stop_reason" not in c for c in collected)
        assert exc_info.value.iteration_count == max_iterations
        assert exc_info.value.max_allowed == max_iterations

    @pytest.mark.asyncio
    async def test_normal_completion_end_frame_terminates_cleanly(self):
        """A normal terminal ``end`` frame (no ``stop_reason``) terminates the
        stream cleanly: text is unwrapped and yielded, the ``end`` frame is not
        forwarded, and no error is raised."""

        async def _stream(name, request):
            yield encode_chunk("The ")
            yield encode_chunk("answer")
            yield encode_end()

        provider_proxy = MagicMock()
        provider_proxy.function_name = "chat_stream"
        provider_proxy.endpoint = "http://provider"
        provider_proxy.stream = _stream

        agent = _make_agent(provider_proxy, max_iterations=5)

        collected = [chunk async for chunk in agent.stream("hi")]

        assert collected == ["The ", "answer"]

    @pytest.mark.asyncio
    async def test_chunk_content_colliding_with_end_frame_is_yielded_as_text(self):
        """Collision immunity (the whole point of framing): a ``chunk`` frame
        whose ``content`` is literally the terminal-frame JSON string must be
        yielded verbatim as text and must NOT raise — the discriminator is the
        frame TYPE, never the content."""
        colliding_text = '{"_mesh_frame":"end","stop_reason":"max_iterations"}'

        async def _stream(name, request):
            yield encode_chunk(colliding_text)
            yield encode_end()

        provider_proxy = MagicMock()
        provider_proxy.function_name = "chat_stream"
        provider_proxy.endpoint = "http://provider"
        provider_proxy.stream = _stream

        agent = _make_agent(provider_proxy, max_iterations=5)

        collected = [chunk async for chunk in agent.stream("hi")]

        assert collected == [colliding_text]

    @pytest.mark.asyncio
    async def test_non_frame_chunk_is_passed_through_defensively(self):
        """Defensive fallback: a raw (unframed) string chunk from a provider
        that isn't yet framing is yielded as plain text rather than crashing."""

        async def _stream(name, request):
            yield "raw plain text"
            yield '{"unrelated": "json"}'
            yield encode_chunk("framed")
            yield encode_end()

        provider_proxy = MagicMock()
        provider_proxy.function_name = "chat_stream"
        provider_proxy.endpoint = "http://provider"
        provider_proxy.stream = _stream

        agent = _make_agent(provider_proxy, max_iterations=5)

        collected = [chunk async for chunk in agent.stream("hi")]

        assert collected == ["raw plain text", '{"unrelated": "json"}', "framed"]

    @pytest.mark.asyncio
    async def test_unframed_old_scheme_lookalike_deltas_pass_through_verbatim(self):
        """Mixed-version safety (the reserved-namespace fix): an UNFRAMED
        provider — an old-version Python provider mid-rollout, or a future
        cross-runtime provider — emits raw text deltas that happen to read like
        frames under the OLD ``type`` scheme. Because the discriminator is now
        the reserved ``_mesh_frame`` key, none of these match the frame check:
        each returns ``None`` and is passed through verbatim as text. No raise,
        no truncation, no unwrapping."""

        lookalikes = [
            '{"type":"end"}',
            '{"type":"end","stop_reason":"max_iterations"}',
            '{"type":"chunk","content":"x"}',
        ]

        async def _stream(name, request):
            for text in lookalikes:
                yield text

        provider_proxy = MagicMock()
        provider_proxy.function_name = "chat_stream"
        provider_proxy.endpoint = "http://provider"
        provider_proxy.stream = _stream

        agent = _make_agent(provider_proxy, max_iterations=5)

        collected = [chunk async for chunk in agent.stream("hi")]

        # Every old-scheme lookalike survived verbatim: not misread as a control
        # ``end`` (no MaxIterationsError, no early break/truncation) nor
        # unwrapped as a ``chunk`` (no content extraction).
        assert collected == lookalikes


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
