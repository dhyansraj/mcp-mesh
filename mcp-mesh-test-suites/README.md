# MCP Mesh Integration Test Suite

Automated integration tests for MCP Mesh releases.

## Quick Start

```bash
# Install dependencies
cd ../test-suite
pip install -e .

# Run all tests
cd ../mcp-mesh-test-suites
./run.py --all

# Run specific use case
./run.py --uc uc01_scaffolding

# Run specific test
./run.py --tc uc01_scaffolding/tc01_python_agent

# Dry run (list tests)
./run.py --all --dry-run
```

## Configuration

Edit `config.yaml` to set the version to test:

```yaml
packages:
  cli_version: "0.7.21"           # @mcpmesh/cli
  sdk_python_version: "0.7.21"    # mcpmesh (pip)
  sdk_typescript_version: "0.7.21"  # @mcpmesh/sdk
```

## Test Structure

```
mcp-mesh-test-suites/
├── config.yaml              # Version and settings
├── global/
│   └── routines.yaml        # Reusable routines
├── suites/
│   ├── uc01_scaffolding/    # Use case: Scaffolding
│   │   ├── tc01_python_agent/
│   │   │   └── test.yaml
│   │   └── tc02_typescript_agent/
│   │       └── test.yaml
│   ├── uc02_agent_lifecycle/
│   └── uc03_llm_integration/
└── reports/                 # Generated reports
```

## Writing Tests

Create a `test.yaml` file in a new test case directory:

```yaml
name: "My Test"
tags: [smoke, python]

pre_run:
  - routine: global.setup_environment
    params:
      meshctl_version: "${config.packages.cli_version}"

test:
  - handler: shell
    command: "meshctl scaffold agent --name my-agent --language python"
    workdir: /workspace

assertions:
  - expr: ${last.exit_code} == 0
    message: "Command should succeed"
  - expr: ${file:/workspace/my-agent/main.py} exists
    message: "main.py should be created"

post_run:
  - routine: global.cleanup_workspace
```

## CLI Options

| Option | Description |
|--------|-------------|
| `--all` | Run all tests |
| `--uc NAME` | Run tests in use case |
| `--tc PATH` | Run specific test |
| `--tag NAME` | Filter by tag |
| `--dry-run` | List tests only |
| `--verbose` | Show detailed output |
| `--stop-on-fail` | Stop on first failure |

## Environment Variables

For LLM integration tests, create `.env` from `.env.example`:

```bash
cp .env.example .env
# Edit .env with your API keys
```
