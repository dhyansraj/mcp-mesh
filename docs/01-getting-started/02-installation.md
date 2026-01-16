# Installation

> Get MCP Mesh running in under 2 minutes

## Quick Install (Recommended)

```bash
# Install CLI tools (meshctl and mcp-mesh-registry)
npm install -g @mcpmesh/cli

# Install Python runtime
pip install "mcp-mesh>=0.8,<0.9"

# Verify installation
meshctl --version
mcp-mesh-registry --version
```

**What this installs:**

- **meshctl**: CLI tool for managing the mesh
- **mcp-mesh-registry**: Service discovery and coordination server
- **mcp-mesh** (Python): Runtime for building agents

## Alternative Installation Methods

<details>
<summary><strong>Homebrew (macOS)</strong></summary>

```bash
# Install CLI tools
brew tap dhyansraj/mcp-mesh
brew install mcp-mesh

# Install Python package
pip install "mcp-mesh>=0.8,<0.9"

# Verify installation
meshctl --version
```

</details>

<details>
<summary><strong>Install Script (Linux/macOS)</strong></summary>

```bash
# Install Python package
pip install "mcp-mesh>=0.8,<0.9"

# Download CLI tools
curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash

# Verify installation
meshctl --version
```

</details>

<details>
<summary><strong>Build from Source</strong></summary>

For contributors or advanced users who want to build from source:

### Prerequisites

- Python 3.11 or higher
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

</details>

## What Gets Installed?

When you install MCP Mesh, you get:

1. **Python Package** (`mcp_mesh`): The decorators and runtime for your agents
2. **CLI Tool** (`meshctl`): Go-based command-line tool for running agents
3. **Registry Binary** (`mcp-mesh-registry`): Go-based service registry

## System Requirements

- **Python**: 3.11 or higher
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

**Solution**: Ensure npm global binaries are in your PATH:

```bash
# Check where npm installs global packages
npm config get prefix

# Add to PATH (add to your shell profile for persistence)
export PATH="$(npm config get prefix)/bin:$PATH"

# Verify installation
meshctl --version
```

### 2. ImportError: No module named 'mcp_mesh'

**Solution**: Activate the virtual environment:

```bash
source .venv/bin/activate  # or your custom venv
python -c "import mcp_mesh"
```

### 3. Port 8080 already in use

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

📚 **Note**: For production deployments, consider using Docker or Kubernetes for easier management. See our [deployment guides](../deployment.md) for more options.

## 🔧 Troubleshooting

### Installation Issues

1. **pip SSL errors** - Update certificates or use `--trusted-host pypi.org`
2. **Compilation errors** - Install build tools (`build-essential` on Linux, Xcode on macOS)
3. **Permission errors** - Never use `sudo pip`; use virtual environments
4. **Dependency conflicts** - Create a fresh virtual environment

For comprehensive solutions, see our [Troubleshooting Guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Windows**: Native Windows support is limited; WSL2 or Docker recommended
- **Building from source**: Requires Go 1.23+ with CGO enabled for SQLite support
- **Air-gapped environments**: Requires manual dependency download
