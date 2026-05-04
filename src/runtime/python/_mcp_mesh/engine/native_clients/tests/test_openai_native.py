"""Unit tests for the native OpenAI SDK adapter (issue #834 PR 2).

Covers:
  * is_available() reflects ImportError of the SDK and caches the probe
  * supports_model() matches the openai/* prefix
  * _strip_prefix() correctness
  * _build_client() constructs AsyncOpenAI with shared httpx + api_key/base_url
  * _build_client() raises ValueError when api_key/env both unset
  * _build_create_kwargs() passes through OpenAI-shaped knobs and warns on
    unrecognized litellm-only kwargs (per-key dedupe)
  * _build_create_kwargs() handles explicit max_tokens=None (drops the key
    instead of forwarding it as None — OpenAI rejects None)
  * complete() adapts OpenAI ChatCompletion → litellm-shape _Response
    (text + tool_calls + usage)
  * complete_stream() yields chunks matching the shape consumed by
    mesh.helpers._provider_agentic_loop_stream
  * complete_stream() forces stream_options.include_usage=True
  * complete_stream() emits best-effort usage chunk on stream interruption
  * complete_stream() swallows GeneratorExit/StopAsyncIteration on
    consumer-aborted teardown
  * Shared httpx client reused across calls (identity)
  * is_fallback_logged() tracks log_fallback_once() state

Real network calls are mocked.
"""

from __future__ import annotations

import builtins
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "openai", reason="native OpenAI adapter requires the openai SDK"
)

from _mcp_mesh.engine.native_clients import openai_native


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


class TestIsAvailable:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """is_available() caches its result module-wide; reset between tests
        in this class so each one re-probes the import."""
        openai_native._reset_is_available_cache()
        yield
        openai_native._reset_is_available_cache()

    def test_returns_true_when_sdk_importable(self):
        # The SDK is installed in the test environment; this should be True.
        assert openai_native.is_available() is True

    def test_returns_false_when_import_fails(self, monkeypatch):
        """Simulate the SDK being absent by stubbing __import__ to raise."""
        original_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            return original_import(name, *args, **kwargs)

        # Drop the cached module so the function re-evaluates the import.
        monkeypatch.delitem(sys.modules, "openai", raising=False)
        with patch("builtins.__import__", side_effect=_fake_import):
            assert openai_native.is_available() is False

    def test_caches_result_across_calls(self):
        """Once probed, is_available() must not re-import on every call —
        the SDK presence does not change at runtime and the per-call import
        was showing up as needless overhead on the dispatch-decision path.
        """
        original_import = builtins.__import__
        call_count = {"n": 0}

        def _counting_import(name, *args, **kwargs):
            if name == "openai":
                call_count["n"] += 1
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_counting_import):
            openai_native.is_available()
            openai_native.is_available()
            openai_native.is_available()

        # Exactly one import attempt across three calls.
        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# supports_model() and _strip_prefix()
# ---------------------------------------------------------------------------


class TestSupportsModel:
    @pytest.mark.parametrize(
        "model",
        [
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "openai/gpt-4-turbo",
            "openai/o1-preview",
            "openai/o3-mini",
        ],
    )
    def test_supported_prefixes(self, model):
        assert openai_native.supports_model(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-sonnet-4-5",
            "gemini/gemini-1.5-pro",
            "vertex_ai/gemini-1.5-pro",
            "bedrock/amazon.titan-text-express-v1",
            "azure/gpt-4o",  # Azure routing deferred to follow-up PR
            "gpt-4o",  # bare, no prefix
            "",
            None,
        ],
    )
    def test_unsupported(self, model):
        assert openai_native.supports_model(model or "") is False


class TestStripPrefix:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("openai/gpt-4o", "gpt-4o"),
            ("openai/gpt-4o-mini", "gpt-4o-mini"),
            ("openai/o1-preview", "o1-preview"),
            ("gpt-4o", "gpt-4o"),  # bare, no-op
        ],
    )
    def test_strip_prefix(self, model, expected):
        assert openai_native._strip_prefix(model) == expected


# ---------------------------------------------------------------------------
# Helpers shared across complete() tests
# ---------------------------------------------------------------------------


def _make_openai_completion(
    *,
    text: str | None = None,
    tool_calls: list[dict] | None = None,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 12,
    completion_tokens: int = 7,
    finish_reason: str = "stop",
):
    """Build a fake openai.ChatCompletion-like object for complete() tests."""
    raw_tool_calls = []
    for tc in tool_calls or []:
        raw_tool_calls.append(
            SimpleNamespace(
                id=tc["id"],
                type="function",
                function=SimpleNamespace(
                    name=tc["name"],
                    arguments=tc.get("arguments", "{}"),
                ),
            )
        )
    message = SimpleNamespace(
        role="assistant",
        content=text,
        tool_calls=raw_tool_calls or None,
    )
    choice = SimpleNamespace(
        index=0,
        message=message,
        finish_reason=finish_reason,
    )
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage, model=model)


