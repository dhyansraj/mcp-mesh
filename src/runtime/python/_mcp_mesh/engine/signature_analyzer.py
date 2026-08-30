"""
Function signature analysis for MCP Mesh dependency injection.
"""

import inspect
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional, get_type_hints

from mesh.types import McpMeshTool, MeshJob, MeshLlmAgent

logger = logging.getLogger(__name__)

# Also support deprecated McpMeshAgent for backwards compatibility
try:
    from mesh.types import McpMeshAgent
except ImportError:
    McpMeshAgent = McpMeshTool  # type: ignore


def _get_original_func(func: Any) -> Any:
    """Follow __wrapped__ chain to get the original function.

    Injection wrappers override __signature__ to hide injectable params
    from FastMCP. Internal analysis functions need the original signature.
    """
    original = func
    # Follow __wrapped__ (set by @functools.wraps)
    while hasattr(original, "__wrapped__"):
        original = original.__wrapped__
    # Also check _mesh_original_func (set by DI injector)
    if hasattr(original, "_mesh_original_func"):
        original = original._mesh_original_func
    return original


#: Bare identifiers inside a string annotation, e.g. ``"mesh.MeshLlmAgent | None"``
#: → ``["mesh", "MeshLlmAgent", "None"]``.
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: ``typing.get_type_hints`` key for the return annotation. Cannot collide with
#: a parameter name — ``return`` is a keyword.
_RETURN_KEY = "return"


def resolve_param_annotations(func: Any) -> dict[str, Any]:
    """Resolve a callable's parameter annotations to runtime type objects.

    The single resolution step in front of every annotation-identity check in
    the runtime — the ``McpMeshTool`` / ``McpMeshAgent`` / ``MeshJob`` /
    service-view scans in this module and the ``MeshLlmAgent`` scan in
    ``mesh.decorators`` — so the two surfaces cannot drift apart again
    (issue #1548).

    Under ``from __future__ import annotations`` (PEP 563) every annotation in
    the module is a **string**, so comparing ``param.annotation`` to a class is
    unconditionally False and a correctly written parameter goes undetected.
    ``typing.get_type_hints`` undoes the stringification and (on every Python
    this package supports, ``>=3.11``) returns the bare class without wrapping
    a ``= None`` default in ``Optional`` — the auto-``Optional`` behaviour was
    removed in 3.11 — so the existing ``== SomeClass`` comparisons keep working
    once the annotation is resolved.

    Resolution degrades in three steps and **never raises**. A module that
    imports today must still import afterwards: turning an unresolvable
    annotation into an import failure would be a worse version of the bug being
    fixed.

    1. function-wide :func:`typing.get_type_hints`;
    2. per-parameter evaluation against the defining module's globals, because
       ``get_type_hints`` is all-or-nothing — one ``TYPE_CHECKING``-only import
       or dangling forward reference on ANY parameter (or the return
       annotation) would otherwise blind the resolvable siblings;
    3. the annotation exactly as written. Under PEP 563 that is a string, which
       the ``_is_*_type`` predicates still match by name (see
       :func:`_annotation_mentions`).

    Returns:
        Mapping of parameter name to resolved annotation. Unannotated
        parameters are omitted, so callers can treat "absent" as untyped. The
        return annotation is NOT included — use
        :func:`resolve_return_annotation`.
    """
    resolved = _resolve_param_annotations(func)[0]
    resolved.pop(_RETURN_KEY, None)
    return resolved


def resolve_return_annotation(func: Any) -> Any:
    """Resolve a callable's **return** annotation through the same ladder as
    :func:`resolve_param_annotations`.

    Returns ``inspect.Signature.empty`` when the callable declares no return
    annotation, matching ``inspect.Signature.return_annotation`` so callers can
    swap one for the other. Never raises.

    Same #1548 exposure as the parameters: under PEP 563 the raw return
    annotation is the *string* ``"ChatResponse"``, which silently becomes the
    ``@mesh.llm`` output type — failing the Pydantic-model check that drives
    structured output.
    """
    resolved, _ = _resolve_param_annotations(func)
    return resolved.get(_RETURN_KEY, inspect.Signature.empty)


