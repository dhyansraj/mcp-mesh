"""
Function signature analysis for MCP Mesh dependency injection.
"""

import inspect
from typing import Any, get_type_hints

from mcp_mesh.types import McpMeshAgent


def get_mesh_agent_positions(func: Any) -> list[int]:
    """
    Get positions of McpMeshAgent parameters in function signature.

    Args:
        func: Function to analyze

    Returns:
        List of parameter positions (0-indexed) that are McpMeshAgent types

    Example:
        def greet(name: str, date_svc: McpMeshAgent, weather_svc: McpMeshAgent):
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
                        and param_type.__origin__ is type(McpMeshAgent)
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
