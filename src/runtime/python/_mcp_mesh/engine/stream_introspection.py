"""Stream return-type detection for @mesh.tool / @mesh.llm.

A tool author opts in to token-by-token streaming by annotating the return
type as ``mesh.Stream[str]`` (alias for ``AsyncIterator[str]``) — see
``mesh/types.py``. The framework inspects the annotation at decoration time
via :func:`detect_stream_type` and stamps ``metadata["stream_type"] = "text"``
on the tool. The runtime later wraps the user's async generator so each chunk
is forwarded over the open MCP SSE connection as a ``notifications/progress``
message.

This module is intentionally minimal — it only inspects the return annotation
and reports back ``"text"`` (only supported variant in v1) or ``None``. It
raises ``ValueError`` when the return is an async iterator over a non-``str``
type so the decorator can refuse the tool with a clear, actionable error.

Pattern shared with :mod:`_mcp_mesh.utils.fastmcp_schema_extractor` (lines
425-453): peel up to four layers of ``Awaitable[T]`` / ``Coroutine[..., T]``
to reach the inner ``AsyncIterator[T]``. Without the peel, ``async def f()``
declared as ``-> Stream[str]`` would surface as
``Coroutine[Any, Any, AsyncIterator[str]]`` after type-eval.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import (
    AsyncGenerator as AbcAsyncGenerator,
)
from collections.abc import (
    AsyncIterable as AbcAsyncIterable,
)
from collections.abc import (
    AsyncIterator as AbcAsyncIterator,
)
from collections.abc import (
    Awaitable as AbcAwaitable,
)
from collections.abc import (
    Coroutine as AbcCoroutine,
)
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Coroutine,
    get_args,
    get_origin,
    get_type_hints,
)

logger = logging.getLogger(__name__)

_STREAM_ORIGINS = {
    AsyncIterator,
    AbcAsyncIterator,
    AsyncIterable,
    AbcAsyncIterable,
    AsyncGenerator,
    AbcAsyncGenerator,
}


def _peel_async_wrappers(annotation: Any) -> tuple[Any, bool]:
    """Strip Awaitable[T] / Coroutine[..., T] layers around T.

    Returns ``(inner, peeled_async_iter)`` where ``peeled_async_iter`` is
    True iff the outermost peeled layer was an async-iterator origin
    (AsyncIterator / AsyncIterable / AsyncGenerator). The flag lets the
    caller distinguish ``Stream[str]`` (async iter) from ``Awaitable[str]``
    (just a coroutine returning a string — *not* a stream).
    """
    current = annotation
    saw_async_iter = False

    for _ in range(4):
        origin = get_origin(current)

        if origin in _STREAM_ORIGINS:
            args = get_args(current)
            if not args:
                return current, True
            saw_async_iter = True
            current = args[0]
            continue

        if origin in (Awaitable, AbcAwaitable):
            args = get_args(current)
            if not args:
                return current, saw_async_iter
            current = args[0]
            continue

        if origin in (Coroutine, AbcCoroutine):
            args = get_args(current)
            if len(args) < 3:
                return current, saw_async_iter
            current = args[2]
            continue

        break

    return current, saw_async_iter


def detect_stream_type(fn: Any) -> str | None:
    """Detect whether a tool function declares a streaming return type.

    Returns:
        ``"text"`` when the function returns ``AsyncIterator[str]`` /
        ``AsyncGenerator[str, None]`` / ``mesh.Stream[str]`` (with optional
        ``Awaitable`` / ``Coroutine`` wrapping).
        ``None`` when no async-iterator return is declared.

    Raises:
        ValueError: when the return is an async-iterator over a type other
            than ``str``. v1 supports text streams only; the wrapper that
            forwards chunks via ``ctx.report_progress(message=chunk)``
            requires string payloads.
    """
    if fn is None:
        return None

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None

    annotation = sig.return_annotation
    if annotation is inspect.Signature.empty or annotation is None:
        return None

    # Resolve string annotations (PEP 563 / `from __future__ import annotations`)
    # to real types so get_origin / get_args work. get_type_hints walks the
    # function's module globals + closure to resolve forward refs; it can fail
    # if the type is unresolvable, in which case we fall through to using the
    # raw annotation (which may already be a typing alias if the user did not
    # opt into future annotations).
    if isinstance(annotation, str):
        try:
            hints = get_type_hints(fn)
            annotation = hints.get("return", annotation)
        except Exception as e:
            logger.debug(
                "detect_stream_type: get_type_hints failed for %s: %s",
                getattr(fn, "__qualname__", repr(fn)),
                e,
            )
            return None

    inner, is_async_iter = _peel_async_wrappers(annotation)
    if not is_async_iter:
        return None

    if inner is str:
        return "text"

    # Untyped or unparameterized async iterator (e.g. `AsyncIterator` with no
    # [T]). Treat as non-streaming rather than raising — the type doesn't
    # express a contract we can fulfil. The wrapper falls back to the
    # default non-streaming code path.
    if (
        inner is inspect.Signature.empty
        or inner is Any
        or inner in _STREAM_ORIGINS
    ):
        logger.debug(
            "detect_stream_type: untyped/unparameterized async iterator on %s; "
            "treating as non-streaming",
            getattr(fn, "__qualname__", repr(fn)),
        )
        return None

    inner_repr = getattr(inner, "__name__", None) or repr(inner)
    raise ValueError(
        f"Stream[T] is currently supported only for T = str. "
        f"Got Stream[{inner_repr}]. v1 limitation; will be revisited."
    )