def _resolve_param_annotations(func: Any) -> tuple[dict[str, Any], bool]:
    """Body of :func:`resolve_param_annotations`, additionally reporting
    whether function-wide :func:`typing.get_type_hints` succeeded.

    The flag is for callers that warn about degraded resolution (the RFC #1280
    service-view scan); everything else wants the mapping alone.
    """
    func = _get_original_func(func)
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return {}, False

    hints_ok = True
    try:
        hints = get_type_hints(func)
    except Exception as e:
        # NameError for an unimportable name, TypeError for a malformed
        # annotation, anything else a __getattr__ on the module raises: all
        # non-fatal, all handled by the per-parameter pass below.
        logger.debug(
            "resolve_param_annotations: get_type_hints failed for %s (%s); "
            "falling back to per-parameter resolution",
            getattr(func, "__qualname__", getattr(func, "__name__", "?")),
            e,
        )
        hints = {}
        hints_ok = False

    globalns = getattr(func, "__globals__", None)
    if globalns is None:
        import sys

        module = getattr(func, "__module__", None)
        globalns = getattr(sys.modules.get(module), "__dict__", {}) if module else {}

    def _resolve_one(name: str, raw: Any) -> Any:
        if name in hints:
            return hints[name]
        if not isinstance(raw, str):
            return raw
        try:
            return eval(raw, globalns)  # noqa: S307 - module-scoped
        except Exception:
            # Step 3: keep the string. The predicates match it by name so a
            # parameter the developer spelled correctly still binds.
            return raw

    resolved: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if param.annotation is inspect.Parameter.empty:
            continue
        resolved[name] = _resolve_one(name, param.annotation)
    if sig.return_annotation is not inspect.Signature.empty:
        resolved[_RETURN_KEY] = _resolve_one(_RETURN_KEY, sig.return_annotation)
    return resolved, hints_ok


def _annotation_mentions(param_type: Any, *names: str) -> bool:
    """Whether an **unresolved string** annotation names one of ``names``.

    Last-resort arm of the resolution ladder in
    :func:`resolve_param_annotations`: only strings reach here, and only when
    both the function-wide and the per-parameter resolution failed — i.e. the
    named type is not importable at module scope (a ``TYPE_CHECKING``-only
    import being the realistic case). Matching the bare identifier is the same
    class of heuristic as the long-standing ``__name__``-based fallbacks below,
    applied to the one shape those cannot see.
    """
    if not isinstance(param_type, str):
        return False
    return any(token in names for token in _IDENTIFIER_RE.findall(param_type))


def describe_unresolved_annotations(func: Any) -> str:
    """Render the parameters whose annotations stayed strings after
    :func:`resolve_param_annotations`, or ``""`` when every annotation resolved.

    Used to append an accurate cause to "no parameter of type X" errors: a
    string annotation means the name was not importable at module scope, which
    is nothing like the "you forgot the parameter" the bare message implies.
    """
    unresolved = [
        f"{name}: {value!r}"
        for name, value in resolve_param_annotations(func).items()
        if isinstance(value, str)
    ]
    if not unresolved:
        return ""
    return (
        f" Note: the annotation(s) {', '.join(unresolved)} could not be resolved "
        f"to a type. Under `from __future__ import annotations` every annotation "
        f"is a string, and the name must be importable at module scope — not "
        f"only under `if TYPE_CHECKING:`."
    )


