# Development Environment Setup

> Configure your IDE, tools, and workspace for productive MCP Mesh development

## Overview

A well-configured development environment is crucial for productive MCP Mesh development. This guide will help you set up your IDE with debugging capabilities, configure essential tools, and establish best practices that will accelerate your development workflow.

We'll cover setup for popular IDEs (VS Code, PyCharm/WebStorm), essential development tools, and productivity enhancers that make working with distributed MCP agents a breeze.

## Key Concepts

- **IDE Integration**: Debugging, IntelliSense, and code navigation for MCP Mesh
- **Project Setup**: Python virtual environments or Node.js projects
- **Development Tools**: Linters, formatters, and type checkers
- **Environment Variables**: Managing configuration across development stages
- **Git Workflow**: Version control best practices for MCP projects

## Step-by-Step Guide

### Step 1: Choose and Configure Your IDE

#### VS Code Setup

=== "Python"

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

=== "TypeScript"

    ```bash
    # Install TypeScript/JavaScript extensions
    code --install-extension dbaeumer.vscode-eslint
    code --install-extension esbenp.prettier-vscode
    code --install-extension redhat.vscode-yaml
    ```

    Create `.vscode/settings.json` in your project:

    ```json
    {
      "editor.formatOnSave": true,
      "editor.defaultFormatter": "esbenp.prettier-vscode",
      "editor.codeActionsOnSave": {
        "source.fixAll.eslint": "explicit"
      },
      "typescript.preferences.importModuleSpecifier": "relative",
      "[typescript]": {
        "editor.rulers": [100]
      }
    }
    ```

#### PyCharm / WebStorm Setup

=== "Python (PyCharm)"

    1. Open PyCharm → Preferences → Project → Python Interpreter
    2. Click gear icon → Add → Virtual Environment
    3. Select existing `.venv` or create new
    4. Enable: File → Settings → Tools → Python Integrated Tools → Docstring format: Google

=== "TypeScript (WebStorm)"

    1. Open WebStorm → Preferences → Languages & Frameworks → TypeScript
    2. Ensure TypeScript version is set to project's `node_modules/typescript`
    3. Enable: Preferences → Languages & Frameworks → JavaScript → Code Quality Tools → ESLint

### Step 2: Set Up Your Project

=== "Python"

    ```bash
    # Create project-specific virtual environment
    python -m venv .venv

    # Activate it
    source .venv/bin/activate  # Linux/macOS
    # or
    .venv\Scripts\activate     # Windows

    # Upgrade pip and essential tools
    pip install --upgrade pip setuptools wheel

    # Install MCP Mesh SDK
    pip install "mcp-mesh>=0.8,<0.9"
    ```

=== "TypeScript"

    ```bash
    # Initialize npm project
    npm init -y

    # Install MCP Mesh SDK and runtime dependencies
    npm install @mcpmesh/sdk zod

    # Install development dependencies
    npm install -D typescript tsx @types/node

    # Create src directory
    mkdir src
    ```

### Step 3: Configure Development Tools

=== "Python"

    Create `pyproject.toml` for modern Python tooling:

    ```toml
    [tool.black]
    line-length = 88
    target-version = ['py311']

    [tool.pylint.messages_control]
    disable = "C0330, C0326"

    [tool.mypy]
    python_version = "3.11"
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

=== "TypeScript"

    Create `tsconfig.json`:

    ```json
    {
      "compilerOptions": {
        "target": "ES2022",
        "module": "NodeNext",
        "moduleResolution": "NodeNext",
        "esModuleInterop": true,
        "strict": true,
        "skipLibCheck": true,
        "outDir": "dist",
        "declaration": true,
        "sourceMap": true
      },
      "include": ["src/**/*"],
      "exclude": ["node_modules", "dist"]
    }
    ```

    Update `package.json` scripts:

    ```json
    {
      "type": "module",
      "scripts": {
        "start": "tsx src/index.ts",
        "dev": "tsx watch src/index.ts",
        "build": "tsc",
        "test": "vitest",
        "lint": "eslint src/"
      }
    }
    ```

    Install development tools:

    ```bash
    # Testing
    npm install -D vitest

    # Linting (optional)
    npm install -D eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin
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

