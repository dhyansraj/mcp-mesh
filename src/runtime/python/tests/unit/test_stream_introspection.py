"""Unit tests for stream return-type detection.

Covers ``detect_stream_type`` (P1 of issue #645):
- Positive: AsyncIterator[str], AsyncGenerator[str, None], mesh.Stream[str],
  Awaitable[AsyncIterator[str]], Coroutine wrappers, async generator funcs.
- Negative: plain str / dict / int returns, no annotation.
- Reject: Stream[T] for T != str (raises ValueError).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator as AbcAsyncGenerator
from collections.abc import AsyncIterable as AbcAsyncIterable
from collections.abc import AsyncIterator as AbcAsyncIterator
from collections.abc import Awaitable as AbcAwaitable
from collections.abc import Coroutine as AbcCoroutine
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Coroutine,
)

import pytest
from pydantic import BaseModel

import mesh
from _mcp_mesh.engine.stream_introspection import detect_stream_type


class _Chunk(BaseModel):
    """Module-level Pydantic model so get_type_hints can resolve it."""

    text: str


# ---------------------------------------------------------------------------
# Positive cases — should detect "text"
# ---------------------------------------------------------------------------


class TestDetectsTextStream:
    def test_async_iterator_str_typing(self):
        async def chat(prompt: str) -> AsyncIterator[str]:
            yield "x"

        assert detect_stream_type(chat) == "text"

    def test_async_iterator_str_abc(self):
        async def chat(prompt: str) -> AbcAsyncIterator[str]:
            yield "x"

        assert detect_stream_type(chat) == "text"

    def test_async_iterable_str(self):
        async def chat(prompt: str) -> AsyncIterable[str]:
            yield "x"

        assert detect_stream_type(chat) == "text"

    def test_async_generator_str_none(self):
        async def chat(prompt: str) -> AsyncGenerator[str, None]:
            yield "x"

        assert detect_stream_type(chat) == "text"

    def test_async_generator_abc(self):
        async def chat(prompt: str) -> AbcAsyncGenerator[str, None]:
            yield "x"

        assert detect_stream_type(chat) == "text"

    def test_mesh_stream_str(self):
        async def chat(prompt: str) -> mesh.Stream[str]:
            yield "x"

        assert detect_stream_type(chat) == "text"

    def test_awaitable_async_iterator_str(self):
        # An async function returning an async iterator. This is the shape a
        # type checker sees on `async def f() -> Stream[str]: yield ...` once
        # the typing layer wraps the user's annotation.
        async def chat(prompt: str) -> Awaitable[AsyncIterator[str]]:
            ...

        assert detect_stream_type(chat) == "text"

    def test_coroutine_wrapping_async_iterator_str(self):
        async def chat(prompt: str) -> Coroutine[Any, Any, AsyncIterator[str]]:
            ...

        assert detect_stream_type(chat) == "text"

    def test_coroutine_abc_wrapping_async_iterator(self):
        async def chat(prompt: str) -> AbcCoroutine[Any, Any, AsyncIterator[str]]:
            ...

        assert detect_stream_type(chat) == "text"

    def test_awaitable_abc_wrapping_async_iterator(self):
        async def chat(prompt: str) -> AbcAwaitable[AsyncIterator[str]]:
            ...

        assert detect_stream_type(chat) == "text"

    def test_sync_function_returning_async_iterator(self):
        def chat(prompt: str) -> AsyncIterator[str]:
            ...

        assert detect_stream_type(chat) == "text"


# ---------------------------------------------------------------------------
# Negative cases — should return None
# ---------------------------------------------------------------------------


class TestNonStreamingReturnsNone:
    def test_plain_str(self):
        async def chat(prompt: str) -> str:
            return "x"

        assert detect_stream_type(chat) is None

    def test_plain_dict(self):
        async def chat(prompt: str) -> dict:
            return {}

        assert detect_stream_type(chat) is None

    def test_no_annotation(self):
        async def chat(prompt: str):
            return "x"

        assert detect_stream_type(chat) is None

    def test_none_function(self):
        assert detect_stream_type(None) is None

    def test_awaitable_str_only(self):
        async def chat(prompt: str) -> Awaitable[str]:
            ...

        assert detect_stream_type(chat) is None

    def test_coroutine_returning_str(self):
        async def chat(prompt: str) -> Coroutine[Any, Any, str]:
            ...

        assert detect_stream_type(chat) is None


# ---------------------------------------------------------------------------
# Reject cases — Stream[T] for T != str must raise
# ---------------------------------------------------------------------------


class TestStreamNonStrRejected:
    def test_async_iterator_int(self):
        async def chat(prompt: str) -> AsyncIterator[int]:
            yield 1

        with pytest.raises(ValueError, match="Stream\\[T\\].*only for T = str"):
            detect_stream_type(chat)

    def test_async_iterator_bytes(self):
        async def chat(prompt: str) -> AsyncIterator[bytes]:
            yield b"x"

        with pytest.raises(ValueError, match="Got Stream\\[bytes\\]"):
            detect_stream_type(chat)

    def test_async_iterator_pydantic_model(self):
        async def chat(prompt: str) -> AsyncIterator[_Chunk]:
            yield _Chunk(text="x")

        with pytest.raises(ValueError, match="Got Stream\\[_Chunk\\]"):
            detect_stream_type(chat)

    def test_mesh_stream_int(self):
        async def chat(prompt: str) -> mesh.Stream[int]:
            yield 1

        with pytest.raises(ValueError, match="Stream\\[T\\].*only for T = str"):
            detect_stream_type(chat)

    def test_async_generator_dict_none(self):
        async def chat(prompt: str) -> AsyncGenerator[dict, None]:
            yield {}

        with pytest.raises(ValueError, match="Stream\\[T\\].*only for T = str"):
            detect_stream_type(chat)


# ---------------------------------------------------------------------------
# Robustness — no annotation, untyped iterators, broken signature
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_async_iterator_unparameterized(self):
        # `AsyncIterator` with no [T] — fall back to None rather than raise.
        async def chat(prompt: str) -> AsyncIterator:
            yield "x"

        assert detect_stream_type(chat) is None

    def test_lambda_no_signature_safe(self):
        # Builtin / C-level callables can fail inspect.signature; the helper
        # should return None instead of bubbling an exception.
        assert detect_stream_type(len) is None

    def test_callable_object_with_str_return(self):
        class Callable:
            def __call__(self, prompt: str) -> str:
                return prompt

        assert detect_stream_type(Callable()) is None
