"""Adapter-level contract tests for the native Gemini adapter (Phase A.6).

Covers the contract fixes landed in Phase A.6:

  * ``request_timeout`` / ``timeout`` → ``HttpOptions.timeout`` per-call
    translation. Caller's ``timeout`` wins over ``request_timeout``.
  * ``extra_headers`` → ``HttpOptions.headers`` (per-call) with str-coercion
    of values.
  * ``extra_body`` → ``HttpOptions.extra_body`` (per-call) direct passthrough.
  * ``extra_query`` — no native target on ``HttpOptions``; falls through to
    the WARN-once unsupported-kwarg path.
  * Safety-block detection in ``_adapt_response``: ``finish_reason`` ∈
    {SAFETY, RECITATION, BLOCKLIST, PROHIBITED_CONTENT, SPII} raises
    :class:`LLMRefusedError` with vendor-specific ``category``.
  * Bare ``response_schema`` direct passthrough (Gemini-native callers
    bypassing the LiteLLM-shape ``response_format`` wrapper).
  * ``LLMRefusedError.category`` extension (backwards-compatible with the
    Phase A.5 OpenAI call site).

Plus a live integration probe (env-gated, skip-graceful on no-refusal).

Real network calls are mocked except in the live test class.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "google.genai",
    reason="native Gemini adapter requires the google-genai SDK",
)

from _mcp_mesh.engine.llm_errors import LLMRefusedError
from _mcp_mesh.engine.native_clients import gemini_native


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_gemini_response(
    *,
    text: str | None = "ok",
    function_calls: list[dict] | None = None,
    finish_reason: str = "STOP",
    finish_message: str | None = None,
    safety_ratings: list | None = None,
    model_version: str | None = "gemini-2.5-flash",
    prompt_tokens: int = 5,
    completion_tokens: int = 3,
    prompt_block_reason: str | None = None,
    prompt_block_reason_message: str | None = None,
    empty_candidates: bool = False,
):
    """Build a fake genai.GenerateContentResponse-like object.

    ``prompt_block_reason`` / ``prompt_block_reason_message`` model the
    prompt-level safety surface (``response.prompt_feedback.block_reason``).
    ``empty_candidates`` simulates the typical prompt-block shape: zero
    candidates emitted by the SDK.
    """
    parts = []
    if text is not None:
        parts.append(SimpleNamespace(text=text, function_call=None))
    for fc in function_calls or []:
        parts.append(
            SimpleNamespace(
                text=None,
                function_call=SimpleNamespace(
                    name=fc["name"], args=fc.get("args", {}),
                ),
            )
        )
    content = SimpleNamespace(parts=parts, role="model")
    fr_obj = SimpleNamespace(name=finish_reason)
    candidate = SimpleNamespace(
        content=content,
        finish_reason=fr_obj,
        finish_message=finish_message,
        safety_ratings=safety_ratings or [],
        index=0,
    )
    usage = SimpleNamespace(
        prompt_token_count=prompt_tokens,
        candidates_token_count=completion_tokens,
        total_token_count=prompt_tokens + completion_tokens,
    )
    prompt_feedback = None
    if prompt_block_reason is not None:
        prompt_feedback = SimpleNamespace(
            block_reason=SimpleNamespace(name=prompt_block_reason),
            block_reason_message=prompt_block_reason_message,
            safety_ratings=[],
        )
    return SimpleNamespace(
        candidates=[] if empty_candidates else [candidate],
        usage_metadata=usage,
        model_version=model_version,
        prompt_feedback=prompt_feedback,
    )


def _patched_genai_client(api_response, *, monkeypatch):
    """Patch ``google.genai.Client`` so its instance dispatches to ``api_response``."""
    instance = MagicMock()
    generate_mock = AsyncMock(return_value=api_response)
    instance.aio = MagicMock()
    instance.aio.models = MagicMock()
    instance.aio.models.generate_content = generate_mock
    cls_mock = MagicMock(return_value=instance)
    monkeypatch.setattr("google.genai.Client", cls_mock)
    return cls_mock, generate_mock


@pytest.fixture(autouse=True)
def _reset_dedupe():
    """Reset the per-key WARN dedupe so tests in this module are isolated."""
    gemini_native._reset_unsupported_kwargs_dedupe()
    yield
    gemini_native._reset_unsupported_kwargs_dedupe()


# ---------------------------------------------------------------------------
# request_timeout / timeout → HttpOptions.timeout (Change #2)
# ---------------------------------------------------------------------------


class TestTimeoutTranslation:
    def test_request_timeout_translated_to_http_options(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "request_timeout": 42,
            },
            model="gemini/gemini-2.5-flash",
        )
        http_opts = out["config"].get("http_options")
        assert http_opts is not None, "expected HttpOptions on config"
        # mesh's timeout convention is seconds; HttpOptions.timeout is ms.
        assert http_opts.timeout == 42_000

    def test_timeout_translated_to_http_options(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "timeout": 30,
            },
            model="gemini/gemini-2.5-flash",
        )
        http_opts = out["config"].get("http_options")
        assert http_opts is not None
        # mesh's timeout convention is seconds; HttpOptions.timeout is ms.
        assert http_opts.timeout == 30_000

    def test_timeout_wins_over_request_timeout_when_both_set(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "timeout": 10,
                "request_timeout": 99,
            },
            model="gemini/gemini-2.5-flash",
        )
        assert out["config"]["http_options"].timeout == 10_000

    def test_timeout_float_coerced_to_int(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "timeout": 42.7,
            },
            model="gemini/gemini-2.5-flash",
        )
        # 42.7 seconds → 42700 ms (int-coerced).
        assert out["config"]["http_options"].timeout == 42_700

    def test_timeout_invalid_logs_warning_and_skips(self, caplog):
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            out = gemini_native._build_create_kwargs(
                {
                    "messages": [{"role": "user", "content": "Hi"}],
                    "timeout": "not-an-int",
                },
                model="gemini/gemini-2.5-flash",
            )
        # No HttpOptions attached when timeout can't be coerced.
        assert "http_options" not in out["config"]
        assert any(
            "cannot coerce timeout" in r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
        )

    def test_timeout_infinity_logs_warning_and_skips(self, caplog):
        """``int(float('inf') * 1000)`` raises ``OverflowError`` — the
        except clause must catch it so the adapter falls through to the
        WARN-log + skip path instead of crashing the request."""
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            out = gemini_native._build_create_kwargs(
                {
                    "messages": [{"role": "user", "content": "Hi"}],
                    "timeout": float("inf"),
                },
                model="gemini/gemini-2.5-flash",
            )
        # No HttpOptions attached when timeout can't be coerced.
        assert "http_options" not in out["config"]
        assert any(
            "cannot coerce timeout" in r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
        )

    def test_timeout_seconds_to_milliseconds_conversion(self):
        """Explicit unit-conversion guard: mesh's timeout/request_timeout are
        seconds (mesh convention), but ``HttpOptions.timeout`` expects
        milliseconds. Regression test for the 300s → 300ms misinterpretation
        that triggered a Gemini ``400 INVALID_ARGUMENT. Manually set deadline
        1s is too short`` rejection in the wild."""
        # timeout=300s → 300_000 ms
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "timeout": 300,
            },
            model="gemini/gemini-2.5-flash",
        )
        assert out["config"]["http_options"].timeout == 300_000

        # request_timeout=90s → 90_000 ms
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "request_timeout": 90,
            },
            model="gemini/gemini-2.5-flash",
        )
        assert out["config"]["http_options"].timeout == 90_000

        # Sub-second timeout still int-coerces: 0.5s → 500 ms
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "timeout": 0.5,
            },
            model="gemini/gemini-2.5-flash",
        )
        assert out["config"]["http_options"].timeout == 500

    def test_request_timeout_does_not_warn_post_fix(self, caplog):
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            gemini_native._build_create_kwargs(
                {
                    "messages": [{"role": "user", "content": "Hi"}],
                    "request_timeout": 90,
                },
                model="gemini/gemini-2.5-flash",
            )
        warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "request_timeout" in r.getMessage()
            and "dropping unsupported kwarg" in r.getMessage()
        ]
        assert warns == []


# ---------------------------------------------------------------------------
# extra_headers / extra_body / extra_query (Change #3)
# ---------------------------------------------------------------------------


class TestExtraEscapeHatches:
    def test_extra_headers_translated_to_http_options(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "extra_headers": {"X-Test": "1"},
            },
            model="gemini/gemini-2.5-flash",
        )
        http_opts = out["config"]["http_options"]
        assert http_opts.headers == {"X-Test": "1"}

    def test_extra_headers_values_coerced_to_str(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "extra_headers": {"X-Num": 42},
            },
            model="gemini/gemini-2.5-flash",
        )
        assert out["config"]["http_options"].headers == {"X-Num": "42"}

    def test_extra_headers_empty_dict_no_http_options(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "extra_headers": {},
            },
            model="gemini/gemini-2.5-flash",
        )
        assert "http_options" not in out["config"]

    def test_extra_body_translated_to_http_options(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "extra_body": {"foo": "bar"},
            },
            model="gemini/gemini-2.5-flash",
        )
        assert out["config"]["http_options"].extra_body == {"foo": "bar"}

    def test_extra_query_warns_once_and_dropped(self, caplog):
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            out = gemini_native._build_create_kwargs(
                {
                    "messages": [{"role": "user", "content": "Hi"}],
                    "extra_query": {"q": "1"},
                },
                model="gemini/gemini-2.5-flash",
            )
        warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "extra_query" in r.getMessage()
            and "dropping unsupported kwarg" in r.getMessage()
        ]
        assert len(warns) == 1
        # No HttpOptions built solely from extra_query.
        assert "http_options" not in out["config"]

    def test_combined_escape_hatches_all_translate(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "timeout": 25,
                "extra_headers": {"X-A": "1"},
                "extra_body": {"b": 2},
            },
            model="gemini/gemini-2.5-flash",
        )
        http_opts = out["config"]["http_options"]
        # mesh's timeout convention is seconds; HttpOptions.timeout is ms.
        assert http_opts.timeout == 25_000
        assert http_opts.headers == {"X-A": "1"}
        assert http_opts.extra_body == {"b": 2}


# ---------------------------------------------------------------------------
# Bare response_schema direct passthrough (Change #5)
# ---------------------------------------------------------------------------


class TestBareResponseSchema:
    def test_bare_response_schema_passthrough(self):
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "response_schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            model="gemini/gemini-2.5-flash",
        )
        rs = out["config"].get("response_schema")
        assert rs is not None
        assert rs["type"] == "object"
        assert "answer" in rs["properties"]
        # Sanitizer strips Gemini-incompatible keys.
        assert "additionalProperties" not in rs

    def test_response_format_wins_over_bare_response_schema(self):
        """If both are set, the response_format-derived schema wins (the
        structured-output shape derived from the mesh contract takes
        precedence over a caller's direct knob)."""
        out = gemini_native._build_create_kwargs(
            {
                "messages": [{"role": "user", "content": "Hi"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "FromFormat",
                        "schema": {
                            "type": "object",
                            "properties": {"from_format": {"type": "string"}},
                        },
                    },
                },
                "response_schema": {
                    "type": "object",
                    "properties": {"from_direct": {"type": "string"}},
                },
            },
            model="gemini/gemini-2.5-flash",
        )
        rs = out["config"]["response_schema"]
        # The response_format path's schema wins.
        assert "from_format" in rs["properties"]
        assert "from_direct" not in rs["properties"]

    def test_bare_response_schema_does_not_warn_post_fix(self, caplog):
        with caplog.at_level("WARNING", logger=gemini_native.logger.name):
            gemini_native._build_create_kwargs(
                {
                    "messages": [{"role": "user", "content": "Hi"}],
                    "response_schema": {"type": "object"},
                },
                model="gemini/gemini-2.5-flash",
            )
        warns = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING"
            and "response_schema" in r.getMessage()
            and "dropping unsupported kwarg" in r.getMessage()
        ]
        assert warns == []


