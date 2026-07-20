"""Unit tests for OpenAI sampling-param gating (temperature/top_p).

OpenAI o-series reasoning models (o1/o3/o4) and the gpt-5 family (except
gpt-5-chat) reject non-default ``temperature``/``top_p`` with HTTP 400. These
tests cover:

  * the shared :func:`restricts_sampling_params` classifier truth table, and
  * the native-SDK gating in ``openai_native._build_create_kwargs``.

Mirrors the Java ``OpenAiHandler.restrictsSamplingParams`` behavior.
"""

from __future__ import annotations

import pytest

from _mcp_mesh.engine.native_clients._native_client_helpers import (
    is_openai_reasoning_model,
    restricts_anthropic_sampling_params,
    restricts_sampling_params,
    translate_max_tokens_for_restricted,
)


# ---------------------------------------------------------------------------
# Classifier truth table
# ---------------------------------------------------------------------------


class TestRestrictsSamplingParams:
    @pytest.mark.parametrize(
        "model",
        [
            "o1",
            "o3",
            "o4",
            "o3-mini",
            "o4-mini",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            # #1332 — version-agnostic: gpt-5 point releases stay restricted.
            "gpt-5.6",
            "gpt-5-6",
            "openai/gpt-5.6",
            "openai/gpt-5",
            "openai/o3-mini",
            "GPT-5-MINI",  # case-insensitive
        ],
    )
    def test_restricted_models(self, model):
        assert restricts_sampling_params(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o",
            "gpt-4.1",
            "gpt-4o-mini",
            "gpt-5-chat-latest",
            "gpt-5-chat",
            # #1332 — version-agnostic chat exclusion covers versioned chat ids.
            "gpt-5.6-chat",
            "gpt-5.6-chat-latest",
            "openai/gpt-4o",
            "gemini/gemini-2.5-flash",
            "anthropic/claude-sonnet-4-5",
            "o3xyz",  # not an o-series family member (no trailing dash)
            None,
            "",
        ],
    )
    def test_unrestricted_models(self, model):
        assert restricts_sampling_params(model) is False


# ---------------------------------------------------------------------------
# Native-SDK path: _build_create_kwargs gating
# ---------------------------------------------------------------------------