=== "Python"

    ```
    my-mcp-project/
    ├── .venv/                 # Virtual environment
    ├── .env                   # Local environment variables
    ├── .env.example           # Template for team
    ├── .gitignore             # Git ignore rules
    ├── pyproject.toml         # Python project config
    ├── agents/
    │   ├── __init__.py
    │   ├── weather_agent.py   # Your MCP agents
    │   └── database_agent.py
    ├── tests/
    │   ├── __init__.py
    │   ├── test_weather.py    # Agent tests
    │   └── test_database.py
    └── README.md
    ```

=== "TypeScript"

    ```
    my-mcp-project/
    ├── node_modules/          # npm dependencies
    ├── .env                   # Local environment variables
    ├── .env.example           # Template for team
    ├── .gitignore             # Git ignore rules
    ├── package.json           # npm project config
    ├── tsconfig.json          # TypeScript config
    ├── agents/
    │   ├── weather-agent/
    │   │   └── src/index.ts   # Your MCP agents
    │   └── database-agent/
    │       └── src/index.ts
    ├── tests/
    │   ├── weather.test.ts    # Agent tests
    │   └── database.test.ts
    └── README.md
    ```

### Example 2: VS Code Debug Configuration

=== "Python"

    Create `.vscode/launch.json`:

    ```json
    {
      "version": "0.2.0",
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

=== "TypeScript"

    Create `.vscode/launch.json`:

    ```json
    {
      "version": "0.2.0",
      "configurations": [
        {
          "name": "Debug Weather Agent",
          "type": "node",
          "request": "launch",
          "runtimeExecutable": "npx",
          "runtimeArgs": ["tsx", "agents/weather-agent/src/index.ts"],
          "console": "integratedTerminal",
          "env": {
            "MCP_MESH_LOG_LEVEL": "DEBUG"
          }
        },
        {
          "name": "Debug with Watch",
          "type": "node",
          "request": "launch",
          "runtimeExecutable": "npx",
          "runtimeArgs": ["tsx", "watch", "agents/weather-agent/src/index.ts"],
          "console": "integratedTerminal"
        }
      ]
    }
    ```

## Best Practices

=== "Python"

    1. **Always Use Virtual Environments**: Keep dependencies isolated and reproducible
    2. **Version Control Your Config**: Track `.env.example` but never `.env`
    3. **Automate Code Quality**: Use pre-commit hooks for black, pylint, mypy
    4. **Document Dependencies**: Keep `requirements.txt` or use `poetry`/`pipenv`
    5. **Use Type Hints**: Enable better IDE support and catch errors early

=== "TypeScript"

    1. **Use Package Lock Files**: Commit `package-lock.json` for reproducible installs
    2. **Version Control Your Config**: Track `.env.example` but never `.env`
    3. **Automate Code Quality**: Use ESLint and Prettier with pre-commit hooks
    4. **Enable Strict Mode**: Use `"strict": true` in `tsconfig.json`
    5. **Use Zod for Validation**: Define tool parameters with Zod schemas

## Common Pitfalls

### Pitfall 1: Global Package Conflicts

=== "Python"

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

=== "TypeScript"

    **Problem**: Global npm packages cause version conflicts

    **Solution**: Use project-local dependencies:

    ```bash
    # Never do this (globally)
    npm install -g @mcpmesh/sdk

    # Always do this (project-local)
    npm install @mcpmesh/sdk
    ```

### Pitfall 2: Missing Environment Variables

=== "Python"

    **Problem**: Agents fail to start due to missing configuration

    **Solution**: Use python-dotenv for automatic loading:

    ```python
    # In your agent files
    from dotenv import load_dotenv
    load_dotenv()  # Load .env file automatically
    ```

=== "TypeScript"

    **Problem**: Agents fail to start due to missing configuration

    **Solution**: Use dotenv for automatic loading:

    ```typescript
    // At the top of src/index.ts
    import "dotenv/config";
    ```

    Or install and configure:

    ```bash
    npm install dotenv
    ```

## Testing

### Unit Test Example

=== "Python"

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

=== "TypeScript"

    ```typescript
    // tests/agent.test.ts
    import { describe, it, expect } from "vitest";
    import { z } from "zod";

    describe("Tool Schema", () => {
      it("should validate parameters correctly", () => {
        const schema = z.object({
          a: z.number(),
          b: z.number(),
        });

        const result = schema.safeParse({ a: 1, b: 2 });
        expect(result.success).toBe(true);
      });
    });
    ```

### Integration Test Example

=== "Python"

    ```python
    # tests/test_environment.py
    import os
    import pytest

    def test_environment_variables():
        """Ensure development environment is configured"""
        assert os.getenv('MCP_MESH_REGISTRY_URL') is not None
        assert os.getenv('MCP_MESH_LOG_LEVEL') == 'DEBUG'
    ```

=== "TypeScript"

    ```typescript
    // tests/environment.test.ts
    import { describe, it, expect } from "vitest";

    describe("Environment", () => {
      it("should have required environment variables", () => {
        expect(process.env.MCP_MESH_REGISTRY_URL).toBeDefined();
      });
    });
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

