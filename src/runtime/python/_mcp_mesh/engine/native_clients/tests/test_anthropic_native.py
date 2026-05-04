"""Unit tests for the native Anthropic SDK adapter (issue #834).

Covers:
  * is_available() reflects ImportError of the SDK
  * supports_model() matches expected vendor prefixes
  * complete() builds the correct ``messages.create`` kwargs from a
    typical litellm-shape input (system extraction, tool translation,
    message translation, prefix stripping)
  * complete() adapts the API response to a litellm-shape object
    (content + usage + tool_calls)
  * complete_stream() yields chunks matching the shape consumed by
    ``mesh.helpers._provider_agentic_loop_stream``
  * Bedrock model prefix routes through AsyncAnthropicBedrock
  * Custom base_url is forwarded to AsyncAnthropic
  * System message is extracted from the messages list and passed as
    ``system=`` (not as a message role)
  * Synthetic-tool pass-through: tool_use deltas for the synthetic
    ``__mesh_format_response`` tool flow through unchanged — the agentic
    loop in ``mesh.helpers`` recognizes the name post-merge. The previous
    response_format → adapter-side translation was removed (broke real
    tool calls — see issue #834 refactor).

Real network calls are mocked.
"""

from __future__ import annotations

import builtins
import importlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from _mcp_mesh.engine.native_clients import anthropic_native


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


class TestIsAvailable:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """is_available() now caches its result module-wide; reset between
        tests in this class so each one re-probes the import."""
        anthropic_native._reset_is_available_cache()
        yield
        anthropic_native._reset_is_available_cache()

    def test_returns_true_when_sdk_importable(self):
        # The SDK is installed in the test environment; this should be True.
        assert anthropic_native.is_available() is True

    def test_returns_false_when_import_fails(self, monkeypatch):
        """Simulate the SDK being absent by stubbing __import__ to raise."""
        original_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("No module named 'anthropic'")
            return original_import(name, *args, **kwargs)

        # Drop the cached module so the function re-evaluates the import.
        monkeypatch.delitem(sys.modules, "anthropic", raising=False)
        with patch("builtins.__import__", side_effect=_fake_import):
            assert anthropic_native.is_available() is False

    def test_caches_result_across_calls(self, monkeypatch):
        """Once probed, is_available() must not re-import on every call —
        the SDK presence does not change at runtime and the per-call import
        was showing up as needless overhead on the dispatch-decision path.
        """
        original_import = builtins.__import__
        call_count = {"n": 0}

        def _counting_import(name, *args, **kwargs):
            if name == "anthropic":
                call_count["n"] += 1
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_counting_import):
            anthropic_native.is_available()
            anthropic_native.is_available()
            anthropic_native.is_available()

        # Exactly one import attempt across three calls.
        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# supports_model()
# ---------------------------------------------------------------------------


class TestSupportsModel:
    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-3-5-sonnet-latest",
            "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
            "databricks/anthropic.claude-3-5-sonnet",
        ],
    )
    def test_supported_prefixes(self, model):
        assert anthropic_native.supports_model(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "openai/gpt-4o",
            "gemini/gemini-1.5-pro",
            "vertex_ai/gemini-1.5-pro",
            "bedrock/amazon.titan-text-express-v1",
            "claude-3-5-sonnet",  # bare, no prefix
            "",
            None,
        ],
    )
    def test_unsupported(self, model):
        assert anthropic_native.supports_model(model or "") is False


# ---------------------------------------------------------------------------
# Helpers shared across complete() tests
# ---------------------------------------------------------------------------


def _make_anthropic_message(
    *,
    text: str | None = None,
    tool_uses: list[dict] | None = None,
    model: str = "claude-sonnet-4-5",
    input_tokens: int = 12,
    output_tokens: int = 7,
):
    """Build a fake anthropic.types.Message-like object for complete() tests."""
    blocks: list[SimpleNamespace] = []
    if text is not None:
        blocks.append(SimpleNamespace(type="text", text=text))
    for tu in tool_uses or []:
        blocks.append(
            SimpleNamespace(
                type="tool_use",
                id=tu["id"],
                name=tu["name"],
                input=tu.get("input", {}),
            )
        )
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=blocks, usage=usage, model=model)


def _patched_async_anthropic(api_response):
    """Return a (cls_mock, messages_create_mock, instance_mock) triple.

    Patches anthropic.AsyncAnthropic so its instance has a
    ``.messages.create`` AsyncMock returning ``api_response``. Lets tests
    assert on both the constructor kwargs (api_key, base_url) and the
    create() kwargs.
    """
    instance = MagicMock()
    create_mock = AsyncMock(return_value=api_response)
    instance.messages = MagicMock()
    instance.messages.create = create_mock
    cls_mock = MagicMock(return_value=instance)
    return cls_mock, create_mock, instance


# ---------------------------------------------------------------------------
# complete() — request shaping
# ---------------------------------------------------------------------------


