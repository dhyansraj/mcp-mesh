# Prerequisites

What you need before starting Day 1 of the TripPlanner tutorial.

## Supported platforms

- macOS (Intel or Apple Silicon)
- Linux (x86_64 or ARM64)
- Windows via WSL2

## meshctl

`meshctl` is the command-line tool you'll use to start, inspect, and call agents.

```bash
npm install -g @mcpmesh/cli
```

### Verify

```bash
meshctl --version
```

## Language runtime

### Python 3.11 or later

```bash
# Check your version
python3 --version

# Install if needed
brew install python@3.11          # macOS (Homebrew)
sudo apt install python3.11       # Ubuntu/Debian
```

### Virtual environment

Create a `.venv` in your project root and install `mcp-mesh` into it. `meshctl`
auto-detects `.venv` when starting an agent — you only need to activate it when
running `pip`.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install mcp-mesh
deactivate
```

### Verify

```bash
.venv/bin/python -c "import mesh; print('mesh OK')"
```

!!! note "Other languages"
    This tutorial uses Python. For TypeScript or Java setup, see the
    [TypeScript prerequisites](../typescript/getting-started/prerequisites.md) and
    [Java prerequisites](../java/getting-started/prerequisites.md).

## Ready to start

Once `meshctl --version` prints a version and `.venv/bin/python -c "import mesh"`
succeeds, you're ready for [Day 1](day-01-scaffold.md).
