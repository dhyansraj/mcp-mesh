"""
Dynamic dependency injection system for MCP Mesh.

Handles both initial injection and runtime updates when topology changes.
Focused purely on dependency injection - telemetry/tracing is handled at
the HTTP middleware layer for unified approach across MCP agents and FastAPI apps.
"""

import asyncio
import functools
import inspect
import json
import logging
import weakref
from collections.abc import Callable, Iterable
from typing import Any, Optional

from ..shared.logging_config import (
    format_log_value,
    format_result_summary,
    get_trace_prefix,
)
from .settle import (
    collect_pending_settle_deps,
    get_settle_state,
    wait_for_settle_async,
    wait_for_settle_sync,
)
from .signature_analyzer import get_mesh_agent_positions, has_llm_agent_parameter
from .strict_di import (
    StrictDIError,
    is_strict_di_enabled,
    pluralize,
    warn_or_raise,
)

logger = logging.getLogger(__name__)

# Internal parameter name used to receive FastMCP's auto-injected ``Context``
# in streaming wrappers. Must NOT collide with anything a user could plausibly
# declare on their own ``@mesh.tool`` function.
#
# Why not just call it ``ctx``? Users routinely declare ``ctx`` themselves —
# in particular ``@mesh.llm(context_param="ctx", ...)`` is the natural default
# and pairs with ``ctx: SomeContextModel`` on the function. If we synthesize a
# parameter with the same NAME but a different TYPE (``Context``), FastMCP's
# ``transform_context_annotations`` reads the user's annotation, doesn't see
# ``Context``, and silently never injects — streaming then degrades to a
# buffered single-chunk response. The ``_mesh_`` prefix signals "framework
# internal, don't touch" and avoids any realistic collision.
_MESH_PROGRESS_CTX_PARAM = "_mesh_progress_ctx"

# Cached convention for ctx.report_progress; resolved lazily per FastMCP
# version. Newer FastMCP exposes a ``message`` kwarg; older builds only accept
# ``(progress, total)`` positionally with a third positional ``message``.
_REPORT_PROGRESS_CONVENTION: Optional[str] = None


def _resolve_report_progress_convention(report_progress: Callable) -> str:
    """Detect whether ``ctx.report_progress`` accepts ``message`` as a kwarg.

    Returns ``"kwarg"`` when the bound method advertises a ``message``
    parameter; otherwise ``"positional"`` (fall back to passing the chunk as
    the third positional argument). Cached after the first probe.
    """
    global _REPORT_PROGRESS_CONVENTION
    if _REPORT_PROGRESS_CONVENTION is not None:
        return _REPORT_PROGRESS_CONVENTION
    try:
        sig = inspect.signature(report_progress)
        if "message" in sig.parameters:
            _REPORT_PROGRESS_CONVENTION = "kwarg"
        else:
            _REPORT_PROGRESS_CONVENTION = "positional"
    except (TypeError, ValueError):
        _REPORT_PROGRESS_CONVENTION = "positional"
    return _REPORT_PROGRESS_CONVENTION


async def _forward_chunk(ctx: Any, index: int, chunk: str) -> None:
    """Send a streaming chunk to the MCP client via ``ctx.report_progress``.

    No-ops gracefully when ``ctx`` is None (caller did not pass a
    ``progressToken``) or when the report itself fails — a transport hiccup
    must not abort the rest of the stream.
    """
    if ctx is None:
        return
    report = getattr(ctx, "report_progress", None)
    if report is None:
        return
    try:
        if _resolve_report_progress_convention(report) == "kwarg":
            await report(index, None, message=chunk)
        else:
            await report(index, None, chunk)
    except Exception as e:
        logger.debug(
            "stream wrapper: ctx.report_progress failed at index %d: %s", index, e
        )


def _is_stream_tool(func: Callable) -> bool:
    """True iff the user function should be wrapped as a streaming tool.

    Combines two signals: the metadata stamped by ``@mesh.tool`` /
    ``@mesh.llm`` (``stream_type == "text"``) and the runtime check
    ``inspect.isasyncgenfunction``. Either alone is sufficient — the
    metadata covers ``async def f() -> Stream[str]: yield ...`` (which is
    an async-generator function) and also any callable returning an async
    iterator (e.g. a coroutine that constructs and returns one).
    """
    if inspect.isasyncgenfunction(func):
        return True
    meta = getattr(func, "_mesh_tool_metadata", None)
    if isinstance(meta, dict) and meta.get("stream_type") == "text":
        return True
    return False


def _build_stream_signature(func: Callable) -> inspect.Signature:
    """Construct the FastMCP-facing signature for a streaming wrapper.

    Starts from the user function's clean signature (McpMeshTool /
    MeshLlmAgent params already removed) and appends a keyword-only
    ``_mesh_progress_ctx: Context | None = None`` so FastMCP's
    ``transform_context_annotations`` auto-fills it at call time without
    exposing it on the tool's input schema.

    The parameter is intentionally NOT named ``ctx``: users can (and often
    do) have their own ``ctx`` parameter — typically a ``MeshContextModel``
    paired with ``@mesh.llm(context_param="ctx", ...)``. Reusing the name
    would silently disable streaming because FastMCP injects ``Context``
    by type annotation, and the user's annotation wins. See
    ``_MESH_PROGRESS_CTX_PARAM`` for the full rationale.
    """
    from fastmcp import Context

    base = _build_clean_signature(func)
    if base is None:
        try:
            base = inspect.signature(func)
        except (TypeError, ValueError):
            base = inspect.Signature(parameters=[])

    # Idempotency: if we've already augmented this signature once, don't add
    # the synthesized parameter twice. (User parameters cannot collide with
    # the ``_mesh_`` prefix unless they're deliberately poking at internals.)
    if _MESH_PROGRESS_CTX_PARAM in base.parameters:
        return base

    params = list(base.parameters.values())
    ctx_param = inspect.Parameter(
        _MESH_PROGRESS_CTX_PARAM,
        kind=inspect.Parameter.KEYWORD_ONLY,
        default=None,
        annotation=Optional[Context],
    )
    return base.replace(parameters=params + [ctx_param])


