"""
Function signature analysis for MCP Mesh dependency injection.
"""

import inspect
from typing import Any, get_type_hints

from mesh.types import McpAgent, McpMeshAgent


def get_agent_parameter_types(func: Any) -> dict[int, str]:
    """
    Get parameter positions and their agent types (McpAgent vs McpMeshAgent).

    Args:
        func: Function to analyze

    Returns:
        Dict mapping parameter position to agent type name
        e.g., {1: "McpAgent", 2: "McpMeshAgent"}
    """
    try:
        # Get type hints for the function
        type_hints = get_type_hints(func)

        # Get parameter names in order
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())

        # Find positions and types of agent parameters
        agent_types = {}
        for i, param_name in enumerate(param_names):
            if param_name in type_hints:
                param_type = type_hints[param_name]

                # Check for McpAgent or McpMeshAgent (handle Union types too)
                agent_type = None

                # Direct type check
                if param_type == McpAgent or (
                    hasattr(param_type, "__name__")
                    and param_type.__name__ == "McpAgent"
                ):
                    agent_type = "McpAgent"
                elif param_type == McpMeshAgent or (
                    hasattr(param_type, "__name__")
                    and param_type.__name__ == "McpMeshAgent"
                ):
                    agent_type = "McpMeshAgent"

                # Union type check (e.g., McpAgent | None)
                elif hasattr(param_type, "__args__"):
                    for arg in param_type.__args__:
                        if arg == McpAgent or (
                            hasattr(arg, "__name__") and arg.__name__ == "McpAgent"
                        ):
                            agent_type = "McpAgent"
                            break
                        elif arg == McpMeshAgent or (
                            hasattr(arg, "__name__") and arg.__name__ == "McpMeshAgent"
                        ):
                            agent_type = "McpMeshAgent"
                            break

                if agent_type:
                    agent_types[i] = agent_type

        return agent_types

    except Exception as e:
        # If we can't analyze the signature, return empty dict
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to analyze agent parameter types for {func}: {e}")
        return {}


def get_mesh_agent_positions(func: Any) -> list[int]:
    """
    Get positions of McpAgent and McpMeshAgent parameters in function signature.

    Args:
        func: Function to analyze

    Returns:
        List of parameter positions (0-indexed) that are McpAgent or McpMeshAgent types

    Example:
        def greet(name: str, date_svc: McpMeshAgent, file_svc: McpAgent):
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

                # Check if it's McpAgent or McpMeshAgent type (handle different import paths and Union types)
                is_agent = False

                # Direct McpAgent or McpMeshAgent type
                if (
                    param_type in (McpAgent, McpMeshAgent)
                    or (
                        hasattr(param_type, "__name__")
                        and param_type.__name__ in ("McpAgent", "McpMeshAgent")
                    )
                    or (
                        hasattr(param_type, "__origin__")
                        and param_type.__origin__
                        in (type(McpAgent), type(McpMeshAgent))
                    )
                ):
                    is_agent = True

                # Union type (e.g., McpAgent | None, McpMeshAgent | None)
                elif hasattr(param_type, "__args__"):
                    # Check if any arg in the union is McpAgent or McpMeshAgent
                    for arg in param_type.__args__:
                        if arg in (McpAgent, McpMeshAgent) or (
                            hasattr(arg, "__name__")
                            and arg.__name__ in ("McpAgent", "McpMeshAgent")
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
                if param_type == McpMeshAgent or (
                    hasattr(param_type, "__origin__")
                    and param_type.__origin__ is type(McpMeshAgent)
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
