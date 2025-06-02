# MCP SDK Examples and Usage Guide

## Hello World MCP Server

This guide demonstrates how to create and test a minimal MCP server using the official MCP Python SDK.

### Server Implementation

The Hello World server is located at `src/mcp_mesh_sdk/server/hello_world.py` and demonstrates:

- **FastMCP Framework**: Using `mcp.server.fastmcp.FastMCP` for simplified server creation
- **Tools**: 4 tools including `say_hello`, `echo`, `add_numbers`, and `get_server_info`
- **Resources**: 2 text resources (`text://hello` and `text://info`)
- **Prompts**: 2 prompts for greeting and help functionality
- **Protocol Compliance**: Full MCP 2024-11-05 protocol support

### Key Features

#### 1. Server Creation

```python
from mcp.server.fastmcp import FastMCP

app = FastMCP(
    name="hello-world-server",
    instructions="A simple Hello World MCP server demonstrating basic MCP protocol capabilities."
)
```

#### 2. Tool Definition

```python
@app.tool()
def say_hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}! Welcome to the MCP Mesh SDK."
```

#### 3. Resource Definition

```python
@app.resource("text://hello")
def hello_resource() -> str:
    """A simple text resource containing a greeting."""
    return "Hello from the MCP Mesh SDK! This is a sample text resource."
```

#### 4. Prompt Definition

```python
@app.prompt()
def greeting_prompt(name: str = "there") -> List[PromptMessage]:
    """Generate a friendly greeting prompt."""
    return [PromptMessage(role="user", content=TextContent(...))]
```

### Running the Server

#### Method 1: Direct Execution

```bash
python src/mcp_mesh_sdk/server/hello_world.py
```

#### Method 2: Import and Use

```python
from mcp_mesh_sdk.server.hello_world import create_hello_world_server

server = create_hello_world_server()
server.run(transport="stdio")
```

### Testing and Verification

#### Protocol Compliance Test

Run the protocol compliance test to verify MCP initialization:

```bash
python protocol_test.py
```

**Expected Output:**

```
🧪 MCP Protocol Compliance Test
===================================
🔧 Testing MCP protocol compliance...
📤 Sending initialization request...
📥 Received: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05",...}}
✅ Protocol compliance verified!
   Protocol version: 2024-11-05
   Capabilities: ['experimental', 'prompts', 'resources', 'tools']
   Server: hello-world-server v1.9.3

🎉 Protocol compliance test PASSED!
```

#### Server Creation Test

Run the basic functionality test:

```bash
python quick_test.py
```

This verifies:

- ✅ Server can be imported and created successfully
- ✅ Server has correct name and properties
- ✅ No import errors or dependency issues

### Protocol Compliance Verification

The Hello World server demonstrates full MCP protocol compliance:

#### ✅ Initialization Protocol

- Responds to `initialize` method with correct JSON-RPC 2.0 format
- Returns protocol version `2024-11-05`
- Declares all required capabilities: `tools`, `resources`, `prompts`
- Includes proper server information

#### ✅ Capability Declaration

- **Tools**: Declares tools capability with `listChanged: false`
- **Resources**: Declares resources capability with `subscribe: false, listChanged: false`
- **Prompts**: Declares prompts capability with `listChanged: false`
- **Experimental**: Supports experimental features

#### ✅ Server Information

- Server name: `hello-world-server`
- Version: `1.9.3` (matches MCP SDK version)
- Instructions: Provides clear server description

### Available Tools

1. **say_hello**: Greets a person by name

   - Input: `name` (string, optional, defaults to "World")
   - Output: Greeting message

2. **echo**: Echoes back a message

   - Input: `message` (string, required)
   - Output: Message with "Echo:" prefix

3. **add_numbers**: Adds two numbers

   - Input: `a`, `b` (float, required)
   - Output: Sum of the numbers

4. **get_server_info**: Returns server metadata
   - Input: None
   - Output: Dictionary with server information

### Available Resources

1. **text://hello**: Simple greeting text resource
2. **text://info**: Detailed server information in Markdown format

### Available Prompts

1. **greeting_prompt**: Generates friendly greeting prompts

   - Parameter: `name` (string, optional)

2. **help_prompt**: Generates help information prompts
   - No parameters

### Integration with MCP Clients

This server can be used with any MCP-compatible client:

1. **Claude Desktop**: Add to configuration for use with Claude
2. **MCP Client Libraries**: Use with official MCP client SDKs
3. **Custom Applications**: Integrate via JSON-RPC over stdio

### Next Steps

This Hello World server serves as a foundation for building more complex MCP servers with:

- Database integration
- File system operations
- Web API integrations
- Machine learning model serving
- Custom business logic

The server demonstrates proper MCP patterns that can be extended for real-world applications.

---

**Status**: ✅ **COMPLETE** - MCP SDK Exploration tasks for Week 1, Day 1

- Minimal Hello World server created using official MCP SDK
- Server startup and basic functionality verified
- Protocol compliance confirmed with MCP 2024-11-05
- Working examples documented and ready for use
