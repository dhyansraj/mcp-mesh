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

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "openai", reason="native OpenAI adapter requires the openai SDK"
)

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
            if r.levelname == "WARNING"
            and "n_greater_than_1" in r.getMessage()
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
            if r.levelname == "WARNING"
            and "n_greater_than_1" in r.getMessage()
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
            if r.levelname == "WARNING"
            and "n_greater_than_1" in r.getMessage()
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
            "content). content={!r}".format(
                (content or "")[:200]
            )
        )
