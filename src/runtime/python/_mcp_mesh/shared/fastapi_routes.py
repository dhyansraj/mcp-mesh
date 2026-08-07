"""Version-independent traversal of the routes a FastAPI app actually serves.

Historically ``app.router.routes`` was a flat list: ``include_router()``
copied every ``APIRoute`` off the mounted ``APIRouter`` into it, so walking
that one list saw everything the app served. FastAPI 0.137.0 changed the
representation — ``include_router()`` now appends a *single* entry that keeps
a live reference to the user's ``APIRouter`` and derives the served
("effective") routes from it lazily. The mounted ``APIRoute`` objects are no
longer present in ``app.router.routes`` at all.

Every mesh code path that walked ``app.router.routes`` directly therefore
stopped seeing ``@mesh.route`` handlers registered on an ``APIRouter``
(issue #1396): discovery found nothing, so no DI wrapper was registered for
them, no dependency ever resolved, and the handlers served as plain FastAPI
endpoints. ``examples/simple/simple_fastapi_router.py`` is exactly that
pattern.

This module is the single place that knows how to walk an app's routes, so
the next representation change has one site to fix rather than five.

Accessor choice
---------------
An ``include_router()`` entry is recognised by **duck-typing on
``original_router``** — the attribute that links the entry back to the
``APIRouter`` the user built — never by its class name (which is private and
would be exactly the kind of fragile coupling #1397 removed).

``original_router.routes`` is the authoritative, *mutable* list that owns the
route objects, which is what route integration needs in order to swap a
handler. Effective paths come from the entry's ``effective_route_contexts()``
when it exposes one, because a router included into another router keeps its
own unprefixed path (``/inner/deep``) while the app serves it under the
combined prefix (``/api/v1/inner/deep``); FastAPI computes that composition
itself and mesh should not re-derive it.

Both names are non-underscore members of the entry, are read through
``getattr`` with a working fallback, and neither is imported — a FastAPI
release that drops one degrades to the other rather than raising.

Starlette ``Mount`` / ``Host`` entries are deliberately NOT traversed even
though they expose ``.routes``: a mount is a separate ASGI application whose
routes are not this app's ``@mesh.route`` surface, and mesh itself mounts the
FastMCP app as a catch-all at ``""``. Requiring ``original_router`` keeps
them out.

On FastAPI < 0.137.0 nothing exposes ``original_router``, so the walk collapses
to precisely the old flat iteration — no version branching anywhere.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteRef:
    """One route an app will serve, plus where it lives.

    Attributes:
        route: The route object itself (``APIRoute``, or a plain Starlette
            ``Route`` for the docs/openapi endpoints).
        path: The path the app serves it under — the effective path, with
            every ``include_router(prefix=...)`` already applied.
        methods: HTTP methods, as a list.
        endpoint: The handler callable FastAPI will dispatch to.
        container: The mutable list that holds ``route``, or ``None`` when it
            could not be located. Assigning ``container[index]`` swaps the
            route; callers must follow that with
            :func:`invalidate_route_caches`.
        index: ``route``'s position within ``container``.
        included: True when the route came from an ``include_router()`` mount
            rather than from the app's own top-level list.
    """

    route: Any
    path: str
    methods: list[str]
    endpoint: Any
    container: list | None
    index: int | None
    included: bool


def _included_routes(entry: Any) -> list | None:
    """Return the mutable route list an ``include_router()`` entry owns.

    ``None`` for anything that is not such an entry — plain routes, and
    ``Mount``/``Host`` (which expose ``.routes`` but are separate ASGI apps).
    """
    router = getattr(entry, "original_router", None)
    if router is None:
        return None
    routes = getattr(router, "routes", None)
    return routes if isinstance(routes, list) else None


def _effective_contexts(entry: Any) -> list | None:
    """FastAPI's own view of what an ``include_router()`` entry serves.

    Each context carries the composed path/methods for one route plus
    ``original_route``, the object in the router's list. Returns ``None``
    when the accessor is absent or unusable, so the caller can fall back to
    walking the raw lists.
    """
    accessor = getattr(entry, "effective_route_contexts", None)
    if not callable(accessor):
        return None
    try:
        return list(accessor())
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("effective_route_contexts() unusable on %r: %s", entry, e)
        return None


def _is_route(entry: Any) -> bool:
    return hasattr(entry, "endpoint") and hasattr(entry, "path")


def _methods_of(obj: Any) -> list[str]:
    methods = getattr(obj, "methods", None)
    return list(methods) if methods else []


def _index_owners(routes: list, owners: dict, seen: set) -> None:
    """Map ``id(route) -> (owning list, index)`` over a router subtree."""
    if id(routes) in seen:
        return
    seen.add(id(routes))
    for index, entry in enumerate(routes):
        nested = _included_routes(entry)
        if nested is not None:
            _index_owners(nested, owners, seen)
        elif _is_route(entry):
            owners.setdefault(id(entry), (routes, index))


def _iter_included(entry: Any, nested: list, seen: set) -> Iterator[RouteRef]:
    owners: dict = {}
    _index_owners(nested, owners, set())

    contexts = _effective_contexts(entry)
    if contexts is None:
        # No effective-route accessor: walk the raw lists. Paths are then the
        # routes' own (a nested include's outer prefix is not applied), which
        # is the best available answer and still strictly better than not
        # seeing the routes at all.
        yield from _iter_routes(nested, included=True, seen=seen)
        return

    for context in contexts:
        route = getattr(context, "original_route", None)
        if route is None or not _is_route(route):
            # A Mount/Host context — nothing mesh can wrap.
            continue
        endpoint = getattr(context, "endpoint", None) or route.endpoint
        if endpoint is None:
            continue
        container, index = owners.get(id(route), (None, None))
        yield RouteRef(
            route=route,
            path=getattr(context, "path", "") or route.path,
            methods=_methods_of(context) or _methods_of(route),
            endpoint=endpoint,
            container=container,
            index=index,
            included=True,
        )


def _iter_routes(routes: list, included: bool, seen: set) -> Iterator[RouteRef]:
    if id(routes) in seen:
        # Cyclic include (FastAPI guards its own traversals against this too).
        return
    seen.add(id(routes))
    for index, entry in enumerate(routes):
        nested = _included_routes(entry)
        if nested is not None:
            yield from _iter_included(entry, nested, seen)
        elif _is_route(entry):
            yield RouteRef(
                route=entry,
                path=entry.path,
                methods=_methods_of(entry),
                endpoint=entry.endpoint,
                container=routes,
                index=index,
                included=included,
            )


def iter_app_routes(app: Any) -> Iterator[RouteRef]:
    """Yield a :class:`RouteRef` for every route ``app`` will serve.

    Covers routes registered directly on the app and routes reached through
    any depth of ``include_router()``.
    """
    routes = getattr(getattr(app, "router", None), "routes", None)
    if not isinstance(routes, list):
        return
    yield from _iter_routes(routes, included=False, seen=set())


def iter_routers(app: Any) -> Iterator[Any]:
    """Yield ``app.router`` and every ``APIRouter`` included beneath it."""
    router = getattr(app, "router", None)
    if router is None:
        return
    pending = [router]
    seen: set = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for entry in getattr(current, "routes", None) or []:
            nested = getattr(entry, "original_router", None)
            if nested is not None:
                pending.append(nested)


def invalidate_route_caches(app: Any) -> None:
    """Tell FastAPI that an app's route lists changed underneath it.

    ``include_router()`` entries cache the effective routes they derive from
    their router, keyed on a version counter the router bumps whenever a route
    is *added or removed* through its API. Mesh swaps a route by assigning
    into the list, which is invisible to that counter — so without this the
    cached (pre-swap) dispatch state keeps serving whenever the cache was
    already warm.

    The bump hook is private, so it is called only if present. Losing it does
    not degrade silently: route integration verifies afterwards that FastAPI's
    own view picked the rebuilt route up, and fails loudly if it did not
    (#1387's rule).

    No-op on FastAPI < 0.137.0, which has no such cache.
    """
    for router in iter_routers(app):
        mark = getattr(router, "_mark_routes_changed", None)
        if not callable(mark):
            continue
        try:
            mark()
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("Could not mark routes changed on %r: %s", router, e)
