"""
RFC #1280 service views — Python runtime.

Two related roles depending on the decorated class (mirrors the Java
``@McpMeshService`` contract; uc37 is the cross-runtime seam):

CONSUMER VIEW (no prefix) — a typed aggregation of ordinary capability
dependencies. Every public method carries ``@mesh.selector(...)`` and is a
stub whose body is never executed; the framework injects a facade whose
methods delegate to each capability's own resolved proxy::

    @mesh.service                       # or @mesh.service(min_available=2)
    class MediaService:
        @mesh.selector("media.caption", required=True, tags=["+fast"])
        async def caption(self, args: dict) -> dict: ...
        @mesh.selector("media.thumbnail")
        async def thumbnail(self, args: dict) -> dict: ...

    @mesh.tool(capability="process", dependencies=["audit_log"])
    async def process(req: dict, audit: mesh.McpMeshTool = None,
                      media: MediaService = None):
        cap = await media.caption({"text": req["text"]})

PRODUCER SUGAR (prefix argument) — each public method of the class becomes an
ordinary mesh tool with capability ``prefix.<method>``, published through the
existing ``@mesh.tool`` machinery::

    @mesh.service("media")              # publishes media.caption, media.thumbnail
    class MediaTools:
        async def caption(self, args: dict) -> dict:
            return {...}

Disambiguation: a prefix present → producer (methods must be real
implementations; any ``@mesh.selector`` inside → boot-fail "mixed roles"); no
prefix → consumer view (every public method must carry ``@mesh.selector``).
``min_available`` is only valid on a consumer view.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Marker attribute stamped on a consumer-view class. Detection (in
# signature_analyzer) keys on this attribute so the engine never imports this
# public module.
SERVICE_VIEW_ATTR = "_mesh_service_view"

# Marker attribute stamped on a method by @mesh.selector.
SELECTOR_ATTR = "_mesh_selector"


class MeshServiceUnavailableError(Exception):
    """Raised when a service view is below its declared ``min_available`` floor.

    When fewer than ``min_available`` of the view's methods currently resolve
    to a provider, EVERY facade call raises this instead of delegating — a
    consumer-local circuit breaker with no wire effect. Carries the view name
    and the current/required availability counts so the failure is actionable.
    Mirrors Java's ``MeshServiceUnavailableException``.
    """

    def __init__(
        self,
        service: str,
        methods_available: int,
        methods_total: int,
        min_available: int,
    ) -> None:
        super().__init__(
            f"Mesh service view unavailable ({service}): "
            f"{methods_available}/{methods_total} method(s) resolved, "
            f"below the declared min_available={min_available} floor"
        )
        self.service = service
        self.methods_available = methods_available
        self.methods_total = methods_total
        self.min_available = min_available


@dataclass(frozen=True)
class ServiceMethodBinding:
    """A single validated view method → capability binding (name-sorted)."""

    method_name: str
    capability: str
    tags: list = field(default_factory=list)
    version: Optional[str] = None
    required: bool = False
    expected_type: Any = None
    match_mode: Optional[str] = None


@dataclass(frozen=True)
class ServiceViewMeta:
    """Metadata for a discovered consumer-view class."""

    name: str
    min_available: int
    bindings: list  # list[ServiceMethodBinding], sorted by method_name


def _validate_capability_segmented(capability: str, context: str) -> None:
    """Reuse the pydantic ``AgentCapability`` name validator (RFC #1280 v3
    dotted rule) so views/producers accept exactly what the registry does —
    no duplicated regex.
    """
    from pydantic import ValidationError

    from _mcp_mesh.shared.support_types import AgentCapability

    try:
        AgentCapability(name=capability)
    except ValidationError as e:
        raise ValueError(f"{context}: invalid capability name '{capability}' — {e}") from None


def selector(
    capability: Optional[str] = None,
    *,
    tags: Optional[list] = None,
    version: Optional[str] = None,
    required: bool = False,
    expected_type: Any = None,
    match_mode: Optional[str] = None,
):
    """Bind a service-view method to a single capability (RFC #1280).

    Same keys as a ``@mesh.tool`` dependency dict. ``expected_type`` /
    ``match_mode`` opt into schema-aware matching exactly like a dict dep.
    """
    if capability is not None and not isinstance(capability, str):
        raise ValueError("@mesh.selector capability must be a string")
    if tags is not None and not isinstance(tags, list):
        raise ValueError("@mesh.selector tags must be a list")
    if version is not None and not isinstance(version, str):
        raise ValueError("@mesh.selector version must be a string")
    if not isinstance(required, bool):
        raise ValueError("@mesh.selector required must be a boolean")
    if match_mode is not None and match_mode not in ("subset", "strict"):
        raise ValueError("@mesh.selector match_mode must be 'subset' or 'strict'")

    def decorator(fn):
        setattr(
            fn,
            SELECTOR_ATTR,
            {
                "capability": capability,
                "tags": list(tags or []),
                "version": version,
                "required": required,
                "expected_type": expected_type,
                "match_mode": match_mode,
            },
        )
        return fn

    return decorator


def binding_to_dependency_dict(b: ServiceMethodBinding) -> dict:
    """Convert a view-method binding into a ``@mesh.tool`` dependency dict.

    Mirrors the dict-dependency handling in ``@mesh.tool`` (expected_type →
    expected_schema_raw, default match_mode "subset") so a view edge is
    indistinguishable from a hand-written dependency once expanded.
    """
    dep: dict = {"capability": b.capability, "tags": list(b.tags or [])}
    if b.version is not None:
        dep["version"] = b.version
    if b.required:
        dep["required"] = True
    if b.expected_type is not None:
        mm = b.match_mode or "subset"
        if isinstance(b.expected_type, dict):
            dep["expected_schema_raw"] = b.expected_type
        else:
            from _mcp_mesh.utils.fastmcp_schema_extractor import FastMCPSchemaExtractor

            schema = FastMCPSchemaExtractor.extract_type_schema(b.expected_type)
            if schema is not None:
                dep["expected_schema_raw"] = schema
        dep["match_mode"] = mm
    elif b.match_mode is not None:
        dep["match_mode"] = b.match_mode
    return dep


def _public_methods(cls) -> list:
    """Public instance methods declared on the class, in name-sorted order.

    Underscore-prefixed methods are skipped; ``object`` methods are excluded.
    """
    import inspect

    names = []
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        if getattr(object, name, None) is not None:
            continue
        names.append(name)
    return sorted(names)


def _build_consumer_view(cls, min_available: int):
    """Validate a consumer-view class and stamp its metadata."""
    if not isinstance(min_available, int) or isinstance(min_available, bool):
        raise ValueError("@mesh.service min_available must be an integer")
    if min_available < 0:
        raise ValueError(
            f"@mesh.service view '{cls.__name__}': min_available must be >= 0 "
            f"(got {min_available})"
        )

    method_names = _public_methods(cls)
    bindings: list = []
    for name in method_names:
        member = getattr(cls, name)
        sel = getattr(member, SELECTOR_ATTR, None)
        if sel is None:
            raise ValueError(
                f"@mesh.service view '{cls.__name__}': public method '{name}' "
                f"has no @mesh.selector — every method of a consumer view must "
                f"bind a capability with @mesh.selector (or make it private "
                f"with a leading underscore)."
            )
        # Facade methods are async (they delegate to async proxies). A sync
        # stub would return an un-awaited coroutine and silently break — fail
        # loudly at decoration instead.
        import asyncio as _asyncio

        if not _asyncio.iscoroutinefunction(member):
            raise ValueError(
                f"@mesh.service view '{cls.__name__}': selector method '{name}' "
                f"must be `async def` — service-view facade methods are async "
                f"(they delegate to async mesh proxies). Mark it `async def`."
            )
        capability = sel.get("capability")
        if not capability or not str(capability).strip():
            raise ValueError(
                f"@mesh.service view '{cls.__name__}': method '{name}' has "
                f"@mesh.selector with a blank capability."
            )
        _validate_capability_segmented(
            capability, f"@mesh.service view '{cls.__name__}' method '{name}'"
        )
        bindings.append(
            ServiceMethodBinding(
                method_name=name,
                capability=capability,
                tags=sel.get("tags", []),
                version=sel.get("version"),
                required=bool(sel.get("required", False)),
                expected_type=sel.get("expected_type"),
                match_mode=sel.get("match_mode"),
            )
        )

    if min_available > len(bindings):
        raise ValueError(
            f"@mesh.service view '{cls.__name__}': min_available={min_available} "
            f"exceeds the number of selector-bound methods ({len(bindings)}) — "
            f"the floor can never be satisfied."
        )

    if not bindings:
        logger.warning(
            f"@mesh.service view '{cls.__name__}' declares no selector methods — "
            f"the injected facade is a no-op view."
        )

    setattr(
        cls,
        SERVICE_VIEW_ATTR,
        ServiceViewMeta(
            name=cls.__name__,
            min_available=min_available,
            bindings=bindings,
        ),
    )

    # Make the view type appear optional/nullable in MCP schemas so FastMCP
    # hides a view-typed tool parameter (mirrors McpMeshTool / MeshJob). The
    # DI wrapper also strips it from __signature__, but the schema marker is
    # the belt-and-suspenders that matches the other injectables.
    _attach_pydantic_schema(cls)
    return cls


def _attach_pydantic_schema(cls) -> None:
    try:
        from pydantic_core import core_schema
    except ImportError:
        # Fallback when pydantic-core is unavailable — mirror the dict form
        # McpMeshTool / MeshJob use so FastMCP still treats the view param as
        # optional/nullable rather than rejecting it.
        def __get_pydantic_core_schema_fallback__(cls_, source_type, handler):  # noqa: N807
            return {
                "type": "default",
                "schema": {"type": "nullable", "schema": {"type": "any"}},
                "default": None,
            }

        cls.__get_pydantic_core_schema__ = classmethod(
            __get_pydantic_core_schema_fallback__
        )
        return

    def __get_pydantic_core_schema__(cls_, source_type, handler):  # noqa: N807
        return core_schema.with_default_schema(
            core_schema.nullable_schema(core_schema.any_schema()),
            default=None,
        )

    cls.__get_pydantic_core_schema__ = classmethod(__get_pydantic_core_schema__)


def _build_producer(cls, prefix: str, min_available: int):
    """Publish each public method of a prefixed class as a mesh tool."""
    if min_available:
        raise ValueError(
            f"@mesh.service producer '{cls.__name__}': min_available is only "
            f"valid on a consumer view (no prefix), not on a producer class."
        )
    if not prefix or not str(prefix).strip():
        raise ValueError(
            f"@mesh.service producer '{cls.__name__}': prefix must not be blank."
        )
    _validate_capability_segmented(prefix, f"@mesh.service producer '{cls.__name__}' prefix")

    method_names = _public_methods(cls)

    # Mixed-roles guard: a producer method must be a real implementation, not
    # a selector stub.
    for name in method_names:
        if getattr(getattr(cls, name), SELECTOR_ATTR, None) is not None:
            raise ValueError(
                f"@mesh.service producer '{cls.__name__}' (prefix '{prefix}'): "
                f"method '{name}' carries @mesh.selector — a prefixed class is a "
                f"producer (methods are implementations), not a consumer view. "
                f"Remove the prefix to make it a view, or remove @mesh.selector."
            )

    from . import decorators

    # Instantiate ONCE at decoration time (bound methods are what get
    # published). Producers must be zero-arg constructible; surface a
    # constructor failure with a message naming @mesh.service and the class
    # rather than a bare traceback from deep in the decorator.
    try:
        instance = cls()
    except Exception as e:
        raise ValueError(
            f"@mesh.service producer '{cls.__name__}' (prefix '{prefix}'): "
            f"failed to instantiate the class — producer classes must be "
            f"zero-arg constructible (the sugar instantiates once at "
            f"decoration time to publish bound methods). Constructor raised: "
            f"{e!r}"
        ) from e

    for name in method_names:
        member = getattr(cls, name)
        own_meta = getattr(member, "_mesh_tool_metadata", None)
        bound = getattr(instance, name)
        if own_meta is not None:
            # A method carrying its own @mesh.tool WINS: it keeps its declared
            # capability (NOT the prefix sugar). But that @mesh.tool ran on the
            # UNBOUND method during class-body evaluation, so `self` leaked into
            # the FastMCP schema and it registered under the bare method name.
            # Re-publish the BOUND method with the user's original metadata so
            # `self` is gone and the registry key is unique per capability.
            _republish_tool_wins(name, bound, own_meta, cls)
            continue

        capability = f"{prefix}.{name}"
        _validate_capability_segmented(
            capability, f"@mesh.service producer '{cls.__name__}' method '{name}'"
        )
        published = _wrap_bound(bound)
        # Unique, deterministic, cross-runtime-consistent identity: the dotted
        # capability itself (Java sugar uses the capability as the tool name;
        # FastMCP accepts dots). DecoratorRegistry keys on __name__, so two
        # producer classes sharing a method name (get/list/status) no longer
        # silently clobber each other.
        published.__name__ = capability
        published.__qualname__ = capability
        wrapper = decorators.tool(capability=capability)(published)
        _mark_for_serving(wrapper, capability)

    return cls


def _mark_for_serving(wrapper, capability: str) -> None:
    """Flag a sugar/tool-wins-published wrapper so the startup pipeline attaches
    it to the SERVED FastMCP server.

    Unlike an ordinary tool (where the user stacks ``@app.tool()`` +
    ``@mesh.tool()`` — the former SERVES, the latter WIRES), producer sugar
    applies ``@mesh.tool`` programmatically and the user never touches the
    FastMCP server. The DI wrapper lands in DecoratorRegistry (→ heartbeat/wire)
    but NOT on the served FastMCP instance, so tools/list wouldn't show it and
    tools/call would 'Unknown tool'. ``ServiceViewProducerServingStep`` reads
    this marker after FastMCP discovery and registers the wrapper on the server
    — the same late-bind pattern the MeshJob helper tools use.
    """
    try:
        wrapper._mesh_service_served_name = capability
    except (AttributeError, TypeError):
        logger.debug(
            "@mesh.service: could not mark '%s' for FastMCP serving", capability
        )


def _wrap_bound(bound):
    """Wrap a bound method in a plain function @mesh.tool can decorate.

    Bound methods are read-only (no attribute assignment); the wrapper gives a
    clean module-level-style callable. ``functools.wraps`` preserves
    ``__annotations__`` / ``__doc__`` / ``__wrapped__`` so signature analysis
    (``self`` already excluded on the bound method) and schema extraction
    resolve exactly as for a hand-written tool.
    """
    import functools
    import inspect

    if inspect.isasyncgenfunction(bound):
        # Streaming producer method (``async def ... -> Stream[str]: yield``).
        # The wrapper MUST itself be an async-generator function so the stream
        # detection (``inspect.isasyncgenfunction``) and dispatch treat it as a
        # stream directly, rather than relying on the wraps-carried annotation +
        # the stream wrapper's non-asyncgen fallback.
        @functools.wraps(bound)
        async def published(*args, __bound=bound, **kwargs):
            async for _item in __bound(*args, **kwargs):
                yield _item

    elif inspect.iscoroutinefunction(bound):

        @functools.wraps(bound)
        async def published(*args, __bound=bound, **kwargs):
            return await __bound(*args, **kwargs)

    else:

        @functools.wraps(bound)
        def published(*args, __bound=bound, **kwargs):
            return __bound(*args, **kwargs)

    return published


def _republish_tool_wins(method_name: str, bound, own_meta: dict, cls) -> None:
    """Re-publish a tool-wins producer method as its BOUND form.

    The user's ``@mesh.tool`` decorated the unbound method (``self`` in the
    signature, registered under the bare name). Reconstruct the exact
    ``@mesh.tool`` call from the stored metadata onto the bound method so the
    schema has no ``self`` and the registry key is unique per capability.
    """
    from . import decorators

    capability = own_meta.get("capability")
    # Drop the stale unbound registration (keyed by the bare method __name__).
    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    DecoratorRegistry.unregister_mesh_tool(method_name)

    published = _wrap_bound(bound)
    # Unique identity: the user's own capability if set, else the bare name.
    published.__name__ = capability or method_name
    published.__qualname__ = published.__name__

    # Reconstruct the tool() call from the standard fields; forward any extra
    # metadata (vendor kwargs) verbatim. ``retry_on`` is stored as a tuple
    # (``()`` when unset) but tool() rejects a non-None retry_on with task=False
    # — normalize empty → None.
    _standard = {
        "capability",
        "tags",
        "version",
        "dependencies",
        "description",
        "output_schema_strict",
        "task",
        "retry_on",
    }
    extra = {
        k: v
        for k, v in own_meta.items()
        if k not in _standard and k not in ("stream_type", "function_name")
    }
    retry_on = own_meta.get("retry_on") or None
    wrapper = decorators.tool(
        capability=capability,
        tags=own_meta.get("tags"),
        version=own_meta.get("version", "1.0.0"),
        dependencies=own_meta.get("dependencies"),
        description=own_meta.get("description"),
        output_schema_strict=own_meta.get("output_schema_strict", True),
        task=own_meta.get("task", False),
        retry_on=retry_on,
        **extra,
    )(published)
    _mark_for_serving(wrapper, published.__name__)


def service(arg=None, *, min_available: int = 0):
    """RFC #1280 ``@mesh.service`` — consumer view or producer sugar.

    Forms::

        @mesh.service                    # consumer view
        @mesh.service()                  # consumer view
        @mesh.service(min_available=2)   # consumer view with availability floor
        @mesh.service("media")           # producer sugar (publishes media.<method>)
    """
    # Bare @mesh.service (class passed directly) → consumer view.
    if isinstance(arg, type):
        return _build_consumer_view(arg, min_available)

    prefix = arg  # str (producer) or None (consumer view)

    def decorator(cls):
        if not isinstance(cls, type):
            raise ValueError("@mesh.service must decorate a class")
        if prefix is not None:
            return _build_producer(cls, prefix, min_available)
        return _build_consumer_view(cls, min_available)

    return decorator
