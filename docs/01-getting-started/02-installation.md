# Installation

> Get MCP Mesh running in under 2 minutes

## Quick Install (Recommended)

### macOS with Homebrew

```bash
# Install CLI tools (includes meshctl and mcp-mesh-registry)
brew tap dhyansraj/mcp-mesh
brew install mcp-mesh

# Install Python package with semantic versioning
pip install "mcp-mesh>=0.7,<0.8"

# Verify installation
meshctl --version
mcp-mesh-registry --version
```

### Linux/macOS with Install Script

```bash
# Install MCP Mesh from PyPI with semantic versioning (allows patch updates)
pip install "mcp-mesh>=0.7,<0.8"

# Download the CLI tools
curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash

# Verify installation
meshctl --version
mcp-mesh-registry --version
```

**What this installs:**

- 📦 **Python package**: MCP Mesh runtime for building agents
- 🔧 **meshctl**: CLI tool for managing the mesh
- 🏗️ **mcp-mesh-registry**: Service discovery and coordination server

## Alternative: Build from Source

For contributors or advanced users who want to build from source:

### Prerequisites

- Python 3.9 or higher
- Go 1.23 or higher
- Make (build tool)

### Quick Install (Recommended)

```bash
# Clone the repository
git clone https://github.com/mcp-mesh/mcp-mesh.git
cd mcp-mesh

# Install everything with one command
make install

# Activate the virtual environment that was created
source .venv/bin/activate

# Verify installation
meshctl --version
```

That's it! The `make install` command:

- Builds the Go binaries
- Creates a Python virtual environment in `.venv` (if needed)
- Installs the Python package with all dependencies
- Installs binaries to `/usr/local/bin` (may prompt for sudo)

> **Note**: MCP Mesh always uses `.venv` in the project root for consistency

### Manual Installation

If you prefer to control each step:

```bash
# Build Go binaries
make build

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install Python package
pip install src/runtime/python/

# Install binaries (optional, requires sudo)
sudo make install

# Or add to PATH instead
export PATH=$PATH:$(pwd)/bin
```

## What Gets Installed?

When you install MCP Mesh, you get:

1. **Python Package** (`mcp_mesh`): The decorators and runtime for your agents
2. **CLI Tool** (`meshctl`): Go-based command-line tool for running agents
3. **Registry Binary** (`mcp-mesh-registry`): Go-based service registry

## System Requirements

- **Python**: 3.9 or higher
- **OS**: Linux, macOS, or Windows (WSL2 recommended)
- **Memory**: 1GB free RAM
- **Disk**: 500MB free space

## For Developers

If you're contributing to MCP Mesh:

```bash
# Development installation
make install-dev

# This creates symlinks instead of copying binaries
# and installs the Python package in editable mode
```

See our [Contributing Guide](../contributing.md) for more details.

## Verify Installation

Run a quick test to ensure everything is working:

```bash
# Make sure you're in the virtual environment
source .venv/bin/activate

# Test the CLI
meshctl --version

# Test Python import
python -c "from mcp_mesh import mesh_agent; print('✅ MCP Mesh is installed!')"

# Start the registry (in one terminal)
meshctl start --registry-only

# Run an example agent (in another terminal)
meshctl start examples/hello_world.py
```

## Your First Agent in 30 Seconds

Create `hello.py`:

```python
import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Hello Service")

@app.tool()  # FastMCP decorator for MCP protocol
@mesh.tool(capability="greeting")  # Mesh decorator for orchestration
def say_hello(name: str = "World") -> str:
    return f"Hello, {name}!"

# Agent configuration - mesh handles server startup
@mesh.agent(
    name="hello-service",
    http_port=8000,
    auto_run=True  # No main method needed!
)
class HelloService:
    pass

# Mesh discovers 'app' and handles everything automatically!
```

Run it:

```bash
# Start your agent (registry starts automatically)
python hello.py

# Test it (MCP JSON-RPC format)
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "say_hello",
      "arguments": {"name": "MCP Mesh"}
    }
  }'
```

That's it! You've just created and deployed your first MCP Mesh agent.

## Common Installation Issues

### 1. Command 'meshctl' not found

**Solution**: Either add `/usr/local/bin` to your PATH or use the local binary:

```bash
# Option 1: Use full path
/usr/local/bin/meshctl --version

# Option 2: Add to PATH
export PATH=$PATH:/usr/local/bin

# Option 3: Use local binary
./bin/meshctl --version
```

### 2. ImportError: No module named 'mcp_mesh'

**Solution**: Activate the virtual environment:

```bash
source .venv/bin/activate  # or your custom venv
python -c "import mcp_mesh"
```

### 3. Permission denied when installing to /usr/local/bin

**Solution**: The installer will prompt for sudo. Alternatively, use local binaries:

```bash
# Just build without installing
make build

# Add to PATH
export PATH=$PATH:$(pwd)/bin
```

### 4. Port 8080 already in use

**Solution**: Another service is using port 8080:

```bash
# Find what's using port 8080
lsof -i :8080

# Kill the process (replace PID with actual process ID)
kill <PID>

# Or use a different port
meshctl start --registry-port 8081
```

## Next Steps

Now that MCP Mesh is installed, let's run your first example:

**[Running Hello World Example](./03-hello-world.md)** →

### Reference Guides

- **[meshctl CLI](../meshctl-cli.md)** - Command-line tool reference
- **[Environment Variables](../environment-variables.md)** - Configuration options

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

- [x] Create one-line installer script
- [x] Add Homebrew formula for macOS
- [ ] Create snap package for Linux
- [ ] Add Windows installer (.exe)
- [ ] Support poetry and pipenv
- [ ] Create Docker image for development