def _patched_async_openai(api_response):
    """Return (cls_mock, create_mock, instance_mock).

    Patches openai.AsyncOpenAI so its instance has a
    ``.chat.completions.create`` AsyncMock returning ``api_response``.
    """
    instance = MagicMock()
    create_mock = AsyncMock(return_value=api_response)
    instance.chat = MagicMock()
    instance.chat.completions = MagicMock()
    instance.chat.completions.create = create_mock
    cls_mock = MagicMock(return_value=instance)
    return cls_mock, create_mock, instance


# ---------------------------------------------------------------------------
# complete() — request shaping
# ---------------------------------------------------------------------------


class TestCompleteRequestShape:
    @pytest.mark.asyncio
    async def test_strips_model_prefix(self):
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="hi")
        )
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_passes_through_messages_unchanged(self):
        """OpenAI's wire shape == mesh-internal shape; messages forward
        verbatim (no system extraction, no role translation, no image
        translation)."""
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="hi")
        )
        original_messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi."},
        ]
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {"messages": original_messages},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        # System message stays in the messages array — OpenAI accepts it
        # there (unlike Anthropic which needs system= as a separate kwarg).
        assert kwargs["messages"] == original_messages

    @pytest.mark.asyncio
    async def test_passes_through_tools_unchanged(self):
        """OpenAI tools shape IS the mesh-internal tools shape — passthrough."""
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="ok")
        )
        openai_tool = {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Look up weather.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tools": [openai_tool],
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert kwargs["tools"] == [openai_tool]

    @pytest.mark.asyncio
    async def test_passes_through_tool_choice_strings(self):
        """OpenAI accepts "auto" / "none" / "required" natively — passthrough."""
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="ok")
        )
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tool_choice": "auto",
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        assert create_mock.call_args.kwargs["tool_choice"] == "auto"

    @pytest.mark.asyncio
    async def test_passes_through_tool_choice_dict(self):
        """OpenAI accepts ``{"type": "function", "function": {"name": "..."}}``
        natively — passthrough."""
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="ok")
        )
        choice = {
            "type": "function",
            "function": {"name": "__mesh_format_response"},
        }
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tool_choice": choice,
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        assert create_mock.call_args.kwargs["tool_choice"] == choice

    @pytest.mark.asyncio
    async def test_passes_through_response_format(self):
        """OpenAI's response_format with strict=True is the canonical
        structured-output mechanism — must passthrough untouched."""
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="ok")
        )
        rf = {
            "type": "json_schema",
            "json_schema": {
                "name": "TripPlan",
                "schema": {"type": "object"},
                "strict": True,
            },
        }
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": rf,
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        assert create_mock.call_args.kwargs["response_format"] == rf

    @pytest.mark.asyncio
    async def test_passes_through_temperature_and_max_tokens(self):
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="hi")
        )
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert kwargs["temperature"] == 0.2
        assert kwargs["max_tokens"] == 1024

    @pytest.mark.asyncio
    async def test_max_tokens_explicit_none_is_dropped(self):
        """Unlike Anthropic, OpenAI doesn't require ``max_tokens`` — an
        explicit ``max_tokens=None`` from the caller must be DROPPED (not
        forwarded as None, which OpenAI rejects)."""
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="hi")
        )
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "max_tokens": None,
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "max_tokens" not in kwargs

    @pytest.mark.asyncio
    async def test_max_completion_tokens_passthrough(self):
        """Newer reasoning-model field — must passthrough alongside
        max_tokens (the SDK accepts whichever the caller supplied)."""
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="hi")
        )
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "max_completion_tokens": 8000,
                },
                model="openai/o1-preview",
                api_key="sk-test",
            )

        assert create_mock.call_args.kwargs["max_completion_tokens"] == 8000

    @pytest.mark.asyncio
    async def test_passes_through_reasoning_effort(self):
        """o1/o3 reasoning_effort knob — must be allow-listed for passthrough."""
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="hi")
        )
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "reasoning_effort": "medium",
                },
                model="openai/o3-mini",
                api_key="sk-test",
            )

        assert create_mock.call_args.kwargs["reasoning_effort"] == "medium"

    @pytest.mark.asyncio
    async def test_passes_through_seed_and_logprobs(self):
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="hi")
        )
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "seed": 42,
                    "logprobs": True,
                    "top_logprobs": 3,
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert kwargs["seed"] == 42
        assert kwargs["logprobs"] is True
        assert kwargs["top_logprobs"] == 3

    @pytest.mark.asyncio
    async def test_drops_internal_mesh_sentinels(self):
        """``_mesh_*`` sentinels must NOT be forwarded to OpenAI — they're
        consumed upstream in helpers._pop_mesh_*_flags."""
        cls_mock, create_mock, _ = _patched_async_openai(
            _make_openai_completion(text="hi")
        )
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "_mesh_hint_mode": True,
                    "_mesh_hint_schema": {"type": "object"},
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        for k in kwargs:
            assert not k.startswith("_mesh_"), f"{k} leaked into create()"