class TestNativeBuildCreateKwargsGating:
    def _build(self, model: str, **params):
        from _mcp_mesh.engine.native_clients import openai_native

        request_params = {
            "messages": [{"role": "user", "content": "Hi."}],
            **params,
        }
        return openai_native._build_create_kwargs(request_params, model=model)

    def test_restricted_model_omits_temperature_and_top_p(self):
        kwargs = self._build(
            "openai/o3-mini",
            temperature=0.7,
            top_p=0.9,
            max_completion_tokens=256,
        )
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs
        # Everything else is still forwarded.
        assert kwargs["max_completion_tokens"] == 256
        assert kwargs["model"] == "o3-mini"

    def test_restricted_gpt5_omits_sampling_params(self):
        kwargs = self._build("openai/gpt-5-mini", temperature=0.5, top_p=0.8)
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs

    def test_restricted_gpt5_point_release_omits_sampling_params(self):
        # #1332 — a gpt-5 point release is restricted like the base model.
        kwargs = self._build("openai/gpt-5.6", temperature=0.5, top_p=0.8)
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs

    def test_unrestricted_model_keeps_temperature(self):
        kwargs = self._build("openai/gpt-4o", temperature=0.7, top_p=0.9)
        assert kwargs["temperature"] == 0.7
        assert kwargs["top_p"] == 0.9

    def test_gpt5_chat_keeps_temperature(self):
        kwargs = self._build("openai/gpt-5-chat-latest", temperature=0.7)
        assert kwargs["temperature"] == 0.7

    def test_restricted_model_warns_on_omission(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            self._build("openai/o3-mini", temperature=0.7, top_p=0.9)
        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("temperature" in m for m in warnings)
        assert any("top_p" in m for m in warnings)


# ---------------------------------------------------------------------------
# Native-SDK path: max_tokens → max_completion_tokens translation
# ---------------------------------------------------------------------------


class TestNativeMaxTokensTranslation:
    def _build(self, model: str, **params):
        from _mcp_mesh.engine.native_clients import openai_native

        request_params = {
            "messages": [{"role": "user", "content": "Hi."}],
            **params,
        }
        return openai_native._build_create_kwargs(request_params, model=model)

    def test_restricted_model_moves_max_tokens(self):
        kwargs = self._build("openai/o3-mini", max_tokens=256)
        assert "max_tokens" not in kwargs
        assert kwargs["max_completion_tokens"] == 256

    def test_restricted_gpt5_moves_max_tokens(self):
        kwargs = self._build("openai/gpt-5-mini", max_tokens=256)
        assert "max_tokens" not in kwargs
        assert kwargs["max_completion_tokens"] == 256

    def test_restricted_gpt5_point_release_moves_max_tokens(self):
        # #1332 — a gpt-5 point release translates max_tokens like the base model.
        kwargs = self._build("openai/gpt-5.6", max_tokens=256)
        assert "max_tokens" not in kwargs
        assert kwargs["max_completion_tokens"] == 256

    def test_restricted_model_both_supplied_keeps_max_completion_tokens(self):
        kwargs = self._build(
            "openai/o3-mini", max_tokens=256, max_completion_tokens=512
        )
        assert "max_tokens" not in kwargs
        assert kwargs["max_completion_tokens"] == 512

    def test_unrestricted_model_keeps_max_tokens(self):
        kwargs = self._build("openai/gpt-4o", max_tokens=256)
        assert kwargs["max_tokens"] == 256
        assert "max_completion_tokens" not in kwargs

    def test_gpt5_chat_keeps_max_tokens(self):
        kwargs = self._build("openai/gpt-5-chat-latest", max_tokens=256)
        assert kwargs["max_tokens"] == 256
        assert "max_completion_tokens" not in kwargs

    def test_restricted_model_warns_on_translation(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            self._build("openai/o3-mini", max_tokens=256)
        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("max_tokens" in m and "max_completion_tokens" in m for m in warnings)


# ---------------------------------------------------------------------------
# Shared helper: translate_max_tokens_for_restricted (direct, in place)
# ---------------------------------------------------------------------------


class TestTranslateMaxTokensForRestricted:
    def _log(self):
        import logging

        return logging.getLogger("test_translate_max_tokens")

    def test_restricted_moves_max_tokens(self):
        params = {"max_tokens": 256}
        translate_max_tokens_for_restricted(params, "openai/o3-mini", self._log())
        assert params == {"max_completion_tokens": 256}

    def test_restricted_both_supplied_keeps_max_completion_tokens(self):
        params = {"max_tokens": 256, "max_completion_tokens": 512}
        translate_max_tokens_for_restricted(params, "openai/o3-mini", self._log())
        assert params == {"max_completion_tokens": 512}

    def test_unrestricted_is_noop(self):
        params = {"max_tokens": 256}
        translate_max_tokens_for_restricted(params, "openai/gpt-4o", self._log())
        assert params == {"max_tokens": 256}

    def test_gemini_is_noop(self):
        params = {"max_tokens": 256}
        translate_max_tokens_for_restricted(
            params, "gemini/gemini-2.5-flash", self._log()
        )
        assert params == {"max_tokens": 256}

    def test_absent_max_tokens_is_noop(self):
        params = {"max_completion_tokens": 512}
        translate_max_tokens_for_restricted(params, "openai/o3-mini", self._log())
        assert params == {"max_completion_tokens": 512}


# ---------------------------------------------------------------------------
# Anthropic classifier truth table (#1344)
# ---------------------------------------------------------------------------
# Anthropic REMOVED temperature/top_p/top_k on the Opus 4.7+ / Sonnet 5 /
# Fable 5 families — presence is HTTP 400. Narrower than the native
# structured-output list: opus-4-6 / sonnet-4-6 / haiku-4-5 still accept them.


class TestRestrictsAnthropicSamplingParams:
    @pytest.mark.parametrize(
        "model",
        [
            # bare ids
            "claude-sonnet-5",
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-fable-5",
            # anthropic/ prefix
            "anthropic/claude-sonnet-5",
            "anthropic/claude-opus-4-7",
            "anthropic/claude-opus-4-8",
            "anthropic/claude-fable-5",
            # bedrock / databricks prefixes keep the ``anthropic.`` segment
            "bedrock/anthropic.claude-opus-4-8-20260101-v1:0",
            "databricks/anthropic.claude-sonnet-5",
            # dot-separated version form
            "anthropic/claude-opus-4.7",
            "anthropic/claude-opus-4.8",
            # date-pinned
            "claude-sonnet-5-20260201",
            # case-insensitive
            "ANTHROPIC/CLAUDE-OPUS-4-8",
        ],
    )
    def test_restricted_models(self, model):
        assert restricts_anthropic_sampling_params(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            # Structured-output-capable but sampling params still accepted.
            "anthropic/claude-opus-4-6",
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-haiku-4-5",
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-opus-4-5",
            "anthropic/claude-opus-4-1",
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
            "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
            # Boundary guard: a hypothetical future minor version must NOT
            # match the shorter pattern.
            "anthropic/claude-opus-4-70",
            "anthropic/claude-opus-4-80",
            "anthropic/claude-sonnet-50",
            "anthropic/claude-fable-50",
            # Leading-digit guard.
            "anthropic/claude-opus-14-7",
            # Other vendors.
            "openai/gpt-4o",
            "gemini/gemini-2.5-flash",
            None,
            "",
        ],
    )
    def test_unrestricted_models(self, model):
        assert restricts_anthropic_sampling_params(model) is False


class TestGeneralizedRestrictsSamplingParams:
    """The vendor-agnostic gate is the union of the two vendor predicates."""

    @pytest.mark.parametrize(
        "model",
        ["o3-mini", "openai/gpt-5", "anthropic/claude-opus-4-8", "claude-sonnet-5"],
    )
    def test_union_matches(self, model):
        assert restricts_sampling_params(model) is True

    @pytest.mark.parametrize(
        "model", ["gpt-4o", "anthropic/claude-sonnet-4-5", "gemini/gemini-2.5-flash"]
    )
    def test_union_does_not_match(self, model):
        assert restricts_sampling_params(model) is False


class TestIsOpenAiReasoningModelStaysOpenAiOnly:
    """``is_openai_reasoning_model`` drives Responses-API routing (#1334) —
    generalizing the sampling gate must NOT make Claude ids reasoning models.
    """

    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-opus-4-8",
            "anthropic/claude-opus-4-7",
            "anthropic/claude-sonnet-5",
            "anthropic/claude-fable-5",
        ],
    )
    def test_claude_is_not_an_openai_reasoning_model(self, model):
        assert is_openai_reasoning_model(model) is False
        # …even though the vendor-agnostic gate does match it.
        assert restricts_sampling_params(model) is True

    @pytest.mark.parametrize("model", ["o3-mini", "openai/gpt-5-mini"])
    def test_openai_reasoning_unchanged(self, model):
        assert is_openai_reasoning_model(model) is True


class TestAnthropicMaxTokensUntouched:
    """Anthropic REQUIRES max_tokens — the OpenAI-only
    max_tokens → max_completion_tokens translation must not follow the
    generalized gate onto Claude ids.
    """

    def test_restricted_claude_keeps_max_tokens(self):
        import logging

        params = {"max_tokens": 256}
        translate_max_tokens_for_restricted(
            params, "anthropic/claude-opus-4-8", logging.getLogger("t")
        )
        assert params == {"max_tokens": 256}