def _make_stream_wrapper(
    func: Callable,
    mesh_positions: list[int],
    dependencies: list[str],
    get_dependency_fn: Callable[[str], Any | None],
    log: logging.Logger,
    settle_keys: Optional[list] = None,
    settle_params: Optional[list] = None,
    view_slots: Optional[list] = None,
) -> Callable:
    """Build a wrapper that drives an async-iterator tool over MCP progress.

    FastMCP auto-fills ``Context`` for any tool parameter annotated with
    it. We declare that parameter under the internal name
    ``_mesh_progress_ctx`` (see ``_MESH_PROGRESS_CTX_PARAM``) so it cannot
    collide with the user's own ``ctx`` parameter. The wrapper pops it out
    of ``**kwargs`` and never forwards it to the user function. Each chunk
    yielded by the user function is forwarded via ``ctx.report_progress``
    as a progress notification, then accumulated; the final return value
    is the concatenated text so non-streaming consumers still get the full
    response in the ``CallToolResult``.

    Cancellation by the consumer propagates back to the user function via
    ``gen.aclose()`` so generators can run their ``finally`` blocks.
    """
    # Imported for side-effect of validating fastmcp is installed; the
    # actual Context type is referenced in the synthesized signature.
    from fastmcp import Context  # noqa: F401

    @functools.wraps(func)
    async def stream_wrapper(*args, **kwargs):
        # FastMCP injects its Context under our internal name; pop it so
        # it never leaks into the user function's kwargs.
        progress_ctx = kwargs.pop(_MESH_PROGRESS_CTX_PARAM, None)

        # Settling-window grace (#1193): bounded wait for declared-but-
        # unresolved deps while the agent is still settling. No-op (single
        # latch check) once settled. Caller-supplied slots (mock contract)
        # are skipped via the kwargs consult.
        pending_settle = collect_pending_settle_deps(
            settle_keys,
            dependencies,
            stream_wrapper._mesh_injected_deps,
            get_dependency_fn,
            kwargs,
            settle_params,
        )
        if pending_settle:
            await wait_for_settle_async(pending_settle, log)

        final_kwargs, injected_count = _prepare_injection_kwargs(
            func,
            kwargs,
            mesh_positions,
            dependencies,
            stream_wrapper._mesh_injected_deps,
            get_dependency_fn,
            log,
            view_slots=view_slots,
        )

        original = func._mesh_original_func

        if inspect.isasyncgenfunction(original):
            gen = original(*args, **final_kwargs)
        else:
            produced = original(*args, **final_kwargs)
            if inspect.iscoroutine(produced):
                produced = await produced
            gen = produced

        if not hasattr(gen, "__aiter__"):
            raise TypeError(
                f"Stream tool '{func.__name__}' did not return an async iterator "
                f"(got {type(gen).__name__})."
            )

        chunks: list[str] = []
        index = 0
        try:
            async for chunk in gen:
                if not isinstance(chunk, str):
                    raise TypeError(
                        f"Stream tool '{func.__name__}' yielded non-str chunk "
                        f"of type {type(chunk).__name__}; v1 supports str only."
                    )
                chunks.append(chunk)
                await _forward_chunk(progress_ctx, index, chunk)
                index += 1
        except asyncio.CancelledError:
            aclose = getattr(gen, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception as e:
                    log.debug(
                        f"stream wrapper: aclose() failed during cancel: {e}"
                    )
            raise

        result = "".join(chunks)
        _log_wrapper_result(func, result, log)
        return result

    return stream_wrapper


def _build_clean_signature(func: Any) -> inspect.Signature | None:
    """Build a signature excluding McpMeshTool and MeshJob parameters.

    Uses type-based detection (not position-based) to avoid false positives
    from the injector heuristic that treats single/non-typed params as targets.

    Excludes both McpMeshTool and MeshJob (Phase 1 substrate) so neither
    framework-injected slot appears in the FastMCP-visible signature —
    otherwise FastMCP advertises them as user-callable args. MeshLlmAgent
    is excluded by the @mesh.llm decorator's own __signature__ override.

    Returns None if no parameters need removal.

    Errors:
        :class:`ValueError` from :func:`analyze_mesh_job_signature` is
        intentionally allowed to propagate. Per
        ``MESHJOB_DDDI_CONTRACT.md`` ("Multiple MeshJob params"), the
        resolver MUST reject a function with more than one ``MeshJob``
        parameter at registration / decoration time with a clear
        message. Swallowing it here would mean a misuse silently
        decorates and the user only sees a cryptic ``AttributeError``
        on first invocation. Other inspection failures (forward refs,
        broken signatures) still fall through to ``return None`` so the
        decorator path is unaffected.
    """
    from .signature_analyzer import (
        _get_original_func,
        analyze_mesh_job_signature,
        get_mesh_agent_parameter_names,
        get_service_view_parameter_names,
    )

    # Respect explicit ``__signature__`` overrides. Decorators (e.g.
    # ``@mesh.a2a_consumer``) may stamp a curated signature on their wrapper
    # to hide framework-injected parameters from FastMCP/Pydantic schema
    # introspection. Per Python convention, ``__signature__`` wins over
    # signature-from-source rebuilds — treat it as authoritative and skip
    # the rebuild path so we don't re-introduce the hidden params by
    # peeling back to the user's raw function via ``_get_original_func``.
    sig_override = getattr(func, "__signature__", None)
    if isinstance(sig_override, inspect.Signature):
        return sig_override

    try:
        original = _get_original_func(func)
        injectable_names = set(get_mesh_agent_parameter_names(original))
    except (TypeError, AttributeError):
        # Inspection failure on the user's function (e.g. a built-in or a
        # callable without a signature). Not a contract violation; fall
        # back to "no clean signature" so the wrapper uses the original.
        return None

    # Phase 1 MeshJob substrate: also strip the MeshJob slot so it
    # doesn't surface in FastMCP's tools/list schema as a user arg.
    # ``analyze_mesh_job_signature`` may raise ``ValueError`` when the
    # user declares multiple MeshJob parameters — we let that propagate
    # so @mesh.tool fails loudly at decoration time per the contract.
    mj = analyze_mesh_job_signature(original)
    if mj.mesh_job_param_name:
        injectable_names.add(mj.mesh_job_param_name)

    # RFC #1280: a @mesh.service consumer-view parameter is framework-injected
    # (a facade), so hide it from FastMCP's tools/list schema too.
    try:
        injectable_names.update(get_service_view_parameter_names(original))
    except Exception:  # noqa: BLE001 - never block clean-signature on view introspection
        pass

    if not injectable_names:
        return None
    try:
        sig = inspect.signature(original)
    except (TypeError, ValueError):
        return None
    clean_params = [
        param
        for name, param in sig.parameters.items()
        if name not in injectable_names
    ]
    return sig.replace(parameters=clean_params)


def _describe_skipped_params(func: Callable, params: list[inspect.Parameter]) -> str:
    """Render each parameter with the reason it was passed over for injection.

    Used by the multi-parameter "none typed as McpMeshTool" diagnostic so
    the warning names every skipped parameter and WHY it was skipped
    (untyped vs annotated with a non-injectable type).

    Reasons are classified with the SAME type resolution the eligibility
    scan uses (``get_type_hints`` on the original function) — raw
    ``p.annotation`` values are strings under
    ``from __future__ import annotations`` and would misreport a perfectly
    valid ``db: "McpMeshTool"`` as the self-contradictory "annotated as
    McpMeshTool, not McpMeshTool". When the hints themselves cannot be
    resolved (TYPE_CHECKING-only imports, dangling forward references) —
    which is exactly the condition that made the eligibility scan fall back
    to "no eligible parameters" — the reason states that failure explicitly
    instead of misdiagnosing the annotation.
    """
    from typing import get_type_hints

    from .signature_analyzer import _get_original_func, _is_mesh_tool_type

    hints: Optional[dict[str, Any]] = None
    try:
        hints = get_type_hints(_get_original_func(func))
    except Exception:
        # Same failure the eligibility scan (``_scan_params``) swallowed —
        # report it as the skip reason below rather than guessing from raw
        # annotations.
        hints = None

    parts = []
    for p in params:
        if p.annotation is inspect.Parameter.empty:
            parts.append(f"'{p.name}' (untyped)")
        elif hints is None:
            parts.append(
                f"'{p.name}' (type hints could not be resolved — check "
                f"TYPE_CHECKING imports / forward references)"
            )
        else:
            resolved = hints.get(p.name)
            if resolved is None:
                parts.append(f"'{p.name}' (untyped)")
            elif _is_mesh_tool_type(resolved):
                # Defensive: eligibility uses this same resolution, so a
                # mesh-typed parameter cannot land in a skipped list — but
                # if a future skew ever puts one here, never emit the
                # contradictory "annotated as McpMeshTool, not McpMeshTool".
                parts.append(f"'{p.name}' (McpMeshTool)")
            else:
                ann_name = getattr(resolved, "__name__", None) or str(resolved)
                parts.append(
                    f"'{p.name}' (annotated as {ann_name}, not McpMeshTool)"
                )
    return ", ".join(parts)


def _format_selected_pairings(
    dependencies: list[str],
    eligible_positions: list[int],
    param_names: list[str],
) -> str:
    """Render the dep→param pairs positional pairing selects, in order.

    ``dependencies[i]`` pairs with ``eligible_positions[i]`` (declaration
    order); only the overlapping prefix is rendered. Out-of-range positions
    (signature-view skew) degrade to a ``<arg N>`` placeholder instead of
    raising — these strings feed diagnostics that must never crash dispatch.
    """
    pairs = []
    for i, (dep, pos) in enumerate(zip(dependencies, eligible_positions)):
        name = param_names[pos] if pos < len(param_names) else f"<arg {pos}>"
        pairs.append(f"dependencies[{i}] '{dep}' → parameter '{name}'")
    return ", ".join(pairs) if pairs else "nothing (no dependencies declared)"


def _format_unfilled_slots_message(
    func_label: str,
    eligible_positions: list[int],
    dependencies: list[str],
    param_names: list[str],
    tp: str = "",
    unfilled_param_names: Optional[list[str]] = None,
) -> str:
    """Build the "more eligible slots than dependencies" diagnostic text.

    Shared by the runtime warning in :func:`_prepare_injection_kwargs` and
    the strict-mode decoration-time promotion in
    :func:`analyze_injection_strategy`, so warn-mode and strict-mode users
    read the exact same prescriptive message.

    ``unfilled_param_names`` lets the call-time site pass the
    genuinely-unfilled slots (after caller-supplied kwargs are accounted
    for); when omitted, every eligible position beyond the declared
    dependencies is reported (the decoration-time view, where no call
    kwargs exist yet).
    """
    if unfilled_param_names is None:
        untouched_positions = eligible_positions[len(dependencies):]
        unfilled_param_names = [
            param_names[pos] if pos < len(param_names) else f"<arg {pos}>"
            for pos in untouched_positions
        ]
    selected = _format_selected_pairings(dependencies, eligible_positions, param_names)
    param_word = "Parameter" if len(unfilled_param_names) == 1 else "Parameters"
    return (
        f"{tp}⚠️ Function '{func_label}' has "
        f"{pluralize(len(eligible_positions), 'injection-eligible parameter')} "
        f"(McpMeshTool/MeshJob) but only "
        f"{pluralize(len(dependencies), 'dependency', 'dependencies')} "
        f"declared. Positional pairing "
        f"(declaration order) selected: {selected}. {param_word} "
        f"{unfilled_param_names} will remain None. Fix: add one entry per "
        f"unfilled parameter to dependencies=[...] (order matters — "
        f"dependencies[i] pairs with the i-th McpMeshTool/MeshJob parameter; "
        f"parameter names are never matched), or remove the "
        f"McpMeshTool/MeshJob annotation from parameters that should not be "
        f"injected."
    )


def analyze_injection_strategy(func: Callable, dependencies: list[str]) -> list[int]:
    """
    Analyze function signature and determine McpMeshTool injection positions.

    Rules:
    1. Single parameter: inject regardless of typing (with warning if not McpMeshTool)
    2. Multiple parameters: only inject into McpMeshTool typed parameters
    3. Log prescriptive warnings for mismatches and edge cases; under
       MCP_MESH_STRICT_DI the ambiguity/skip class of those warnings is
       raised as :class:`StrictDIError` at decoration time instead
       (informational warnings never raise; the only call-time strict
       raise is the wrapper-rewrite bounds guard, which is not statically
       detectable). Injection semantics are identical in both modes.

    Returns ONLY ``McpMeshTool`` positions — ``MeshJob`` positions are
    computed independently in :func:`_prepare_injection_kwargs` so the
    diagnostic warnings below stay scoped to the proxy-injection path.

    Args:
        func: Function to analyze
        dependencies: List of dependency names to inject

    Returns:
        List of McpMeshTool parameter positions to inject into
    """
    # Consistent view (#1162 MED-1): ``mesh_positions`` (and the MeshJob
    # analysis below) index the ORIGINAL function's parameter space —
    # ``get_mesh_agent_positions`` peels back to it via
    # ``_get_original_func`` (follows ``__wrapped__``). The param count
    # MUST come from that SAME view: positions and the param list they
    # index have to move together. Decorators like ``@mesh.a2a_consumer``
    # rewrite the wrapper's ``__signature__`` to hide framework-bound
    # params (e.g. ``_a2a``), so ``inspect.signature(func)`` can be
    # SHORTER than the position space. Pre-fix, mixing the two views
    # injected into the WRONG slot — ``(_a2a, db: McpMeshTool, y)``:
    # original-space position 1 indexed the wrapper param list
    # ``['db', 'y']`` and landed the proxy in ``y`` — or raised
    # IndexError outright (``(_a2a, job: MeshJob)``: position 1 against
    # a 1-param wrapper view).
    from .signature_analyzer import _get_original_func

    try:
        sig = inspect.signature(_get_original_func(func))
    except (TypeError, ValueError):
        sig = inspect.signature(func)
    params = list(sig.parameters.values())
    param_count = len(params)
    mesh_positions = get_mesh_agent_positions(func)
    func_name = f"{func.__module__}.{func.__qualname__}"

    # Detect ``__signature__``-hidden params structurally (count comparison
    # only — dependency binding stays strictly positional, never by name).
    # A wrapper that advertises FEWER params than the original is hiding a
    # framework-bound slot (e.g. the a2a_consumer ``_a2a`` client); the
    # untyped single-parameter heuristic must not target such a slot.
    try:
        visible_count = len(inspect.signature(func).parameters)
    except (TypeError, ValueError):
        visible_count = param_count
    has_hidden_params = visible_count < param_count

    # Detect whether the function declares any MeshJob param. The unified
    # positional injection path handles those alongside McpMeshTool slots,
    # so this function's diagnostics must NOT shout about "no injection
    # target" when a MeshJob slot will consume the dependency. The index
    # (not just presence) is kept so diagnostics can name the dep→param
    # pairings positional pairing selects.
    has_mesh_job_param = False
    mesh_job_index: Optional[int] = None
    try:
        from .signature_analyzer import analyze_mesh_job_signature

        _mj = analyze_mesh_job_signature(func)
        has_mesh_job_param = _mj.mesh_job_param_name is not None
        mesh_job_index = _mj.mesh_job_param_index
    except (TypeError, AttributeError):
        # Only narrow signature-introspection errors swallow silently;
        # ValueError (Phase-1 multiple-MeshJob contract violation) MUST
        # propagate per the resolver contract.
        pass

    # RFC #1280: @mesh.service consumer-view parameters are a NEW type-detected
    # slot kind (a facade), NOT positional McpMeshTool targets. Exclude them so
    # the untyped single-parameter heuristic never mistakes a lone view param
    # for an injection target and so the "no McpMeshTool params" diagnostics
    # aren't skewed. Injection into view slots is handled separately in the
    # facade block of ``_prepare_injection_kwargs``.
    view_positions: set[int] = set()
    try:
        from .signature_analyzer import get_service_view_positions

        view_positions = set(get_service_view_positions(func))
    except Exception:  # noqa: BLE001
        pass

    # Strict-mode decoration-time promotion of the "eligible slots will
    # remain None" diagnostic, checked UP FRONT so every branch below —
    # including the early returns for single-MeshJob-param and
    # MeshJob-only multi-param functions — is covered. Counts TYPED
    # eligible slots only (McpMeshTool + MeshJob); the untyped
    # single-parameter heuristic slot is deliberately excluded so a plain
    # zero-dependency tool like 'def greet(name)' never trips strict mode.
    # Permissive mode keeps the existing per-call warning cadence in
    # ``_prepare_injection_kwargs`` (with caller-supplied kwargs accounted
    # for), so this site raises directly instead of using warn_or_raise —
    # it must stay silent when strict is off.
    if is_strict_di_enabled():
        typed_eligible_positions = sorted(
            set(mesh_positions)
            | ({mesh_job_index} if mesh_job_index is not None else set())
        )
        if len(dependencies) < len(typed_eligible_positions):
            raise StrictDIError(
                _format_unfilled_slots_message(
                    func_name,
                    typed_eligible_positions,
                    dependencies,
                    [p.name for p in params],
                )
            )

    # No parameters at all — every declared dependency is skipped.
    # Ambiguity/skip class: raises under MCP_MESH_STRICT_DI.
    if param_count == 0:
        if dependencies:
            warn_or_raise(
                logger,
                f"Function '{func_name}' has no parameters but "
                f"{pluralize(len(dependencies), 'dependency', 'dependencies')} "
                f"declared {dependencies} — there is no parameter to "
                f"receive a proxy, so all declared dependencies are skipped. "
                f"Positional pairing assigns dependencies[i] to the i-th "
                f"McpMeshTool-typed parameter in declaration order (parameter "
                f"names are never matched). Fix: declare one parameter per "
                f"dependency, e.g. 'dep_0: McpMeshTool = None'.",
            )
        return []

    # Single parameter rule: inject regardless of typing. Only applies when
    # no params are hidden — a hidden single param is framework-bound by the
    # hiding decorator itself, never an injection target — and when the lone
    # param is not a @mesh.service view (RFC #1280: views are facade slots,
    # never untyped single-parameter injection targets).
    if param_count == 1 and not has_hidden_params and not view_positions:
        if not mesh_positions:
            if has_mesh_job_param:
                # The single parameter is a MeshJob — the unified injection
                # path constructs a MeshJobSubmitter for it. No McpMeshTool
                # position to record here.
                return []

            # Informational only — injection still happens, so this stays a
            # plain warning even under MCP_MESH_STRICT_DI.
            param_name = params[0].name
            logger.warning(
                f"Single parameter '{param_name}' in function '{func_name}' found, "
                f"injecting {dependencies[0] if dependencies else 'dependency'} proxy "
                f"(consider typing as McpMeshTool for clarity: "
                f"'{param_name}: McpMeshTool = None')"
            )
        return [0]  # Inject into the single parameter

    # Multiple parameters rule: only inject into McpMeshTool typed
    # parameters. Functions with hidden params route here too (even at
    # param_count == 1) so the typed-only rule governs them.
    if param_count > 1 or has_hidden_params:
        if not mesh_positions:
            if dependencies and not has_mesh_job_param:
                # Ambiguity/skip class: every declared dependency is
                # dropped because no parameter is annotation-eligible.
                # Raises under MCP_MESH_STRICT_DI.
                example_param = next(
                    (
                        p.name
                        for p in params
                        if p.annotation is inspect.Parameter.empty
                    ),
                    params[0].name,
                )
                warn_or_raise(
                    logger,
                    f"⚠️ Function '{func_name}' has "
                    f"{pluralize(param_count, 'parameter')} but none are "
                    f"typed as McpMeshTool. Skipping injection of "
                    f"{pluralize(len(dependencies), 'dependency', 'dependencies')} "
                    f"{dependencies}. Skipped parameters: "
                    f"{_describe_skipped_params(func, params)}. Positional pairing assigns "
                    f"dependencies[i] to the i-th McpMeshTool-typed parameter in "
                    f"declaration order — '{dependencies[0]}' would go to the first "
                    f"McpMeshTool-typed parameter (parameter names are never matched). "
                    f"Fix: annotate the intended parameter(s), e.g. "
                    f"'{example_param}: McpMeshTool = None'.",
                )
            return []

        # Check for excess-dependency mismatch. Eligible slots =
        # McpMeshTool + MeshJob positions taken together, so MeshJob slots
        # don't trigger spurious "excess dependencies" warnings.
        # NOTE: the inverse case (more eligible slots than dependencies) is
        # diagnosed at injection time inside ``_prepare_injection_kwargs``
        # in permissive mode; under MCP_MESH_STRICT_DI it already raised at
        # the up-front decoration-time check above.
        param_names = [p.name for p in params]
        eligible_positions = sorted(
            set(mesh_positions)
            | ({mesh_job_index} if mesh_job_index is not None else set())
        )
        eligible_count = len(eligible_positions)
        if len(dependencies) > eligible_count:
            # Ambiguity/skip class: trailing dependencies are dropped.
            # Raises under MCP_MESH_STRICT_DI.
            excess_deps = dependencies[eligible_count:]
            selected = _format_selected_pairings(
                dependencies, eligible_positions, param_names
            )
            warn_or_raise(
                logger,
                f"Function '{func_name}' has "
                f"{pluralize(len(dependencies), 'dependency', 'dependencies')} "
                f"but only {pluralize(eligible_count, 'injectable parameter')} "
                f"(McpMeshTool + MeshJob). Positional pairing (declaration "
                f"order) selected: {selected}. Dependencies {excess_deps} will "
                f"not be injected — no injectable parameter remains for them. "
                f"Fix: declare one McpMeshTool-typed parameter per excess "
                f"dependency, e.g. 'extra_dep: McpMeshTool = None', or remove "
                f"the excess entries from dependencies=[...].",
            )

        # Return McpMeshTool positions we can actually inject into. The
        # MeshJob slot's index in ``dependencies`` is computed positionally
        # at injection time by :func:`_prepare_injection_kwargs`.
        return mesh_positions[: len(dependencies)]

    return mesh_positions


def _prepare_injection_kwargs(
    func: Callable,
    kwargs: dict,
    mesh_positions: list[int],
    dependencies: list[str],
    injected_deps_array: list,
    get_dependency_fn: Callable[[str], Any | None],
    log: logging.Logger,
    view_slots: Optional[list] = None,
) -> tuple[dict, int]:
    """Prepare kwargs with injected dependencies and LLM agent.

    Unified positional injection — ``McpMeshTool`` and ``MeshJob`` params
    share a single ``dep_index`` namespace in declaration order. Each
    ``dependencies[i]`` strictly pairs with ONE parameter position; the
    slot's type (proxy vs submitter) determines what gets constructed.
    Unresolved deps leave their slot ``None`` — positions never shift.

    The ``mesh_positions`` argument carries the McpMeshTool positions
    pre-computed by :func:`analyze_injection_strategy` (used for cache
    indexing into ``injected_deps_array``); the MeshJob positions are
    re-derived here from the live signature.

    Args:
        func: The original function being wrapped
        kwargs: Caller-supplied keyword arguments
        mesh_positions: McpMeshTool parameter positions (from analyze step)
        dependencies: Dependency capability names declared on the function
        injected_deps_array: Wrapper's mutable array of cached proxy instances
        get_dependency_fn: Fallback lookup for proxies not in the array
        log: Logger instance for debug output

    Returns:
        Tuple of (final_kwargs dict ready for invocation, injected_count)
    """
    tp = get_trace_prefix()

    # Log tool invocation
    arg_keys = list(kwargs.keys()) if kwargs else []
    log.debug(f"{tp}🔧 Tool '{func.__name__}' called with kwargs={arg_keys}")
    log.debug(f"{tp}🔧 Tool '{func.__name__}' args: {format_log_value(kwargs)}")

    # Build final kwargs with injected dependencies.
    #
    # Consistent view (#1162 MED-1): every position used below —
    # ``mesh_positions`` (from :func:`get_mesh_agent_positions`) and the
    # MeshJob index (from :func:`analyze_mesh_job_signature`) — indexes the
    # ORIGINAL function's parameter space (both follow ``__wrapped__`` via
    # ``_get_original_func``). The param-name list MUST come from that SAME
    # view: decorators like ``@mesh.a2a_consumer`` rewrite the wrapper's
    # ``__signature__`` to hide framework-bound params (e.g. ``_a2a``), so
    # ``inspect.signature(func)`` can be SHORTER — indexing it with an
    # original-derived position raised IndexError or silently injected into
    # the WRONG parameter. The resulting kwargs are keyed by ORIGINAL param
    # names, which is correct because hiding wrappers (a2a_consumer bridge,
    # @mesh.llm wrappers) forward ``**kwargs`` verbatim to the original.
    from .signature_analyzer import _get_original_func

    try:
        sig = inspect.signature(_get_original_func(func))
    except (TypeError, ValueError):
        sig = inspect.signature(func)
    params = list(sig.parameters.keys())
    final_kwargs = kwargs.copy()

    # Build the unified eligible-positions list from the live signature.
    # Order is declaration order; the set is used inside the loop to
    # branch between proxy- and submitter-construction.
    mesh_job_positions: set[int] = set()
    try:
        from .signature_analyzer import analyze_mesh_job_signature

        sig_target = getattr(func, "_mesh_original_func", func)
        _mj_resolution = analyze_mesh_job_signature(sig_target)
        if _mj_resolution.mesh_job_param_index is not None:
            mesh_job_positions.add(_mj_resolution.mesh_job_param_index)
    except (TypeError, AttributeError) as e:
        # Only narrow signature-introspection errors swallow silently;
        # ValueError (Phase-1 multiple-MeshJob contract violation) MUST
        # propagate per the resolver contract.
        log.debug(f"{tp}MeshJob analysis skipped for {func.__name__}: {e}")

    eligible_positions = sorted(set(mesh_positions) | mesh_job_positions)

    # Diagnostic: more eligible (McpMeshTool + MeshJob) slots than declared
    # dependencies — the trailing slots will silently stay None. Flagging
    # here (at injection time) covers cases the strategy-time warning at
    # ``analyze_injection_strategy`` can't see (paths that bypass the
    # multi-parameter branch). A slot the CALLER filled is not unfilled:
    # the documented contract lets callers pass a fake/mock for any
    # injectable slot (see the explicit-kwarg skip in the loop below), so
    # the diagnostic only reports slots that genuinely remain None after
    # accounting for caller-supplied kwargs. This is a permissive-mode
    # warning ONLY — every statically-detectable unfilled configuration
    # already raised at decoration time under MCP_MESH_STRICT_DI, and the
    # sole call-time strict raise is the bounds guard below (the one
    # condition not detectable at decoration).
    if len(eligible_positions) > len(dependencies):
        unfilled_message = None
        try:
            # ``params`` above is resolved from the same original signature
            # the positions came from (#1105), so positions line up — and
            # the message builder bounds-guards regardless.
            genuinely_unfilled = [
                params[pos] if pos < len(params) else f"<arg {pos}>"
                for pos in eligible_positions[len(dependencies):]
                if not (
                    pos < len(params)
                    and params[pos] in final_kwargs
                    and final_kwargs.get(params[pos]) is not None
                )
            ]
            if genuinely_unfilled:
                unfilled_message = _format_unfilled_slots_message(
                    func.__name__,
                    eligible_positions,
                    dependencies,
                    params,
                    tp=tp,
                    unfilled_param_names=genuinely_unfilled,
                )
        except (TypeError, ValueError, IndexError) as e:
            # The message construction must never crash dispatch regardless
            # of wrapper/original signature shape.
            log.debug(
                f"{tp}untouched-positional diagnostic skipped for "
                f"{func.__name__}: {e}"
            )
        if unfilled_message is not None:
            log.warning(unfilled_message)

    injected_count = 0
    injected_deps: list[str] = []

    # MeshJobSubmitter construction needs the registry URL + agent_id;
    # resolve lazily on first MeshJob slot so non-job tools pay nothing.
    _submitter_ctx: Optional[tuple[Optional[str], str]] = None

    def _resolve_submitter_ctx() -> tuple[Optional[str], str]:
        nonlocal _submitter_ctx
        if _submitter_ctx is not None:
            return _submitter_ctx
        import os as _os

        from .decorator_registry import DecoratorRegistry

        registry_url = _os.environ.get("MCP_MESH_REGISTRY_URL")
        instance_id = "unknown"
        try:
            cfg = DecoratorRegistry.get_resolved_agent_config()
            if isinstance(cfg, dict):
                candidate = cfg.get("agent_id")
                if candidate:
                    instance_id = candidate
        except Exception as exc:
            log.debug(
                f"{tp}MeshJob: DecoratorRegistry agent_id lookup failed "
                f"({exc}); using 'unknown'"
            )
        _submitter_ctx = (registry_url, instance_id)
        return _submitter_ctx

    for dep_index, position in enumerate(eligible_positions):
        if dep_index >= len(dependencies):
            break

        dep_name = dependencies[dep_index]

        # Defensive bounds guard (#1171): positions are derived from the
        # same original signature as ``params`` above, so this should never
        # trigger — but a decorator chain we don't model could still skew
        # the views. Skip this one injection rather than crash dispatch;
        # remaining deps keep their own positional slots. Ambiguity/skip
        # class: raises under MCP_MESH_STRICT_DI (this condition is only
        # detectable at call time, so strict promotes it here).
        if position >= len(params):
            warn_or_raise(
                log,
                f"{tp}⚠️ Injection position {position} for dependency "
                f"'{dep_name}' (dep_index={dep_index}) on '{func.__name__}' "
                f"is out of bounds for its {len(params)}-parameter signature "
                f"{params}. Positional pairing (declaration order) selected "
                f"position {position}, but the resolved signature ends at "
                f"index {len(params) - 1} — dependency '{dep_name}' is "
                f"skipped and its parameter stays unset. Fix: ensure any "
                f"decorator that rewrites __signature__ also sets "
                f"__wrapped__ (use functools.wraps) so injection positions "
                f"and parameter names resolve from the same "
                f"original-function view.",
            )
            continue

        param_name = params[position]

        # Skip if user explicitly passed a value — preserves the
        # test-friendly contract that callers can supply a fake/mock for
        # either a proxy or a submitter slot.
        if param_name in final_kwargs and final_kwargs.get(param_name) is not None:
            continue

        if position in mesh_job_positions:
            # MeshJob slot — construct a MeshJobSubmitter for the
            # capability at this dep_index. Param NAME does not matter;
            # the binding is positional.
            registry_url, instance_id = _resolve_submitter_ctx()
            if registry_url:
                from .mesh_job_submitter import MeshJobSubmitter

                submitter = MeshJobSubmitter(
                    capability=dep_name,
                    submitted_by=instance_id,
                    registry_url=registry_url,
                )
                final_kwargs[param_name] = submitter
                injected_count += 1
                injected_deps.append(f"{dep_name} → MeshJobSubmitter")
                log.debug(
                    f"{tp}📨 MESH_JOB_INJECTION: Injected MeshJobSubmitter "
                    f"for capability={dep_name!r} into param={param_name!r}"
                )
            else:
                # This branch knows only two facts: the MeshJob slot was
                # matched to the declared dependency dep_name, and no
                # registry URL is available to build a submitter — so the
                # param is left None silently (#1231). It does NOT verify
                # provider/capability resolution, so the message must not
                # claim it did. Route through warn_or_raise so the diagnostic
                # rides MCP_MESH_STRICT_DI and the text can't drift.
                warn_or_raise(
                    log,
                    f"{tp}⚠️ MeshJob parameter {param_name!r} on "
                    f"'{func.__name__}' was matched to dependency "
                    f"{dep_name!r}, but no MeshJobSubmitter could be injected "
                    f"because MCP_MESH_REGISTRY_URL is not set; the parameter "
                    f"stays None. Fix: set MCP_MESH_REGISTRY_URL so the "
                    f"submitter for dependency {dep_name!r} can be built.",
                )
                # Set the slot explicitly to None so the user function's
                # call signature is satisfied even when the MeshJob param
                # has no default. Mirrors the McpMeshTool branch's behavior
                # of always assigning into final_kwargs.
                final_kwargs[param_name] = None
        else:
            # McpMeshTool slot — use the cached proxy / get_dependency_fn
            # fallback. The dep_index lines up with the wrapper's
            # injected_deps_array slot allocated at decoration time.
            dependency = None
            if dep_index < len(injected_deps_array):
                dependency = injected_deps_array[dep_index]
            if dependency is None:
                dep_key = f"{func.__module__}.{func.__qualname__}:dep_{dep_index}"
                dependency = get_dependency_fn(dep_key)

            final_kwargs[param_name] = dependency
            injected_count += 1
            proxy_type = type(dependency).__name__ if dependency else "None"
            injected_deps.append(f"{dep_name} → {proxy_type}")

    if injected_count > 0:
        log.debug(
            f"{tp}🔧 Injected {injected_count} dependencies: {', '.join(injected_deps)}"
        )

    # Inject LLM agent if the function has @mesh.llm metadata
    if hasattr(func, "_mesh_llm_param_name"):
        llm_param = func._mesh_llm_param_name
        if llm_param not in final_kwargs or final_kwargs.get(llm_param) is None:
            llm_agent = getattr(func, "_mesh_llm_agent", None)
            final_kwargs[llm_param] = llm_agent
            log.debug(f"{tp}🤖 LLM_INJECTION: Injected {llm_param}={llm_agent}")

    # RFC #1280: inject a facade for each @mesh.service consumer-view parameter.
    # Additive slot kind — the view-method deps live in ``injected_deps_array``
    # at the appended indices recorded on each view slot, read by the facade at
    # CALL time so rebinding via update_dependency is picked up transparently.
    # A caller-supplied non-None value (mock contract) is left untouched.
    if view_slots:
        func_id = f"{func.__module__}.{func.__qualname__}"
        for v in view_slots:
            pname = v["param_name"]
            if pname in final_kwargs and final_kwargs.get(pname) is not None:
                continue
            from .service_view import MeshServiceFacade

            final_kwargs[pname] = MeshServiceFacade(
                view_name=v["view_name"],
                min_available=v["min_available"],
                methods=v["methods"],
                func_id=func_id,
                injected_deps_array=injected_deps_array,
                get_dependency_fn=get_dependency_fn,
            )
            injected_count += 1
            log.debug(
                f"{tp}🧩 VIEW_INJECTION: Injected facade for view "
                f"{v['view_name']!r} into param {pname!r} "
                f"({len(v['methods'])} method edge(s))"
            )

    return final_kwargs, injected_count


def _first_unavailable_required(
    func_id: str,
    route_required_caps: list[Optional[str]],
    injected_deps_array: list,
    get_dependency_fn: Callable[[str], Any | None],
    kwargs: Optional[dict] = None,
    settle_params: Optional[list] = None,
) -> Optional[str]:
    """Return the capability of the first unavailable required route dep.

    Issue #1249 perimeter check. For each dependency slot flagged required
    (``route_required_caps[i]`` is the capability name, else ``None``),
    resolve the proxy the same way the injection path does — the wrapper's
    cached ``injected_deps_array[i]`` first, then the injector's composite-key
    fallback. A ``None`` proxy means the (transitively) required capability is
    unavailable AT CALL TIME; return its name so the caller can emit a 503.
    Returns ``None`` when every required dep has a live proxy.

    Honors the documented mock contract (mirrors
    ``_prepare_injection_kwargs`` line ~878 and the settle skip): a slot the
    CALLER supplied a non-None value for via ``kwargs`` — keyed by the
    parameter NAME in ``settle_params[dep_index]`` — counts as available and
    is skipped, so a route invoked with an explicit fake for a required dep
    runs the handler even while the mesh proxy is unresolved.

    Runs AFTER the settle grace (the caller waits first), so a still-settling
    dep is given its full window before being judged unavailable.
    """
    for dep_index, cap in enumerate(route_required_caps):
        if cap is None:
            continue
        # Caller-supplied fake for this slot (mock contract) → available.
        if kwargs and settle_params and dep_index < len(settle_params):
            param_name = settle_params[dep_index]
            if (
                param_name is not None
                and param_name in kwargs
                and kwargs.get(param_name) is not None
            ):
                continue
        resolved = None
        if dep_index < len(injected_deps_array):
            resolved = injected_deps_array[dep_index]
        if resolved is None:
            resolved = get_dependency_fn(f"{func_id}:dep_{dep_index}")
        if resolved is None:
            return cap
    return None


def _log_wrapper_result(func: Callable, result: Any, log: logging.Logger) -> None:
    """Log the result of a dependency-injected function call."""
    tp = get_trace_prefix()
    log.debug(
        f"{tp}🔧 Tool '{func.__name__}' returned: {format_result_summary(result)}"
    )
    log.debug(f"{tp}🔧 Tool '{func.__name__}' result: {format_log_value(result)}")


class DependencyInjector:
    """
    Manages dynamic dependency injection for mesh agents.

    This class:
    1. Maintains a registry of available dependencies (McpMeshTool)
    2. Coordinates with MeshLlmAgentInjector for LLM agent injection
    3. Tracks which functions depend on which services
    4. Updates function bindings when topology changes
    5. Handles graceful degradation when dependencies unavailable
    """

    def __init__(self):
        self._dependencies: dict[str, Any] = {}
        self._function_registry: weakref.WeakValueDictionary = (
            weakref.WeakValueDictionary()
        )
        self._dependency_mapping: dict[str, set[str]] = (
            {}
        )  # dep_name -> set of function_ids
        self._lock = asyncio.Lock()

        # LLM agent injector for MeshLlmAgent parameters
        from .mesh_llm_agent_injector import get_global_llm_injector

        self._llm_injector = get_global_llm_injector()
        logger.debug("🤖 DependencyInjector initialized with MeshLlmAgentInjector")

    def iter_dependency_keys(self) -> Iterable[str]:
        """Iterate over all currently-registered dependency keys.

        Each key has the shape ``"<module>.<qualname>:dep_<N>"`` where
        ``<module>`` is the fully-qualified module path the @mesh.tool
        decorator observed when the dependency was registered.

        Used by startup-time consistency checks (e.g.
        :class:`DualModuleCheckStep`) that need to inspect registrations
        across all modules. Public so callers don't depend on the private
        storage layout of the injector.

        The returned view reflects live mutations to the underlying mapping —
        callers that need a stable snapshot (e.g., for iteration that may
        overlap with register_dependency / unregister_dependency calls) should
        materialize via list(...) or tuple(...) explicitly.
        """
        return self._dependency_mapping.keys()

    async def register_dependency(self, name: str, instance: Any) -> None:
        """Register a new dependency or update existing one.

        Args:
            name: Composite key in format "function_id:dep_N" or legacy capability name
            instance: Proxy instance to register
        """
        async with self._lock:
            logger.debug(f"📦 Registering dependency: {name}")
            self._dependencies[name] = instance

            # Notify all functions that depend on this (using composite keys)
            if name in self._dependency_mapping:
                for func_id in self._dependency_mapping[name]:
                    if func_id in self._function_registry:
                        func = self._function_registry[func_id]
                        logger.debug(
                            f"🔄 UPDATING dependency '{name}' for {func_id} -> {func} at {hex(id(func))}"
                        )
                        if hasattr(func, "_mesh_update_dependency"):
                            # Extract dep_index from composite key (format: "function_id:dep_N")
                            if ":dep_" in name:
                                dep_index_str = name.split(":dep_")[-1]
                                try:
                                    dep_index = int(dep_index_str)
                                    func._mesh_update_dependency(dep_index, instance)
                                except ValueError:
                                    logger.warning(
                                        f"⚠️ Invalid dep_index in key '{name}', skipping update"
                                    )
                            else:
                                # Legacy format (shouldn't happen with new code)
                                logger.warning(
                                    f"⚠️ Legacy dependency key format '{name}' not supported in array-based injection"
                                )

    async def unregister_dependency(self, name: str) -> None:
        """Remove a dependency (e.g., service went down).

        Args:
            name: Composite key in format "function_id:dep_N" or legacy capability name
        """
        async with self._lock:
            logger.info(f"🗑️ INJECTOR: Unregistering dependency: {name}")
            if name in self._dependencies:
                del self._dependencies[name]
                logger.info(f"🗑️ INJECTOR: Removed {name} from dependencies registry")

                # Notify all functions that depend on this
                if name in self._dependency_mapping:
                    affected_functions = self._dependency_mapping[name]
                    logger.info(
                        f"🗑️ INJECTOR: Updating {len(affected_functions)} functions affected by {name} removal"
                    )

                    for func_id in affected_functions:
                        if func_id in self._function_registry:
                            func = self._function_registry[func_id]
                            if hasattr(func, "_mesh_update_dependency"):
                                logger.info(
                                    f"🗑️ INJECTOR: Removing {name} from function {func_id}"
                                )
                                # Extract dep_index from composite key
                                if ":dep_" in name:
                                    dep_index_str = name.split(":dep_")[-1]
                                    try:
                                        dep_index = int(dep_index_str)
                                        func._mesh_update_dependency(dep_index, None)
                                    except ValueError:
                                        logger.warning(
                                            f"⚠️ Invalid dep_index in key '{name}', skipping removal"
                                        )
                                else:
                                    # Legacy format
                                    logger.warning(
                                        f"⚠️ Legacy dependency key format '{name}' not supported in array-based injection"
                                    )
                            else:
                                logger.warning(
                                    f"🗑️ INJECTOR: Function {func_id} has no _mesh_update_dependency method"
                                )
                        else:
                            logger.warning(
                                f"🗑️ INJECTOR: Function {func_id} not found in registry"
                            )
                else:
                    logger.info(f"🗑️ INJECTOR: No functions mapped to dependency {name}")
            else:
                logger.info(f"🗑️ INJECTOR: Dependency {name} was not registered (no-op)")

    def get_dependency(self, name: str) -> Any | None:
        """Get current instance of a dependency."""
        return self._dependencies.get(name)

    def find_original_function(self, function_name: str) -> Any | None:
        """Find the original function by name from wrapper registry or decorator registry.

        This is used for self-dependency proxy creation to get the cached
        original function reference for direct calls.

        Args:
            function_name: Name of the function to find

        Returns:
            Original function if found, None otherwise
        """
        logger.debug(f"🔍 Searching for original function: '{function_name}'")

        # First, search through wrapper registry (functions with dependencies)
        for func_id, wrapper_func in self._function_registry.items():
            if hasattr(wrapper_func, "_mesh_original_func"):
                original = wrapper_func._mesh_original_func

                # Match by function name
                if hasattr(original, "__name__") and original.__name__ == function_name:
                    logger.debug(
                        f"✅ Found original function '{function_name}' in wrapper registry: {func_id}"
                    )
                    return original

        # If not found in wrapper registry, search in decorator registry (all functions)
        try:
            from .decorator_registry import DecoratorRegistry

            # Search through mesh tools (functions decorated with @mesh.tool)
            mesh_tools = DecoratorRegistry.get_mesh_tools()
            for tool_name, decorated_func in mesh_tools.items():
                original_func = decorated_func.function  # Get the original function
                if (
                    hasattr(original_func, "__name__")
                    and original_func.__name__ == function_name
                ):
                    logger.debug(
                        f"✅ Found original function '{function_name}' in decorator registry: {tool_name}"
                    )
                    return original_func

        except Exception as e:
            logger.warning(f"⚠️ Error searching decorator registry: {e}")

        # List available functions for debugging
        available_functions = []
        for wrapper_func in self._function_registry.values():
            if hasattr(wrapper_func, "_mesh_original_func"):
                original = wrapper_func._mesh_original_func
                if hasattr(original, "__name__"):
                    available_functions.append(original.__name__)

        # Also list functions from decorator registry
        try:
            from .decorator_registry import DecoratorRegistry

            mesh_tools = DecoratorRegistry.get_mesh_tools()
            for tool_name, decorated_func in mesh_tools.items():
                if hasattr(decorated_func.function, "__name__"):
                    available_functions.append(decorated_func.function.__name__)
        except (AttributeError, KeyError, TypeError):
            pass

        logger.warning(
            f"❌ Original function '{function_name}' not found. "
            f"Available functions: {list(set(available_functions))}"
        )
        return None

    def process_llm_tools(self, llm_tools: dict[str, list[dict[str, Any]]]) -> None:
        """
        Process llm_tools from registry response and delegate to MeshLlmAgentInjector.

        Args:
            llm_tools: Dict mapping function_id -> list of tool metadata
                      Format: {"function_id": [{"function_name": "...", "endpoint": {...}, ...}]}
        """
        logger.info(
            f"🤖 DependencyInjector processing llm_tools for {len(llm_tools)} functions"
        )
        self._llm_injector.process_llm_tools(llm_tools)

    def process_llm_providers(self, llm_providers: dict[str, dict[str, Any]]) -> None:
        """
        Process llm_providers from registry response and delegate to MeshLlmAgentInjector (v0.6.1).

        Args:
            llm_providers: Dict mapping function_name -> ResolvedLLMProvider
                          Format: {"function_name": {"agent_id": "...", "endpoint": "...", ...}}
        """
        logger.info(
            f"🔌 DependencyInjector processing llm_providers for {len(llm_providers)} functions"
        )
        self._llm_injector.process_llm_providers(llm_providers)

    def update_llm_tools(self, llm_tools: dict[str, list[dict[str, Any]]]) -> None:
        """
        Update llm_tools when topology changes (heartbeat updates).

        Args:
            llm_tools: Updated llm_tools dict from registry
        """
        logger.info(
            f"🔄 DependencyInjector updating llm_tools for {len(llm_tools)} functions"
        )
        self._llm_injector.update_llm_tools(llm_tools)

    def create_llm_injection_wrapper(
        self, func: Callable, function_id: str
    ) -> Callable:
        """
        Create wrapper for function with MeshLlmAgent parameter.

        Delegates to MeshLlmAgentInjector.

        Args:
            func: Function to wrap
            function_id: Unique function ID from @mesh.llm decorator

        Returns:
            Wrapped function with MeshLlmAgent injection
        """
        logger.debug(f"🤖 Creating LLM injection wrapper for {function_id}")
        return self._llm_injector.create_injection_wrapper(func, function_id)

    def create_injection_wrapper(
        self,
        func: Callable,
        dependencies: list[str],
        route_required_caps: Optional[list[Optional[str]]] = None,
        tool_required_caps: Optional[list[Optional[str]]] = None,
        view_slots: Optional[list] = None,
    ) -> Callable:
        """
        Create in-place dependency injection by modifying the original function.

        This approach:
        1. Preserves the original function pointer for FastMCP
        2. Adds dynamic dependency injection capability
        3. Can be updated when topology changes
        4. Handles missing dependencies gracefully
        5. Logs warnings for configuration issues

        ``route_required_caps`` (issue #1249) is set ONLY by @mesh.route: an
        index-aligned list where each entry is the capability name if that
        dependency slot is ``required=True`` (perimeter 503), else ``None``.
        When any slot is required, the non-streaming DI wrapper returns HTTP
        503 (naming the capability) before invoking user code if that dep's
        proxy is unavailable at call time. @mesh.tool passes
        ``tool_required_caps`` instead — mesh-internal calls are chain-gated,
        not perimeter-gated, but a direct ``tools/call`` for a tool with a
        required dep is still refused (issue #1273).

        ``tool_required_caps`` (issue #1273) is the @mesh.tool analogue set by
        the tool decorator: an index-aligned list where each entry is the
        capability name if that dependency slot is ``required=True`` (else
        ``None``). When any slot is required, the tool DI wrapper REFUSES the
        direct ``tools/call`` dispatch — raising a ``dependency_unavailable``
        tool error (an ``isError`` result naming the capability, same semantic
        class as the route perimeter's 503) rather than invoking the handler
        with a null required proxy — if that dep is unresolved at call time.
        This closes the same DOWN→UP flap window #1268 closed on the claim
        path. Optional deps keep their None-passthrough.
        """
        func_id = f"{func.__module__}.{func.__qualname__}"

        # Normalize to a plain list so the closures below can test truthiness
        # cheaply; None (the @mesh.tool case) short-circuits the whole check.
        _route_required_caps: list[Optional[str]] = list(route_required_caps or [])
        _has_route_required = any(c is not None for c in _route_required_caps)
        # Issue #1273: @mesh.tool required-dep slots (index-aligned with
        # ``dependencies``). The MeshJob-paired slot is nulled out below once
        # ``mesh_job_index`` is known — its slot holds a locally-built
        # submitter, never a resolved proxy, so gating on it would refuse
        # every call (mirrors the claim dispatcher's mesh_job_dep_index skip).
        _tool_required_caps: list[Optional[str]] = list(tool_required_caps or [])

        # RFC #1280: ``dependencies`` is the FULL edge list — explicit deps
        # first, then each @mesh.service view's method edges (name-sorted)
        # appended AFTER. The positional McpMeshTool/MeshJob pairing concerns
        # ONLY the explicit prefix; view-method edges have no parameter of
        # their own (a facade fans them out). Everything else keyed by
        # dep_index (``_mesh_injected_deps`` sizing, the dependency mapping,
        # settle keys, update_dependency, the required-refusal caps) spans the
        # full list unchanged — so this is purely additive: a function with no
        # view slots computes exactly as before.
        _view_slots: list = list(view_slots or [])
        _n_view_methods = sum(len(v["methods"]) for v in _view_slots)
        _n_explicit = len(dependencies) - _n_view_methods

        # Use new smart injection strategy — over the EXPLICIT prefix only, so
        # the McpMeshTool positional pairing + diagnostics stay identical to
        # the pre-view behaviour (view edges never pair with a McpMeshTool
        # parameter).
        mesh_positions = analyze_injection_strategy(func, dependencies[:_n_explicit])

        # Track which dependencies this function needs (using composite keys)
        for dep_index, dep in enumerate(dependencies):
            dep_key = f"{func_id}:dep_{dep_index}"
            if dep_key not in self._dependency_mapping:
                self._dependency_mapping[dep_key] = set()
            self._dependency_mapping[dep_key].add(func_id)

        # Store current dependency values as array (indexed by position)
        if not hasattr(func, "_mesh_injected_deps"):
            func._mesh_injected_deps = [None] * len(dependencies)

        # Store original implementation if not already stored
        if not hasattr(func, "_mesh_original_func"):
            func._mesh_original_func = func

        # Create a wrapper function that handles dependency injection
        # Capture logger in local scope to avoid NameError
        wrapper_logger = logger

        is_stream = _is_stream_tool(func)

        # Phase 1 MeshJob substrate: detect if the function declares a
        # MeshJob param. If so, we must run the FULL DI path even when
        # ``mesh_positions`` is empty — otherwise ``_prepare_injection_kwargs``
        # never runs, the MeshJob auto-injection block never fires, and
        # consumer-side jobs silently lose their submitter (#bug 1).
        has_mesh_job_param = False
        mesh_job_index: Optional[int] = None
        try:
            from .signature_analyzer import analyze_mesh_job_signature

            _mj = analyze_mesh_job_signature(func)
            has_mesh_job_param = _mj.mesh_job_param_name is not None
            mesh_job_index = _mj.mesh_job_param_index
        except (TypeError, AttributeError):
            # Narrow catch: only swallow signature-introspection errors.
            # ValueError (multi-MeshJob contract violation per the Phase-1
            # resolver) MUST propagate so the wrapper fails fast.
            pass

        # Settling-window grace (#1193): composite keys for the proxy slots
        # this wrapper will inject, index-aligned with ``dependencies``.
        # ``None`` marks slots the grace does not cover: MeshJob submitter
        # slots (constructed locally, no resolution event) and excess
        # dependencies with no parameter to land in. ``settle_params``
        # carries the parameter NAME behind each slot so the call-time
        # pending collection can skip caller-supplied slots (the documented
        # mock contract). The declared set is registered with the
        # process-wide settle state so the agent-level "all declared deps
        # resolved" latch can flip eagerly — the FIRST registration anchors
        # the settle window.
        from .signature_analyzer import _get_original_func

        settle_eligible = sorted(
            set(mesh_positions)
            | ({mesh_job_index} if mesh_job_index is not None else set())
        )
        try:
            _settle_param_names = list(
                inspect.signature(_get_original_func(func)).parameters.keys()
            )
        except (TypeError, ValueError):
            _settle_param_names = []
        settle_keys: list[Optional[str]] = [None] * len(dependencies)
        settle_params: list[Optional[str]] = [None] * len(dependencies)
        for _i, _pos in enumerate(settle_eligible):
            if _i >= len(dependencies):
                break
            if _pos != mesh_job_index:
                settle_keys[_i] = f"{func_id}:dep_{_i}"
                if _pos < len(_settle_param_names):
                    settle_params[_i] = _settle_param_names[_pos]
        # RFC #1280: view-method edges are settle-covered too (item 2 + the
        # floor's settle-aware wait). Map each edge's settle_params entry to the
        # view's PARAMETER NAME so the documented mock contract works: a caller
        # that supplies a fake facade for the view param skips both the settle
        # wait and the required-edge pre-invoke refusal for ALL that view's
        # edges (mirrors the McpMeshTool per-slot mock skip).
        for _v in _view_slots:
            for _m in _v["methods"]:
                _di = _m["dep_index"]
                if 0 <= _di < len(dependencies):
                    settle_keys[_di] = f"{func_id}:dep_{_di}"
                    settle_params[_di] = _v["param_name"]
        _settle_state = get_settle_state()
        for _key in settle_keys:
            if _key is not None:
                _settle_state.register_declared(_key)

        # Issue #1273: exclude the MeshJob-paired dep slot from the tool
        # required-dep refusal. Its dep_index is the rank of the MeshJob
        # parameter position among the sorted eligible positions (same math
        # as the settle loop and the claim dispatcher's mesh_job_dep_index).
        # That slot injects a locally-built MeshJobSubmitter, never a resolved
        # proxy, so leaving it in would refuse every call.
        if mesh_job_index is not None and mesh_job_index in settle_eligible:
            _mj_dep_index = settle_eligible.index(mesh_job_index)
            if 0 <= _mj_dep_index < len(_tool_required_caps):
                _tool_required_caps[_mj_dep_index] = None
        _has_tool_required = any(c is not None for c in _tool_required_caps)

        # If no mesh positions to inject AND no MeshJob slot AND no service-view
        # slot, fall back to the minimal tracking wrapper. With a MeshJob slot
        # or a @mesh.service view we route to the full path so the auto-injection
        # / facade blocks in ``_prepare_injection_kwargs`` can fire.
        if not mesh_positions and not has_mesh_job_param and not _view_slots:
            logger.debug(
                f"🔧 No injection positions for {func.__name__}, creating minimal wrapper for tracking"
            )

            # Issue #1249: a @mesh.route declared required deps but the handler
            # has no injectable (McpMeshTool) slot to receive a proxy — the
            # perimeter check has nothing to evaluate and is SILENTLY inactive.
            # This is almost always a mis-annotation (the dep param isn't typed
            # McpMeshTool). Fail loud so the route isn't left thinking it's
            # protected. Enforcement stays off (positional injection contract is
            # unchanged) — the signal is the fix.
            if _has_route_required:
                _req_caps = [c for c in _route_required_caps if c is not None]
                logger.warning(
                    f"⚠️ Route '{func.__name__}': required perimeter INACTIVE — "
                    f"declared required {_req_caps} but the handler has no "
                    f"injectable McpMeshTool parameter to receive them, so the "
                    f"503 perimeter cannot evaluate and is skipped. Fix: annotate "
                    f"the intended parameter(s) as McpMeshTool "
                    f"(e.g. 'dep: McpMeshTool = None')."
                )

            # Issue #1273: the @mesh.tool analogue — a required dep declared but
            # the tool took the minimal path (no injectable McpMeshTool slot), so
            # the direct-dispatch refusal (_tool_required_refusal) has nothing to
            # evaluate. With NO slot the handler can never observe a null required
            # proxy (the #1273 null-observation bug is structurally impossible
            # here), so — exactly like the route perimeter above — enforcement
            # stays OFF and we WARN instead: the mis-annotation (the dep param
            # isn't typed McpMeshTool) is the thing to fix, not a refuse-all guard.
            if _has_tool_required:
                _req_caps = [c for c in _tool_required_caps if c is not None]
                logger.warning(
                    f"⚠️ Tool '{func.__name__}': required-dependency guard "
                    f"INACTIVE — declared required {_req_caps} but the handler has "
                    f"no injectable McpMeshTool parameter to receive them, so the "
                    f"dependency_unavailable refusal cannot evaluate and is "
                    f"skipped. Fix: annotate the intended parameter(s) as "
                    f"McpMeshTool (e.g. 'dep: McpMeshTool = None')."
                )

            if is_stream:
                minimal_wrapper = _make_stream_wrapper(
                    func,
                    mesh_positions,
                    dependencies,
                    self.get_dependency,
                    wrapper_logger,
                    settle_keys=settle_keys,
                    settle_params=settle_params,
                )
            elif inspect.iscoroutinefunction(func):

                @functools.wraps(func)
                async def minimal_wrapper(*args, **kwargs):
                    # Use ExecutionTracer for functions without dependencies (v0.4.0 style)
                    from ..tracing.execution_tracer import ExecutionTracer
                    from .job_dispatch import maybe_dispatch_as_job

                    wrapper_logger.debug(
                        f"🔧 DI: Executing async function {func.__name__} (no dependencies)"
                    )

                    # Phase 1 MeshJob substrate: wrap the user-function call in
                    # maybe_dispatch_as_job. For non-task tools this is a thin
                    # passthrough (zero overhead). For task=True tools invoked
                    # with X-Mesh-Job-Id, it binds the JobController + contexts
                    # for the duration of the call.
                    async def _invoke(kw: dict) -> Any:
                        return await ExecutionTracer.trace_function_execution_async(
                            func, args, kw, [], [], 0, wrapper_logger
                        )

                    return await maybe_dispatch_as_job(func, _invoke, kwargs)

            else:

                @functools.wraps(func)
                def minimal_wrapper(*args, **kwargs):
                    # Use ExecutionTracer for functions without dependencies (v0.4.0 style)
                    from ..tracing.execution_tracer import ExecutionTracer

                    wrapper_logger.debug(
                        f"🔧 DI: Executing sync function {func.__name__} (no dependencies)"
                    )

                    # Use original function tracer for functions without dependencies
                    return ExecutionTracer.trace_original_function(
                        func, args, kwargs, wrapper_logger
                    )

            # Add minimal metadata for compatibility (use array for consistency)
            minimal_wrapper._mesh_injected_deps = [None] * len(dependencies)
            minimal_wrapper._mesh_dependencies = dependencies
            minimal_wrapper._mesh_positions = mesh_positions
            minimal_wrapper._mesh_original_func = func

            # Override signature to hide injectable parameters from FastMCP
            if is_stream:
                minimal_wrapper.__signature__ = _build_stream_signature(func)
            else:
                clean_sig = _build_clean_signature(func)
                if clean_sig is not None:
                    minimal_wrapper.__signature__ = clean_sig

            def update_dependency(dep_index: int, instance: Any | None) -> None:
                """No-op update for functions without injection positions."""
                pass

            minimal_wrapper._mesh_update_dependency = update_dependency

            # Register this wrapper for dependency updates (even though it won't use them)
            logger.debug(
                f"🔧 REGISTERING minimal wrapper: {func_id} -> {minimal_wrapper} at {hex(id(minimal_wrapper))}"
            )
            self._function_registry[func_id] = minimal_wrapper

            return minimal_wrapper

        # Issue #1249 perimeter (shared by the async + sync dependency_wrapper
        # closures): return a 503 JSONResponse when a required @mesh.route dep
        # is unavailable at call time (naming the capability), else None so the
        # handler runs. Called AFTER the settle wait / injection, so a
        # still-settling dep gets its full window and caller-supplied mocks are
        # honored. Only @mesh.route sets ``_route_required_caps``; @mesh.tool
        # never does, so this is a no-op there.
        def _route_perimeter_response(injected_deps, kwargs):
            if not _has_route_required:
                return None
            unavailable = _first_unavailable_required(
                func_id,
                _route_required_caps,
                injected_deps,
                self.get_dependency,
                kwargs,
                settle_params,
            )
            if unavailable is None:
                return None
            from fastapi.responses import JSONResponse

            wrapper_logger.warning(
                f"🚫 Route '{func.__name__}': required dependency "
                f"'{unavailable}' unavailable — returning 503"
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": "dependency_unavailable",
                    "capability": unavailable,
                },
            )

        # Issue #1273 tool-dispatch guard (shared by the async + sync
        # dependency_wrapper closures): when a @mesh.tool has a required dep
        # slot that is unresolved at direct ``tools/call`` time, raise a
        # ``dependency_unavailable`` tool error naming the capability instead
        # of invoking the handler with a null required proxy. FastMCP surfaces
        # a raised ``ToolError`` as an ``isError`` result whose text carries
        # the message, so the JSON body ``{"error":"dependency_unavailable",
        # "capability":"<cap>"}`` reaches the caller — the SAME semantic class
        # as the route perimeter's 503, letting callers classify it as
        # retryable topology rather than application failure. Runs AFTER the
        # settle wait / injection (so a still-settling dep gets its full window
        # and caller-supplied mocks are honored) and is a no-op unless the tool
        # declared a required dep (@mesh.tool sets ``tool_required_caps``).
        def _tool_required_refusal(injected_deps, kwargs):
            if not _has_tool_required:
                return
            unavailable = _first_unavailable_required(
                func_id,
                _tool_required_caps,
                injected_deps,
                self.get_dependency,
                kwargs,
                settle_params,
            )
            if unavailable is None:
                return
            from fastmcp.exceptions import ToolError

            wrapper_logger.warning(
                f"🚫 Tool '{func.__name__}': required dependency "
                f"'{unavailable}' unavailable at invocation time — refusing "
                f"with dependency_unavailable (not invoking the handler with a "
                f"null required proxy)"
            )
            raise ToolError(
                json.dumps(
                    {
                        "error": "dependency_unavailable",
                        "capability": unavailable,
                    }
                )
            )

        # Determine if we need async wrapper
        need_async_wrapper = inspect.iscoroutinefunction(func)

        if is_stream:
            # Issue #1249: the perimeter 503 is BYPASSED BY DESIGN on the
            # stream path (an SSE/streaming response can't carry a pre-body
            # 503 without breaking the stream). A streaming route that declares
            # required deps keeps soft-fail semantics — flag it so the author
            # knows enforcement is off for this route.
            if _has_route_required:
                _req_caps = [c for c in _route_required_caps if c is not None]
                logger.warning(
                    f"⚠️ Route '{func.__name__}': required perimeter NOT "
                    f"enforced — streaming routes bypass the 503 perimeter by "
                    f"design, so required {_req_caps} are soft-fail (None "
                    f"injected) rather than 503 when unavailable."
                )
            dependency_wrapper = _make_stream_wrapper(
                func,
                mesh_positions,
                dependencies,
                self.get_dependency,
                wrapper_logger,
                settle_keys=settle_keys,
                settle_params=settle_params,
                view_slots=_view_slots,
            )
        elif need_async_wrapper:

            @functools.wraps(func)
            async def dependency_wrapper(*args, **kwargs):
                # Settling-window grace (#1193): bounded wait for declared-
                # but-unresolved deps while the agent is still settling.
                # No-op (single latch check) once settled. The wait is a
                # loop-native asyncio.Event await (set by the resolution
                # funnel via call_soon_threadsafe) — no executor, the loop
                # stays free. Caller-supplied slots (mock contract) skip.
                pending_settle = collect_pending_settle_deps(
                    settle_keys,
                    dependencies,
                    dependency_wrapper._mesh_injected_deps,
                    self.get_dependency,
                    kwargs,
                    settle_params,
                )
                if pending_settle:
                    await wait_for_settle_async(pending_settle, wrapper_logger)

                final_kwargs, injected_count = _prepare_injection_kwargs(
                    func,
                    kwargs,
                    mesh_positions,
                    dependencies,
                    dependency_wrapper._mesh_injected_deps,
                    self.get_dependency,
                    wrapper_logger,
                    view_slots=_view_slots,
                )

                # Issue #1249 perimeter (shared helper; runs after settle).
                _perimeter = _route_perimeter_response(
                    dependency_wrapper._mesh_injected_deps, kwargs
                )
                if _perimeter is not None:
                    return _perimeter

                # Issue #1273 direct-dispatch guard (no-op for @mesh.route and
                # for tools with no required dep). Raises ToolError → isError.
                _tool_required_refusal(
                    dependency_wrapper._mesh_injected_deps, kwargs
                )

                from ..tracing.execution_tracer import ExecutionTracer
                from .job_dispatch import maybe_dispatch_as_job

                # Phase 1 MeshJob substrate: wrap the user-function call in
                # maybe_dispatch_as_job. For non-task tools this is a thin
                # passthrough (zero overhead). For task=True tools invoked
                # with X-Mesh-Job-Id, it binds the JobController + contexts
                # for the duration of the call.
                async def _invoke(kw: dict) -> Any:
                    return await ExecutionTracer.trace_function_execution_async(
                        func._mesh_original_func,
                        args,
                        kw,
                        dependencies,
                        mesh_positions,
                        injected_count,
                        wrapper_logger,
                    )

                result = await maybe_dispatch_as_job(func, _invoke, final_kwargs)

                _log_wrapper_result(func, result, wrapper_logger)
                return result

        else:

            @functools.wraps(func)
            def dependency_wrapper(*args, **kwargs):
                # Settling-window grace (#1193): sync tools are dispatched
                # by FastMCP onto anyio.to_thread worker threads (see
                # fastmcp.utilities.async_utils.call_sync_fn_in_threadpool),
                # so a blocking threading.Event wait here never stalls an
                # event loop (wait_for_settle_sync additionally probes for
                # a running loop and skips if one is found). No-op (single
                # latch check) once settled. Caller-supplied slots (mock
                # contract) skip via the kwargs consult.
                pending_settle = collect_pending_settle_deps(
                    settle_keys,
                    dependencies,
                    dependency_wrapper._mesh_injected_deps,
                    self.get_dependency,
                    kwargs,
                    settle_params,
                )
                if pending_settle:
                    wait_for_settle_sync(pending_settle, wrapper_logger)

                final_kwargs, injected_count = _prepare_injection_kwargs(
                    func,
                    kwargs,
                    mesh_positions,
                    dependencies,
                    dependency_wrapper._mesh_injected_deps,
                    self.get_dependency,
                    wrapper_logger,
                    view_slots=_view_slots,
                )

                # Issue #1249 perimeter (shared helper; sync route variant).
                _perimeter = _route_perimeter_response(
                    dependency_wrapper._mesh_injected_deps, kwargs
                )
                if _perimeter is not None:
                    return _perimeter

                # Issue #1273 direct-dispatch guard (sync variant). Raises
                # ToolError → isError when a required tool dep is unresolved.
                _tool_required_refusal(
                    dependency_wrapper._mesh_injected_deps, kwargs
                )

                from ..tracing.execution_tracer import ExecutionTracer

                result = ExecutionTracer.trace_function_execution(
                    func._mesh_original_func,
                    args,
                    final_kwargs,
                    dependencies,
                    mesh_positions,
                    injected_count,
                    wrapper_logger,
                )

                _log_wrapper_result(func, result, wrapper_logger)
                return result

        # Override signature to hide injectable parameters from FastMCP schema generation
        if is_stream:
            dependency_wrapper.__signature__ = _build_stream_signature(func)
        else:
            clean_sig = _build_clean_signature(func)
            if clean_sig is not None:
                dependency_wrapper.__signature__ = clean_sig

        # Store dependency state on wrapper as array (indexed by position)
        dependency_wrapper._mesh_injected_deps = [None] * len(dependencies)

        # Add update method to wrapper (now uses index-based updates)
        def update_dependency(dep_index: int, instance: Any | None) -> None:
            """Called when a dependency changes (index-based for duplicate capability support)."""
            if dep_index < len(dependency_wrapper._mesh_injected_deps):
                dependency_wrapper._mesh_injected_deps[dep_index] = instance
                if instance is not None:
                    # Settling-window grace (#1193): this closure is the
                    # single funnel for resolution across every path (MCP
                    # register_dependency, API/A2A heartbeat direct calls)
                    # — wake any settling call waiting on this dependency
                    # AFTER the array slot is set so the woken call re-reads
                    # a real proxy.
                    get_settle_state().mark_resolved(
                        f"{func_id}:dep_{dep_index}"
                    )
                if instance is None:
                    wrapper_logger.debug(
                        f"Removed dependency at index {dep_index} from {func_id}"
                    )
                else:
                    wrapper_logger.debug(
                        f"Updated dependency at index {dep_index} for {func_id}"
                    )
                    wrapper_logger.debug(
                        f"🔗 Wrapper pointer receiving dependency: {dependency_wrapper} at {hex(id(dependency_wrapper))}"
                    )
            else:
                wrapper_logger.warning(
                    f"⚠️ Attempted to update dependency at index {dep_index} but wrapper only has {len(dependency_wrapper._mesh_injected_deps)} dependencies"
                )

        # Store update method on wrapper
        dependency_wrapper._mesh_update_dependency = update_dependency
        dependency_wrapper._mesh_dependencies = dependencies
        dependency_wrapper._mesh_positions = mesh_positions
        dependency_wrapper._mesh_original_func = func
        # Settling-window grace (#1193): exposed so secondary invocation
        # paths built on this wrapper's arrays (e.g. the SSE route endpoint
        # in route_integration) can apply the same bounded wait — including
        # the caller-supplied (mock contract) skip via settle_params.
        dependency_wrapper._mesh_settle_keys = settle_keys
        dependency_wrapper._mesh_settle_params = settle_params

        # Register this wrapper for dependency updates
        logger.debug(
            f"🔧 REGISTERING in function_registry: {func_id} -> {dependency_wrapper} at {hex(id(dependency_wrapper))}"
        )
        self._function_registry[func_id] = dependency_wrapper

        # Return the wrapper (which FastMCP will register)
        return dependency_wrapper


# Global injector instance
_global_injector = DependencyInjector()


def get_global_injector() -> DependencyInjector:
    """Get the global dependency injector instance."""
    return _global_injector
