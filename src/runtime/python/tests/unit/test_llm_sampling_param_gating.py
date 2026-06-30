"""Unit tests for OpenAI sampling-param gating on the LiteLLM path.

OpenAI o-series reasoning models (o1/o3/o4) and the gpt-5 family (except
gpt-5-chat) reject non-default ``temperature``/``top_p`` with HTTP 400. The
provider's LiteLLM dispatch must strip those params from ``completion_args``
before they reach ``litellm.completion``/``acompletion``.

Covers the shared ``_sanitize_sampling_params`` helper and its application in
``_build_iteration_completion_args`` (the agentic-loop build site shared by the
buffered and streaming loops). Mirrors the Java ``OpenAiHandler`` gating.
"""

from __future__ import annotations

import logging

import pytest

from mesh.helpers import (
    _build_iteration_completion_args,
    _sanitize_sampling_params,
)


# ---------------------------------------------------------------------------
# _sanitize_sampling_params
# ---------------------------------------------------------------------------


class TestSanitizeSamplingParams:
    def test_restricted_model_pops_temperature_and_top_p(self):
        args = {"model": "o3-mini", "temperature": 0.7, "top_p": 0.9}
        _sanitize_sampling_params(args, "o3-mini")
        assert "temperature" not in args
        assert "top_p" not in args

    def test_restricted_prefixed_model_pops_params(self):
        args = {"temperature": 0.5, "top_p": 0.8}
        _sanitize_sampling_params(args, "openai/gpt-5-mini")
        assert "temperature" not in args
        assert "top_p" not in args

    def test_unrestricted_model_keeps_params(self):
        args = {"temperature": 0.7, "top_p": 0.9}
        _sanitize_sampling_params(args, "gpt-4o")
        assert args["temperature"] == 0.7
        assert args["top_p"] == 0.9

    def test_gemini_model_is_noop(self):
        args = {"temperature": 0.7}
        _sanitize_sampling_params(args, "gemini/gemini-2.5-flash")
        assert args["temperature"] == 0.7

    def test_only_present_params_touched(self):
        # No temperature supplied → nothing to strip, no crash.
        args = {"model": "o3-mini"}
        _sanitize_sampling_params(args, "o3-mini")
        assert "temperature" not in args

    def test_restricted_model_warns(self, caplog):
        args = {"temperature": 0.7, "top_p": 0.9}
        with caplog.at_level(logging.WARNING):
            _sanitize_sampling_params(args, "o3-mini")
        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("temperature" in m for m in warnings)
        assert any("top_p" in m for m in warnings)


# ---------------------------------------------------------------------------
# _build_iteration_completion_args integration
# ---------------------------------------------------------------------------


class TestBuildIterationCompletionArgsGating:
    def _build(self, model, model_params):
        return _build_iteration_completion_args(
            effective_model=model,
            current_messages=[{"role": "user", "content": "Hi."}],
            tools=[],
            litellm_kwargs={},
            model_params=model_params,
        )

    def test_restricted_model_omits_sampling_params(self):
        args = self._build(
            "o3-mini",
            {"temperature": 0.7, "top_p": 0.9, "max_completion_tokens": 256},
        )
        assert "temperature" not in args
        assert "top_p" not in args
        # max_completion_tokens (and everything else) is preserved.
        assert args["max_completion_tokens"] == 256

    def test_restricted_gpt5_omits_sampling_params(self):
        args = self._build("openai/gpt-5", {"temperature": 0.7, "top_p": 0.9})
        assert "temperature" not in args
        assert "top_p" not in args

    def test_unrestricted_model_keeps_sampling_params(self):
        args = self._build("gpt-4o", {"temperature": 0.7, "top_p": 0.9})
        assert args["temperature"] == 0.7
        assert args["top_p"] == 0.9