def _is_mesh_tool_type(param_type: Any) -> bool:
    """Check if a type is McpMeshTool or deprecated McpMeshAgent."""
    # Unresolved PEP 563 / forward-reference string (issue #1548).
    if _annotation_mentions(param_type, "McpMeshTool", "McpMeshAgent"):
        return True

    # Direct McpMeshTool type
    if (
        param_type == McpMeshTool
        or (hasattr(param_type, "__name__") and param_type.__name__ == "McpMeshTool")
        or (
            hasattr(param_type, "__origin__")
            and param_type.__origin__ == type(McpMeshTool)
        )
    ):
        return True

    # Support deprecated McpMeshAgent
    if (
        param_type == McpMeshAgent
        or (hasattr(param_type, "__name__") and param_type.__name__ == "McpMeshAgent")
        or (
            hasattr(param_type, "__origin__")
            and param_type.__origin__ == type(McpMeshAgent)
        )
    ):
        return True

    # Union type (e.g., McpMeshTool | None)
    if hasattr(param_type, "__args__"):
        for arg in param_type.__args__:
            if arg == McpMeshTool or (
                hasattr(arg, "__name__") and arg.__name__ == "McpMeshTool"
            ):
                return True
            # Support deprecated McpMeshAgent in unions
            if arg == McpMeshAgent or (
                hasattr(arg, "__name__") and arg.__name__ == "McpMeshAgent"
            ):
                return True

    return False


def _is_mesh_llm_type(param_type: Any) -> bool:
    """Check if a type is MeshLlmAgent."""
    # Unresolved PEP 563 / forward-reference string (issue #1548).
    if _annotation_mentions(param_type, "MeshLlmAgent"):
        return True

    # Direct MeshLlmAgent type
    if param_type == MeshLlmAgent or (
        hasattr(param_type, "__name__") and param_type.__name__ == "MeshLlmAgent"
    ):
        return True

    # Union type (e.g., MeshLlmAgent | None)
    if hasattr(param_type, "__args__"):
        for arg in param_type.__args__:
            if arg == MeshLlmAgent or (
                hasattr(arg, "__name__") and arg.__name__ == "MeshLlmAgent"
            ):
                return True

    return False


def _is_mesh_job_type(param_type: Any) -> bool:
    """Check if a type is :class:`mesh.MeshJob` (Phase 1 — MeshJob substrate).

    Mirrors :func:`_is_mesh_tool_type` / :func:`_is_mesh_llm_type` for the
    new injectable. Handles direct ``MeshJob`` annotations as well as
    ``Optional[MeshJob]`` / ``MeshJob | None`` unions per the resolver
    contract (``MESHJOB_DDDI_CONTRACT.md`` → "Optional / Union types").
    """
    # Unresolved PEP 563 / forward-reference string (issue #1548).
    if _annotation_mentions(param_type, "MeshJob"):
        return True

    # Direct MeshJob type
    if param_type == MeshJob or (
        hasattr(param_type, "__name__") and param_type.__name__ == "MeshJob"
    ):
        return True

    # Union type (e.g., MeshJob | None, Optional[MeshJob])
    if hasattr(param_type, "__args__"):
        for arg in param_type.__args__:
            if arg == MeshJob or (
                hasattr(arg, "__name__") and arg.__name__ == "MeshJob"
            ):
                return True

    return False


def _service_view_meta(param_type: Any) -> Any:
    """Return the ``ServiceViewMeta`` for a ``@mesh.service`` consumer-view
    class (RFC #1280), unwrapping ``Optional[View]`` / ``View | None``, or
    ``None`` if the type is not a service view.

    Detection keys purely on the marker attribute stamped by ``@mesh.service``
    (``SERVICE_VIEW_ATTR``, imported lazily from ``mesh._service`` — the marker
    name only, never the decorator machinery, avoiding an import cycle).
    Producer classes are NOT views (they publish tools and carry no marker), so
    they are never detected here.
    """
    from mesh._service import SERVICE_VIEW_ATTR

    candidates = [param_type]
    if hasattr(param_type, "__args__"):
        candidates.extend(param_type.__args__)
    for candidate in candidates:
        if inspect.isclass(candidate):
            # DIRECT annotation only (``__dict__``, not ``getattr`` which walks
            # the MRO): an UNDECORATED subclass of a view is NOT itself a view —
            # inheriting the parent's marker would resolve the subclass's own
            # selectors to the PARENT's bindings (wrong methods, wrong name in
            # errors). Mirrors Java's direct-annotation scanning rule. A
            # subclass that WANTS to be a view re-applies @mesh.service (its own
            # marker then lands in its __dict__).
            meta = candidate.__dict__.get(SERVICE_VIEW_ATTR)
            if meta is not None:
                return meta
    return None


