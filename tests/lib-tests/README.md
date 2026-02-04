# MCP Mesh Library Test Suite

Tests MCP Mesh package availability and builds the `tsuite-mesh` base image for faster integration testing.

## Purpose

1. **Verify packages are published** - Tests that all MCP Mesh packages exist on npm/PyPI
2. **Verify packages are installable** - Tests that packages install correctly
3. **Build base image** - Creates `tsuite-mesh:X.Y.Z` with all packages pre-installed

## Prerequisites

**IMPORTANT:** Use Python 3.11 for the virtual environment. The `mcp-mesh-core` Rust package only has pre-built wheels for Python 3.11.

```bash
# Create venv with Python 3.11 (required for mcp-mesh-core wheels)
cd /path/to/mcp-mesh/mcp-mesh-lib-test-suites
python3.11 -m venv venv
source venv/bin/activate
pip install -e ../tsuite
```

## Usage

```bash
cd /path/to/mcp-mesh/mcp-mesh-lib-test-suites

# Activate venv if using local installation
source venv/bin/activate

# Run all tests (WITHOUT --docker flag!)
tsuite --all

# Or run specific use case
tsuite --uc uc01_npm_packages
tsuite --uc uc02_pip_packages
tsuite --uc uc03_build_image
```

**IMPORTANT:** Run WITHOUT `--docker` flag. These tests run on the host machine because:

- They check npm/PyPI registries
- They build Docker images

## Test Cases

### UC01: npm Packages

- `tc01_cli_package` - Verify `@mcpmesh/cli` exists, installs, `--version` works
- `tc02_sdk_package` - Verify `@mcpmesh/sdk` exists and installs
- `tc03_core_package` - Verify `@mcpmesh/core` exists and installs

### UC02: pip Packages

- `tc01_mcpmesh_package` - Verify `mcp-mesh` exists on PyPI, installs, is importable

### UC03: Build Image

- `tc01_build_base` - Build `tsuite-mesh:X.Y.Z` Docker image

## Output

After successful run, you'll have:

- `tsuite-mesh:0.9.0-beta.6` (or current version) Docker image

Verify with:

```bash
docker images | grep tsuite-mesh
```

## Configuration

Edit `config.yaml` to update versions:

```yaml
packages:
  cli_version: "0.9.0-beta.6"
  sdk_python_version: "0.9.0-beta.6" # PEP 440 format for Python
  sdk_typescript_version: "0.9.0-beta.6"
  core_version: "0.9.0-beta.6"
```

## Next Steps

After building the base image, run integration tests:

```bash
cd ../mcp-mesh-test-suites
source venv/bin/activate
tsuite --all --docker
```
