"""
Function signature analysis for MCP Mesh dependency injection.
"""

import inspect
import logging
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


def _is_mesh_tool_type(param_type: Any) -> bool:
    """Check if a type is McpMeshTool or deprecated McpMeshAgent."""
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


@dataclass(frozen=True)
class MeshJobResolution:
    """Resolver output for ``MeshJob`` parameter classification.

    Per ``MESHJOB_DDDI_CONTRACT.md``: ``MeshJob`` is **orthogonal** to
    ``MeshTool`` positional indexing — its signature position is recorded
    separately so adding/removing a ``MeshJob`` parameter does not shift
    the slot numbers used to inject mesh-tool dependencies.

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
    mesh_job_param_index: Optional[int] = None
    mesh_job_param_name: Optional[str] = None


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
    try:
        type_hints = get_type_hints(func)
    except Exception as e:
        # If we can't resolve type hints (forward refs, missing imports),
        # fall back to empty resolution — same defensive posture as the
        # legacy positional analysers above. The caller can still invoke
        # the function as a plain tool; jobs just won't bind.
        logger.warning(f"analyze_mesh_job_signature: get_type_hints failed for {func}: {e}")
        return MeshJobResolution()

    sig = inspect.signature(func)
    mesh_tool_positions: list[int] = []
    mesh_job_param_index: Optional[int] = None
    mesh_job_param_name: Optional[str] = None

    for i, (param_name, _param) in enumerate(sig.parameters.items()):
        if param_name not in type_hints:
            continue
        param_type = type_hints[param_name]

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
                    f"'{mesh_job_param_name}' and '{param_name}'"
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
    try:
        func = _get_original_func(func)
        # Get type hints for the function
        type_hints = get_type_hints(func)

        # Get parameter names in order
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())

        # Find positions of McpMeshTool parameters
        mesh_positions = []
        for i, param_name in enumerate(param_names):
            if param_name in type_hints:
                param_type = type_hints[param_name]
                if _is_mesh_tool_type(param_type):
                    mesh_positions.append(i)

        return mesh_positions

    except Exception as e:
        # If we can't analyze the signature, return empty list
        logger.warning(f"Failed to analyze signature for {func}: {e}")
        return []


def get_mesh_agent_parameter_names(func: Any) -> list[str]:
    """
    Get names of McpMeshTool parameters in function signature.

    Args:
        func: Function to analyze

    Returns:
        List of parameter names that are McpMeshTool types
    """
    try:
        func = _get_original_func(func)
        type_hints = get_type_hints(func)
        sig = inspect.signature(func)

        mesh_param_names = []
        for param_name, param in sig.parameters.items():
            if param_name in type_hints:
                param_type = type_hints[param_name]
                if _is_mesh_tool_type(param_type):
                    mesh_param_names.append(param_name)

        return mesh_param_names

    except Exception as e:
        logger.warning(f"Failed to analyze signature for {func}: {e}")
        return []


def validate_mesh_dependencies(func: Any, dependencies: list[dict]) -> tuple[bool, str]:
    """
    Validate that the number of dependencies matches the function's
    injectable slots.

    A function may declare two kinds of typed dependency slot:

    * ``McpMeshTool`` — positional, dispatch via remote tools/call. Counted
      via :func:`get_mesh_agent_positions`.
    * ``MeshJob`` — name-matched (by parameter name == dependency
      capability), dispatch via job submit. Counted by inspecting whether
      the function declares any ``MeshJob`` param whose name appears in the
      declared dependency capabilities (see MeshJob DDDI contract).

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
    """
    func = _get_original_func(func)
    mesh_positions = get_mesh_agent_positions(func)

    # Count MeshJob slots that match a declared dependency capability.
    # MeshJob params are name-matched (not positional) so an unmatched
    # MeshJob param does NOT consume a dependency slot — only the matched
    # ones do.
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

    if resolution is not None and resolution.mesh_job_param_name:
        dep_caps = {
            d.get("capability") for d in dependencies if isinstance(d, dict)
        }
        if resolution.mesh_job_param_name in dep_caps:
            job_slots = 1

    expected = len(mesh_positions) + job_slots
    if len(dependencies) != expected:
        return False, (
            f"Function {func.__name__} has {len(mesh_positions)} McpMeshTool "
            f"parameter(s) and {job_slots} matched MeshJob slot(s) "
            f"but {len(dependencies)} dependencies declared. "
            f"Each typed slot needs a corresponding dependency."
        )

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
    try:
        func = _get_original_func(func)
        # Get type hints for the function
        type_hints = get_type_hints(func)

        # Get parameter names in order
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())

        # Find positions of MeshLlmAgent parameters
        llm_positions = []
        for i, param_name in enumerate(param_names):
            if param_name in type_hints:
                param_type = type_hints[param_name]

                if _is_mesh_llm_type(param_type):
                    llm_positions.append(i)

        return llm_positions

    except Exception as e:
        # If we can't analyze the signature, return empty list
        logger.warning(f"Failed to analyze signature for {func}: {e}")
        return []


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
    try:
        func = _get_original_func(func)
        type_hints = get_type_hints(func)
        sig = inspect.signature(func)

        llm_param_names = []
        for param_name, param in sig.parameters.items():
            if param_name in type_hints:
                param_type = type_hints[param_name]
                if _is_mesh_llm_type(param_type):
                    llm_param_names.append(param_name)

        return llm_param_names
    except Exception as e:
        logger.warning(f"Failed to analyze signature for {func}: {e}")
        return []


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

        # Get type hints (may fail for some functions)
        type_hints = {}
        try:
            type_hints = get_type_hints(func)
        except Exception:
            pass  # Continue without type hints

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