### Issue 1: IDE Can't Find Imports

=== "Python"

    **Symptoms**: Red squiggles under `from mcp_mesh import mesh_agent`

    **Cause**: IDE using wrong Python interpreter

    **Solution**:

    ```bash
    # VS Code: Ctrl+Shift+P → Python: Select Interpreter
    # Choose the .venv interpreter

    # PyCharm: Settings → Project → Python Interpreter
    # Select .venv/bin/python
    ```

=== "TypeScript"

    **Symptoms**: Red squiggles under `import { mesh } from "@mcpmesh/sdk"`

    **Cause**: TypeScript can't find the module

    **Solution**:

    ```bash
    # Ensure dependencies are installed
    npm install

    # Restart TypeScript server in VS Code
    # Ctrl+Shift+P → TypeScript: Restart TS Server
    ```

### Issue 2: Permission / Path Issues

=== "Python"

    **Symptoms**: Can't activate venv on macOS/Linux

    **Cause**: Missing execute permissions

    **Solution**:

    ```bash
    chmod +x .venv/bin/activate
    source .venv/bin/activate
    ```

=== "TypeScript"

    **Symptoms**: `npx tsx` command not found

    **Cause**: Node.js not in PATH or wrong version

    **Solution**:

    ```bash
    # Check Node.js version (requires 18+)
    node --version

    # Reinstall dependencies
    rm -rf node_modules package-lock.json
    npm install
    ```

For more issues, see the [section troubleshooting guide](./troubleshooting.md).

## ⚠️ Known Limitations

=== "Python"

    - **Windows Path Length**: Virtual environment paths can exceed Windows limits - use short project names
    - **Python 3.10 or below**: Not supported - requires Python 3.11+
    - **ARM Macs**: Some dependencies may need Rosetta 2 for M1/M2 Macs

=== "TypeScript"

    - **Node.js 16 or below**: Not supported - requires Node.js 18+
    - **CommonJS modules**: SDK uses ESM - ensure `"type": "module"` in package.json
    - **Windows**: Use PowerShell or Git Bash, not CMD

## Summary

You now have a professional development environment configured for MCP Mesh development with:

Key takeaways:

- 🔑 IDE configured with debugging and IntelliSense support
- 🔑 Project isolation (Python venv or Node.js project)
- 🔑 Development tools for code quality and testing
- 🔑 Environment variables managing configuration

## Next Steps

Now that your environment is set up, let's run the MCP Mesh registry locally for development.

Continue to [Running Registry Locally](./02-local-registry.md) →

---

=== "Python"

    💡 **Tip**: Use `direnv` to automatically activate your virtual environment when entering the project directory

    📚 **Reference**: [Python Development Best Practices](https://docs.python-guide.org/dev/env/)

    🧪 **Try It**: Create a simple "Hello Developer" agent and debug it using your IDE's debugger

=== "TypeScript"

    💡 **Tip**: Use `npm run dev` with `tsx watch` for automatic reload during development

    📚 **Reference**: [TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/)

    🧪 **Try It**: Create a simple "Hello Developer" agent and debug it using your IDE's debugger
