#!/usr/bin/env python3
"""
Comparison of old vs new approach for FastMCP server naming with @mesh.agent.

This shows the difference between the problematic approach and the fixed approach.
"""

import mesh
from mcp.server.fastmcp import FastMCP

# PROBLEM: Old approach - server name doesn't match @mesh.agent
print("❌ PROBLEMATIC APPROACH:")
print("This will cause a warning because server name differs from agent configuration")


@mesh.agent(name="my-service", version="1.0.0")
class MyAgent:
    pass


# Problem: Hard-coded server name that doesn't match @mesh.agent
old_server = FastMCP("some-hardcoded-name")  # ❌ This name won't match agent_id


@mesh.tool(capability="old_greeting")
@old_server.tool()
def old_hello():
    return "Hello from old approach"


print("Server name: 'some-hardcoded-name'")
print("Agent name: 'my-service'")
print("Result: Warning logged about name mismatch")
print()

# SOLUTION: New approach - server name matches @mesh.agent
print("✅ FIXED APPROACH:")
print("This will work correctly with no warnings")


@mesh.agent(name="my-fixed-service", version="1.0.0")
class MyFixedAgent:
    pass


# Solution: Use mesh.create_server() to automatically use @mesh.agent name
new_server = mesh.create_server()  # ✅ This will use "my-fixed-service" as server name


@mesh.tool(capability="new_greeting")
@new_server.tool()
def new_hello():
    return "Hello from fixed approach"


print("Server name: 'my-fixed-service' (from @mesh.agent)")
print("Agent name: 'my-fixed-service'")
print("Result: Perfect match, no warnings")
print()

# ALTERNATIVE: Explicit naming
print("✅ ALTERNATIVE: Explicit naming")
print("You can also explicitly specify the server name")


@mesh.agent(name="explicit-service", version="1.0.0")
class ExplicitAgent:
    pass


# Alternative: Explicitly pass the same name as @mesh.agent
explicit_server = mesh.create_server("explicit-service")  # ✅ Explicit but consistent


@mesh.tool(capability="explicit_greeting")
@explicit_server.tool()
def explicit_hello():
    return "Hello from explicit approach"


print("Server name: 'explicit-service' (explicitly provided)")
print("Agent name: 'explicit-service'")
print("Result: Explicit match, no warnings")
print()

print("📚 SUMMARY:")
print("1. Use mesh.create_server() without arguments to auto-use @mesh.agent name")
print("2. Or use mesh.create_server('name') with same name as @mesh.agent")
print("3. Avoid FastMCP('name') with different name than @mesh.agent")
print("4. The processor will warn if server name != agent_id")