class TestCompleteRequestShape:
    @pytest.mark.asyncio
    async def test_strips_model_prefix(self):
        cls_mock, create_mock, _ = _patched_async_anthropic(
            _make_anthropic_message(text="hi")
        )
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert kwargs["model"] == "claude-sonnet-4-5"

    @pytest.mark.asyncio
    async def test_extracts_system_message_to_system_kwarg(self):
        cls_mock, create_mock, _ = _patched_async_anthropic(
            _make_anthropic_message(text="hi")
        )
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [
                        {"role": "system", "content": "You are helpful."},
                        {"role": "user", "content": "Hi."},
                    ]
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert kwargs["system"] == "You are helpful."
        # System message must NOT appear in the messages array.
        assert all(m["role"] != "system" for m in kwargs["messages"])
        assert kwargs["messages"] == [{"role": "user", "content": "Hi."}]

    @pytest.mark.asyncio
    async def test_translates_openai_tool_schema_to_anthropic(self):
        cls_mock, create_mock, _ = _patched_async_anthropic(
            _make_anthropic_message(text="ok")
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
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tools": [openai_tool],
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        tools = kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "get_weather"
        assert tools[0]["description"] == "Look up weather."
        # OpenAI's "parameters" → Anthropic's "input_schema".
        assert tools[0]["input_schema"]["properties"]["city"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_translates_role_tool_to_user_with_tool_result(self):
        cls_mock, create_mock, _ = _patched_async_anthropic(
            _make_anthropic_message(text="done")
        )
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [
                        {"role": "user", "content": "Use tool"},
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tool_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"city": "NYC"}',
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "tool_1",
                            "content": "72F sunny",
                        },
                    ]
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        msgs = kwargs["messages"]
        # 3 turns: user (text), assistant (tool_use), user (tool_result)
        assert len(msgs) == 3
        assert msgs[1]["role"] == "assistant"
        # Assistant message contains a tool_use block with parsed input.
        assistant_blocks = msgs[1]["content"]
        tool_use_block = next(b for b in assistant_blocks if b["type"] == "tool_use")
        assert tool_use_block["id"] == "tool_1"
        assert tool_use_block["name"] == "get_weather"
        assert tool_use_block["input"] == {"city": "NYC"}
        # Final turn is a user message containing tool_result.
        assert msgs[2]["role"] == "user"
        tool_result_block = msgs[2]["content"][0]
        assert tool_result_block["type"] == "tool_result"
        assert tool_result_block["tool_use_id"] == "tool_1"
        assert tool_result_block["content"] == "72F sunny"

    @pytest.mark.asyncio
    async def test_applies_default_max_tokens(self):
        cls_mock, create_mock, _ = _patched_async_anthropic(
            _make_anthropic_message(text="hi")
        )
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        # Anthropic requires max_tokens; we default to 8192 when caller omits.
        assert create_mock.call_args.kwargs["max_tokens"] == 8192

    @pytest.mark.asyncio
    async def test_passes_through_temperature_and_max_tokens(self):
        cls_mock, create_mock, _ = _patched_async_anthropic(
            _make_anthropic_message(text="hi")
        )
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert kwargs["temperature"] == 0.2
        assert kwargs["max_tokens"] == 1024

    @pytest.mark.asyncio
    async def test_drops_litellm_only_kwargs(self):
        """``response_format``, ``stream``, ``stream_options`` etc. must
        not be forwarded to anthropic.messages.create."""
        cls_mock, create_mock, _ = _patched_async_anthropic(
            _make_anthropic_message(text="hi")
        )
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "response_format": {"type": "json_object"},
                    "stream": True,  # should be ignored
                    "stream_options": {"include_usage": True},
                    "request_timeout": 30,
                    "parallel_tool_calls": True,
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        for forbidden in (
            "response_format",
            "stream",
            "stream_options",
            "request_timeout",
            "parallel_tool_calls",
        ):
            assert forbidden not in kwargs, f"{forbidden} leaked into create()"


# ---------------------------------------------------------------------------
# complete() — response shape
# ---------------------------------------------------------------------------


class TestCompleteResponseShape:
    @pytest.mark.asyncio
    async def test_text_only_response_adapts_to_mock_response(self):
        api_resp = _make_anthropic_message(
            text="Hello world",
            input_tokens=11,
            output_tokens=4,
            model="claude-sonnet-4-5",
        )
        cls_mock, _, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            response = await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        assert response.choices[0].message.content == "Hello world"
        assert response.choices[0].message.role == "assistant"
        assert response.choices[0].message.tool_calls is None
        assert response.usage.prompt_tokens == 11
        assert response.usage.completion_tokens == 4
        assert response.usage.total_tokens == 15
        assert response.model == "claude-sonnet-4-5"

    @pytest.mark.asyncio
    async def test_tool_use_response_adapts_to_tool_calls(self):
        api_resp = _make_anthropic_message(
            text=None,
            tool_uses=[
                {
                    "id": "toolu_abc",
                    "name": "get_weather",
                    "input": {"city": "NYC"},
                }
            ],
            input_tokens=20,
            output_tokens=8,
        )
        cls_mock, _, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            response = await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Weather?"}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        msg = response.choices[0].message
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        tc = msg.tool_calls[0]
        assert tc.id == "toolu_abc"
        assert tc.type == "function"
        assert tc.function.name == "get_weather"
        # Arguments come back as a JSON string (matches OpenAI/litellm shape).
        assert json.loads(tc.function.arguments) == {"city": "NYC"}
        assert response.usage.prompt_tokens == 20
        assert response.usage.completion_tokens == 8


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