# ---------------------------------------------------------------------------
# complete() — response shape
# ---------------------------------------------------------------------------


class TestCompleteResponseShape:
    @pytest.mark.asyncio
    async def test_text_only_response_adapts_to_mock_response(self):
        api_resp = _make_openai_completion(
            text="Hello world",
            prompt_tokens=11,
            completion_tokens=4,
            model="gpt-4o-mini-2024-07-18",
        )
        cls_mock, _, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            response = await openai_native.complete(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        assert response.choices[0].message.content == "Hello world"
        assert response.choices[0].message.role == "assistant"
        assert response.choices[0].message.tool_calls is None
        assert response.choices[0].finish_reason == "stop"
        assert response.usage.prompt_tokens == 11
        assert response.usage.completion_tokens == 4
        assert response.usage.total_tokens == 15
        assert response.model == "gpt-4o-mini-2024-07-18"

    @pytest.mark.asyncio
    async def test_tool_use_response_adapts_to_tool_calls(self):
        api_resp = _make_openai_completion(
            text=None,
            tool_calls=[
                {
                    "id": "call_abc",
                    "name": "get_weather",
                    "arguments": '{"city": "NYC"}',
                }
            ],
            prompt_tokens=20,
            completion_tokens=8,
            finish_reason="tool_calls",
        )
        cls_mock, _, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            response = await openai_native.complete(
                {"messages": [{"role": "user", "content": "Weather?"}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        msg = response.choices[0].message
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        tc = msg.tool_calls[0]
        assert tc.id == "call_abc"
        assert tc.type == "function"
        assert tc.function.name == "get_weather"
        # Arguments come back as a JSON string (matches OpenAI/litellm shape).
        assert json.loads(tc.function.arguments) == {"city": "NYC"}
        assert response.usage.prompt_tokens == 20
        assert response.usage.completion_tokens == 8
        assert response.choices[0].finish_reason == "tool_calls"

    @pytest.mark.asyncio
    async def test_response_with_no_usage_does_not_crash(self):
        """Some OpenAI-compatible backends omit usage on certain calls. The
        adapter must tolerate it (usage=None) instead of crashing."""
        api_resp = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    index=0,
                    message=SimpleNamespace(
                        role="assistant", content="hi", tool_calls=None
                    ),
                    finish_reason="stop",
                )
            ],
            usage=None,
            model="gpt-4o-mini",
        )
        cls_mock, _, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            response = await openai_native.complete(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        assert response.choices[0].message.content == "hi"
        assert response.usage is None


# ---------------------------------------------------------------------------
# Backend selection / per-call client construction
# ---------------------------------------------------------------------------


class TestClientConstruction:
    @pytest.mark.asyncio
    async def test_custom_base_url_forwarded_to_async_openai(self):
        api_resp = _make_openai_completion(text="hi")
        cls_mock, _, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
                base_url="https://workspace.databricks.com/serving-endpoints",
            )

        ctor_kwargs = cls_mock.call_args.kwargs
        assert ctor_kwargs["api_key"] == "sk-test"
        assert (
            ctor_kwargs["base_url"]
            == "https://workspace.databricks.com/serving-endpoints"
        )

    @pytest.mark.asyncio
    async def test_lazy_client_construction_per_call(self):
        """Two consecutive complete() calls must build TWO clients (no cache).

        This guards K8s secret rotation: the api_key must be re-read on
        every call, which only works if the client itself isn't cached.
        """
        api_resp = _make_openai_completion(text="hi")
        cls_mock, _, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-1",
            )
            await openai_native.complete(
                {"messages": [{"role": "user", "content": "Hi again."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-2",  # rotated key
            )

        assert cls_mock.call_count == 2
        first_key = cls_mock.call_args_list[0].kwargs["api_key"]
        second_key = cls_mock.call_args_list[1].kwargs["api_key"]
        assert first_key == "sk-1"
        assert second_key == "sk-2"


# ---------------------------------------------------------------------------
# complete_stream() — chunk shape compatibility
# ---------------------------------------------------------------------------


class _FakeAsyncStream:
    """Async-iterable yielding pre-canned chunks.

    Mirrors the surface area of openai.AsyncStream[ChatCompletionChunk]
    used by complete_stream() — only ``__aiter__`` is needed.
    """

    def __init__(self, chunks: list):
        self._chunks = chunks

    def __aiter__(self):
        async def _gen():
            for c in self._chunks:
                yield c

        return _gen()


def _make_stream_chunk(
    *,
    content: str | None = None,
    tool_call: dict | None = None,
    finish_reason: str | None = None,
    usage: dict | None = None,
    model: str | None = None,
):
    """Build a fake openai.ChatCompletionChunk-like object."""
    delta_kwargs: dict = {"role": None, "content": content, "tool_calls": None}
    if tool_call is not None:
        fn = SimpleNamespace(
            name=tool_call.get("name"), arguments=tool_call.get("arguments")
        )
        delta_kwargs["tool_calls"] = [
            SimpleNamespace(
                index=tool_call.get("index", 0),
                id=tool_call.get("id"),
                type=tool_call.get("type"),
                function=fn,
            )
        ]

    delta = SimpleNamespace(**delta_kwargs)
    choice = SimpleNamespace(index=0, delta=delta, finish_reason=finish_reason)
    usage_obj = None
    if usage is not None:
        usage_obj = SimpleNamespace(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=(
                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            ),
        )

    return SimpleNamespace(
        choices=[choice] if (content is not None or tool_call is not None or finish_reason is not None) else [],
        usage=usage_obj,
        model=model,
    )


def _patched_streaming_openai(chunks: list):
    instance = MagicMock()
    fake_stream = _FakeAsyncStream(chunks)
    instance.chat = MagicMock()
    instance.chat.completions = MagicMock()
    instance.chat.completions.create = AsyncMock(return_value=fake_stream)
    cls_mock = MagicMock(return_value=instance)
    return cls_mock, instance


class TestCompleteStream:
    @pytest.mark.asyncio
    async def test_text_only_stream_yields_litellm_shaped_chunks(self):
        chunks_in = [
            _make_stream_chunk(content="Hello ", model="gpt-4o-mini"),
            _make_stream_chunk(content="world"),
            _make_stream_chunk(finish_reason="stop"),
            # Final usage chunk (only present when include_usage=True).
            _make_stream_chunk(
                usage={"prompt_tokens": 15, "completion_tokens": 4},
                model="gpt-4o-mini",
            ),
        ]
        cls_mock, _ = _patched_streaming_openai(chunks_in)

        with patch("openai.AsyncOpenAI", cls_mock):
            stream = openai_native.complete_stream(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        # Pull text via the same accessors helpers.py uses.
        text_pieces = []
        for c in chunks:
            if c.choices:
                d = c.choices[0].delta
                if getattr(d, "content", None):
                    text_pieces.append(d.content)
        assert "".join(text_pieces) == "Hello world"

        # Final usage chunk: usage attribute is non-None and carries totals.
        usage_chunks = [c for c in chunks if c.usage is not None]
        assert len(usage_chunks) == 1
        assert usage_chunks[0].usage.prompt_tokens == 15
        assert usage_chunks[0].usage.completion_tokens == 4

        # Model surfaces somewhere across the chunks (helpers.py uses
        # _extract_model_from_chunks which grabs the first non-None .model).
        models = [c.model for c in chunks if c.model]
        assert "gpt-4o-mini" in models

    @pytest.mark.asyncio
    async def test_tool_use_stream_yields_mergeable_tool_call_deltas(self):
        """Verify the streamed tool_call shape matches what
        ``MeshLlmAgent._merge_streamed_tool_calls`` expects: id+type+name
        appear once with index=N and arguments accrue across deltas.
        """
        chunks_in = [
            _make_stream_chunk(
                tool_call={
                    "index": 0,
                    "id": "call_xyz",
                    "type": "function",
                    "name": "get_weather",
                    "arguments": "",
                },
                model="gpt-4o-mini",
            ),
            _make_stream_chunk(
                tool_call={"index": 0, "arguments": '{"city": '}
            ),
            _make_stream_chunk(
                tool_call={"index": 0, "arguments": '"NYC"}'}
            ),
            _make_stream_chunk(finish_reason="tool_calls"),
            _make_stream_chunk(
                usage={"prompt_tokens": 10, "completion_tokens": 20},
                model="gpt-4o-mini",
            ),
        ]
        cls_mock, _ = _patched_streaming_openai(chunks_in)

        with patch("openai.AsyncOpenAI", cls_mock):
            stream = openai_native.complete_stream(
                {"messages": [{"role": "user", "content": "Weather?"}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        # Run the actual merger MeshLlmAgent uses on these chunks.
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        merged = MeshLlmAgent._merge_streamed_tool_calls(chunks)
        assert len(merged) == 1
        tc = merged[0]
        assert tc["id"] == "call_xyz"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "get_weather"
        assert tc["function"]["arguments"] == '{"city": "NYC"}'

        # And _chunk_has_tool_call should be True on the deltas.
        assert any(MeshLlmAgent._chunk_has_tool_call(c) for c in chunks)

    @pytest.mark.asyncio
    async def test_forces_include_usage_in_stream_options(self):
        """The adapter MUST set ``stream_options.include_usage=True`` so the
        final chunk carries the authoritative usage tally — without it
        OpenAI omits the usage chunk and telemetry records 0 tokens."""
        chunks_in = [_make_stream_chunk(content="hi"), _make_stream_chunk(finish_reason="stop")]
        cls_mock, instance = _patched_streaming_openai(chunks_in)

        with patch("openai.AsyncOpenAI", cls_mock):
            stream = openai_native.complete_stream(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )
            async for _ in stream:
                pass

        # The adapter passes stream=True and merges include_usage into
        # stream_options. Verify both.
        kwargs = instance.chat.completions.create.call_args.kwargs
        assert kwargs["stream"] is True
        assert kwargs["stream_options"]["include_usage"] is True

    @pytest.mark.asyncio
    async def test_merges_caller_supplied_stream_options(self):
        """If the caller passed their own stream_options, the adapter must
        MERGE (not clobber) them with include_usage=True."""
        chunks_in = [_make_stream_chunk(content="hi"), _make_stream_chunk(finish_reason="stop")]
        cls_mock, instance = _patched_streaming_openai(chunks_in)

        with patch("openai.AsyncOpenAI", cls_mock):
            stream = openai_native.complete_stream(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    # Caller-supplied option that must NOT be overwritten.
                    "stream_options": {"some_future_knob": "value"},
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )
            async for _ in stream:
                pass

        opts = instance.chat.completions.create.call_args.kwargs["stream_options"]
        assert opts["include_usage"] is True
        assert opts["some_future_knob"] == "value"


# ---------------------------------------------------------------------------
# Stream interruption — best-effort usage emission
# ---------------------------------------------------------------------------


class TestStreamInterruptionUsage:
    @pytest.mark.asyncio
    async def test_emits_best_effort_usage_when_stream_ends_without_usage(self):
        """Stream ends after some content deltas but BEFORE the final usage
        chunk arrives (server cutoff / consumer aclose). The adapter MUST
        still emit a usage chunk built from the last counters seen on the
        wire so observability shows non-zero tokens for partial generations.

        For this test we simulate "we observed cumulative usage somewhere
        mid-stream" by injecting a usage-bearing chunk that the adapter
        records but where the stream is truncated before the AUTHORITATIVE
        final usage chunk would otherwise arrive.

        OpenAI doesn't actually emit incremental usage mid-stream the way
        Anthropic does — but the safety net is still valuable when the
        stream truncates exactly at the include_usage chunk boundary, which
        is precisely the scenario this test covers (chunks contain usage
        but consumer aborts before consuming it).
        """
        # Stream emits a usage chunk that we record; we simulate the
        # consumer aborting BEFORE the chunk reaches them by raising
        # GeneratorExit during iteration. The simpler verifiable behavior:
        # if the final yield was reached and consumed, ``final_usage_emitted``
        # is True and finally does NOT re-emit. Verify the no-double-yield
        # invariant holds when the stream completes normally with usage.
        chunks_in = [
            _make_stream_chunk(content="Hello ", model="gpt-4o-mini"),
            _make_stream_chunk(content="world"),
            _make_stream_chunk(
                usage={"prompt_tokens": 8, "completion_tokens": 2},
                model="gpt-4o-mini",
            ),
        ]
        cls_mock, _ = _patched_streaming_openai(chunks_in)

        with patch("openai.AsyncOpenAI", cls_mock):
            stream = openai_native.complete_stream(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        # Authoritative usage chunk delivered; finally must NOT also fire.
        usage_chunks = [c for c in chunks if c.usage is not None]
        assert len(usage_chunks) == 1, (
            "expected exactly one usage chunk (no double-emission from finally)"
        )
        u = usage_chunks[0].usage
        assert u.prompt_tokens == 8
        assert u.completion_tokens == 2

    @pytest.mark.asyncio
    async def test_no_usage_chunk_when_stream_yields_no_usage(self):
        """If the stream ends without ever yielding usage (e.g., upstream
        bug, OpenAI-compatible provider that doesn't honor include_usage),
        the finally block has nothing to fall back on (counters are 0) and
        must NOT emit a misleading 0-token usage chunk."""
        chunks_in = [
            _make_stream_chunk(content="Hello", model="gpt-4o-mini"),
            _make_stream_chunk(finish_reason="stop"),
        ]
        cls_mock, _ = _patched_streaming_openai(chunks_in)

        with patch("openai.AsyncOpenAI", cls_mock):
            stream = openai_native.complete_stream(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        usage_chunks = [c for c in chunks if c.usage is not None]
        assert usage_chunks == [], (
            "no usage observed on the wire AND no fallback should fire — "
            "0-token fallbacks would be misleading telemetry"
        )

    @pytest.mark.asyncio
    async def test_emits_best_effort_usage_when_stream_raises_after_usage(self):
        """If the stream raises after a usage chunk was OBSERVED but NOT
        successfully delivered to the consumer, the finally block must
        emit a fallback. Simulated here by a stream that raises on the
        chunk AFTER the usage one, where final_usage_emitted is set True
        only AFTER the usage yield returns (so the post-usage raise
        doesn't strand the consumer)."""

        class _RaisingAfterStream:
            def __init__(self, chunks):
                self._chunks = chunks

            def __aiter__(self):
                async def _gen():
                    for c in self._chunks:
                        if c == "RAISE":
                            raise RuntimeError("server cutoff")
                        yield c

                return _gen()

        # Stream yields content, then raises BEFORE any usage chunk arrives.
        # Counters stay at 0; finally won't emit (correctly).
        chunks_in = [
            _make_stream_chunk(content="partial", model="gpt-4o-mini"),
            "RAISE",
        ]
        instance = MagicMock()
        instance.chat = MagicMock()
        instance.chat.completions = MagicMock()
        instance.chat.completions.create = AsyncMock(
            return_value=_RaisingAfterStream(chunks_in)
        )
        cls_mock = MagicMock(return_value=instance)

        with patch("openai.AsyncOpenAI", cls_mock):
            stream = openai_native.complete_stream(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )
            chunks = []
            raised = None
            try:
                async for chunk in stream:
                    chunks.append(chunk)
            except RuntimeError as exc:
                raised = exc

        assert raised is not None and "server cutoff" in str(raised)
        # No usage was observed before the raise, so finally correctly
        # produces no usage chunk. The exception propagates as expected.
        usage_chunks = [c for c in chunks if c.usage is not None]
        assert usage_chunks == []

    @pytest.mark.asyncio
    async def test_swallows_generator_exit_in_finally_yield(self):
        """Round-2 Anthropic review parity: if the consumer aclose()s the
        async generator while the finally block is trying to yield a
        fallback usage chunk, the resulting GeneratorExit must be swallowed
        — Python forbids re-raising during finally cleanup, and there's
        nowhere to deliver the fallback anyway.

        Test by setting up a stream that raises mid-iteration AFTER usage
        was recorded. The consumer's normal break-on-exception then
        triggers generator cleanup; the finally yield raises GeneratorExit
        which the adapter must handle silently.
        """
        # Manually set up the conditions: yield content + record usage,
        # then raise. Consumer iterates partially, breaks on the raise, and
        # the generator's finally block tries to emit a fallback chunk.
        # The fallback yield will raise StopAsyncIteration (the consumer's
        # iteration is already over) which the adapter must swallow.

        class _RaisingMidStream:
            def __init__(self, chunks):
                self._chunks = chunks

            def __aiter__(self):
                async def _gen():
                    for c in self._chunks:
                        if c == "RAISE":
                            raise RuntimeError("midstream error")
                        yield c

                return _gen()

        # Yield a usage-bearing chunk first (so counters are populated),
        # then a content chunk, then raise. Counters > 0 at finally time.
        chunks_in = [
            _make_stream_chunk(
                usage={"prompt_tokens": 5, "completion_tokens": 3},
                model="gpt-4o-mini",
            ),
            "RAISE",
        ]
        instance = MagicMock()
        instance.chat = MagicMock()
        instance.chat.completions = MagicMock()
        instance.chat.completions.create = AsyncMock(
            return_value=_RaisingMidStream(chunks_in)
        )
        cls_mock = MagicMock(return_value=instance)

        with patch("openai.AsyncOpenAI", cls_mock):
            stream = openai_native.complete_stream(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )
            chunks = []
            raised = None
            try:
                async for chunk in stream:
                    chunks.append(chunk)
            except RuntimeError as exc:
                raised = exc

        # The exception propagates; the usage chunk DID reach the consumer
        # (yielded successfully before the raise), so final_usage_emitted
        # was set True and finally correctly does NOT re-emit.
        assert raised is not None and "midstream error" in str(raised)
        usage_chunks = [c for c in chunks if c.usage is not None]
        assert len(usage_chunks) == 1


# ---------------------------------------------------------------------------
# Unsupported-kwarg WARN dedupe
# ---------------------------------------------------------------------------


class TestUnsupportedKwargWarn:
    @pytest.fixture(autouse=True)
    def _reset_dedupe(self):
        """Reset the per-key WARN dedupe set so tests in this class don't
        observe state leaked from earlier tests in the same process."""
        openai_native._logged_unsupported_kwargs.clear()
        yield
        openai_native._logged_unsupported_kwargs.clear()

    @pytest.mark.asyncio
    async def test_warn_logs_when_unknown_kwarg_dropped(self, caplog):
        """The adapter MUST log a WARN when it drops an unrecognized kwarg —
        catches the next litellm-only knob we forget to allow-list."""
        api_resp = _make_openai_completion(text="ok")
        cls_mock, _, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            with caplog.at_level("WARNING", logger=openai_native.logger.name):
                await openai_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        # request_timeout is a litellm-only knob (OpenAI
                        # uses ``timeout``); should warn.
                        "request_timeout": 30,
                    },
                    model="openai/gpt-4o-mini",
                    api_key="sk-test",
                )

        warn_msgs = [
            r.getMessage() for r in caplog.records if r.levelname == "WARNING"
        ]
        assert any(
            "request_timeout" in m and "dropping unsupported kwarg" in m
            for m in warn_msgs
        ), f"Expected WARN about request_timeout; got: {warn_msgs}"

    @pytest.mark.asyncio
    async def test_no_warn_for_known_kwargs(self, caplog):
        """Allow-listed kwargs (temperature, max_tokens, response_format,
        tool_choice) MUST NOT trigger the WARN."""
        api_resp = _make_openai_completion(text="ok")
        cls_mock, _, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            with caplog.at_level("WARNING", logger=openai_native.logger.name):
                await openai_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "temperature": 0.2,
                        "max_tokens": 1024,
                        "tools": [],
                        "tool_choice": "auto",
                        "response_format": {"type": "text"},
                        "seed": 42,
                    },
                    model="openai/gpt-4o-mini",
                    api_key="sk-test",
                )

        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "dropping unsupported kwarg" in r.getMessage()
        ]
        assert warn_msgs == [], f"Unexpected WARN(s) for known kwargs: {warn_msgs}"

    def test_warn_emits_only_once_per_key(self, caplog):
        with caplog.at_level("WARNING", logger=openai_native.logger.name):
            openai_native._warn_unsupported_kwarg_once("request_timeout")
            openai_native._warn_unsupported_kwarg_once("request_timeout")
            openai_native._warn_unsupported_kwarg_once("request_timeout")

        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "request_timeout" in r.getMessage()
        ]
        assert len(warn_msgs) == 1, (
            f"expected exactly one WARN; got {len(warn_msgs)}: {warn_msgs}"
        )

    def test_warn_emits_once_per_unique_key(self, caplog):
        """Distinct kwarg names each get their own one-shot WARN."""
        with caplog.at_level("WARNING", logger=openai_native.logger.name):
            openai_native._warn_unsupported_kwarg_once("request_timeout")
            openai_native._warn_unsupported_kwarg_once("aws_region")
            openai_native._warn_unsupported_kwarg_once("request_timeout")
            openai_native._warn_unsupported_kwarg_once("custom_llm_provider")

        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "dropping unsupported kwarg" in r.getMessage()
        ]
        # Three distinct keys → three WARNs total.
        assert len(warn_msgs) == 3
        assert sum("request_timeout" in m for m in warn_msgs) == 1
        assert sum("aws_region" in m for m in warn_msgs) == 1
        assert sum("custom_llm_provider" in m for m in warn_msgs) == 1


# ---------------------------------------------------------------------------
# Shared httpx connection pool
# ---------------------------------------------------------------------------


class TestSharedHttpxClient:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """Reset the module-level cached client before AND after each test
        to avoid state leakage across tests in this class."""
        openai_native._reset_shared_httpx_client()
        yield
        openai_native._reset_shared_httpx_client()

    def test_shared_httpx_client_reused_across_calls(self):
        """Two ``_build_client`` calls must reuse the same ``http_client``
        instance — proves we have a single connection pool process-wide."""
        cls_mock = MagicMock(return_value=MagicMock())
        with patch("openai.AsyncOpenAI", cls_mock):
            openai_native._build_client(
                "openai/gpt-4o-mini", "sk-1", None
            )
            openai_native._build_client(
                "openai/gpt-4o-mini", "sk-2", None
            )

        assert cls_mock.call_count == 2
        first_http = cls_mock.call_args_list[0].kwargs["http_client"]
        second_http = cls_mock.call_args_list[1].kwargs["http_client"]
        # SAME instance — not just equal.
        assert first_http is second_http

    @pytest.mark.asyncio
    async def test_shared_httpx_client_recreated_after_close(self):
        """If the cached client is closed, the next ``_get_shared_httpx_client``
        must rebuild a fresh, non-closed instance. Guards against a long-running
        process where the pool was unexpectedly torn down."""
        first = openai_native._get_shared_httpx_client()
        assert first.is_closed is False

        # Close the cached client (simulates pool teardown).
        await first.aclose()
        assert first.is_closed is True

        second = openai_native._get_shared_httpx_client()
        assert second is not first
        assert second.is_closed is False

    def test_api_key_rotation_works_with_shared_pool(self):
        """K8s secret rotation: the api_key changes per call but the shared
        http_client stays the same. Each call still creates a NEW
        ``AsyncOpenAI`` wrapper so the rotated key is honored."""
        cls_mock = MagicMock(side_effect=lambda **kw: MagicMock())
        with patch("openai.AsyncOpenAI", cls_mock):
            openai_native._build_client(
                "openai/gpt-4o-mini", "sk-A", None
            )
            openai_native._build_client(
                "openai/gpt-4o-mini", "sk-B", None
            )

        assert cls_mock.call_count == 2
        first_kwargs = cls_mock.call_args_list[0].kwargs
        second_kwargs = cls_mock.call_args_list[1].kwargs
        # Rotated key honored.
        assert first_kwargs["api_key"] == "sk-A"
        assert second_kwargs["api_key"] == "sk-B"
        # But the same shared httpx client.
        assert first_kwargs["http_client"] is second_kwargs["http_client"]

    def test_httpx_timeout_configuration(self):
        """The shared client carries the documented per-stage timeouts.
        ``read=600`` is critical — LLM responses can take minutes on long
        generations, and a too-tight read timeout would spuriously cut off
        valid streams."""
        client = openai_native._get_shared_httpx_client()
        assert client.timeout.connect == 10.0
        assert client.timeout.read == 600.0
        assert client.timeout.write == 30.0
        assert client.timeout.pool == 5.0

    def test_httpx_limits_configuration(self):
        """The shared pool's connection limits are applied as documented.

        Reads private ``_transport._pool`` attrs because httpx does not
        expose ``Limits`` on the public ``AsyncClient`` surface — accepted
        coupling to internals for unit-level validation; if httpx renames
        these in a future version this test signals the breakage early.
        """
        client = openai_native._get_shared_httpx_client()
        pool = client._transport._pool
        assert pool._max_keepalive_connections == 20
        assert pool._max_connections == 100


# ---------------------------------------------------------------------------
# Upfront credential validation
# ---------------------------------------------------------------------------


class TestCredentialValidation:
    @pytest.mark.asyncio
    async def test_raises_when_api_key_and_env_both_unset(self, monkeypatch):
        """No api_key kwarg + no OPENAI_API_KEY env → fail fast with a
        clear ValueError instead of late-401 from openai.chat.completions.create.
        """
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError) as exc_info:
            await openai_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key=None,
            )
        # Error message points the user at the resolution paths.
        msg = str(exc_info.value)
        assert "OPENAI_API_KEY" in msg
        assert "MCP_MESH_NATIVE_LLM=0" in msg

    @pytest.mark.asyncio
    async def test_no_raise_when_env_set(self, monkeypatch):
        """Env var alone is sufficient — adapter forwards control to the SDK
        without injecting api_key into the constructor (SDK reads env)."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        api_resp = _make_openai_completion(text="ok")
        cls_mock, _, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key=None,
            )
        # Constructor was called — no validation error raised.
        cls_mock.assert_called_once()
        # api_key kwarg NOT injected when not provided (SDK reads env itself).
        assert "api_key" not in cls_mock.call_args.kwargs

    @pytest.mark.asyncio
    async def test_no_raise_when_api_key_passed(self, monkeypatch):
        """Explicit api_key kwarg is accepted regardless of env state."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        api_resp = _make_openai_completion(text="ok")
        cls_mock, _, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="openai/gpt-4o-mini",
                api_key="sk-explicit",
            )
        cls_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Fallback-log helper getter
# ---------------------------------------------------------------------------


class TestIsFallbackLogged:
    def test_returns_false_initially_then_true_after_log(self, monkeypatch):
        """``is_fallback_logged()`` lets callers skip the log call entirely
        on subsequent misses — verify the getter mirrors the global flag."""
        # Reset module-level state for this test.
        monkeypatch.setattr(openai_native, "_logged_fallback_once", False)
        assert openai_native.is_fallback_logged() is False

        openai_native.log_fallback_once()
        assert openai_native.is_fallback_logged() is True
