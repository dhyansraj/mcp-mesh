# MCP Mesh Source Build Suite

This suite builds MCP Mesh packages from source code, producing a Docker image (`tsuite-mesh:local`) that can be used by the integration test suite for local testing.

## Overview

The build suite runs in **standalone mode** on the host machine. Build commands execute inside Docker containers via `docker run`, and the final test image is built with `docker build`.

The suite compiles:

1. **meshctl** - Go CLI binary
2. **mcp-mesh-core** - Rust core library (Python wheel via maturin)
3. **mcp-mesh** - Python SDK wheel
4. **@mcpmesh/sdk** - TypeScript SDK npm tarball

## Output

After running the suite, you get:

1. **Build artifacts** in `./out/`:

   ```
   out/
   ├── bin/
   │   └── meshctl                    # Go CLI binary
   ├── wheels/
   │   ├── mcp_mesh_core-*.whl       # Rust core wheel
   │   └── mcp_mesh-*.whl            # Python SDK wheel
   └── packages/
       └── mcpmesh-sdk-*.tgz         # TypeScript SDK tarball
   ```

2. **Docker image**: `tsuite-mesh:local`
   - Contains all build artifacts
   - Has `/wheels` and `/packages` directories for local mode detection
   - Ready to use with integration tests

## Usage

### Prerequisites

1. **Docker** must be running on the host
2. **mcp-mesh source** must be available at `../mcp-mesh` (relative to src-tests directory)

### Running the Suite

```bash
# Navigate to src-tests directory
cd src-tests

# Run all tests (builds src-build image, compiles packages, builds final image)
tsuite --all

# Or run specific test cases
tsuite --test tc00  # Build src-build:latest image
tsuite --test tc01  # Build meshctl
tsuite --test tc02  # Build mcp-mesh-core wheel
tsuite --test tc03  # Build mcp-mesh wheel
tsuite --test tc04  # Build TypeScript SDK
tsuite --test tc05  # Verify all artifacts
tsuite --test tc06  # Build tsuite-mesh:local image
```

### Using with Integration Tests

After building `tsuite-mesh:local`:

```bash
# Update integration/config.yaml to use local image
# docker:
#   base_image: "tsuite-mesh:local"

# Run integration tests in docker mode
cd ../integration
tsuite --all --docker
```

The pip-install and npm-install handlers will auto-detect `/wheels` and `/packages` in the image and install from local builds.

## Test Cases

| Test Case                 | Description                             |
| ------------------------- | --------------------------------------- |
| tc00_build_image          | Build src-build:latest with build tools |
| tc01_build_meshctl        | Build meshctl Go binary                 |
| tc02_build_rust_core      | Build mcp-mesh-core Rust wheel          |
| tc03_build_python_sdk     | Build mcp-mesh Python wheel             |
| tc04_build_typescript_sdk | Build @mcpmesh/sdk npm tarball          |
| tc05_verify_artifacts     | Verify all artifacts are present        |
| tc06_build_local_image    | Build tsuite-mesh:local Docker image    |

## Configuration

See `config.yaml`:

```yaml
suite:
  name: "MCP Mesh Source Build"
  mode: standalone # Runs on host, uses docker run for builds

source:
  path: "../mcp-mesh" # Path to mcp-mesh repository (relative to src-tests)

output:
  base: "./out"
  bin: "./out/bin"
  wheels: "./out/wheels"
  packages: "./out/packages"

build:
  image: "src-build:latest" # Image with build tools

docker:
  output_image: "tsuite-mesh:local" # Final test image
```

## Build Tools Image

The `src-build:latest` image includes:

- Go 1.23
- Rust (latest stable)
- Python 3.11 + maturin
- Node.js 20

This image is built automatically by tc00. The Dockerfile is at `src-tests/Dockerfile`.

## CI Integration

```yaml
# GitHub Actions example
jobs:
  build-local:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Checkout mcp-mesh
        uses: actions/checkout@v4
        with:
          repository: dhyansraj/mcp-mesh
          path: mcp-mesh

      - name: Install tsuite
        run: pip install tsuite

      - name: Build local packages and image
        run: |
          cd src-tests
          tsuite --all

      - name: Run integration tests with local image
        run: |
          cd integration
          # Update config to use tsuite-mesh:local
          sed -i 's/base_image:.*/base_image: "tsuite-mesh:local"/' config.yaml
          tsuite --all --docker
```

## Workflow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     HOST (standalone mode)                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  tc00: docker build → src-build:latest                      │
│                                                             │
│  tc01-tc04: docker run src-build:latest "build command"     │
│             ↓                                               │
│  ./out/bin/meshctl                                          │
│  ./out/wheels/*.whl                                         │
│  ./out/packages/*.tgz                                       │
│                                                             │
│  tc05: verify artifacts exist                               │
│                                                             │
│  tc06: docker build → tsuite-mesh:local                     │
│        (copies artifacts from ./out/ into image)            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