class TestBackendSelection:
    @pytest.mark.asyncio
    async def test_bedrock_prefix_uses_async_anthropic_bedrock(self):
        api_resp = _make_anthropic_message(text="hi from bedrock")
        bedrock_cls = MagicMock()
        bedrock_instance = MagicMock()
        bedrock_instance.messages = MagicMock()
        bedrock_instance.messages.create = AsyncMock(return_value=api_resp)
        bedrock_cls.return_value = bedrock_instance

        # Also patch AsyncAnthropic to ensure it's NOT used for bedrock.
        direct_cls = MagicMock(side_effect=AssertionError("direct client used for bedrock"))

        with (
            patch("anthropic.AsyncAnthropic", direct_cls),
            patch("anthropic.AsyncAnthropicBedrock", bedrock_cls),
        ):
            response = await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
                # api_key unused for Bedrock; AWS chain handles auth.
            )

        bedrock_cls.assert_called_once()
        # Bedrock model id keeps the "anthropic." prefix as part of the
        # model identifier (only the "bedrock/" routing prefix is stripped).
        call_kwargs = bedrock_instance.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"
        assert response.choices[0].message.content == "hi from bedrock"

    @pytest.mark.asyncio
    async def test_custom_base_url_forwarded_to_async_anthropic(self):
        api_resp = _make_anthropic_message(text="hi")
        cls_mock, _, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
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
    async def test_databricks_prefix_uses_async_anthropic(self):
        api_resp = _make_anthropic_message(text="hi from databricks")
        cls_mock, create_mock, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="databricks/anthropic.claude-3-5-sonnet",
                api_key="dapi-token",
                base_url="https://workspace.databricks.com/serving-endpoints",
            )

        # Databricks routes through AsyncAnthropic with the workspace base_url.
        cls_mock.assert_called_once()
        ctor_kwargs = cls_mock.call_args.kwargs
        assert ctor_kwargs["api_key"] == "dapi-token"
        assert "databricks.com" in ctor_kwargs["base_url"]
        # Model id keeps "anthropic." prefix (only "databricks/" stripped).
        assert (
            create_mock.call_args.kwargs["model"]
            == "anthropic.claude-3-5-sonnet"
        )

    @pytest.mark.asyncio
    async def test_lazy_client_construction_per_call(self):
        """Two consecutive complete() calls must build TWO clients (no cache).

        This guards K8s secret rotation: the api_key must be re-read on
        every call, which only works if the client itself isn't cached.
        """
        api_resp = _make_anthropic_message(text="hi")
        cls_mock, _, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-1",
            )
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi again."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-2",  # rotated key
            )

        assert cls_mock.call_count == 2
        # Both calls used the key that was passed at request time.
        first_key = cls_mock.call_args_list[0].kwargs["api_key"]
        second_key = cls_mock.call_args_list[1].kwargs["api_key"]
        assert first_key == "sk-1"
        assert second_key == "sk-2"


# ---------------------------------------------------------------------------
# complete_stream() — chunk shape compatibility
# ---------------------------------------------------------------------------


def _stream_event(event_type: str, **fields):
    """Build a fake Anthropic streaming event."""
    return SimpleNamespace(type=event_type, **fields)


def _content_block(**fields):
    return SimpleNamespace(**fields)


class _FakeAsyncStream:
    """Async context manager yielding pre-canned events.

    Mirrors anthropic.lib.streaming.AsyncMessageStream's surface area used
    by complete_stream(): __aenter__ returns self; iterating self yields
    events; get_final_message() returns a message with .usage / .model /
    .stop_reason for the closing chunk.
    """

    def __init__(self, events: list, final_message):
        self._events = events
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        async def _gen():
            for e in self._events:
                yield e

        return _gen()

    async def get_final_message(self):
        return self._final_message


def _patched_streaming_anthropic(events, final_message):
    instance = MagicMock()
    fake_stream = _FakeAsyncStream(events, final_message)
    instance.messages = MagicMock()
    instance.messages.stream = MagicMock(return_value=fake_stream)
    cls_mock = MagicMock(return_value=instance)
    return cls_mock, instance


