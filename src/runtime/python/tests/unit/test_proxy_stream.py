"""Unit tests for ``UnifiedMCPProxy.stream()`` — consumer-side streaming bridge.

Covers P2 of issue #645:
- Progress notifications surface as iterator chunks in arrival order.
- The sentinel-terminated queue closes the iterator after the last chunk.
- Trace-context (X-Trace-ID / _trace_id / merged headers) injects identically
  to the buffered ``call_tool`` path via the shared ``_inject_trace_into_args``.
- Errors raised inside ``client.call_tool`` propagate as their original class
  out of the consumer's ``async for`` (no generic ``RuntimeError`` wrapping).
- Mid-iteration cancellation (consumer breaks/aclose) cancels the call_task
  and runs the proxy's cleanup ``finally`` blocks.
- Soft-warn fallback: when the producer's ``stream_type`` is not ``"text"`` we
  log a warning and yield the buffered final-result text as one chunk.
- Cross-loop safety: the queue, call_task and FastMCP client work correctly
  when ``stream()`` is dispatched onto a worker loop distinct from the caller's.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy

# ---------------------------------------------------------------------------
# Fakes mirroring fastmcp.Client.call_tool surface for the streaming path
# ---------------------------------------------------------------------------


class _FakeContent:
    """Stand-in for fastmcp content items with .text attribute."""

    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


class _FakeCallToolResult:
    """Stand-in for fastmcp.CallToolResult with .content list."""

    __slots__ = ("content",)

    def __init__(self, text: str | None):
        self.content = [_FakeContent(text)] if text is not None else []


class _FakeFastMCPClient:
    """Reentrant async-context fake mirroring fastmcp.Client surface used by
    ``UnifiedMCPProxy.stream``.

    ``call_tool`` invokes the supplied ``progress_handler`` once per scripted
    chunk, then returns the configured ``CallToolResult``-shaped payload (or
    raises the configured exception).
    """

    def __init__(
        self,
        *,
        chunks: list[str] | None = None,
        result_text: str | None = None,
        raise_exc: BaseException | None = None,
        block_event: asyncio.Event | None = None,
    ):
        self._chunks = chunks or []
        self._result_text = result_text
        self._raise_exc = raise_exc
        self._block_event = block_event
        self.call_count = 0
        self.last_args: dict | None = None
        self.last_name: str | None = None

    async def __aenter__(self) -> _FakeFastMCPClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def call_tool(
        self,
        name: str,
        arguments: dict,
        *,
        progress_handler=None,
    ):
        self.call_count += 1
        self.last_name = name
        self.last_args = arguments

        for idx, chunk in enumerate(self._chunks):
            if progress_handler is not None:
                await progress_handler(float(idx), None, chunk)

        if self._block_event is not None:
            await self._block_event.wait()

        if self._raise_exc is not None:
            raise self._raise_exc

        return _FakeCallToolResult(self._result_text)


def _make_proxy(*, kwargs_config: dict | None = None) -> UnifiedMCPProxy:
    """Build a proxy with streaming-friendly defaults for tests."""
    return UnifiedMCPProxy(
        endpoint="http://fake-host:9000",
        function_name="chat",
        kwargs_config=kwargs_config or {"stream_type": "text"},
    )


# ---------------------------------------------------------------------------
# Chunk arrival in order
# ---------------------------------------------------------------------------


class TestStreamYieldsChunks:
    @pytest.mark.asyncio
    async def test_yields_chunks_in_order(self):
        proxy = _make_proxy()
        fake_client = _FakeFastMCPClient(
            chunks=["Hello", ", ", "world!"], result_text="Hello, world!"
        )

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            collected: list[str] = []
            async for chunk in proxy.stream(prompt="hi"):
                collected.append(chunk)

        assert collected == ["Hello", ", ", "world!"]
        assert fake_client.call_count == 1
        # Default name resolved from function_name when name=None
        assert fake_client.last_name == "chat"

    @pytest.mark.asyncio
    async def test_explicit_tool_name_overrides_default(self):
        proxy = _make_proxy()
        fake_client = _FakeFastMCPClient(chunks=["x"], result_text="x")

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            async for _ in proxy.stream("other_tool", prompt="hi"):
                pass

        assert fake_client.last_name == "other_tool"

    @pytest.mark.asyncio
    async def test_iteration_terminates_after_last_chunk(self):
        # Sentinel-driven termination: queue.get loop must exit on SENTINEL,
        # not hang forever waiting for more progress events.
        proxy = _make_proxy()
        fake_client = _FakeFastMCPClient(
            chunks=["a", "b"], result_text="ab"
        )

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            collected: list[str] = []
            # Wrap in wait_for to fail loudly if the iterator hangs past last chunk
            async def _drive() -> None:
                async for chunk in proxy.stream(prompt="x"):
                    collected.append(chunk)

            await asyncio.wait_for(_drive(), timeout=2.0)

        assert collected == ["a", "b"]


# ---------------------------------------------------------------------------
# Trace-context propagation
# ---------------------------------------------------------------------------


class TestStreamTraceContext:
    @pytest.mark.asyncio
    async def test_injects_trace_into_arguments_when_context_present(self):
        proxy = _make_proxy()
        fake_client = _FakeFastMCPClient(chunks=["x"], result_text="x")

        from _mcp_mesh.tracing.context import TraceContext

        TRACE_ID = "trace-abc-1234"
        SPAN_ID = "span-xyz-5678"
        TraceContext.set_current(TRACE_ID, SPAN_ID)

        try:
            with patch.object(
                UnifiedMCPProxy,
                "_get_or_create_fastmcp_client",
                new=AsyncMock(return_value=fake_client),
            ):
                async for _ in proxy.stream(prompt="hi"):
                    pass
        finally:
            TraceContext.clear_current()

        # The proxy delegates injection to the Rust core when present and
        # falls back to manual injection otherwise. Either path must surface
        # the trace IDs in the outbound arguments dict.
        assert fake_client.last_args is not None
        args = fake_client.last_args
        assert args.get("prompt") == "hi"
        # Both Rust-core and the Python fallback use ``_trace_id`` /
        # ``_parent_span`` keys for cross-runtime parity.
        assert args.get("_trace_id") == TRACE_ID
        assert args.get("_parent_span") == SPAN_ID

    @pytest.mark.asyncio
    async def test_omits_trace_keys_when_no_context(self):
        proxy = _make_proxy()
        fake_client = _FakeFastMCPClient(chunks=["x"], result_text="x")

        from _mcp_mesh.tracing.context import TraceContext

        TraceContext.clear_current()

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            async for _ in proxy.stream(prompt="hi"):
                pass

        assert fake_client.last_args is not None
        assert "_trace_id" not in fake_client.last_args
        assert "_parent_span" not in fake_client.last_args


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class _ConnRefused(ConnectionError):
    """Custom connection error to verify class identity is preserved."""


class TestStreamErrorPropagation:
    @pytest.mark.asyncio
    async def test_connection_error_propagates_unchanged(self):
        proxy = _make_proxy()
        fake_client = _FakeFastMCPClient(
            chunks=[], raise_exc=_ConnRefused("remote down")
        )

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            with pytest.raises(_ConnRefused, match="remote down"):
                async for _ in proxy.stream(prompt="hi"):
                    pass

    @pytest.mark.asyncio
    async def test_mid_stream_error_propagates_after_partial_chunks(self):
        proxy = _make_proxy()
        # Three chunks land first, then call_tool raises on return.
        fake_client = _FakeFastMCPClient(
            chunks=["one ", "two "], raise_exc=RuntimeError("tool blew up")
        )

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            collected: list[str] = []
            with pytest.raises(RuntimeError, match="tool blew up"):
                async for chunk in proxy.stream(prompt="hi"):
                    collected.append(chunk)

        assert collected == ["one ", "two "]

    @pytest.mark.asyncio
    async def test_timeout_error_propagates_unchanged(self):
        proxy = _make_proxy()
        fake_client = _FakeFastMCPClient(
            chunks=[], raise_exc=TimeoutError()
        )

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            with pytest.raises(TimeoutError):
                async for _ in proxy.stream(prompt="hi"):
                    pass


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestStreamCancellation:
    @pytest.mark.asyncio
    async def test_consumer_break_cancels_call_task(self):
        # Producer parks indefinitely after one chunk so the consumer must
        # cancel it explicitly when breaking out of the loop.
        proxy = _make_proxy()
        block = asyncio.Event()
        fake_client = _FakeFastMCPClient(
            chunks=["first"], result_text="first", block_event=block
        )

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            agen = proxy.stream(prompt="hi")
            chunk = await agen.__anext__()
            assert chunk == "first"

            # Closing the async generator triggers GeneratorExit at the yield
            # point, which our finally block converts into call_task.cancel().
            await agen.aclose()

        # Block was never released; the call_task should have been cancelled.
        # If it weren't, the test would hang on aclose() above.


# ---------------------------------------------------------------------------
# Soft-warn fallback for non-streaming producers
# ---------------------------------------------------------------------------


class TestStreamNonStreamingFallback:
    @pytest.mark.asyncio
    async def test_non_streaming_producer_yields_buffered_text_once(self, caplog):
        # Producer kwargs_config does NOT advertise stream_type=text, and
        # call_tool returns a single buffered string with no progress events.
        proxy = _make_proxy(kwargs_config={"capability": "chat"})
        fake_client = _FakeFastMCPClient(
            chunks=[], result_text="Whole response in one go."
        )

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            with caplog.at_level("WARNING"):
                collected: list[str] = []
                async for chunk in proxy.stream(prompt="hi"):
                    collected.append(chunk)

        assert collected == ["Whole response in one go."]
        # Soft-warn was emitted because stream_type != "text"
        assert any(
            "does not advertise" in record.message for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_non_streaming_with_no_text_yields_nothing(self):
        proxy = _make_proxy(kwargs_config={"capability": "chat"})
        # Empty content list — no fallback chunk possible.
        fake_client = _FakeFastMCPClient(chunks=[], result_text=None)

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            collected: list[str] = []
            async for chunk in proxy.stream(prompt="hi"):
                collected.append(chunk)

        assert collected == []


# ---------------------------------------------------------------------------
# Cross-loop safety: stream dispatched on a worker loop in another thread
# ---------------------------------------------------------------------------


class TestStreamCrossLoopSafety:
    def test_stream_works_on_isolated_worker_loop(self):
        """The queue, call_task, and FastMCP client must all live on the
        SAME loop as the running coroutine. We construct a fresh loop in a
        worker thread and drive ``proxy.stream`` there to confirm no
        cross-loop binding leaks (mirrors the worker_loop dispatch model
        from ``_mcp_mesh.shared.tool_executor``).
        """
        proxy = _make_proxy()
        fake_client = _FakeFastMCPClient(chunks=["a", "b", "c"], result_text="abc")

        result: dict[str, Any] = {}

        def _run_on_worker_loop() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)

                async def _drive() -> list[str]:
                    out: list[str] = []
                    with patch.object(
                        UnifiedMCPProxy,
                        "_get_or_create_fastmcp_client",
                        new=AsyncMock(return_value=fake_client),
                    ):
                        async for chunk in proxy.stream(prompt="hi"):
                            out.append(chunk)
                    return out

                result["chunks"] = loop.run_until_complete(_drive())
            except BaseException as e:
                result["error"] = e
            finally:
                loop.close()

        thread = threading.Thread(target=_run_on_worker_loop)
        thread.start()
        thread.join(timeout=5.0)

        assert "error" not in result, f"worker loop raised: {result.get('error')!r}"
        assert result.get("chunks") == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# call_tool_streaming back-compat alias delegates to stream
# ---------------------------------------------------------------------------


class TestCallToolStreamingAlias:
    @pytest.mark.asyncio
    async def test_alias_yields_same_chunks_as_stream(self):
        proxy = _make_proxy()
        fake_client = _FakeFastMCPClient(chunks=["x", "y"], result_text="xy")

        with patch.object(
            UnifiedMCPProxy,
            "_get_or_create_fastmcp_client",
            new=AsyncMock(return_value=fake_client),
        ):
            collected: list[Any] = []
            async for chunk in proxy.call_tool_streaming("chat", {"prompt": "hi"}):
                collected.append(chunk)

        assert collected == ["x", "y"]
        assert fake_client.last_args is not None
        assert fake_client.last_args.get("prompt") == "hi"
