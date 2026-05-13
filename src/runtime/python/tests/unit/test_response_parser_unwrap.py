"""
Unit tests for ResponseParser envelope-unwrap defense.

Covers the defensive unwrap added to `_validate_and_create` to handle
LLM-side envelope hallucinations (e.g. Claude in tool_use mode wrapping
the response in {"parameter": {...}}).

Reference: issue #961 covers the fuller retry-on-validation-failure fix.
"""

from typing import List

import pytest
from pydantic import BaseModel

from _mcp_mesh.engine.response_parser import ResponseParseError, ResponseParser


class LogisticsPlanLike(BaseModel):
    """Small fixture model mirroring the real LogisticsPlan shape."""

    daily_schedule: List[str]
    transit_tips: List[str]
    time_optimization: str


class SingleParameterModel(BaseModel):
    """Model whose single required field is literally named 'parameter'."""

    parameter: str


class TestResponseParserUnwrap:
    def test_unwrap_happens_for_envelope_with_inner_required_keys(self):
        """{"parameter": {<real fields>}} should be unwrapped and validated."""
        envelope = {
            "parameter": {
                "daily_schedule": ["09:00 visit shrine", "12:00 lunch"],
                "transit_tips": ["buy IC card"],
                "time_optimization": "cluster nearby stops",
            }
        }
        parsed = ResponseParser.parse(envelope, LogisticsPlanLike)
        assert isinstance(parsed, LogisticsPlanLike)
        assert parsed.daily_schedule == ["09:00 visit shrine", "12:00 lunch"]
        assert parsed.transit_tips == ["buy IC card"]
        assert parsed.time_optimization == "cluster nearby stops"

    def test_unwrap_skipped_when_sole_key_is_a_legit_model_field(self):
        """If the sole key matches a real field on the model, do NOT unwrap."""
        flat = {"parameter": "this is the real value"}
        parsed = ResponseParser.parse(flat, SingleParameterModel)
        assert isinstance(parsed, SingleParameterModel)
        assert parsed.parameter == "this is the real value"

    def test_unwrap_skipped_when_inner_keys_dont_match_model(self):
        """Envelope whose inner shape is alien should propagate to Pydantic.

        Preserves error fidelity for genuine schema mismatches — we should
        get a ResponseParseError originating from a Pydantic ValidationError,
        not silently unwrap into something equally invalid.
        """
        bogus = {"some_envelope": {"unrelated": "stuff"}}
        with pytest.raises(ResponseParseError):
            ResponseParser.parse(bogus, LogisticsPlanLike)

    def test_noop_on_flat_input(self):
        """Already-flat input passes through unchanged (idempotent unwrap)."""
        flat = {
            "daily_schedule": ["09:00 visit shrine"],
            "transit_tips": ["buy IC card"],
            "time_optimization": "cluster nearby stops",
        }
        parsed = ResponseParser.parse(flat, LogisticsPlanLike)
        assert isinstance(parsed, LogisticsPlanLike)
        assert parsed.daily_schedule == ["09:00 visit shrine"]
        assert parsed.transit_tips == ["buy IC card"]
        assert parsed.time_optimization == "cluster nearby stops"