class TestCompleteStream:
    @pytest.mark.asyncio
    async def test_text_only_stream_yields_litellm_shaped_chunks(self):
        events = [
            _stream_event(
                "message_start",
                message=SimpleNamespace(model="claude-sonnet-4-5"),
            ),
            _stream_event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(type="text_delta", text="Hello "),
            ),
            _stream_event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(type="text_delta", text="world"),
            ),
            _stream_event("message_stop"),
        ]
        final_msg = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=15, output_tokens=4),
            model="claude-sonnet-4-5",
            stop_reason="end_turn",
        )
        cls_mock, _ = _patched_streaming_anthropic(events, final_msg)

        with patch("anthropic.AsyncAnthropic", cls_mock):
            stream = anthropic_native.complete_stream(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        # Pull text via the same accessors helpers.py uses.
        text_pieces = []
        for c in chunks:
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
        assert "claude-sonnet-4-5" in models

    @pytest.mark.asyncio
    async def test_tool_use_stream_yields_mergeable_tool_call_deltas(self):
        """Verify the streamed tool_call shape matches what
        ``MeshLlmAgent._merge_streamed_tool_calls`` expects: id+type+name
        appear once with index=N and arguments accrue across deltas.
        """
        events = [
            _stream_event(
                "message_start",
                message=SimpleNamespace(model="claude-sonnet-4-5"),
            ),
            _stream_event(
                "content_block_start",
                index=0,
                content_block=_content_block(
                    type="tool_use", id="toolu_xyz", name="get_weather"
                ),
            ),
            _stream_event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(
                    type="input_json_delta", partial_json='{"city": '
                ),
            ),
            _stream_event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(
                    type="input_json_delta", partial_json='"NYC"}'
                ),
            ),
            _stream_event("message_stop"),
        ]
        final_msg = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10, output_tokens=20),
            model="claude-sonnet-4-5",
            stop_reason="tool_use",
        )
        cls_mock, _ = _patched_streaming_anthropic(events, final_msg)

        with patch("anthropic.AsyncAnthropic", cls_mock):
            stream = anthropic_native.complete_stream(
                {"messages": [{"role": "user", "content": "Weather?"}]},
                model="anthropic/claude-sonnet-4-5",
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
        assert tc["id"] == "toolu_xyz"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "get_weather"
        assert tc["function"]["arguments"] == '{"city": "NYC"}'

        # And _chunk_has_tool_call should be True on the deltas.
        assert any(MeshLlmAgent._chunk_has_tool_call(c) for c in chunks)


# ---------------------------------------------------------------------------
# Synthetic tool pass-through (issue #834 refactor): the adapter no longer
# special-cases the synthetic format tool. The handler injects it upstream;
# the adapter forwards tool_use deltas uniformly for all tool names. The
# agentic loop in mesh.helpers disambiguates by name after merging.
# ---------------------------------------------------------------------------


class TestSyntheticToolPassThrough:
    @pytest.mark.asyncio
    async def test_synthetic_named_tool_use_emits_tool_call_delta_unchanged(self):
        """A tool_use whose name matches the synthetic format tool name MUST
        flow through as a regular ``_StreamToolCallDelta`` — no special
        buffering. The agentic loop recognizes the name post-merge.
        """
        events = [
            _stream_event(
                "message_start",
                message=SimpleNamespace(model="claude-sonnet-4-5"),
            ),
            _stream_event(
                "content_block_start",
                index=0,
                content_block=_content_block(
                    type="tool_use",
                    id="toolu_xyz",
                    name="__mesh_format_response",
                ),
            ),
            _stream_event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(
                    type="input_json_delta", partial_json='{"answer": '
                ),
            ),
            _stream_event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(
                    type="input_json_delta", partial_json='"42"}'
                ),
            ),
            _stream_event("message_stop"),
        ]
        final_msg = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=18, output_tokens=14),
            model="claude-sonnet-4-5",
            stop_reason="tool_use",
        )
        cls_mock, _ = _patched_streaming_anthropic(events, final_msg)

        with patch("anthropic.AsyncAnthropic", cls_mock):
            stream = anthropic_native.complete_stream(
                {"messages": [{"role": "user", "content": "Q?"}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        # Run the merger over the chunks to verify the synthetic tool's
        # arguments are recoverable end-to-end (this is what the agentic
        # loop in helpers.py does).
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        merged = MeshLlmAgent._merge_streamed_tool_calls(chunks)
        assert len(merged) == 1
        tc = merged[0]
        assert tc["function"]["name"] == "__mesh_format_response"
        assert json.loads(tc["function"]["arguments"]) == {"answer": "42"}


class TestToolChoicePassThrough:
    @pytest.mark.asyncio
    async def test_string_auto_translates_to_anthropic_auto(self):
        cls_mock, create_mock, _ = _patched_async_anthropic(
            _make_anthropic_message(text="ok")
        )
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "f",
                                "description": "",
                                "parameters": {"type": "object"},
                            },
                        }
                    ],
                    "tool_choice": "auto",
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        assert create_mock.call_args.kwargs["tool_choice"] == {"type": "auto"}

    @pytest.mark.asyncio
    async def test_openai_dict_translates_to_anthropic_named_tool(self):
        cls_mock, create_mock, _ = _patched_async_anthropic(
            _make_anthropic_message(text="ok")
        )
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "__mesh_format_response",
                                "description": "",
                                "parameters": {"type": "object"},
                            },
                        }
                    ],
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": "__mesh_format_response"},
                    },
                },
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        # Anthropic shape: {"type": "tool", "name": "..."}
        assert create_mock.call_args.kwargs["tool_choice"] == {
            "type": "tool",
            "name": "__mesh_format_response",
        }


class TestCompleteWithoutResponseFormat:
    @pytest.mark.asyncio
    async def test_kwargs_untouched_when_no_response_format(self):
        """Sanity check: existing HINT-mode behavior is preserved when
        response_format is absent. No synthetic tool, no forced tool_choice.
        """
        api_resp = _make_anthropic_message(text="ok")
        cls_mock, create_mock, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "tools" not in kwargs
        assert "tool_choice" not in kwargs
        assert "response_format" not in kwargs


