"""Unit tests for ``_build_assistant_tool_call_dict`` (mesh.helpers).

Background:
    The Gemini native adapter lifts a Part-level ``thought_signature`` (bytes)
    off each ``functionCall`` response Part onto the synthesized ``_ToolCall``
    as ``_thought_signature``. The Gemini API REQUIRES that signature to be
    echoed back on the next-turn ``functionCall`` of a multi-turn tool-calling
    conversation; otherwise it rejects with HTTP 400 ("Function call is
    missing a thought_signature").

    Mesh's two paths that serialize an assistant tool_call message into the
    conversation dict are:

      1. ``_provider_agentic_loop`` (line ~849) — the agentic-loop branch.
      2. ``process_chat`` legacy single-call branch (line ~1867) — fires when
         a caller hits ``process_chat`` directly with no agentic-loop context
         but still gets tool_calls back.

    Both must serialize the ``_gemini_thought_signature`` sidecar; both must
    route through ``_build_assistant_tool_call_dict`` (the canonical helper)
    so the contract stays consistent and silent regressions are caught here.

    These tests pin the helper's contract directly so future refactors of
    either branch don't drop the signature again.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

from mesh.helpers import _build_assistant_tool_call_dict


def _make_tool_call(
    *,
    tc_id: str = "call_0",
    name: str = "get_weather",
    arguments: str = '{"city": "NYC"}',
    thought_signature: bytes | None = None,
) -> SimpleNamespace:
    """Build a minimal ``_ToolCall``-shape object using SimpleNamespace.

    Avoids MagicMock — its auto-generated attributes would falsely satisfy
    the ``isinstance(sig, (bytes, bytearray))`` check inside the helper and
    mask real bugs.
    """
    fn = SimpleNamespace(name=name, arguments=arguments)
    tc = SimpleNamespace(
        id=tc_id,
        type="function",
        function=fn,
        _thought_signature=thought_signature,
    )
    return tc


class TestCanonicalFields:
    """The four canonical fields (``id``, ``type``, ``function.name``,
    ``function.arguments``) round-trip exactly."""

    def test_basic_serialization(self):
        tc = _make_tool_call(
            tc_id="call_42", name="add", arguments='{"a": 1, "b": 2}'
        )
        out = _build_assistant_tool_call_dict(tc)
        assert out == {
            "id": "call_42",
            "type": "function",
            "function": {"name": "add", "arguments": '{"a": 1, "b": 2}'},
        }

    def test_no_signature_no_sidecar_field(self):
        """Steady-state path for non-Gemini vendors: ``_thought_signature``
        is None / absent and the sidecar key must NOT appear in the output.
        """
        tc = _make_tool_call(thought_signature=None)
        out = _build_assistant_tool_call_dict(tc)
        assert "_gemini_thought_signature" not in out


class TestThoughtSignatureSidecar:
    """Gemini-only: the ``_gemini_thought_signature`` sidecar carries a
    base64-encoded snapshot of the source bytes through the conversation
    dict so the next-turn request can decode and replay it."""

    def test_signature_serialized_as_base64(self):
        sig_bytes = b"sig-abcd-1234"
        tc = _make_tool_call(thought_signature=sig_bytes)
        out = _build_assistant_tool_call_dict(tc)
        assert "_gemini_thought_signature" in out
        # Round-trip: b64 string must decode back to the original bytes.
        decoded = base64.b64decode(out["_gemini_thought_signature"])
        assert decoded == sig_bytes

    def test_binary_signature_round_trips(self):
        """Real Gemini signatures are opaque binary blobs (not printable
        ASCII). The base64 encoding must handle arbitrary bytes including
        nulls and high-byte values without truncation."""
        sig_bytes = b"\x00\x01\x02\xff\xfe\xfd-binary-blob"
        tc = _make_tool_call(thought_signature=sig_bytes)
        out = _build_assistant_tool_call_dict(tc)
        decoded = base64.b64decode(out["_gemini_thought_signature"])
        assert decoded == sig_bytes

    def test_empty_bytes_treated_as_absent(self):
        """``b""`` is falsy; the helper's ``... and sig`` guard skips it.
        Mirrors the Gemini adapter's behavior where empty-bytes signatures
        are treated as absent (google.genai may emit them on non-thinking
        models)."""
        tc = _make_tool_call(thought_signature=b"")
        out = _build_assistant_tool_call_dict(tc)
        assert "_gemini_thought_signature" not in out

    def test_non_bytes_signature_ignored(self):
        """The strict ``isinstance(sig, (bytes, bytearray))`` check guards
        against accidentally serializing a stray non-bytes attribute (e.g.
        from a MagicMock test double or a misbehaving adapter). Anything
        non-bytes-like must be silently dropped, NOT crash the b64 call."""
        # Set the attribute to a non-bytes value via SimpleNamespace.
        tc = _make_tool_call()
        tc._thought_signature = "not-actually-bytes"
        out = _build_assistant_tool_call_dict(tc)
        assert "_gemini_thought_signature" not in out

    def test_bytearray_signature_round_trips(self):
        """``bytearray`` is in the isinstance whitelist alongside ``bytes``;
        both must be handled symmetrically (some upstream paths produce one
        vs the other)."""
        sig = bytearray(b"bytearray-sig-content")
        tc = _make_tool_call(thought_signature=sig)
        out = _build_assistant_tool_call_dict(tc)
        decoded = base64.b64decode(out["_gemini_thought_signature"])
        assert decoded == bytes(sig)


class TestLegacyBranchSerialization:
    """Pins down the contract for the ``process_chat`` legacy single-call
    branch (helpers.py ~line 1867). That branch was previously building the
    tool_calls dict inline and silently dropped ``_gemini_thought_signature``;
    now it routes through this helper. This test simulates that branch's
    serialization shape and verifies the signature survives.
    """

    def test_legacy_branch_preserves_thought_signature(self):
        """Simulates the legacy branch's list comprehension pattern:

            message_dict["tool_calls"] = [
                _build_assistant_tool_call_dict(tc) for tc in message.tool_calls
            ]

        With a Gemini ``_ToolCall`` carrying ``_thought_signature``, the
        resulting dict's first tool_call entry must include the
        base64-encoded sidecar — otherwise the next-turn Gemini request
        would fail with HTTP 400.
        """
        sig_bytes = b"legacy-branch-signature"
        message = SimpleNamespace(
            role="assistant",
            content=None,
            tool_calls=[
                _make_tool_call(
                    tc_id="gemini_call_0",
                    name="get_weather",
                    arguments='{"city": "SF"}',
                    thought_signature=sig_bytes,
                )
            ],
        )
        # Mirror the legacy branch's serialization (helpers.py ~1867).
        tool_calls_dicts = [
            _build_assistant_tool_call_dict(tc) for tc in message.tool_calls
        ]
        assert len(tool_calls_dicts) == 1
        tc_dict = tool_calls_dicts[0]
        # Canonical fields preserved.
        assert tc_dict["id"] == "gemini_call_0"
        assert tc_dict["function"]["name"] == "get_weather"
        # Gemini sidecar present + decodes back to original bytes.
        assert "_gemini_thought_signature" in tc_dict
        assert (
            base64.b64decode(tc_dict["_gemini_thought_signature"])
            == sig_bytes
        )

    def test_legacy_branch_non_gemini_no_sidecar(self):
        """Backward-compat: a non-Gemini tool_call (no ``_thought_signature``
        attribute set, or set to None) must produce a clean dict with no
        sidecar key — same shape other vendors expect."""
        message = SimpleNamespace(
            role="assistant",
            content=None,
            tool_calls=[
                _make_tool_call(
                    tc_id="call_xyz",
                    name="tool",
                    arguments="{}",
                    thought_signature=None,
                )
            ],
        )
        tool_calls_dicts = [
            _build_assistant_tool_call_dict(tc) for tc in message.tool_calls
        ]
        assert tool_calls_dicts == [
            {
                "id": "call_xyz",
                "type": "function",
                "function": {"name": "tool", "arguments": "{}"},
            }
        ]