def _is_service_view_type(param_type: Any) -> bool:
    """Whether a type is a ``@mesh.service`` consumer view (RFC #1280)."""
    return _service_view_meta(param_type) is not None


def analyze_service_view_params(func: Any) -> list:
    """Classify a function's ``@mesh.service`` consumer-view parameters.

    Returns a list of ``(position, name, ServiceViewMeta)`` tuples in
    declaration order — the parameter-order half of the RFC #1280 view-edge
    layout (methods are name-sorted within each view by ``@mesh.service``).
    A view parameter is a NEW type-detected slot kind (the MeshJob precedent),
    orthogonal to the McpMeshTool/MeshJob positional namespace.
    """
    func = _get_original_func(func)
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return []

    # Shared resolution ladder (#1548). ``get_type_hints`` is all-or-nothing:
    # one unresolvable annotation (e.g. a TYPE_CHECKING-only import under
    # ``from __future__ import annotations``) breaks it for the WHOLE function —
    # including ordinary view-free tools. The resolver falls back to
    # per-parameter resolution so a resolvable view isn't silently lost; we warn
    # ONLY when a view is actually recovered that way (never for a view-free
    # function whose hints happen to fail elsewhere), per RFC #1280's
    # "don't spam" scoping.
    resolved_annotations, hints_ok = _resolve_param_annotations(func)

    result: list = []
    for i, param_name in enumerate(sig.parameters.keys()):
        if param_name not in resolved_annotations:
            continue
        meta = _service_view_meta(resolved_annotations[param_name])
        if meta is not None:
            result.append((i, param_name, meta))

    if result and not hints_ok:
        logger.warning(
            "analyze_service_view_params: function '%s' has @mesh.service view "
            "parameter(s) %s but function-wide type-hint resolution failed "
            "(recovered per-parameter). If this module uses "
            "`from __future__ import annotations`, ensure every annotated type "
            "is importable at module scope so the view is reliably detected.",
            getattr(func, "__qualname__", getattr(func, "__name__", "?")),
            [name for _pos, name, _meta in result],
        )
    return result


def get_service_view_positions(func: Any) -> list[int]:
    """Signature positions (0-indexed) of ``@mesh.service`` view parameters."""
    return [pos for pos, _name, _meta in analyze_service_view_params(func)]


def get_service_view_parameter_names(func: Any) -> list[str]:
    """Parameter names of ``@mesh.service`` view parameters."""
    return [name for _pos, name, _meta in analyze_service_view_params(func)]


def _scan_params(
    func: Any,
    predicate: Callable[[Any], bool],
    *,
    want: str = "positions",
) -> list:
    """Scan a function's typed parameters and collect the ones matching
    ``predicate``.

    Shared body of the four public ``get_*_positions`` / ``get_*_parameter_names``
    helpers — same unwrap-and-introspect loop, differing only in the
    classifier predicate and whether positions (0-indexed) or names are
    returned (``want="positions"`` or ``want="names"``).

    Annotations are resolved through :func:`resolve_param_annotations` (#1548)
    so a module using ``from __future__ import annotations`` — where every
    annotation is a string — is classified the same as one without it.

    The broad ``except Exception`` is intentional: any introspection failure
    (weird callables, a signature that cannot be taken at all) is logged at
    WARNing and yields an empty list so registration can proceed — the
    function is still invokable as a plain tool, the typed slots just won't
    bind. Do NOT narrow this.
    """
    try:
        func = _get_original_func(func)
        resolved_annotations = resolve_param_annotations(func)
        sig = inspect.signature(func)

        result: list = []
        for i, param_name in enumerate(sig.parameters.keys()):
            if param_name not in resolved_annotations:
                continue
            if predicate(resolved_annotations[param_name]):
                result.append(i if want == "positions" else param_name)
        return result

    except Exception as e:
        # If we can't analyze the signature, return empty list
        logger.warning(f"Failed to analyze signature for {func}: {e}")
        return []