class TestUnsupportedKwargWarn:
    @pytest.fixture(autouse=True)
    def _reset_dedupe(self):
        """Reset the per-key WARN dedupe set so tests in this class don't
        observe state leaked from earlier tests in the same process."""
        anthropic_native._logged_unsupported_kwargs.clear()
        yield
        anthropic_native._logged_unsupported_kwargs.clear()

    @pytest.mark.asyncio
    async def test_warn_logs_when_litellm_only_kwarg_dropped(self, caplog):
        """The adapter MUST log a WARN when it drops an unrecognized kwarg —
        this is the diagnostic that catches the next silent regression like
        the original response_format bug.
        """
        api_resp = _make_anthropic_message(text="ok")
        cls_mock, _, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
                await anthropic_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        # parallel_tool_calls is a litellm-only knob; should warn.
                        "parallel_tool_calls": True,
                    },
                    model="anthropic/claude-sonnet-4-5",
                    api_key="sk-test",
                )

        warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "parallel_tool_calls" in m and "dropping unsupported kwarg" in m
            for m in warn_msgs
        ), f"Expected WARN about parallel_tool_calls; got: {warn_msgs}"

    @pytest.mark.asyncio
    async def test_no_warn_for_known_kwargs(self, caplog):
        """Allow-listed kwargs (temperature, max_tokens) and explicitly handled
        ones (messages, tools, tool_choice) MUST NOT trigger the WARN.

        ``response_format`` is intentionally NOT in the handled set anymore
        (issue #834 refactor): the synthetic-tool pattern moved upstream to
        the handler. If response_format leaks here it WILL warn — that's a
        regression signal, not a bug in the test.
        """
        api_resp = _make_anthropic_message(text="ok")
        cls_mock, _, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
                await anthropic_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "temperature": 0.2,
                        "max_tokens": 1024,
                        "tools": [],
                        "tool_choice": "auto",
                    },
                    model="anthropic/claude-sonnet-4-5",
                    api_key="sk-test",
                )

        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "dropping unsupported kwarg" in r.getMessage()
        ]
        assert warn_msgs == [], f"Unexpected WARN(s) for known kwargs: {warn_msgs}"


# ---------------------------------------------------------------------------
# Shared httpx connection pool (issue #834 perf fix)
# ---------------------------------------------------------------------------
# The native adapter shares a single ``httpx.AsyncClient`` across all calls
# so the underlying TCP/TLS connection pool (and HTTP/2 sessions) is reused
# instead of paying ~150-300ms per-call setup overhead. K8s secret rotation
# still works because the api_key is passed fresh per call to the per-call
# ``AsyncAnthropic`` wrapper around the shared http_client.


