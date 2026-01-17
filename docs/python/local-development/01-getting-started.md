# Getting Started (Python)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/local-development/01-getting-started/">TypeScript Getting Started</a></span>
</div>

> Install meshctl CLI and Python SDK

## Prerequisites

- **Node.js 18+** - for meshctl CLI
- **Python 3.11+** - for agent development

## Install meshctl CLI

```bash
npm install -g @mcpmesh/cli

# Verify
meshctl --version
```

## Set Up Python Environment

Create a virtual environment at your **project root**. All agents share this single venv—don't create separate venvs inside agent folders.

```bash
# Create project directory
mkdir my-mesh-project
cd my-mesh-project

# Create venv (one-time setup)
python3 -m venv .venv

# Activate only for pip commands
source .venv/bin/activate         # macOS/Linux
# .venv\Scripts\activate          # Windows

# Install SDK
pip install --upgrade pip
pip install "mcp-mesh>=0.8,<0.9"

# Verify
python -c "import mesh; print('Ready!')"

# Can deactivate after pip install
deactivate
```

!!! info "meshctl auto-detects .venv"
`meshctl` is a Go binary that auto-detects `.venv` in the current directory. You only need to activate the venv for `pip` commands—meshctl commands work without activation.

## Quick Start

```bash
# 1. Scaffold an agent (interactive wizard)
meshctl scaffold

# 2. Edit hello/main.py to implement your tool logic

# 3. Run agent (meshctl uses .venv/bin/python automatically)
meshctl start hello/main.py --debug
```

The scaffolded code includes placeholder tools—edit `main.py` to add your logic.

## Next Steps

Continue to [Scaffold Agents](./02-scaffold.md) →
