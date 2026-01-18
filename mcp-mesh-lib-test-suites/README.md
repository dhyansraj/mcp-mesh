# MCP Mesh Library Test Suite

Tests MCP Mesh package availability and builds the `tsuite-mesh` base image for faster integration testing.

## Purpose

1. **Verify packages are published** - Tests that all MCP Mesh packages exist on npm/PyPI
2. **Verify packages are installable** - Tests that packages install correctly
3. **Build base image** - Creates `tsuite-mesh:X.Y.Z` with all packages pre-installed

## Usage

```bash
# From test-suite directory
cd /path/to/mcp-mesh/test-suite

# Run lib-test-suites (WITHOUT --docker flag!)
tsuite --all --suite-path ../mcp-mesh-lib-test-suites

# Or from lib-test-suites directory
cd /path/to/mcp-mesh/mcp-mesh-lib-test-suites
tsuite --all
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
- `tsuite-mesh:0.8.0-beta.6` (or current version) Docker image

## Using the Built Image

Update `mcp-mesh-test-suites/config.yaml`:

```yaml
docker:
  base_image: "tsuite-mesh:0.8.0-beta.6"
```

Then run integration tests:

```bash
cd mcp-mesh-test-suites
tsuite --all --docker
```

## Configuration

Edit `config.yaml` to update versions:

```yaml
packages:
  cli_version: "0.8.0-beta.6"
  sdk_python_version: "0.8.0b6"  # PEP 440 format
  sdk_typescript_version: "0.8.0-beta.6"
  core_version: "0.8.0-beta.6"
```
