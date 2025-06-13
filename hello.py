from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

server = FastMCP(name="hello")


@server.tool()
@mesh_agent(capability="hello", enable_http=True, http_port=8000)
def say_hello(name: str = "World"):
    return f"Hello, {name}!"


if __name__ == "__main__":
    server.run(transport="stdio")
