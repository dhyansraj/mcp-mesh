# Installation

> Get MCP Mesh running in under 2 minutes

## Quick Install (Recommended)

```bash
# Install MCP Mesh
pip install mcp-mesh

# Verify installation
mcp-mesh-dev --version

# That's it! You're ready to run agents
```

## What Gets Installed?

When you install MCP Mesh, you get:

1. **Python Package** (`mcp_mesh`): The decorators and runtime for your agents
2. **CLI Tool** (`mcp-mesh-dev`): Command-line tool for running agents
3. **Registry Binary**: Go-based service registry (downloaded automatically)

## System Requirements

- **Python**: 3.9 or higher
- **OS**: Linux, macOS, or Windows (WSL2 recommended)
- **Memory**: 1GB free RAM
- **Disk**: 500MB free space

## Installation Options

### Virtual Environment (Recommended)

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install MCP Mesh
pip install mcp-mesh
```

### Global Installation

```bash
# Install globally (requires admin/sudo)
pip install mcp-mesh

# Or user-level installation
pip install --user mcp-mesh
```

### Development Installation

```bash
# Clone and install from source
git clone https://github.com/mcp-mesh/mcp-mesh.git
cd mcp-mesh
pip install -e src/runtime/python/

# Build Go components (optional - for registry development)
make build  # Builds mcp-mesh-registry and mcp-mesh-dev
```

## Verify Installation

Run a quick test to ensure everything is working:

```bash
# Test the CLI
mcp-mesh-dev --help

# Test Python import
python -c "from mcp_mesh import mesh_agent; print('✅ MCP Mesh is installed!')"

# Run the built-in example
mcp-mesh-dev test
```

## Your First Agent in 30 Seconds

Create `hello.py`:

```python
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

server = FastMCP(name="hello")

@server.tool()
@mesh_agent(capability="hello", enable_http=True, http_port=8000)
def say_hello(name: str = "World"):
    return f"Hello, {name}!"

if __name__ == "__main__":
    import asyncio
    from mcp_mesh.server.runner import run_server
    asyncio.run(run_server(server))
```

Run it:

```bash
# Start your agent (registry starts automatically)
mcp-mesh-dev start hello.py

# Test it
curl http://localhost:8000/hello_say_hello
```

That's it! You've just created and deployed your first MCP Mesh agent.

## Common Installation Issues

### 1. ImportError: No module named 'mcp_mesh'

**Solution**: Ensure virtual environment is activated and MCP Mesh is installed:

```bash
pip list | grep mcp-mesh
```

### 2. Permission Denied

**Solution**: Use virtual environments instead of system-wide installation:

```bash
python -m venv .venv
source .venv/bin/activate
pip install mcp-mesh
```

### 3. Version Conflicts

**Solution**: Upgrade pip and reinstall:

```bash
pip install --upgrade pip
pip install --upgrade mcp-mesh
```

### 4. Registry Connection Failed

**Solution**: Ensure registry is running and accessible:

```bash
# Check if registry is running
ps aux | grep mcp-mesh-registry

# Check port availability
lsof -i :8000
```

## Next Steps

Now that MCP Mesh is installed, let's run your first example:

[Running Hello World Example](./03-hello-world.md) →

---

💡 **Tip**: Keep the registry running in a separate terminal while working with agents.

📚 **Note**: For production deployments, consider using Docker or Kubernetes for easier management. See our [deployment guides](../MCP_MESH_DEPLOYMENT_GUIDE.md) for more options.

## 🔧 Troubleshooting

### Installation Issues

1. **pip SSL errors** - Update certificates or use `--trusted-host pypi.org`
2. **Compilation errors** - Install build tools (`build-essential` on Linux, Xcode on macOS)
3. **Permission errors** - Never use `sudo pip`; use virtual environments
4. **Dependency conflicts** - Create a fresh virtual environment

For comprehensive solutions, see our [Troubleshooting Guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **PyPI package**: May lag behind latest GitHub commits
- **Windows**: Some features require WSL2 for full compatibility
- **Go registry**: Requires Go 1.23+ and CGO for SQLite support
- **Air-gapped environments**: Requires manual dependency download

## 📝 TODO

- [ ] Create one-line installer script
- [ ] Add Homebrew formula for macOS
- [ ] Create snap package for Linux
- [ ] Add Windows installer (.exe)
- [ ] Support poetry and pipenv
- [ ] Create Docker image for development
