"""
Backward compatibility imports for old mesh_agent decorator.

The mesh_agent decorator has been replaced by:
- mesh.tool: For individual function/tool decoration
- mesh.agent: For agent-wide configuration

Usage:
    # Old (deprecated):
    from mcp_mesh import mesh_agent

    # New:
    import mesh

    @mesh.agent(name="my-agent")
    class MyAgent:
        @mesh.tool(capability="greeting")
        def say_hello(self):
            return "Hello!"
"""


def mesh_agent(*args, **kwargs):
    """
    Deprecated mesh_agent decorator.

    This decorator has been replaced by mesh.tool and mesh.agent.
    Please update your code to use the new decorators.
    """
    raise ImportError(
        "mesh_agent has been deprecated and removed. "
        "Use 'mesh.tool' for individual functions and 'mesh.agent' for agent-wide configuration. "
        "Example: import mesh; @mesh.tool(capability='test') or @mesh.agent(name='my-agent')"
    )


def _enhance_mesh_agent(processor):
    """Legacy function for runtime enhancement - no longer used."""
    pass  # No-op for compatibility with runtime initialization
