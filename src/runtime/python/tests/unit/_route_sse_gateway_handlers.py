"""Module-scope @mesh.route handlers for issue #1037 regression tests.

These handlers live in a SEPARATE module (no ``from __future__ import
annotations``) so ``inspect.signature`` returns real type objects, not the
PEP 563 string forms. Production agent code is almost always written this
way, so this faithfully mirrors what a real user gateway module produces.

The companion test file (test_route_sse_wrapping.py) uses
``from __future__ import annotations`` and cannot host these handlers
itself — under PEP 563 ``Request``/``McpMeshTool`` annotations stay as
strings and FastAPI cannot recognize ``Request`` as the Starlette injection.
"""

from fastapi import HTTPException
from starlette.requests import Request

import mesh
from mesh.types import McpMeshTool


async def chat_single_fn(
    request: Request, dep: McpMeshTool = None
) -> mesh.Stream[str]:
    """Single-function user-natural shape under test (issue #1037).

    Combines: async-gen body, ``Stream[str]`` return, ``Request`` parameter,
    ``await request.json()`` inside the body, dep consumed via ``async for``,
    and the missing-dep early-yield branch.
    """
    if dep is None:
        yield "no dep"
        return
    body = await request.json()
    async for chunk in dep.stream(text=body["text"]):
        yield chunk


async def _stream_helper(dep, body):
    async for chunk in dep.stream(text=body["text"]):
        yield chunk


async def chat_two_fn_outer(
    request: Request, dep: McpMeshTool = None
):
    """Canonical two-function shape: validate + parse up-front in a plain
    coroutine, then RETURN an async-iter helper that does the actual
    streaming. The outer coroutine can ``raise HTTPException`` cleanly
    because the response has not been committed yet.
    """
    if dep is None:
        raise HTTPException(status_code=503, detail="dep unavailable")
    body = await request.json()
    return _stream_helper(dep, body)