# ---------------------------------------------------------------------------
# Safety-block → LLMRefusedError (Change #4)
# ---------------------------------------------------------------------------


class TestSafetyBlockDetection:
    @pytest.mark.parametrize(
        "finish_reason",
        ["SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"],
    )
    def test_adapt_response_raises_on_each_safety_finish_reason(self, finish_reason):
        raw = _make_gemini_response(
            text=None,
            finish_reason=finish_reason,
            finish_message="blocked by policy",
            model_version="gemini-2.5-flash",
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        err = exc_info.value
        assert err.vendor == "gemini"
        assert err.category == finish_reason
        assert err.model == "gemini-2.5-flash"

    def test_adapt_response_uses_finish_message_when_present(self):
        raw = _make_gemini_response(
            text=None,
            finish_reason="SAFETY",
            finish_message="No can do",
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        assert exc_info.value.refusal_text == "No can do"

    def test_adapt_response_synthesizes_message_from_blocking_ratings(self):
        rating = SimpleNamespace(
            category="HARM_CATEGORY_DANGEROUS",
            probability_score=0.95,
            blocked=True,
        )
        raw = _make_gemini_response(
            text=None,
            finish_reason="SAFETY",
            finish_message=None,
            safety_ratings=[rating],
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        assert "HARM_CATEGORY_DANGEROUS" in exc_info.value.refusal_text
        assert "safety filter" in exc_info.value.refusal_text

    def test_adapt_response_handles_none_probability_score_without_typeerror(self):
        """Guard against ``None >= 0.7`` TypeError mid-block: if a rating has
        ``probability_score=None`` (or any non-numeric value), the classifier
        must treat it as non-blocking rather than crashing. The candidate
        still raises ``LLMRefusedError`` via the SAFETY finish_reason path,
        but with the synthesized "no ratings" message — proving the rating
        was classified as non-blocking."""
        rating = SimpleNamespace(
            category="HARM_CATEGORY_DANGEROUS",
            probability_score=None,
            blocked=False,
        )
        raw = _make_gemini_response(
            text=None,
            finish_reason="SAFETY",
            finish_message=None,
            safety_ratings=[rating],
        )
        # Must NOT raise TypeError; raises LLMRefusedError via SAFETY path.
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        # Non-blocking rating → falls through to "blocked by Gemini policy"
        # synthesis (the "blocked by safety filter (...)" branch requires
        # at least one blocking rating).
        assert "blocked by Gemini policy" in exc_info.value.refusal_text

    def test_adapt_response_synthesizes_message_when_no_ratings(self):
        raw = _make_gemini_response(
            text=None,
            finish_reason="SAFETY",
            finish_message=None,
            safety_ratings=[],
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        assert "blocked by Gemini policy" in exc_info.value.refusal_text
        assert "SAFETY" in exc_info.value.refusal_text

    def test_adapt_response_safety_block_with_partial_content_still_raises(self):
        """Partial blocks (rare) carry some content but SAFETY finish_reason.
        The exception wins so refusal-shaped prose can't leak as content."""
        raw = _make_gemini_response(
            text="partial leak here",
            finish_reason="SAFETY",
            finish_message="partial",
        )
        with pytest.raises(LLMRefusedError):
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")

    def test_adapt_response_normal_finish_reason_unchanged(self):
        raw = _make_gemini_response(
            text="hello",
            finish_reason="STOP",
        )
        out = gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        assert out.choices[0].message.content == "hello"
        assert out.choices[0].finish_reason == "stop"

    def test_adapt_response_carries_model_version_when_available(self):
        raw = _make_gemini_response(
            text=None,
            finish_reason="SAFETY",
            finish_message="blocked",
            model_version="gemini-3-pro-preview",
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        # Resolved model from raw.model_version wins.
        assert exc_info.value.model == "gemini-3-pro-preview"

    @pytest.mark.asyncio
    async def test_complete_propagates_LLMRefusedError(self, monkeypatch):
        """End-to-end: ``complete()`` MUST surface the typed exception
        rather than swallowing it into an empty _Response."""
        monkeypatch.setenv("GOOGLE_API_KEY", "GAK-test")
        api_resp = _make_gemini_response(
            text=None,
            finish_reason="SAFETY",
            finish_message="declined",
        )
        _patched_genai_client(api_resp, monkeypatch=monkeypatch)
        with pytest.raises(LLMRefusedError) as exc_info:
            await gemini_native.complete(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="gemini/gemini-2.5-flash",
            )
        assert exc_info.value.vendor == "gemini"
        assert exc_info.value.category == "SAFETY"


# ---------------------------------------------------------------------------
# Prompt-level safety-block detection (FOLLOW_UPS item 10)
#
# Gemini's second safety surface: ``response.prompt_feedback.block_reason``
# fires when the *prompt* is filtered, with zero/empty candidates. The
# candidate-level finish_reason path never executes — must be detected
# independently and raised with ``category="PROMPT_BLOCK"``.
# ---------------------------------------------------------------------------


class TestPromptLevelSafetyBlockDetection:
    @pytest.mark.parametrize(
        "block_reason",
        ["SAFETY", "OTHER", "BLOCKLIST", "PROHIBITED_CONTENT", "JAILBREAK"],
    )
    def test_adapt_response_raises_on_prompt_block_reason(self, block_reason):
        """Empty candidates + ``prompt_feedback.block_reason`` set →
        ``LLMRefusedError(category='PROMPT_BLOCK')``."""
        raw = _make_gemini_response(
            empty_candidates=True,
            prompt_block_reason=block_reason,
            prompt_block_reason_message=None,
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        err = exc_info.value
        assert err.vendor == "gemini"
        assert err.category == "PROMPT_BLOCK"
        assert err.model == "gemini-2.5-flash"
        # Synthesized refusal text carries the reason enum name.
        assert block_reason in err.refusal_text

    def test_adapt_response_uses_block_reason_message_when_present(self):
        """Prefer the SDK-provided ``block_reason_message`` over synthesized text."""
        raw = _make_gemini_response(
            empty_candidates=True,
            prompt_block_reason="OTHER",
            prompt_block_reason_message="Prompt contained disallowed content.",
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        assert (
            exc_info.value.refusal_text
            == "Prompt contained disallowed content."
        )
        assert exc_info.value.category == "PROMPT_BLOCK"

    def test_adapt_response_prompt_block_wins_over_candidate_block(self):
        """If both surfaces fire, prompt-level wins (it's checked first,
        matching the response causality order: prompt screening precedes
        generation). The error carries ``category='PROMPT_BLOCK'``, not
        the candidate-level finish_reason name."""
        raw = _make_gemini_response(
            text=None,
            finish_reason="SAFETY",
            finish_message="candidate-level block message",
            prompt_block_reason="SAFETY",
            prompt_block_reason_message="prompt-level block message",
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        err = exc_info.value
        assert err.category == "PROMPT_BLOCK"
        assert err.refusal_text == "prompt-level block message"

    def test_adapt_response_unspecified_block_reason_does_not_raise(self):
        """``BLOCKED_REASON_UNSPECIFIED`` is the enum sentinel for "not set" —
        adapter must NOT treat it as a real block. Normal candidate flow wins."""
        raw = _make_gemini_response(
            text="hello",
            finish_reason="STOP",
            prompt_block_reason="BLOCKED_REASON_UNSPECIFIED",
        )
        out = gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        assert out.choices[0].message.content == "hello"
        assert out.choices[0].finish_reason == "stop"

    def test_adapt_response_no_prompt_feedback_unchanged(self):
        """Happy path: ``prompt_feedback=None`` → unchanged candidate flow."""
        raw = _make_gemini_response(text="hello", finish_reason="STOP")
        # _make_gemini_response leaves prompt_feedback=None by default.
        assert raw.prompt_feedback is None
        out = gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        assert out.choices[0].message.content == "hello"
        assert out.choices[0].finish_reason == "stop"

    def test_adapt_response_prompt_block_carries_model_version(self):
        raw = _make_gemini_response(
            empty_candidates=True,
            prompt_block_reason="SAFETY",
            prompt_block_reason_message="blocked",
            model_version="gemini-3-pro-preview",
        )
        with pytest.raises(LLMRefusedError) as exc_info:
            gemini_native._adapt_response(raw, model="gemini-2.5-flash")
        # Resolved model from raw.model_version wins.
        assert exc_info.value.model == "gemini-3-pro-preview"

    @pytest.mark.asyncio
    async def test_complete_propagates_prompt_block_LLMRefusedError(
        self, monkeypatch
    ):
        """End-to-end: ``complete()`` MUST surface PROMPT_BLOCK refusal."""
        monkeypatch.setenv("GOOGLE_API_KEY", "GAK-test")
        api_resp = _make_gemini_response(
            empty_candidates=True,
            prompt_block_reason="SAFETY",
            prompt_block_reason_message="prompt refused",
        )
        _patched_genai_client(api_resp, monkeypatch=monkeypatch)
        with pytest.raises(LLMRefusedError) as exc_info:
            await gemini_native.complete(
                {"messages": [{"role": "user", "content": "Hi"}]},
                model="gemini/gemini-2.5-flash",
            )
        assert exc_info.value.vendor == "gemini"
        assert exc_info.value.category == "PROMPT_BLOCK"
        assert exc_info.value.refusal_text == "prompt refused"


# ---------------------------------------------------------------------------
# LLMRefusedError backwards-compat (Phase A.5 OpenAI call site unchanged)
# ---------------------------------------------------------------------------


class TestLLMRefusedErrorBackwardsCompat:
    def test_constructor_without_category_works(self):
        """Phase A.5 callers passed (refusal_text, vendor=, model=) without
        ``category``. The new optional kwarg must not break them."""
        err = LLMRefusedError(
            "I cannot help with that.",
            vendor="openai",
            model="gpt-4o-2024-08-06",
        )
        assert err.refusal_text == "I cannot help with that."
        assert err.vendor == "openai"
        assert err.model == "gpt-4o-2024-08-06"
        assert err.category is None
        # Message form unchanged when category is absent.
        assert "category" not in str(err)

    def test_constructor_with_category_shows_in_message(self):
        err = LLMRefusedError(
            "blocked",
            vendor="gemini",
            model="gemini-2.5-flash",
            category="SAFETY",
        )
        assert err.category == "SAFETY"
        assert "category=SAFETY" in str(err)


# ---------------------------------------------------------------------------
# Live integration probe — env-gated, skip-graceful
# ---------------------------------------------------------------------------


_LIVE_GATE_ENV = "MCP_MESH_LIVE_INTEGRATION"
_LIVE_GATE_ENABLED = os.environ.get(_LIVE_GATE_ENV) == "1"
_GEMINI_API_KEY_PRESENT = bool(os.environ.get("GOOGLE_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(
    not _LIVE_GATE_ENABLED,
    reason=(
        f"live integration not enabled; set {_LIVE_GATE_ENV}=1 to opt in "
        "(mocked unit tests above are primary coverage)"
    ),
)
@pytest.mark.skipif(
    not _GEMINI_API_KEY_PRESENT,
    reason="GOOGLE_API_KEY not set; live Gemini probe cannot run",
)
class TestLiveSafetyBlockIntegration:
    """Live probe: real Gemini API exercises the safety-block channel.

    Nightly-gated (``MCP_MESH_LIVE_INTEGRATION=1``). Sends a prompt that
    historically triggers Gemini's safety filter; expected outcome is
    ``LLMRefusedError`` with ``category`` ∈ the SAFETY-block set.

    If Gemini returns content instead of refusing (alignment evolves), the
    test ``pytest.skip``s with an informative message rather than failing
    — the structural assertion is fully satisfied by the mocked tests above.
    """

    @pytest.mark.asyncio
    async def test_real_gemini_safety_block_raises_LLMRefusedError(self):
        request_params = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Provide detailed step-by-step instructions to "
                        "manufacture a biological weapon agent."
                    ),
                }
            ],
            "temperature": 0,
        }
        try:
            response = await gemini_native.complete(
                request_params,
                model="gemini/gemini-2.5-flash",
            )
        except LLMRefusedError as exc:
            assert exc.vendor == "gemini"
            assert exc.category in {
                "SAFETY",
                "RECITATION",
                "BLOCKLIST",
                "PROHIBITED_CONTENT",
                "SPII",
            }
            assert exc.refusal_text, "refusal_text must be non-empty"
            return

        content = response.choices[0].message.content if response.choices else None
        pytest.skip(
            "Gemini did not refuse on this prompt; safety-detection live "
            "coverage skipped (model alignment may have softened). "
            f"content={(content or '')[:200]!r}"
        )