@dataclass(frozen=True)
class MeshJobResolution:
    """Resolver output for ``MeshJob`` parameter classification.

    Per ``MESHJOB_DDDI_CONTRACT.md``: ``MeshJob`` and ``McpMeshTool``
    parameters share a **single unified positional ``dep_index``
    namespace**. Adding or removing a ``MeshJob`` parameter shifts the
    shared slot numbering used to inject all mesh dependencies; the
    ``MeshJob`` position is recorded here so the dispatch at injection
    time can identify which slot to construct a ``MeshJobSubmitter``
    for (vs an ``McpMeshTool`` proxy).

    Attributes:
        mesh_tool_positions: Signature positions (0-indexed) of
            ``McpMeshTool`` parameters in declaration order. Each entry
            is the slot the corresponding dependency proxy fills.
            Identical to the legacy ``get_mesh_agent_positions`` output;
            duplicated here so callers get a single resolver output.
        mesh_job_param_index: Signature position (0-indexed) of the
            single ``MeshJob`` parameter, or ``None`` if the function
            does not declare one. Phase 1 enforces "at most one
            ``MeshJob`` per tool" — multiple is a registration-time
            error.
        mesh_job_param_name: Name of the ``MeshJob`` parameter (for
            kwargs-style injection by the runtime), or ``None`` when no
            ``MeshJob`` is declared. Mirrors ``mesh_job_param_index``.
    """

    mesh_tool_positions: list[int] = field(default_factory=list)
    mesh_job_param_index: int | None = None
    mesh_job_param_name: str | None = None


def analyze_mesh_job_signature(func: Any) -> MeshJobResolution:
    """Classify a function's parameters per the MeshJob DDDI contract.

    Iterates parameters in declaration order. For each:
      - ``McpMeshTool``-typed: append signature position to
        ``mesh_tool_positions`` (i.e. the slot the dependency proxy
        will fill at runtime). The list's index acts as the
        ``mesh_tool_position_counter`` from the contract.
      - ``MeshJob``-typed: record signature position in
        ``mesh_job_param_index`` (and the name in
        ``mesh_job_param_name``). Does NOT touch ``mesh_tool_positions``
        — orthogonal injection per contract.
      - Anything else: untouched (user argument).

    Phase 1 invariant: at most one ``MeshJob`` parameter. A second
    occurrence raises ``ValueError`` so the developer sees the problem
    at decoration / registration time rather than at first invocation.

    Args:
        func: Function to analyze. Wrapper chains (``__wrapped__`` /
            ``_mesh_original_func``) are followed to the underlying
            user function so the analysis matches the source-level
            declaration.

    Returns:
        :class:`MeshJobResolution` capturing both the mesh-tool slots
        and the single optional ``MeshJob`` slot.

    Raises:
        ValueError: If the function declares more than one ``MeshJob``
            parameter (Phase 1 disallows; future revisions may relax).
    """
    func = _get_original_func(func)
    # Shared resolution ladder (#1548) — never raises, and classifies a
    # ``from __future__ import annotations`` module the same as a plain one.
    resolved_annotations = resolve_param_annotations(func)

    sig = inspect.signature(func)
    mesh_tool_positions: list[int] = []
    mesh_job_param_index: int | None = None
    mesh_job_param_name: str | None = None

    for i, (param_name, _param) in enumerate(sig.parameters.items()):
        if param_name not in resolved_annotations:
            continue
        param_type = resolved_annotations[param_name]

        # MeshTool: assigns next positional slot, increments the counter
        # (the counter being len(mesh_tool_positions)).
        if _is_mesh_tool_type(param_type):
            mesh_tool_positions.append(i)
            continue

        # MeshJob: orthogonal — does NOT touch the mesh-tool counter.
        if _is_mesh_job_type(param_type):
            if mesh_job_param_index is not None:
                # Phase 1 contract: at most one. Fail loudly with a
                # clear message including both offending parameter names
                # so the developer can fix it without reading the source.
                raise ValueError(
                    f"a tool function may declare at most one MeshJob parameter; "
                    f"function '{func.__name__}' declares both "
                    f"'{mesh_job_param_name}' and '{param_name}'. Fix: keep a "
                    f"single MeshJob parameter (e.g. "
                    f"'{mesh_job_param_name}: MeshJob = None') and remove the "
                    f"other(s)."
                )
            mesh_job_param_index = i
            mesh_job_param_name = param_name
            continue

        # Anything else (user arg, MeshLlmAgent, MeshContextModel, etc.)
        # is untouched here — those classifiers live in their own helpers.

    return MeshJobResolution(
        mesh_tool_positions=mesh_tool_positions,
        mesh_job_param_index=mesh_job_param_index,
        mesh_job_param_name=mesh_job_param_name,
    )


