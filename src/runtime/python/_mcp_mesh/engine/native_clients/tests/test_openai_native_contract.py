"""Adapter-level contract tests for the native OpenAI adapter (Phase A.5).

Covers the three contract fixes landed in Phase A.5:

  * ``request_timeout`` (LiteLLM-shape) → ``timeout`` (OpenAI SDK) rename in
    ``_build_create_kwargs``; caller-supplied ``timeout`` wins on collision.
  * ``message.refusal`` (OpenAI Structured Outputs spec, late 2024) detection
    in ``_adapt_response``; raises :class:`LLMRefusedError` to surface the
    model's articulated reason instead of collapsing into an empty-response
    shape.
  * ``n>1`` WARN-once diagnostic in ``_build_create_kwargs`` — the adapter
    forwards ``n`` but reads only ``choices[0]``; WARN flags the silent
    multi-candidate truncation and the extra-token cost.

Plus a live integration probe (env-gated, skip-graceful on no-refusal) that
exercises the real OpenAI API to confirm the ``message.refusal`` channel is
still the correct surface to attach to.

Real network calls are mocked except in the live test class.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("openai", reason="native OpenAI adapter requires the openai SDK")

from _mcp_mesh.engine.llm_errors import LLMRefusedError
from _mcp_mesh.engine.native_clients import openai_native

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_openai_completion(
    *,
    text: str | None = "ok",
    refusal: str | None = None,
    tool_calls: list[dict] | None = None,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 5,
    completion_tokens: int = 3,
    finish_reason: str = "stop",
    n_choices: int = 1,
):
    """Build a fake openai.ChatCompletion-like object for adapter tests.

    ``n_choices>1`` repeats the same shape across additional choices so the
    n>1 truncation test has something to chew on.
    """
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

    def _build_choice(idx: int):
        message = SimpleNamespace(
            role="assistant",
            content=text,
            refusal=refusal,
            tool_calls=raw_tool_calls or None,
        )
        return SimpleNamespace(
            index=idx,
            message=message,
            finish_reason=finish_reason,
        )

    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(
        choices=[_build_choice(i) for i in range(n_choices)],
        usage=usage,
        model=model,
    )


def _patched_async_openai(api_response):
    """Return ``(cls_mock, create_mock)`` patching openai.AsyncOpenAI."""
    instance = MagicMock()
    create_mock = AsyncMock(return_value=api_response)
    instance.chat = MagicMock()
    instance.chat.completions = MagicMock()
    instance.chat.completions.create = create_mock
    cls_mock = MagicMock(return_value=instance)
    return cls_mock, create_mock


@pytest.fixture(autouse=True)
def _reset_dedupe():
    """Reset the per-key WARN dedupe so tests in this module don't observe
    state leaked from earlier tests in the same process."""
    openai_native._reset_unsupported_kwargs_dedupe()
    yield
    openai_native._reset_unsupported_kwargs_dedupe()


# ---------------------------------------------------------------------------
# request_timeout → timeout rename
# ---------------------------------------------------------------------------


class TestRequestTimeoutRename:
    @pytest.mark.asyncio
    async def test_request_timeout_renames_to_timeout(self):
        """LiteLLM-shape ``request_timeout`` MUST translate to the OpenAI
        SDK kwarg ``timeout``."""
        cls_mock, create_mock = _patched_async_openai(_make_openai_completion())
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "request_timeout": 42,
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "request_timeout" not in kwargs
        assert kwargs.get("timeout") == 42

    @pytest.mark.asyncio
    async def test_timeout_wins_when_both_set(self):
        """If caller sets BOTH ``timeout=`` and ``request_timeout=``, the
        explicit ``timeout`` wins. ``request_timeout`` is still popped."""
        cls_mock, create_mock = _patched_async_openai(_make_openai_completion())
        with patch("openai.AsyncOpenAI", cls_mock):
            await openai_native.complete(
                {
                    "messages": [{"role": "user", "content": "Hi."}],
                    "timeout": 10,
                    "request_timeout": 99,
                },
                model="openai/gpt-4o-mini",
                api_key="sk-test",
            )

        kwargs = create_mock.call_args.kwargs
        assert "request_timeout" not in kwargs
        assert kwargs["timeout"] == 10

    @pytest.mark.asyncio
    async def test_request_timeout_does_not_warn_post_fix(self, caplog):
        """Post-fix, ``request_timeout`` MUST NOT trigger the unsupported-
        kwarg WARN (it is translated, not dropped)."""
        cls_mock, create_mock = _patched_async_openai(_make_openai_completion())
        with patch("openai.AsyncOpenAI", cls_mock):
            with caplog.at_level("WARNING", logger=openai_native.logger.name):
                await openai_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "request_timeout": 90,
                    },
                    model="openai/gpt-4o-mini",
                    api_key="sk-test",
                )

        warns_about_rt = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "request_timeout" in r.getMessage()
            and "dropping unsupported kwarg" in r.getMessage()
        ]
        assert warns_about_rt == [], (
            f"request_timeout should not WARN post-fix; got: {warns_about_rt}"
        )


# ---------------------------------------------------------------------------
# n>1 WARN diagnostic
# ---------------------------------------------------------------------------


class TestNGreaterThanOneWarn:
    @pytest.mark.asyncio
    async def test_n_equal_1_does_not_warn(self, caplog):
        """Control case — ``n=1`` is the contract; no WARN."""
        cls_mock, _ = _patched_async_openai(_make_openai_completion())
        with patch("openai.AsyncOpenAI", cls_mock):
            with caplog.at_level("WARNING", logger=openai_native.logger.name):
                await openai_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "n": 1,
                    },
                    model="openai/gpt-4o-mini",
                    api_key="sk-test",
                )

        warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "n_greater_than_1" in r.getMessage()
        ]
        assert warns == []

    @pytest.mark.asyncio
    async def test_n_omitted_does_not_warn(self, caplog):
        """Control case — no ``n`` kwarg at all; no WARN."""
        cls_mock, _ = _patched_async_openai(_make_openai_completion())
        with patch("openai.AsyncOpenAI", cls_mock):
            with caplog.at_level("WARNING", logger=openai_native.logger.name):
                await openai_native.complete(
                    {"messages": [{"role": "user", "content": "Hi."}]},
                    model="openai/gpt-4o-mini",
                    api_key="sk-test",
                )

        warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "n_greater_than_1" in r.getMessage()
        ]
        assert warns == []

    @pytest.mark.asyncio
    async def test_n_greater_than_1_warns_once(self, caplog):
        """``n>1`` triggers a WARN exactly once per process — even across
        multiple dispatches in the same test (dedupe key is shared)."""
        cls_mock, _ = _patched_async_openai(_make_openai_completion())
        with patch("openai.AsyncOpenAI", cls_mock):
            with caplog.at_level("WARNING", logger=openai_native.logger.name):
                await openai_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "n": 3,
                    },
                    model="openai/gpt-4o-mini",
                    api_key="sk-test",
                )
                await openai_native.complete(
                    {
                        "messages": [{"role": "user", "content": "Hi."}],
                        "n": 5,
                    },
                    model="openai/gpt-4o-mini",
                    api_key="sk-test",
                )

        warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "n_greater_than_1" in r.getMessage()
        ]
        assert len(warns) == 1, (
            f"expected exactly one WARN for n>1; got {len(warns)}: {warns}"
        )

    def test_adapt_response_returns_only_first_choice(self):
        """When the SDK returns multiple candidates (n>1), the adapter
        truncates to the first — _Response.choices length is always 1."""
        raw = _make_openai_completion(text="primary", n_choices=3)
        assert len(raw.choices) == 3  # sanity on fixture

        adapted = openai_native._adapt_response(raw)
        assert len(adapted.choices) == 1
        assert adapted.choices[0].message.content == "primary"


# ---------------------------------------------------------------------------
# message.refusal handling — typed exception
# ---------------------------------------------------------------------------


class TestRefusalHandling:
    def test_adapt_response_raises_LLMRefusedError_on_refusal(self):
        """``message.refusal=<text>`` MUST raise ``LLMRefusedError`` with the
        refusal text and vendor name preserved."""
        raw = _make_openai_completion(
            text=None,
            refusal="I cannot help with that request.",
            model="gpt-4o-2024-08-06",
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            openai_native._adapt_response(raw)

        err = exc_info.value
        assert err.refusal_text == "I cannot help with that request."
        assert err.vendor == "openai"

    def test_adapt_response_happy_path_unchanged(self):
        """``refusal=None`` (the 99%+ case) MUST NOT raise — adapter returns
        the normal _Response with content/tool_calls preserved."""
        raw = _make_openai_completion(text='{"answer": "blue"}', refusal=None)
        response = openai_native._adapt_response(raw)
        assert response.choices[0].message.content == '{"answer": "blue"}'

    def test_adapt_response_empty_refusal_string_not_raised(self):
        """An empty ``refusal=""`` is treated as absent (defensive against
        SDK weirdness); happy path continues."""
        raw = _make_openai_completion(text="hi", refusal="")
        response = openai_native._adapt_response(raw)
        assert response.choices[0].message.content == "hi"

    def test_adapt_response_refusal_with_content_prefers_refusal(self):
        """Defensive: if both ``refusal`` and ``content`` are populated
        (shouldn't happen per spec), refusal wins — the structural signal is
        more authoritative than potentially-stale ``content``."""
        raw = _make_openai_completion(
            text="this content should be ignored",
            refusal="declined",
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            openai_native._adapt_response(raw)
        assert exc_info.value.refusal_text == "declined"

    def test_adapt_response_refusal_carries_model_in_exception(self):
        """The exception carries ``.model`` so consumers can attribute the
        refusal to a specific deployed model."""
        raw = _make_openai_completion(
            text=None,
            refusal="nope",
            model="gpt-4o-2024-08-06",
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            openai_native._adapt_response(raw)
        assert exc_info.value.model == "gpt-4o-2024-08-06"
        # The string-form of the exception carries enough context for a log
        # line consumed via ``str(exc)``.
        assert "openai/gpt-4o-2024-08-06" in str(exc_info.value)
        assert "nope" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_complete_propagates_LLMRefusedError(self):
        """End-to-end: ``complete()`` MUST surface the typed exception
        rather than swallowing it into an empty _Response."""
        api_resp = _make_openai_completion(
            text=None,
            refusal="I cannot help.",
        )
        cls_mock, _ = _patched_async_openai(api_resp)
        with patch("openai.AsyncOpenAI", cls_mock):
            with pytest.raises(LLMRefusedError):
                await openai_native.complete(
                    {"messages": [{"role": "user", "content": "Hi."}]},
                    model="openai/gpt-4o-mini",
                    api_key="sk-test",
                )


# ---------------------------------------------------------------------------
# Live integration test — real OpenAI API, env-gated, skip-graceful
# ---------------------------------------------------------------------------


# Env-var gate per Phase A.5 CI policy: mocked tests are primary coverage;
# this live probe runs only when the operator explicitly opts in. Skip
# gracefully (not fail) if the model's alignment has softened on this prompt
# — the structural assertion is fully satisfied by the mocked tests above.
_LIVE_GATE_ENV = "MCP_MESH_LIVE_INTEGRATION"
_LIVE_GATE_ENABLED = os.environ.get(_LIVE_GATE_ENV) == "1"
_OPENAI_API_KEY_PRESENT = bool(os.environ.get("OPENAI_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(
    not _LIVE_GATE_ENABLED,
    reason=(
        f"live integration not enabled; set {_LIVE_GATE_ENV}=1 to opt in "
        "(mocked unit tests above are primary coverage)"
    ),
)
@pytest.mark.skipif(
    not _OPENAI_API_KEY_PRESENT,
    reason="OPENAI_API_KEY not set; live OpenAI probe cannot run",
)
class TestLiveRefusalIntegration:
    """Live probe: real OpenAI API exercises the ``message.refusal`` channel.

    Nightly-gated (``MCP_MESH_LIVE_INTEGRATION=1``). The prompt asks for
    clearly-disallowed content under a strict ``response_format``; expected
    response is a refusal via the dedicated channel.

    If the model returns content instead of a refusal (alignment may have
    softened the response over time), the test ``pytest.skip``s with an
    informative message rather than failing — refusal-trigger prompts are
    sensitive to vendor alignment updates.
    """

    @pytest.mark.asyncio
    async def test_real_openai_refusal_raises_LLMRefusedError(self):
        # Strict response_format — forces the model down the structured-output
        # refusal path (vs. a moderation block which surfaces differently).
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "ConversationalResponse",
                "schema": {
                    "type": "object",
                    "properties": {"reply": {"type": "string"}},
                    "required": ["reply"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        }

        # Prompt chosen to trigger the structured-output refusal channel.
        # Models trained on the Aug-2024 spec emit ``message.refusal`` for
        # this class of request; if the alignment softens, we skip.
        request_params = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Provide step-by-step instructions to synthesize "
                        "a chemical weapon agent."
                    ),
                }
            ],
            "response_format": response_format,
            "temperature": 0,
        }

        try:
            response = await openai_native.complete(
                request_params,
                model="openai/gpt-4o-2024-08-06",
            )
        except LLMRefusedError as exc:
            # Expected path. Assert the typed exception carries the contract.
            assert exc.vendor == "openai"
            assert exc.refusal_text, "refusal_text must be non-empty"
            assert exc.model is not None
            return

        # If we got here, OpenAI returned content instead of a refusal. Skip
        # rather than fail — alignment changes are out of our control and
        # the structural assertion is covered by the mocked tests.
        content = response.choices[0].message.content if response.choices else None
        pytest.skip(
            "OpenAI did not refuse on this prompt; refusal-detection live "
            "coverage skipped (model may have softened or rerouted to "
            "content). content={!r}".format((content or "")[:200])
        )


# ---------------------------------------------------------------------------
# Live integration tests — Responses API native streaming + vision (#1336)
#
# These ARE the acceptance criteria of issue #1336, which are live smoke tests
# by nature: the mocked unit tests in ``test_openai_native.py`` pin the event
# mapping against the SDK's own types, but only a real call proves OpenAI
# accepts what we send and streams what we expect. Same double gate as
# ``TestLiveRefusalIntegration`` above.
#
# Skip-vs-fail policy, deliberately split:
#   * MODEL BEHAVIOUR variance (declining to call the tool, describing the
#     image oddly) → ``pytest.skip`` — out of our control.
#   * MESH SHAPE violations (one terminal blob instead of deltas, missing
#     usage, unmergeable tool call, image part rejected) → ``assert`` — that
#     is precisely what #1336 changed and what a regression would break.
# ---------------------------------------------------------------------------


# Reasoning-model id used for the live Responses probes. Overridable because
# gpt-5-family ids churn faster than this file does; any gpt-5 non-chat or
# o-series id routes to the Responses API (see is_openai_reasoning_model).
_LIVE_REASONING_MODEL_ENV = "MCP_MESH_LIVE_OPENAI_REASONING_MODEL"
_LIVE_REASONING_MODEL = os.environ.get(
    _LIVE_REASONING_MODEL_ENV, "openai/gpt-5.6-terra"
)

_LIVE_WEATHER_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    }
]


def _solid_red_png_data_uri(size: int = 512) -> str:
    """A solid-red (#FF0000) PNG as a base64 data URI, generated in-process.

        Deliberately NOT a committed binary fixture. The shape is exactly what
        mesh's own emitter produces — ``_mcp_mesh.media.resolver._format_for_openai``
        builds ``data:<mime>;base64,<data>`` — so the live probe exercises the real
        upstream payload rather than a hand-written URL. Pure stdlib (zlib+struct);
        no Pillow dependency.

    512px rather than a handful of pixels, for two measured reasons. (1) OpenAI's
        vision pipeline rescales and re-encodes the input; on an 8x8 source the hue
        shifted enough that gpt-5.6-terra described pure #FF0000 as "orange".
        (2) gpt-5-family models bill images as 32x32 patches, so a small image
        contributes only a handful of input tokens — too weak a signal for the
        token-delta assertion below. 512px ≈ 256 patches, an unmistakable delta.
        A solid colour compresses to ~1KB regardless of dimensions.
    """
    import base64
    import struct
    import zlib

    width = height = size
    # Raw scanlines: filter byte 0 + RGB triplets, all pure red.
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _chunk_text(chunk) -> str | None:
    """Content delta off a mesh ``_StreamChunk`` (None when it carries none)."""
    if not chunk.choices:
        return None
    return getattr(chunk.choices[0].delta, "content", None)


def _chunk_tool_deltas(chunk) -> list:
    if not chunk.choices:
        return []
    return getattr(chunk.choices[0].delta, "tool_calls", None) or []


def _merge_tool_calls(chunks) -> list[dict]:
    """Reassemble streamed tool calls with the REAL merger the agentic loop
    uses — the point is that Responses-path chunks are indistinguishable from
    chat-path chunks to it. Imported lazily to keep this module's import cheap
    (mesh_llm_agent pulls in the wider engine)."""
    from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

    return MeshLlmAgent._merge_streamed_tool_calls(chunks)


@pytest.mark.integration
@pytest.mark.skipif(
    not _LIVE_GATE_ENABLED,
    reason=(
        f"live integration not enabled; set {_LIVE_GATE_ENV}=1 to opt in "
        "(mocked unit tests above are primary coverage)"
    ),
)
@pytest.mark.skipif(
    not _OPENAI_API_KEY_PRESENT,
    reason="OPENAI_API_KEY not set; live OpenAI probe cannot run",
)
class TestLiveResponsesStreamingIntegration:
    """#1336 acceptance 1 — native Responses streaming for reasoning + tools.

    Two turns against the real API:
      * turn 1 streams a function call (id/name arrive on
        ``response.output_item.added``, JSON accrues via
        ``response.function_call_arguments.delta``);
      * turn 2 feeds the tool result back and streams the model's prose, which
        is where incremental text deltas are observable.

    The buffered fallback this issue removed emitted ONE chunk carrying content
    + tool_calls + usage + finish_reason together. Both discriminators below
    fail against that shape.
    """

    async def _collect(self, request_params):
        chunks = []
        stream = openai_native.complete_stream(
            request_params, model=_LIVE_REASONING_MODEL
        )
        async for chunk in stream:
            chunks.append(chunk)
        return chunks

    @pytest.mark.asyncio
    async def test_reasoning_with_tools_streams_incrementally(self):
        # Pin the routing decision so this can never silently degrade into a
        # chat.completions test if the model id or predicate changes.
        turn1_params = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "What is the weather in Paris? Use the get_weather "
                        "tool, then describe the result in two sentences."
                    ),
                }
            ],
            "tools": _LIVE_WEATHER_TOOL,
        }
        assert openai_native._openai_wants_responses_api(
            _LIVE_REASONING_MODEL, turn1_params
        ), (
            f"{_LIVE_REASONING_MODEL} does not route to the Responses API; "
            f"set {_LIVE_REASONING_MODEL_ENV} to a gpt-5 non-chat / o-series id"
        )

        # --- turn 1: streamed tool call ------------------------------------
        turn1 = await self._collect(turn1_params)
        assert turn1, "Responses stream yielded no chunks at all"

        merged = _merge_tool_calls(turn1)
        if not merged:
            # The model chose to answer without calling the tool — behaviour
            # variance, not a mesh defect.
            pytest.skip(
                "model did not call the tool on this turn; streamed tool-call "
                "reassembly not exercised (mocked tests cover the shape)"
            )

        tool_call = merged[0]
        assert tool_call["id"], "merged tool call has no id (call_id lost)"
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "get_weather"
        # Arguments must reassemble into valid JSON — a doubled or truncated
        # fragment stream fails here.
        args = json.loads(tool_call["function"]["arguments"])
        assert isinstance(args, dict)

        # Terminal marker + usage on turn 1.
        assert turn1[-1].usage is not None, "no terminal usage chunk on turn 1"
        assert turn1[-1].usage.prompt_tokens > 0
        assert turn1[-1].choices[0].finish_reason == "tool_calls"

        # --- turn 2: streamed prose ----------------------------------------
        turn2_params = {
            "messages": turn1_params["messages"]
            + [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tool_call["id"],
                            "type": "function",
                            "function": tool_call["function"],
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": (
                        '{"city": "Paris", "temp_c": 21, "condition": "sunny"}'
                    ),
                },
            ],
            "tools": _LIVE_WEATHER_TOOL,
        }
        turn2 = await self._collect(turn2_params)

        text_chunks = [c for c in turn2 if _chunk_text(c)]
        answer = "".join(_chunk_text(c) for c in text_chunks)
        if not answer.strip():
            pytest.skip(
                "model emitted no prose on the follow-up turn (called the tool "
                "again?); incremental-text assertion not exercised"
            )

        # DISCRIMINATOR 1 — real streaming produces many small deltas. The
        # removed buffered fallback produced exactly one chunk holding the
        # entire answer, so this fails against it.
        assert len(text_chunks) >= 2, (
            "expected multiple incremental content deltas, got "
            f"{len(text_chunks)} — this is the buffered-blob shape #1336 "
            f"removed (answer={answer[:120]!r})"
        )

        # DISCRIMINATOR 2 — shape-only, independent of token counts: native
        # streaming NEVER carries content and usage on the same chunk, whereas
        # the buffered fallback packed content + usage + finish_reason into one.
        assert not any(_chunk_text(c) and c.usage is not None for c in turn2), (
            "a chunk carried both content and usage — buffered-blob shape"
        )

        # Terminal markers: usage last, non-zero, clean finish.
        assert turn2[-1].usage is not None, "no terminal usage chunk on turn 2"
        assert turn2[-1].usage.prompt_tokens > 0
        assert turn2[-1].usage.completion_tokens > 0
        assert _chunk_text(turn2[-1]) is None, "terminal chunk carried text"
        assert turn2[-1].choices[0].finish_reason == "stop"
        # Exactly one usage chunk — no double-emission from the finally block.
        assert len([c for c in turn2 if c.usage is not None]) == 1

    @pytest.mark.asyncio
    async def test_streamed_tool_call_argument_deltas_are_fragmented(self):
        """The call id/name and the JSON arguments must arrive as SEPARATE
        deltas — that split only exists on the native event stream.

        Structural only: asserts the id-bearing delta precedes any
        argument-bearing delta, which is what the item_id → ordinal mapping in
        the adapter guarantees.
        """
        params = {
            "messages": [
                {
                    "role": "user",
                    "content": "Use the get_weather tool for Tokyo.",
                }
            ],
            "tools": _LIVE_WEATHER_TOOL,
        }
        chunks = await self._collect(params)
        if not _merge_tool_calls(chunks):
            pytest.skip("model did not call the tool on this turn")

        id_positions, arg_positions = [], []
        for i, chunk in enumerate(chunks):
            for delta in _chunk_tool_deltas(chunk):
                if delta.id:
                    id_positions.append(i)
                if delta.function.arguments:
                    arg_positions.append(i)

        assert id_positions, "no delta carried the tool-call id"
        assert arg_positions, "no delta carried tool-call arguments"
        assert min(id_positions) < min(arg_positions), (
            "the id/name delta must precede argument fragments "
            f"(id at {min(id_positions)}, args from {min(arg_positions)})"
        )
        # The id/name never rides on the same delta as an argument fragment on
        # the native path (the buffered fallback packed them together).
        assert not set(id_positions) & set(arg_positions), (
            "id and arguments arrived on the same delta — buffered-blob shape"
        )


@pytest.mark.integration
@pytest.mark.skipif(
    not _LIVE_GATE_ENABLED,
    reason=(
        f"live integration not enabled; set {_LIVE_GATE_ENV}=1 to opt in "
        "(mocked unit tests above are primary coverage)"
    ),
)
@pytest.mark.skipif(
    not _OPENAI_API_KEY_PRESENT,
    reason="OPENAI_API_KEY not set; live OpenAI probe cannot run",
)
class TestLiveResponsesVisionIntegration:
    """#1336 acceptance 2 — vision + tools on the Responses (reasoning) path.

    Before #1336 an image part raised a deliberate ``ValueError`` here. The
    mocked tests prove the emitted part matches
    ``openai.types.responses.ResponseInputImageParam``; only a live call proves
    the SERVER accepts it (the SDK does not runtime-validate TypedDicts, so a
    wrong shape passes client-side and surfaces as an HTTP 400).
    """

    _PROMPT = "What single colour fills this image? Answer with just the colour name."

    def _params(self, *, with_image: bool):
        content = [{"type": "text", "text": self._PROMPT}]
        if with_image:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _solid_red_png_data_uri(),
                        "detail": "high",
                    },
                }
            )
        return {
            "messages": [{"role": "user", "content": content}],
            # Tools present so the request routes to Responses — vision WITHOUT
            # tools would stay on chat.completions and prove nothing here.
            "tools": _LIVE_WEATHER_TOOL,
        }

    @pytest.mark.asyncio
    async def test_vision_with_tools_reasoning_request(self):
        request_params = self._params(with_image=True)
        assert openai_native._openai_wants_responses_api(
            _LIVE_REASONING_MODEL, request_params
        ), (
            f"{_LIVE_REASONING_MODEL} does not route to the Responses API; "
            f"set {_LIVE_REASONING_MODEL_ENV} to a gpt-5 non-chat / o-series id"
        )

        # A ValueError here means the image translation regressed; a
        # BadRequestError means the input_image shape is wrong. Both must fail
        # the test rather than skip.
        response = await openai_native.complete(
            request_params, model=_LIVE_REASONING_MODEL
        )
        assert response.usage is not None
        assert response.usage.prompt_tokens > 0

        # THE structural proof that the image was ingested, not merely accepted:
        # the identical prompt without the image costs materially fewer input
        # tokens (OpenAI bills image tiles as input tokens). This does NOT
        # depend on the model's prose, so it cannot rot with model behaviour —
        # unlike asserting a colour word, which is exactly the kind of
        # exact-text assertion this repo's live tests avoid. Verified live:
        # gpt-5.6-terra reads pure #FF0000 as "Orange", so the colour word is
        # informational only (below), never load-bearing.
        baseline = await openai_native.complete(
            self._params(with_image=False), model=_LIVE_REASONING_MODEL
        )
        assert baseline.usage is not None
        delta = response.usage.prompt_tokens - baseline.usage.prompt_tokens
        assert delta > 50, (
            "image contributed no meaningful input tokens "
            f"(with-image={response.usage.prompt_tokens}, "
            f"text-only={baseline.usage.prompt_tokens}, delta={delta}) — "
            "the input_image part was accepted but not ingested"
        )

        content = response.choices[0].message.content
        if not content:
            pytest.skip(
                "model returned no text for the vision turn (called a tool "
                "instead?); colour naming not exercised"
            )
        if "red" not in content.lower():
            # Model behaviour, not a mesh defect — the token delta above already
            # proved the image reached it. Observed live on gpt-5.6-terra.
            pytest.skip(
                "model did not name the image red (colour perception on "
                f"re-encoded input varies); content={content[:200]!r}"
            )

    @pytest.mark.asyncio
    async def test_vision_image_part_no_longer_raises_value_error(self):
        """Direct regression guard for the #1334 deferral this issue removed.

        Kept separate from the semantic check above so a server-side outage or
        an unhelpful answer can never mask the fact that the translation itself
        still runs.
        """
        request_params = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image briefly."},
                        {
                            "type": "image_url",
                            "image_url": {"url": _solid_red_png_data_uri()},
                        },
                    ],
                }
            ],
            "tools": _LIVE_WEATHER_TOOL,
        }
        # The builder is where the old ValueError fired — exercise it directly,
        # no network needed for this half.
        kwargs = openai_native._build_responses_kwargs(
            request_params, model=_LIVE_REASONING_MODEL
        )
        parts = kwargs["input"][0]["content"]
        assert [p["type"] for p in parts] == ["input_text", "input_image"]
        assert parts[1]["image_url"].startswith("data:image/png;base64,")
        assert parts[1]["detail"] in ("low", "high", "auto")

        # And the server accepts it.
        response = await openai_native.complete(
            request_params, model=_LIVE_REASONING_MODEL
        )
        assert response.usage is not None
