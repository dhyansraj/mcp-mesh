"""
Function signature analysis for MCP Mesh dependency injection.
"""

import inspect
from typing import Any, get_type_hints

from mesh.types import McpMeshAgent, MeshLlmAgent


def get_mesh_agent_positions(func: Any) -> list[int]:
    """
    Get positions of McpMeshAgent parameters in function signature.

    Args:
        func: Function to analyze

    Returns:
        List of parameter positions (0-indexed) that are McpMeshAgent types

    Example:
        def greet(name: str, date_svc: McpMeshAgent, file_svc: McpMeshAgent):
            pass

        get_mesh_agent_positions(greet) → [1, 2]
    """
    try:
        # Get type hints for the function
        type_hints = get_type_hints(func)

        # Get parameter names in order
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())

        # Find positions of McpMeshAgent parameters
        mesh_positions = []
        for i, param_name in enumerate(param_names):
            if param_name in type_hints:
                param_type = type_hints[param_name]

                # Check if it's McpMeshAgent type (handle different import paths and Union types)
                is_agent = False

                # Direct McpMeshAgent type
                if (
                    param_type == McpMeshAgent
                    or (
                        hasattr(param_type, "__name__")
                        and param_type.__name__ == "McpMeshAgent"
                    )
                    or (
                        hasattr(param_type, "__origin__")
                        and param_type.__origin__ == type(McpMeshAgent)
                    )
                ):
                    is_agent = True

                # Union type (e.g., McpMeshAgent | None)
                elif hasattr(param_type, "__args__"):
                    # Check if any arg in the union is McpMeshAgent
                    for arg in param_type.__args__:
                        if arg == McpMeshAgent or (
                            hasattr(arg, "__name__") and arg.__name__ == "McpMeshAgent"
                        ):
                            is_agent = True
                            break

                if is_agent:
                    mesh_positions.append(i)

        return mesh_positions

    except Exception as e:
        # If we can't analyze the signature, return empty list
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to analyze signature for {func}: {e}")
        return []


def get_mesh_agent_parameter_names(func: Any) -> list[str]:
    """
    Get names of McpMeshAgent parameters in function signature.

    Args:
        func: Function to analyze

    Returns:
        List of parameter names that are McpMeshAgent types
    """
    try:
        type_hints = get_type_hints(func)
        sig = inspect.signature(func)

        mesh_param_names = []
        for param_name, param in sig.parameters.items():
            if param_name in type_hints:
                param_type = type_hints[param_name]

                # Check if it's McpMeshAgent type (handle different import paths and Union types)
                is_mesh_agent = False

                # Direct McpMeshAgent type
                if (
                    param_type == McpMeshAgent
                    or (
                        hasattr(param_type, "__name__")
                        and param_type.__name__ == "McpMeshAgent"
                    )
                    or (
                        hasattr(param_type, "__origin__")
                        and param_type.__origin__ == type(McpMeshAgent)
                    )
                ):
                    is_mesh_agent = True

                # Union type (e.g., McpMeshAgent | None)
                elif hasattr(param_type, "__args__"):
                    # Check if any arg in the union is McpMeshAgent
                    for arg in param_type.__args__:
                        if arg == McpMeshAgent or (
                            hasattr(arg, "__name__") and arg.__name__ == "McpMeshAgent"
                        ):
                            is_mesh_agent = True
                            break

                if is_mesh_agent:
                    mesh_param_names.append(param_name)

        return mesh_param_names

    except Exception:
        return []


def validate_mesh_dependencies(func: Any, dependencies: list[dict]) -> tuple[bool, str]:
    """
    Validate that the number of dependencies matches McpMeshAgent parameters.

    Args:
        func: Function to validate
        dependencies: List of dependency declarations from @mesh.tool

    Returns:
        Tuple of (is_valid, error_message)
    """
    mesh_positions = get_mesh_agent_positions(func)

    if len(dependencies) != len(mesh_positions):
        return False, (
            f"Function {func.__name__} has {len(mesh_positions)} McpMeshAgent parameters "
            f"but {len(dependencies)} dependencies declared. "
            f"Each McpMeshAgent parameter needs a corresponding dependency."
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

                # Check if it's MeshLlmAgent type (handle different import paths and Union types)
                is_llm_agent = False

                # Direct MeshLlmAgent type
                if (
                    param_type == MeshLlmAgent
                    or (
                        hasattr(param_type, "__name__")
                        and param_type.__name__ == "MeshLlmAgent"
                    )
                    or (
                        hasattr(param_type, "__origin__")
                        and param_type.__origin__ == type(MeshLlmAgent)
                    )
                ):
                    is_llm_agent = True

                # Union type (e.g., MeshLlmAgent | None)
                elif hasattr(param_type, "__args__"):
                    # Check if any arg in the union is MeshLlmAgent
                    for arg in param_type.__args__:
                        if arg == MeshLlmAgent or (
                            hasattr(arg, "__name__") and arg.__name__ == "MeshLlmAgent"
                        ):
                            is_llm_agent = True
                            break

                if is_llm_agent:
                    llm_positions.append(i)

        return llm_positions

    except Exception as e:
        # If we can't analyze the signature, return empty list
        import logging

        logger = logging.getLogger(__name__)
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
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(f"Failed to detect context parameter for {func.__name__}: {e}")
        return None
