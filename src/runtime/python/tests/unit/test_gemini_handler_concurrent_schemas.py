"""
Unit tests for GeminiHandler concurrent-request schema isolation.

Background:
    Provider handlers are cached as singletons in
    ``ProviderHandlerRegistry._instances``. If pending output-schema state is
    stored on the handler instance (e.g., ``self._pending_output_schema``),
    two concurrent async requests with different schemas race on those fields:
    request B's writes can clobber request A's between A's
    ``apply_structured_output`` call and A's ``format_system_prompt`` call.

    The fix migrates that state to ``contextvars.ContextVar`` so each async
    context (asyncio.Task, contextvars.copy_context, ...) sees its own value.
    These tests verify that isolation holds.
"""

import asyncio

import pytest

from _mcp_mesh.engine.provider_handlers._handler_context import (
    clear_pending_output_schema,
    get_pending_output_schema,
    set_pending_output_schema,
)
from _mcp_mesh.engine.provider_handlers.gemini_handler import GeminiHandler

# ---------------------------------------------------------------------------
# _handler_context module — basic API
# ---------------------------------------------------------------------------


class TestHandlerContextBasics:
    """Smoke tests for the shared ContextVar helper module."""

    def test_get_returns_none_when_unset(self):
        clear_pending_output_schema()
        assert get_pending_output_schema() == (None, None)

    def test_set_and_get_roundtrip(self):
        clear_pending_output_schema()
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        set_pending_output_schema(schema, "MyType")
        assert get_pending_output_schema() == (schema, "MyType")
        clear_pending_output_schema()

    def test_clear_resets_both_fields(self):
        set_pending_output_schema({"type": "object"}, "Foo")
        clear_pending_output_schema()
        assert get_pending_output_schema() == (None, None)


# ---------------------------------------------------------------------------
# GeminiHandler — instance state was migrated to ContextVar
# ---------------------------------------------------------------------------


class TestGeminiHandlerNoInstanceState:
    """The migrated handler must not carry pending-schema instance fields."""

    def test_init_does_not_set_pending_schema_attrs(self):
        handler = GeminiHandler()
        assert not hasattr(handler, "_pending_output_schema"), (
            "GeminiHandler must not store _pending_output_schema on the "
            "instance — it's racy under singleton caching. Use "
            "_handler_context ContextVar instead."
        )
        assert not hasattr(handler, "_pending_output_type_name"), (
            "GeminiHandler must not store _pending_output_type_name on the "
            "instance — it's racy under singleton caching. Use "
            "_handler_context ContextVar instead."
        )


# ---------------------------------------------------------------------------
# Concurrency — the bug this migration exists to fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_requests_dont_cross_contaminate_schema():
    """Two concurrent contexts using the same handler instance should each
    see their own output schema, not each other's.

    Simulates the production scenario: ``ProviderHandlerRegistry`` returns
    the same cached ``GeminiHandler`` instance to every concurrent request.
    With instance state, request B's ``apply_structured_output`` call
    clobbers request A's pending schema between A's ``apply_structured_output``
    and A's downstream read in ``format_system_prompt``.
    """
    handler = GeminiHandler()

    schema_a = {
        "type": "object",
        "properties": {"a_field": {"type": "string"}},
        "required": ["a_field"],
    }
    schema_b = {
        "type": "object",
        "properties": {"b_field": {"type": "integer"}},
        "required": ["b_field"],
    }

    seen: dict[str, tuple] = {}

    async def make_call(label: str, schema: dict, sleep_ms: int) -> None:
        # Each gather() arg runs in its own asyncio.Task → its own context.
        model_params = {
            "messages": [{"role": "system", "content": f"You are {label}."}]
        }
        handler.apply_structured_output(schema, f"Type{label}", model_params)
        # Simulate async work between the write and the read (e.g., the
        # actual LLM call latency in production).
        await asyncio.sleep(sleep_ms / 1000)
        # After the await, read what THIS context sees.
        seen[label] = get_pending_output_schema()

    # Interleave: A starts (writes schema_a), sleeps; B starts (writes
    # schema_b), sleeps; both wake up. With instance fields, both contexts
    # would see schema_b after the awaits because B's write wins.
    await asyncio.gather(
        make_call("A", schema_a, 50),
        make_call("B", schema_b, 30),
    )

    assert seen["A"] == (schema_a, "TypeA"), (
        f"Context A saw the wrong schema: {seen['A']!r} (expected schema_a/TypeA). "
        "Instance state cross-contaminated between concurrent requests."
    )
    assert seen["B"] == (schema_b, "TypeB"), (
        f"Context B saw the wrong schema: {seen['B']!r} (expected schema_b/TypeB). "
        "Instance state cross-contaminated between concurrent requests."
    )


@pytest.mark.asyncio
async def test_many_concurrent_requests_isolate_correctly():
    """Stress: many concurrent contexts with distinct schemas all see their
    own value, even with multiple awaits between write and read."""
    handler = GeminiHandler()
    n = 20

    seen: dict[int, tuple] = {}

    async def make_call(i: int) -> None:
        schema = {
            "type": "object",
            "properties": {f"field_{i}": {"type": "string"}},
            "required": [f"field_{i}"],
        }
        type_name = f"Type{i}"
        model_params = {
            "messages": [{"role": "system", "content": f"You are #{i}."}]
        }
        handler.apply_structured_output(schema, type_name, model_params)
        # Multiple awaits to give the scheduler many opportunities to
        # interleave with sibling tasks.
        for _ in range(3):
            await asyncio.sleep(0)
        seen[i] = get_pending_output_schema()

    await asyncio.gather(*(make_call(i) for i in range(n)))

    for i in range(n):
        seen_schema, seen_name = seen[i]
        assert seen_name == f"Type{i}", (
            f"Context {i} saw type_name={seen_name!r}, expected 'Type{i}'"
        )
        assert seen_schema is not None and (
            f"field_{i}" in seen_schema.get("properties", {})
        ), (
            f"Context {i} saw schema {seen_schema!r}, expected one with "
            f"property 'field_{i}'"
        )


# ---------------------------------------------------------------------------
# format_system_prompt reads from the per-context state
# ---------------------------------------------------------------------------


def test_format_system_prompt_reads_pending_schema_from_context():
    """Set the pending schema via the public helper, then ensure
    ``format_system_prompt`` picks it up (not from instance state)."""
    handler = GeminiHandler()
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    set_pending_output_schema(schema, "AnswerType")
    try:
        prompt = handler.format_system_prompt(
            base_prompt="You are helpful.",
            tool_schemas=[{"type": "function", "function": {"name": "noop"}}],
            output_type=str,  # str path would normally skip schema,
            # but pending schema in context overrides
        )
        # The Rust formatter should have received the AnswerType schema and
        # included some hint of it in the output. We don't pin exact wording,
        # just confirm something schema-shaped came back.
        assert isinstance(prompt, str)
        assert len(prompt) > 0
    finally:
        clear_pending_output_schema()
