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
    restricts_sampling_params,
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