def get_mesh_agent_positions(func: Any) -> list[int]:
    """
    Get positions of McpMeshTool parameters in function signature.

    Args:
        func: Function to analyze

    Returns:
        List of parameter positions (0-indexed) that are McpMeshTool types

    Example:
        def greet(name: str, date_svc: McpMeshTool, file_svc: McpMeshTool):
            pass

        get_mesh_agent_positions(greet) → [1, 2]
    """
    return _scan_params(func, _is_mesh_tool_type, want="positions")


def get_mesh_agent_parameter_names(func: Any) -> list[str]:
    """
    Get names of McpMeshTool parameters in function signature.

    Args:
        func: Function to analyze

    Returns:
        List of parameter names that are McpMeshTool types
    """
    return _scan_params(func, _is_mesh_tool_type, want="names")


def validate_mesh_dependencies(func: Any, dependencies: list[dict]) -> tuple[bool, str]:
    """
    Validate that the number of dependencies matches the function's
    injectable slots.

    A function may declare two kinds of typed dependency slot, both
    consuming a positional dependency entry (in declaration order):

    * ``McpMeshTool`` — dispatched via remote ``tools/call``. Counted via
      :func:`get_mesh_agent_positions`.
    * ``MeshJob`` — dispatched via job submit. Counted by the presence of
      a single ``MeshJob`` parameter (Phase 1 enforces at most one). The
      parameter name is free-form; binding is positional per
      ``MESHJOB_DDDI_CONTRACT.md``.

    Validation passes when ``len(dependencies) == mcp_slots + job_slots``
    so consumer functions that only depend on a remote ``task=True`` tool
    (one MeshJob param, one dependency, zero McpMeshTool params) are NOT
    skipped from the heartbeat — they still need to be advertised to the
    registry so the resolver can match them against providers.

    Args:
        func: Function to validate
        dependencies: List of dependency declarations from @mesh.tool

    Returns:
        Tuple of (is_valid, error_message)

    Raises:
        StrictDIError: When the slot/dependency counts mismatch AND
            ``MCP_MESH_STRICT_DI`` is truthy — the ambiguity/skip class of
            DI diagnostics is promoted from a heartbeat-time "skipping
            tool" warning to a startup error. The error text is identical
            to the returned ``error_message``.
    """
    func = _get_original_func(func)
    mesh_positions = get_mesh_agent_positions(func)

    # Count MeshJob slots positionally — name does not matter under the
    # unified positional contract.
    #
    # Errors: ``analyze_mesh_job_signature`` raises ``ValueError`` when a
    # function declares multiple MeshJob parameters (Phase 1 contract).
    # We deliberately let that propagate so registration-time validation
    # surfaces the misuse instead of silently advertising the tool with
    # the wrong dependency-slot count. Other inspection failures
    # (TypeError / AttributeError on weird callables) still fall through
    # to the legacy positional-only check — those are non-contractual
    # signatures the legacy validator already tolerated.
    job_slots = 0
    try:
        resolution = analyze_mesh_job_signature(func)
    except (TypeError, AttributeError) as e:
        # Defensive: weird callables that can't be introspected. Skip
        # the MeshJob accounting and fall through to the legacy check.
        logger.debug(
            "validate_mesh_dependencies: MeshJob analysis skipped for %s: %s",
            getattr(func, "__name__", "?"),
            e,
        )
        resolution = None

    if resolution is not None and resolution.mesh_job_param_name is not None:
        job_slots = 1

    # RFC #1280: each @mesh.service view parameter expands to N dependency
    # edges (one per selector method), appended AFTER the explicit deps. Those
    # edges have no McpMeshTool/MeshJob parameter of their own, so the count
    # must add them or the tool would be dropped from the heartbeat.
    view_method_slots = 0
    try:
        for _pos, _name, _meta in analyze_service_view_params(func):
            view_method_slots += len(_meta.bindings)
    except Exception as e:  # noqa: BLE001 - never block validation on view introspection
        logger.debug(
            "validate_mesh_dependencies: service-view analysis skipped for %s: %s",
            getattr(func, "__name__", "?"),
            e,
        )

    expected = len(mesh_positions) + job_slots + view_method_slots
    if len(dependencies) != expected:
        # Name each typed slot (declaration order) so the message shows the
        # exact dep→param pairing positional binding uses, plus the fix.
        try:
            param_names_by_pos = list(inspect.signature(func).parameters.keys())
        except (TypeError, ValueError):
            param_names_by_pos = []
        slot_entries = [(pos, "McpMeshTool") for pos in mesh_positions]
        if resolution is not None and resolution.mesh_job_param_index is not None:
            slot_entries.append((resolution.mesh_job_param_index, "MeshJob"))
        slot_entries.sort()
        slots_desc = (
            ", ".join(
                (
                    f"'{param_names_by_pos[pos]}' ({kind})"
                    if pos < len(param_names_by_pos)
                    else f"<arg {pos}> ({kind})"
                )
                for pos, kind in slot_entries
            )
            or "none"
        )
        from .strict_di import pluralize

        message = (
            f"Function {func.__name__} has "
            f"{pluralize(len(mesh_positions), 'McpMeshTool parameter')}, "
            f"{pluralize(job_slots, 'MeshJob slot')} and "
            f"{pluralize(view_method_slots, 'service-view method edge')} "
            f"but {pluralize(len(dependencies), 'dependency', 'dependencies')} "
            f"declared. "
            f"Each typed slot needs a corresponding dependency. "
            f"Typed slots in declaration order: {slots_desc}; "
            f"dependencies[i] pairs with the i-th slot positionally "
            f"(parameter names are never matched). Fix: declare exactly "
            f"{pluralize(expected, 'entry', 'entries')} in dependencies=[...], "
            f"or add/remove "
            f"typed parameters (e.g. 'my_dep: McpMeshTool = None') so the "
            f"counts match."
        )
        # Opt-in strictness (MCP_MESH_STRICT_DI): promote the skip-class
        # diagnostic to a startup error with the same prescriptive text.
        from .strict_di import StrictDIError, is_strict_di_enabled

        if is_strict_di_enabled():
            raise StrictDIError(message)
        return False, message

    return True, ""


