"""Unit tests for ``mesh.A2ABearer`` construction-time validation.

Brings the Python A2ABearer to parity with Java (PR #919) and
TypeScript (PR #927):

  * mutual exclusion between ``token`` and ``token_env`` enforced at
    construction;
  * blank/whitespace values rejected at construction;
  * happy paths (``token`` only / ``token_env`` only) accepted.

Without this, ``A2ABearer(token="t", token_env="X")`` silently
preferred ``token`` at header-build time and the error only surfaced
if no token resolved — masking misconfiguration. Java + TS already
fail fast at construction; Python now matches.
"""

from __future__ import annotations

import os

import pytest

from mesh._a2a_consumer import A2ABearer


# ---------------------------------------------------------------------------
# Mutual exclusion + blank-rejection at construction
# ---------------------------------------------------------------------------


def test_a2a_bearer_rejects_both_token_and_env_at_construction():
    """Supplying both ``token`` and ``token_env`` is a misconfiguration —
    raise immediately so the user fixes the decorator instead of
    silently preferring one over the other at header-build time."""
    with pytest.raises(RuntimeError, match="mutually exclusive"):
        A2ABearer(token="literal-token", token_env="UPSTREAM_TOKEN")


def test_a2a_bearer_rejects_neither_token_nor_env_at_construction():
    """Empty config is a clear misconfiguration — surface it at
    decoration time with a message that points at the fix."""
    with pytest.raises(RuntimeError, match="must specify either token or token_env"):
        A2ABearer()


def test_a2a_bearer_rejects_blank_token_at_construction():
    """Whitespace-only ``token`` is rejected — matches Java's
    ``A2ABearer.of`` ``trim().isEmpty()`` validation (PR #919)."""
    with pytest.raises(RuntimeError, match="non-blank"):
        A2ABearer(token="   ")


def test_a2a_bearer_rejects_blank_env_var_name_at_construction():
    """Whitespace-only ``token_env`` is rejected — env-var lookups on a
    blank name silently return ``None`` and the error would only
    surface at the first call. Reject up-front instead."""
    with pytest.raises(RuntimeError, match="non-blank"):
        A2ABearer(token_env="\t")


# ---------------------------------------------------------------------------
# Happy paths — sanity checks that the validation does not over-reject
# ---------------------------------------------------------------------------


def test_a2a_bearer_accepts_token_only():
    """Literal-only construction works and ``header()`` returns the
    expected ``Authorization: Bearer <token>`` shape."""
    bearer = A2ABearer(token="abc123")
    assert bearer.header() == {"Authorization": "Bearer abc123"}


def test_a2a_bearer_accepts_env_only(monkeypatch):
    """Env-var-only construction works — ``header()`` resolves the
    env-var at call time so a rotated value is picked up without
    re-decorating."""
    monkeypatch.setenv("UPSTREAM_TOKEN_FOR_TEST", "v-from-env")
    bearer = A2ABearer(token_env="UPSTREAM_TOKEN_FOR_TEST")
    assert bearer.header() == {"Authorization": "Bearer v-from-env"}