class TestSharedHttpxClient:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        """Reset the module-level cached client before AND after each test
        to avoid state leakage across tests in this class."""
        anthropic_native._reset_shared_httpx_client()
        yield
        anthropic_native._reset_shared_httpx_client()

    def test_shared_httpx_client_reused_across_calls(self):
        """Two ``_build_client`` calls must reuse the same ``http_client``
        instance — proves we have a single connection pool process-wide."""
        cls_mock = MagicMock(return_value=MagicMock())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            anthropic_native._build_client(
                "anthropic/claude-sonnet-4-5", "sk-1", None
            )
            anthropic_native._build_client(
                "anthropic/claude-sonnet-4-5", "sk-2", None
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
        first = anthropic_native._get_shared_httpx_client()
        assert first.is_closed is False

        # Close the cached client (simulates pool teardown).
        await first.aclose()
        assert first.is_closed is True

        second = anthropic_native._get_shared_httpx_client()
        assert second is not first
        assert second.is_closed is False

    def test_api_key_rotation_works_with_shared_pool(self):
        """K8s secret rotation: the api_key changes per call but the shared
        http_client stays the same. Each call still creates a NEW
        ``AsyncAnthropic`` wrapper so the rotated key is honored."""
        cls_mock = MagicMock(side_effect=lambda **kw: MagicMock())
        with patch("anthropic.AsyncAnthropic", cls_mock):
            anthropic_native._build_client(
                "anthropic/claude-sonnet-4-5", "sk-A", None
            )
            anthropic_native._build_client(
                "anthropic/claude-sonnet-4-5", "sk-B", None
            )

        assert cls_mock.call_count == 2
        first_kwargs = cls_mock.call_args_list[0].kwargs
        second_kwargs = cls_mock.call_args_list[1].kwargs
        # Rotated key honored.
        assert first_kwargs["api_key"] == "sk-A"
        assert second_kwargs["api_key"] == "sk-B"
        # But the same shared httpx client.
        assert first_kwargs["http_client"] is second_kwargs["http_client"]

    def test_bedrock_skips_shared_pool(self):
        """Bedrock keeps per-call construction (boto3 SigV4 path) — no
        ``http_client`` kwarg is passed. Documented in ``_build_client``
        with a TODO for a future scoped change."""
        bedrock_cls = MagicMock(return_value=MagicMock())
        # Also patch direct so we can prove it's NOT used for bedrock.
        direct_cls = MagicMock(
            side_effect=AssertionError("direct client used for bedrock")
        )
        with (
            patch("anthropic.AsyncAnthropic", direct_cls),
            patch("anthropic.AsyncAnthropicBedrock", bedrock_cls),
        ):
            anthropic_native._build_client(
                "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0", None, None
            )

        bedrock_cls.assert_called_once()
        # No http_client passed on the Bedrock path.
        assert "http_client" not in bedrock_cls.call_args.kwargs

    def test_httpx_timeout_configuration(self):
        """The shared client carries the documented per-stage timeouts.
        ``read=600`` is critical — LLM responses can take minutes on long
        generations, and a too-tight read timeout would spuriously cut off
        valid streams."""
        client = anthropic_native._get_shared_httpx_client()
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
        client = anthropic_native._get_shared_httpx_client()
        pool = client._transport._pool
        assert pool._max_keepalive_connections == 20
        assert pool._max_connections == 100


# ---------------------------------------------------------------------------
# Content block translation: OpenAI image_url → Anthropic-native image
# (defensive fix for #834 multimedia regression — upstream callers emit
# OpenAI-shape image_url blocks regardless of vendor)
# ---------------------------------------------------------------------------


class TestContentBlockTranslation:
    def test_translate_image_url_data_uri_to_anthropic_image(self):
        block = {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,abc"},
        }
        result = anthropic_native._translate_content_block_to_anthropic(block)
        assert result == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "abc",
            },
        }

    def test_translate_image_url_data_uri_png(self):
        block = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
        }
        result = anthropic_native._translate_content_block_to_anthropic(block)
        assert result == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "iVBORw0KGgo=",
            },
        }

    def test_translate_image_url_http_url(self):
        block = {
            "type": "image_url",
            "image_url": {"url": "https://example.com/img.jpg"},
        }
        result = anthropic_native._translate_content_block_to_anthropic(block)
        assert result == {
            "type": "image",
            "source": {
                "type": "url",
                "url": "https://example.com/img.jpg",
            },
        }

    def test_translate_image_url_with_string_field(self):
        """Some clients flatten ``image_url`` to a bare string instead of
        ``{"url": "..."}``. The translator must accept both shapes."""
        block = {
            "type": "image_url",
            "image_url": "data:image/jpeg;base64,abc",
        }
        result = anthropic_native._translate_content_block_to_anthropic(block)
        assert result == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "abc",
            },
        }

    def test_translate_text_block_unchanged(self):
        block = {"type": "text", "text": "hello"}
        result = anthropic_native._translate_content_block_to_anthropic(block)
        assert result == {"type": "text", "text": "hello"}

    def test_translate_image_already_native_unchanged(self):
        """Idempotency: an already-native Anthropic image block must pass
        through untouched. Guards against double-translation if the
        translator runs twice (e.g. nested call paths)."""
        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "abc",
            },
        }
        result = anthropic_native._translate_content_block_to_anthropic(block)
        assert result is block  # not just equal — same object passthrough

    def test_translate_unknown_block_type_passthrough(self):
        block = {"type": "foo", "foo": "bar"}
        result = anthropic_native._translate_content_block_to_anthropic(block)
        assert result == {"type": "foo", "foo": "bar"}

    def test_translate_content_list_mixed_blocks(self):
        content = [
            {"type": "text", "text": "Look at these:"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64,IMG1"},
            },
            {"type": "text", "text": "and"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,IMG2"},
            },
        ]
        result = anthropic_native._translate_content_list_to_anthropic(content)
        assert len(result) == 4
        assert result[0] == {"type": "text", "text": "Look at these:"}
        assert result[1] == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "IMG1",
            },
        }
        assert result[2] == {"type": "text", "text": "and"}
        assert result[3] == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "IMG2",
            },
        }

    def test_translate_content_list_string_unchanged(self):
        result = anthropic_native._translate_content_list_to_anthropic("hello")
        assert result == "hello"

    def test_translate_content_list_non_list_unchanged(self):
        assert anthropic_native._translate_content_list_to_anthropic(None) is None

    def test_convert_messages_with_image_in_user_role(self):
        """End-to-end: a user message with an OpenAI-shape image_url block
        must produce a user message containing an Anthropic-native image
        block. Blocks the original 400 schema rejection from the SDK."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,XYZ"},
                    },
                ],
            }
        ]
        out = anthropic_native._convert_messages_to_anthropic(messages)
        assert len(out) == 1
        assert out[0]["role"] == "user"
        content = out[0]["content"]
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "What is this?"}
        assert content[1] == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "XYZ",
            },
        }

    def test_convert_messages_with_image_in_tool_result(self):
        """End-to-end regression test for the 200k-token blowout: tool_result
        content with image_url blocks MUST be emitted as a typed list (text
        + image blocks), NOT json.dumps'd as a string. The blowout happened
        because base64 image payloads, when serialized as JSON text, balloon
        the input token count past Anthropic's 200k limit.
        """
        messages = [
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": [
                    {"type": "text", "text": "Here are the images:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,IMG_DATA"},
                    },
                ],
            }
        ]
        out = anthropic_native._convert_messages_to_anthropic(messages)
        assert len(out) == 1
        assert out[0]["role"] == "user"
        tool_result = out[0]["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_use_id"] == "call_1"
        # CRITICAL: content must be a typed list, NOT a JSON string. This
        # is what fixes the 200k-token regression.
        assert isinstance(tool_result["content"], list), (
            "tool_result.content must be a typed list of blocks, not a "
            "JSON-encoded string (base64 images blow the token limit when "
            "serialized as text)"
        )
        assert tool_result["content"][0] == {
            "type": "text",
            "text": "Here are the images:",
        }
        assert tool_result["content"][1] == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "IMG_DATA",
            },
        }
        # And explicitly verify the base64 data is NOT embedded as a text
        # substring of any element — that would be the regression shape.
        import json as _json

        flat = _json.dumps(tool_result["content"])
        # The base64 data should appear inside source.data only, not as
        # part of a JSON-encoded text string with extra escaping.
        assert '"data": "IMG_DATA"' in flat

    def test_convert_messages_tool_result_string_content_unchanged(self):
        """String tool_result content (the common non-multimedia path) must
        keep passing through as a string — the typed-list path is only for
        multipart content."""
        messages = [
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "72F sunny",
            }
        ]
        out = anthropic_native._convert_messages_to_anthropic(messages)
        tool_result = out[0]["content"][0]
        assert tool_result["content"] == "72F sunny"
        assert isinstance(tool_result["content"], str)


# ---------------------------------------------------------------------------
# Stream interruption — best-effort usage emission (review fix BLOCKER)
# ---------------------------------------------------------------------------
# When a stream is cut short before ``message_stop`` arrives (server timeout,
# consumer aclose, network drop), the adapter must still emit a final usage
# chunk built from the last cumulative counters seen on the wire. Without
# this, telemetry silently records 0 tokens for any interrupted stream.


class TestStreamInterruptionUsage:
    @pytest.mark.asyncio
    async def test_emits_best_effort_usage_when_no_message_stop(self):
        """Stream ends after message_start + message_delta with cumulative
        output_tokens but BEFORE message_stop. The adapter MUST emit a final
        usage chunk built from the last seen values so observability still
        shows non-zero tokens for interrupted generations.
        """
        events = [
            _stream_event(
                "message_start",
                message=SimpleNamespace(
                    model="claude-sonnet-4-5",
                    usage=SimpleNamespace(input_tokens=42, output_tokens=0),
                ),
            ),
            _stream_event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(type="text_delta", text="Hello "),
            ),
            _stream_event(
                "message_delta",
                usage=SimpleNamespace(output_tokens=5),
            ),
            _stream_event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(type="text_delta", text="world"),
            ),
            _stream_event(
                "message_delta",
                usage=SimpleNamespace(output_tokens=11),
            ),
            # Notably NO message_stop — simulates server cutoff / aclose.
        ]
        # Final message is irrelevant here (get_final_message would only be
        # called from message_stop, which never fires).
        cls_mock, _ = _patched_streaming_anthropic(events, final_message=None)

        with patch("anthropic.AsyncAnthropic", cls_mock):
            stream = anthropic_native.complete_stream(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        # Last chunk should be the best-effort usage — non-None usage with
        # the cumulative counters we observed.
        usage_chunks = [c for c in chunks if c.usage is not None]
        assert len(usage_chunks) == 1, (
            "expected exactly one usage chunk emitted from the finally block"
        )
        u = usage_chunks[0].usage
        assert u.prompt_tokens == 42, "input_tokens should come from message_start"
        assert u.completion_tokens == 11, (
            "completion_tokens should be the LAST cumulative output_tokens "
            "seen on message_delta"
        )

    @pytest.mark.asyncio
    async def test_no_double_usage_when_message_stop_present(self):
        """Sanity check: when message_stop DOES arrive, only the authoritative
        get_final_message().usage chunk is emitted — the finally fallback
        must not also fire."""
        events = [
            _stream_event(
                "message_start",
                message=SimpleNamespace(
                    model="claude-sonnet-4-5",
                    usage=SimpleNamespace(input_tokens=8, output_tokens=0),
                ),
            ),
            _stream_event(
                "content_block_delta",
                index=0,
                delta=SimpleNamespace(type="text_delta", text="ok"),
            ),
            _stream_event(
                "message_delta",
                usage=SimpleNamespace(output_tokens=2),
            ),
            _stream_event("message_stop"),
        ]
        final_msg = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=8, output_tokens=2),
            model="claude-sonnet-4-5",
            stop_reason="end_turn",
        )
        cls_mock, _ = _patched_streaming_anthropic(events, final_msg)

        with patch("anthropic.AsyncAnthropic", cls_mock):
            stream = anthropic_native.complete_stream(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-test",
            )
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        usage_chunks = [c for c in chunks if c.usage is not None]
        assert len(usage_chunks) == 1
        # Authoritative tally from get_final_message().
        assert usage_chunks[0].usage.prompt_tokens == 8
        assert usage_chunks[0].usage.completion_tokens == 2


# ---------------------------------------------------------------------------
# Bedrock backend: WARN on ignored api_key, forward base_url (review fix W#2)
# ---------------------------------------------------------------------------


class TestBedrockKwargs:
    @pytest.mark.asyncio
    async def test_warns_when_api_key_passed_to_bedrock(self, caplog):
        """``AsyncAnthropicBedrock`` uses AWS credentials — passing ``api_key``
        is a misconfiguration that previously was silently ignored. Now WARN."""
        api_resp = _make_anthropic_message(text="ok")
        bedrock_cls = MagicMock()
        bedrock_instance = MagicMock()
        bedrock_instance.messages = MagicMock()
        bedrock_instance.messages.create = AsyncMock(return_value=api_resp)
        bedrock_cls.return_value = bedrock_instance

        with patch("anthropic.AsyncAnthropicBedrock", bedrock_cls):
            with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
                await anthropic_native.complete(
                    {"messages": [{"role": "user", "content": "Hi."}]},
                    model="bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
                    api_key="sk-mistakenly-passed",
                )

        warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "Bedrock backend ignores api_key" in m for m in warn_msgs
        ), f"Expected Bedrock api_key WARN; got: {warn_msgs}"

    @pytest.mark.asyncio
    async def test_base_url_forwarded_to_bedrock(self):
        """``base_url`` IS honored by AsyncAnthropicBedrock (VPC PrivateLink,
        LocalStack endpoints) — the adapter must forward it when set."""
        api_resp = _make_anthropic_message(text="ok")
        bedrock_cls = MagicMock()
        bedrock_instance = MagicMock()
        bedrock_instance.messages = MagicMock()
        bedrock_instance.messages.create = AsyncMock(return_value=api_resp)
        bedrock_cls.return_value = bedrock_instance

        with patch("anthropic.AsyncAnthropicBedrock", bedrock_cls):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
                base_url="https://bedrock-runtime.vpce-abc.vpce.amazonaws.com",
            )

        bedrock_cls.assert_called_once()
        ctor_kwargs = bedrock_cls.call_args.kwargs
        assert ctor_kwargs.get("base_url") == (
            "https://bedrock-runtime.vpce-abc.vpce.amazonaws.com"
        )

    @pytest.mark.asyncio
    async def test_no_base_url_kwarg_when_none(self):
        """When ``base_url`` is not provided, the Bedrock ctor must not get
        a ``base_url=None`` kwarg (would override the SDK default)."""
        api_resp = _make_anthropic_message(text="ok")
        bedrock_cls = MagicMock()
        bedrock_instance = MagicMock()
        bedrock_instance.messages = MagicMock()
        bedrock_instance.messages.create = AsyncMock(return_value=api_resp)
        bedrock_cls.return_value = bedrock_instance

        with patch("anthropic.AsyncAnthropicBedrock", bedrock_cls):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
            )

        ctor_kwargs = bedrock_cls.call_args.kwargs
        assert "base_url" not in ctor_kwargs


# ---------------------------------------------------------------------------
# Upfront credential validation (review fix W#6)
# ---------------------------------------------------------------------------


class TestCredentialValidation:
    @pytest.mark.asyncio
    async def test_raises_when_api_key_and_env_both_unset(self, monkeypatch):
        """No api_key kwarg + no ANTHROPIC_API_KEY env → fail fast with a
        clear ValueError instead of late-401 from anthropic.messages.create.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError) as exc_info:
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key=None,
            )
        # Error message points the user at the resolution paths.
        msg = str(exc_info.value)
        assert "ANTHROPIC_API_KEY" in msg
        assert "MCP_MESH_NATIVE_LLM=0" in msg

    @pytest.mark.asyncio
    async def test_no_raise_when_env_set(self, monkeypatch):
        """Env var alone is sufficient — adapter forwards control to the SDK
        without injecting api_key into the constructor (SDK reads env)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
        api_resp = _make_anthropic_message(text="ok")
        cls_mock, _, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key=None,
            )
        # Constructor was called — no validation error raised.
        cls_mock.assert_called_once()
        # api_key kwarg NOT injected when not provided (SDK reads env itself).
        assert "api_key" not in cls_mock.call_args.kwargs

    @pytest.mark.asyncio
    async def test_no_raise_when_api_key_passed(self, monkeypatch):
        """Explicit api_key kwarg is accepted regardless of env state."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        api_resp = _make_anthropic_message(text="ok")
        cls_mock, _, _ = _patched_async_anthropic(api_resp)
        with patch("anthropic.AsyncAnthropic", cls_mock):
            await anthropic_native.complete(
                {"messages": [{"role": "user", "content": "Hi."}]},
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-explicit",
            )
        cls_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Per-key WARN dedupe for unsupported kwargs (review fix W#5)
# ---------------------------------------------------------------------------


class TestUnsupportedKwargDedupe:
    @pytest.fixture(autouse=True)
    def _reset(self):
        anthropic_native._logged_unsupported_kwargs.clear()
        yield
        anthropic_native._logged_unsupported_kwargs.clear()

    def test_warn_emits_only_once_per_key(self, caplog):
        with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
            anthropic_native._warn_unsupported_kwarg_once("parallel_tool_calls")
            anthropic_native._warn_unsupported_kwarg_once("parallel_tool_calls")
            anthropic_native._warn_unsupported_kwarg_once("parallel_tool_calls")

        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "parallel_tool_calls" in r.getMessage()
        ]
        assert len(warn_msgs) == 1, (
            f"expected exactly one WARN; got {len(warn_msgs)}: {warn_msgs}"
        )

    def test_warn_emits_once_per_unique_key(self, caplog):
        """Distinct kwarg names each get their own one-shot WARN."""
        with caplog.at_level("WARNING", logger=anthropic_native.logger.name):
            anthropic_native._warn_unsupported_kwarg_once("parallel_tool_calls")
            anthropic_native._warn_unsupported_kwarg_once("stream_options")
            anthropic_native._warn_unsupported_kwarg_once("parallel_tool_calls")
            anthropic_native._warn_unsupported_kwarg_once("request_timeout")

        warn_msgs = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "dropping unsupported kwarg" in r.getMessage()
        ]
        # Three distinct keys → three WARNs total.
        assert len(warn_msgs) == 3
        # Each key appears exactly once.
        assert sum("parallel_tool_calls" in m for m in warn_msgs) == 1
        assert sum("stream_options" in m for m in warn_msgs) == 1
        assert sum("request_timeout" in m for m in warn_msgs) == 1


# ---------------------------------------------------------------------------
# Fallback-log helper getter (review fix INFO #11)
# ---------------------------------------------------------------------------


class TestIsFallbackLogged:
    def test_returns_false_initially_then_true_after_log(self, monkeypatch):
        """``is_fallback_logged()`` lets callers skip the log call entirely
        on subsequent misses — verify the getter mirrors the global flag."""
        # Reset module-level state for this test.
        monkeypatch.setattr(anthropic_native, "_logged_fallback_once", False)
        assert anthropic_native.is_fallback_logged() is False

        anthropic_native.log_fallback_once()
        assert anthropic_native.is_fallback_logged() is True
