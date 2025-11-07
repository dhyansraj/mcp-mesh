# Development Environment Setup

> Configure your IDE, tools, and workspace for productive MCP Mesh development

## Overview

A well-configured development environment is crucial for productive MCP Mesh development. This guide will help you set up your IDE with debugging capabilities, configure essential tools, and establish best practices that will accelerate your development workflow.

We'll cover setup for popular IDEs (VS Code, PyCharm), essential development tools, and productivity enhancers that make working with distributed MCP agents a breeze.

## Key Concepts

- **IDE Integration**: Debugging, IntelliSense, and code navigation for MCP Mesh
- **Virtual Environments**: Isolated Python environments for each project
- **Development Tools**: Linters, formatters, and type checkers
- **Environment Variables**: Managing configuration across development stages
- **Git Workflow**: Version control best practices for MCP projects

## Step-by-Step Guide

### Step 1: Choose and Configure Your IDE

#### VS Code Setup

```bash
# Install Python extension
code --install-extension ms-python.python

# Install helpful extensions for MCP development
code --install-extension ms-python.vscode-pylance
code --install-extension ms-python.debugpy
code --install-extension redhat.vscode-yaml
```

Create `.vscode/settings.json` in your project:

```json
{
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": true,
  "python.formatting.provider": "black",
  "python.testing.pytestEnabled": true,
  "python.testing.unittestEnabled": false,
  "editor.formatOnSave": true,
  "python.envFile": "${workspaceFolder}/.env",
  "[python]": {
    "editor.rulers": [88],
    "editor.codeActionsOnSave": {
      "source.organizeImports": true
    }
  }
}
```

#### PyCharm Setup

1. Open PyCharm → Preferences → Project → Python Interpreter
2. Click gear icon → Add → Virtual Environment
3. Select existing `.venv` or create new
4. Enable: File → Settings → Tools → Python Integrated Tools → Docstring format: Google

### Step 2: Create a Robust Virtual Environment

```bash
# Create project-specific virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate     # Windows

# Upgrade pip and essential tools
pip install --upgrade pip setuptools wheel

# Install MCP Mesh from source (not yet on PyPI)
cd /path/to/mcp-mesh
make install-dev  # Installs all dependencies and builds binaries
```

### Step 3: Configure Development Tools

Create `pyproject.toml` for modern Python tooling:

```toml
[tool.black]
line-length = 88
target-version = ['py39']

[tool.pylint.messages_control]
disable = "C0330, C0326"

[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_functions = "test_*"
```

Install development tools:

```bash
# Code quality tools
pip install black pylint mypy

# Testing tools
pip install pytest pytest-cov pytest-asyncio

# Development utilities
pip install ipython rich watchdog
```

### Step 4: Set Up Environment Variables

Create `.env` file for local development:

```bash
# MCP Mesh Configuration
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_LOG_LEVEL=DEBUG
MCP_MESH_DEBUG_MODE=true

# Agent Configuration
MCP_MESH_HTTP_HOST=0.0.0.0
MCP_MESH_HTTP_PORT=0  # Auto-assign port
MCP_MESH_AUTO_RUN=true

# Development Settings
PYTHONPATH=.
MCP_DEV_MODE=true
```

Create `.env.example` for team members:

```bash
# Copy this to .env and configure for your environment
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_LOG_LEVEL=INFO
MCP_MESH_DEBUG_MODE=false
MCP_MESH_AUTO_RUN=true
```

## Configuration Options

| Option                       | Description                 | Default               | Example               |
| ---------------------------- | --------------------------- | --------------------- | --------------------- |
| `MCP_MESH_LOG_LEVEL`         | Logging verbosity           | INFO                  | DEBUG, WARNING, ERROR |
| `MCP_MESH_REGISTRY_URL`      | Registry endpoint           | http://localhost:8080 | http://registry:8080  |
| `MCP_MESH_DB_TYPE`           | Database backend            | sqlite                | postgresql, sqlite    |
| `MCP_MESH_ENABLE_HOT_RELOAD` | Auto-reload on file changes | false                 | true                  |
| `MCP_DEV_MODE`               | Enable development features | false                 | true                  |

## Examples

### Example 1: Basic Project Structure

```
my-mcp-project/
├── .venv/                 # Virtual environment
├── .env                   # Local environment variables
├── .env.example          # Template for team
├── .gitignore            # Git ignore rules
├── pyproject.toml        # Python project config
├── agents/
│   ├── __init__.py
│   ├── weather_agent.py  # Your MCP agents
│   └── database_agent.py
├── tests/
│   ├── __init__.py
│   ├── test_weather.py   # Agent tests
│   └── test_database.py
└── README.md
```

### Example 2: VS Code Debug Configuration

Create `.vscode/launch.json`:

```json
{
  "version": "0.5.7",
  "configurations": [
    {
      "name": "Debug Weather Agent",
      "type": "python",
      "request": "launch",
      "module": "mcp_mesh.cli",
      "args": ["start", "agents/weather_agent.py"],
      "console": "integratedTerminal",
      "env": {
        "MCP_MESH_LOG_LEVEL": "DEBUG"
      }
    },
    {
      "name": "Debug All Agents",
      "type": "python",
      "request": "launch",
      "module": "mcp_mesh.cli",
      "args": ["start", "agents/"],
      "console": "integratedTerminal"
    }
  ]
}
```

## Best Practices

1. **Always Use Virtual Environments**: Keep dependencies isolated and reproducible
2. **Version Control Your Config**: Track `.env.example` but never `.env`
3. **Automate Code Quality**: Use pre-commit hooks for black, pylint, mypy
4. **Document Dependencies**: Keep `requirements.txt` or use `poetry`/`pipenv`
5. **Use Type Hints**: Enable better IDE support and catch errors early

## Common Pitfalls

### Pitfall 1: Global Package Conflicts

**Problem**: Installing MCP Mesh globally conflicts with other projects

**Solution**: Always use virtual environments:

```bash
# Never do this
pip install mcp-mesh  # Global install

# Always do this
python -m venv .venv
source .venv/bin/activate
pip install mcp-mesh
```

### Pitfall 2: Missing Environment Variables

**Problem**: Agents fail to start due to missing configuration

**Solution**: Use python-dotenv for automatic loading:

```python
# In your agent files
from dotenv import load_dotenv
load_dotenv()  # Load .env file automatically
```

## Testing

### Unit Test Example

```python
# tests/test_agent_setup.py
import pytest
from mcp_mesh import mesh_agent

def test_agent_decorator():
    """Test that mesh_agent decorator works"""
    @mesh_agent(capability="test")
    def test_function():
        return "test"

    assert hasattr(test_function, '_mesh_config')
    assert test_function._mesh_config['capability'] == 'test'
```

### Integration Test Example

```python
# tests/test_environment.py
import os
import pytest

def test_environment_variables():
    """Ensure development environment is configured"""
    assert os.getenv('MCP_MESH_REGISTRY_URL') is not None
    assert os.getenv('MCP_MESH_LOG_LEVEL') == 'DEBUG'
```

## Monitoring and Debugging

### Logs to Check

```bash
# MCP Mesh logs location
tail -f ~/.mcp-mesh/logs/mcp-mesh.log

# Filter for specific agent
grep "weather_agent" ~/.mcp-mesh/logs/mcp-mesh.log

# Watch for errors in real-time
tail -f ~/.mcp-mesh/logs/mcp-mesh.log | grep ERROR
```

### Metrics to Monitor

- **Import Time**: Agent startup should be < 2 seconds
- **Memory Usage**: Monitor with `htop` or Activity Monitor
- **File Descriptors**: Check `lsof -p <pid>` for leaks

## 🔧 Troubleshooting

### Issue 1: IDE Can't Find MCP Mesh Imports

**Symptoms**: Red squiggles under `from mcp_mesh import mesh_agent`

**Cause**: IDE using wrong Python interpreter

**Solution**:

```bash
# VS Code: Ctrl+Shift+P → Python: Select Interpreter
# Choose the .venv interpreter

# PyCharm: Settings → Project → Python Interpreter
# Select .venv/bin/python
```

### Issue 2: Permission Denied on Virtual Environment

**Symptoms**: Can't activate venv on macOS/Linux

**Cause**: Missing execute permissions

**Solution**:

```bash
chmod +x .venv/bin/activate
source .venv/bin/activate
```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Windows Path Length**: Virtual environment paths can exceed Windows limits - use short project names
- **Python 3.8**: Not supported - requires Python 3.9+
- **ARM Macs**: Some dependencies may need Rosetta 2 for M1/M2 Macs

## 📝 TODO

- [ ] Add support for Poetry and Pipenv workflows
- [ ] Create IDE plugin for MCP Mesh
- [ ] Add devcontainer configuration
- [ ] Support for Jupyter notebook development

## Summary

You now have a professional development environment configured for MCP Mesh development with:

Key takeaways:

- 🔑 IDE configured with debugging and IntelliSense support
- 🔑 Virtual environment isolating your dependencies
- 🔑 Development tools for code quality and testing
- 🔑 Environment variables managing configuration

## Next Steps

Now that your environment is set up, let's run the MCP Mesh registry locally for development.

Continue to [Running Registry Locally](./02-local-registry.md) →

---

💡 **Tip**: Use `direnv` to automatically activate your virtual environment when entering the project directory

📚 **Reference**: [Python Development Best Practices](https://docs.python-guide.org/dev/env/)

🧪 **Try It**: Create a simple "Hello Developer" agent and debug it using your IDE's debugger
