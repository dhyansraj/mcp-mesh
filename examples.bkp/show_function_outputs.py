#!/usr/bin/env python3
"""
Show the actual outputs of hello_world.py functions
"""

print(
    """
=== MCP Mesh Function Outputs Demo ===

When you run hello_world.py ALONE:
---------------------------------

1. greet_from_mcp() -> "Hello from MCP"
   (Plain MCP, no dependency injection ever)

2. greet_from_mcp_mesh() -> "Hello from MCP Mesh"
   (MCP Mesh but no SystemAgent available yet)

3. greet_single_capability() -> "Hello from single-capability function - No SystemAgent available"
   (Single capability pattern, no SystemAgent yet)

4. test_dependency_injection() -> {
     "dependency_injection_status": "inactive",
     "SystemAgent_available": false,
     "message": "No SystemAgent dependency injected",
     "recommendation": "Start system_agent.py to see dependency injection in action"
   }


When you run BOTH hello_world.py AND system_agent.py:
----------------------------------------------------

1. greet_from_mcp() -> "Hello from MCP"
   (Still the same! Plain MCP never gets injection)

2. greet_from_mcp_mesh() -> "Hello, its December 10, 2024 at 03:45 PM here, what about you?"
   (NOW IT HAS THE DATE! SystemAgent was automatically injected!)

3. greet_single_capability() -> "Hello from single-capability function - Date from SystemAgent: December 10, 2024 at 03:45 PM"
   (Also gets the SystemAgent injection!)

4. test_dependency_injection() -> {
     "dependency_injection_status": "active",
     "SystemAgent_available": true,
     "SystemAgent_response": "December 10, 2024 at 03:45 PM",
     "message": "Dependency injection working perfectly!",
     "mesh_magic": "SystemAgent was automatically discovered and injected"
   }


The Magic:
----------
• No code changes needed in hello_world.py
• SystemAgent is automatically discovered via the registry
• Dependencies are injected at runtime
• Functions gracefully fall back when dependencies aren't available
• This enables true microservice architecture with MCP!

To see this in action:
1. Terminal 1: mcp-mesh-registry
2. Terminal 2: mcp-mesh-dev start examples/hello_world.py
3. Terminal 3: mcp-mesh-dev start examples/system_agent.py
4. Use any MCP client to call the functions and see the difference!
"""
)
