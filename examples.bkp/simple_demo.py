#!/usr/bin/env python3
"""Simple demo of mcp-mesh functionality without running as a server."""

from mcp_mesh import DecoratorRegistry, mesh_agent


# Define some mesh agents
@mesh_agent(
    capability="greeting", version="1.0.0", description="Simple greeting service"
)
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}! Welcome to MCP Mesh."


@mesh_agent(
    capability="calculator", version="1.0.0", description="Basic math operations"
)
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@mesh_agent(
    capability="text_processing",
    version="1.0.0",
    description="Text manipulation service",
    tags=["text", "utility"],
)
def reverse_text(text: str) -> str:
    """Reverse the given text."""
    return text[::-1]


def main():
    print("🚀 MCP Mesh Simple Demo")
    print("=" * 50)

    # Test the functions directly
    print("\n1. Testing direct function calls:")
    print(f"   greet('Alice') = {greet('Alice')}")
    print(f"   add_numbers(5, 3) = {add_numbers(5, 3)}")
    print(f"   reverse_text('Hello') = {reverse_text('Hello')}")

    # Show registered agents
    print("\n2. Registered mesh agents:")
    agents = DecoratorRegistry.get_mesh_agents()
    for name, agent in agents.items():
        metadata = agent.metadata
        print(f"\n   📦 {name}")
        print(f"      Capability: {metadata.get('capability')}")
        print(f"      Version: {metadata.get('version')}")
        print(f"      Description: {metadata.get('description')}")
        if metadata.get("tags"):
            print(f"      Tags: {metadata.get('tags')}")

    # Show how metadata is stored
    print("\n3. Accessing agent metadata:")
    if hasattr(greet, "_mesh_metadata"):
        print(f"   greet._mesh_metadata = {greet._mesh_metadata}")

    print("\n✅ Demo completed successfully!")
    print("\nNote: In a real deployment, these agents would:")
    print("- Register with a mesh registry")
    print("- Be discoverable by other services")
    print("- Support dependency injection")
    print("- Have health monitoring")


if __name__ == "__main__":
    main()