def get_llm_agent_positions(func: Any) -> list[int]:
    """
    Get positions of MeshLlmAgent parameters in function signature.

    Args:
        func: Function to analyze

    Returns:
        List of parameter positions (0-indexed) that are MeshLlmAgent types

    Example:
        def chat(msg: str, llm: MeshLlmAgent):
            pass

        get_llm_agent_positions(chat) → [1]
    """
    return _scan_params(func, _is_mesh_llm_type, want="positions")


def has_llm_agent_parameter(func: Any) -> bool:
    """
    Check if function has any MeshLlmAgent parameters.

    Args:
        func: Function to analyze

    Returns:
        True if function has at least one MeshLlmAgent parameter
    """
    return len(get_llm_agent_positions(func)) > 0


def get_llm_agent_parameter_names(func: Any) -> list[str]:
    """
    Get names of MeshLlmAgent parameters in function signature.

    Args:
        func: Function to analyze

    Returns:
        List of parameter names that are MeshLlmAgent types
    """
    return _scan_params(func, _is_mesh_llm_type, want="names")


def get_context_parameter_name(
    func: Any, explicit_name: str | None = None
) -> tuple[str, int] | None:
    """
    Get context parameter name and index for template rendering (Phase 2).

    This function detects context parameters using a hybrid approach:
    1. Explicit name (if provided) - validates existence
    2. Convention-based detection - checks for prompt_context, llm_context, context
    3. Type hint detection - finds MeshContextModel subclass parameters

    Args:
        func: Function to analyze
        explicit_name: Optional explicit parameter name from @mesh.llm(context_param="...")

    Returns:
        Tuple of (param_name, param_index) or None if no context parameter found

    Raises:
        ValueError: If explicit_name provided but parameter not found

    Example:
        # Explicit name
        def chat(msg: str, ctx: ChatContext, llm: MeshLlmAgent = None):
            pass
        get_context_parameter_name(chat, "ctx") → ("ctx", 1)

        # Convention-based
        def analyze(query: str, prompt_context: dict, llm: MeshLlmAgent = None):
            pass
        get_context_parameter_name(analyze) → ("prompt_context", 1)

        # Type hint detection
        def process(data: str, my_ctx: ChatContext, llm: MeshLlmAgent = None):
            pass
        get_context_parameter_name(process) → ("my_ctx", 1)
    """
    try:
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())

        # Resolved annotations (shared ladder, #1548 — never raises; an
        # annotation that stays a string simply fails the issubclass checks
        # below and falls through to convention-based detection).
        type_hints = resolve_param_annotations(func)

        # Strategy 1: Explicit name (highest priority)
        if explicit_name is not None:
            if explicit_name in param_names:
                param_index = param_names.index(explicit_name)
                return (explicit_name, param_index)
            else:
                raise ValueError(
                    f"Context parameter '{explicit_name}' not found in function '{func.__name__}'. "
                    f"Available parameters: {param_names}"
                )

        # Strategy 2: Type hint detection (find MeshContextModel parameters)
        # This has priority over convention names
        if type_hints:
            from mesh.types import MeshContextModel

            for i, param_name in enumerate(param_names):
                if param_name in type_hints:
                    param_type = type_hints[param_name]

                    # Check if it's MeshContextModel or subclass
                    is_context_model = False

                    # Direct MeshContextModel type
                    try:
                        if inspect.isclass(param_type) and issubclass(
                            param_type, MeshContextModel
                        ):
                            is_context_model = True
                    except TypeError:
                        pass  # Not a class, check other cases

                    # Union type (e.g., Optional[MeshContextModel])
                    if not is_context_model and hasattr(param_type, "__args__"):
                        for arg in param_type.__args__:
                            if arg is not type(None):  # Skip None in Optional
                                try:
                                    if inspect.isclass(arg) and issubclass(
                                        arg, MeshContextModel
                                    ):
                                        is_context_model = True
                                        break
                                except TypeError:
                                    pass

                    if is_context_model:
                        return (param_name, i)

        # Strategy 3: Convention-based detection (check in priority order)
        # This comes after type hint detection
        convention_names = ["prompt_context", "llm_context", "context"]
        for convention_name in convention_names:
            if convention_name in param_names:
                param_index = param_names.index(convention_name)
                return (convention_name, param_index)

        # No context parameter found
        return None

    except ValueError:
        # Re-raise ValueError for explicit name validation errors
        raise
    except Exception as e:
        logger.debug(f"Failed to detect context parameter for {func.__name__}: {e}")
        return None
