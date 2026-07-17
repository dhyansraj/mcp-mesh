# MCP Mesh Integration Test Suite

Automated integration tests for MCP Mesh releases. Tests run inside Docker containers using the `tsuite-mesh` base image.

## Prerequisites

1. **Build the base image first** (from `mcp-mesh-lib-test-suites`):

   ```bash
   cd ../mcp-mesh-lib-test-suites
   source venv/bin/activate
   tsuite --all
   # This builds tsuite-mesh:X.Y.Z Docker image
   ```

2. **Install tsuite in this directory**:
   ```bash
   cd ../mcp-mesh-test-suites
   python3 -m venv venv
   source venv/bin/activate
   pip install -e ../tsuite
   ```

## Quick Start

```bash
cd /path/to/mcp-mesh/mcp-mesh-test-suites
source venv/bin/activate

# Run all tests in Docker
tsuite --all --docker

# Run specific use case
tsuite --uc uc01_registry --docker
tsuite --uc uc02_tools --docker
tsuite --uc uc03_capabilities --docker

# Run specific test case
tsuite --tc uc01_registry/tc01_agent_registration --docker

# Dry run (list tests without running)
tsuite --all --docker --dry-run

# Verbose output
tsuite --uc uc01_registry --docker -v
```

## Test Structure

```
mcp-mesh-test-suites/
├── config.yaml              # Version and Docker settings
├── global/
│   └── routines.yaml        # Reusable setup/cleanup routines
├── suites/
│   ├── uc01_registry/       # Registry & Discovery tests
│   │   ├── artifacts/       # Shared test agents
│   │   ├── tc01_agent_registration/
│   │   ├── tc02_agent_discovery/
│   │   └── ...
│   ├── uc02_tools/          # Tool call tests
│   ├── uc03_capabilities/   # Tag & selector tests
│   ├── uc04_llm_integration/# LLM provider tests
│   └── uc05_scaffold/       # Scaffolding tests
├── results.db               # SQLite test results
└── venv/                    # Python virtual environment
```

## CLI Options

| Option            | Description                                                       |
| ----------------- | ----------------------------------------------------------------- |
| `--all`           | Run all tests                                                     |
| `--uc NAME`       | Run tests in use case (e.g., `uc01_registry`)                     |
| `--tc PATH`       | Run specific test (e.g., `uc01_registry/tc01_agent_registration`) |
| `--tag NAME`      | Filter by tag (e.g., `python`, `typescript`)                      |
| `--skip-tag NAME` | Skip tests with tag (e.g., `disabled`, `llm`)                     |
| `--docker`        | Run tests in Docker containers                                    |
| `--dry-run`       | List tests without running                                        |
| `-v, --verbose`   | Show detailed output                                              |
| `--stop-on-fail`  | Stop on first failure                                             |

## Common Commands

```bash
# Run only Python tests
tsuite --uc uc03_capabilities --tag python --docker

# Run only TypeScript tests
tsuite --uc uc03_capabilities --tag typescript --docker

# Skip disabled tests
tsuite --all --docker --skip-tag disabled

# Skip LLM tests (require API keys)
tsuite --all --docker --skip-tag llm
```

## Configuration

Edit `config.yaml` to set versions:

```yaml
packages:
  cli_version: "3.2.1" # @mcpmesh/cli
  sdk_python_version: "3.2.1" # mcp-mesh (pip) - PEP 440 format
  sdk_typescript_version: "3.2.1" # @mcpmesh/sdk

docker:
  base_image: "tsuite-mesh:3.2.1"
```

## Environment Variables

For LLM integration tests, set API keys:

```bash
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

Or create `.env` file:

```bash
ANTHROPIC_API_KEY=your-key
OPENAI_API_KEY=your-key
```

## Writing Tests

Create a `test.yaml` file in a new test case directory:

```yaml
name: "My Test"
description: "Test description"
tags:
  - smoke
  - python
timeout: 120

pre_run:
  - routine: global.setup_for_python_agent
    params:
      meshctl_version: "${config.packages.cli_version}"
      mcpmesh_version: "${config.packages.sdk_python_version}"

test:
  - handler: shell
    command: "meshctl start my-agent/main.py -d"
    workdir: /workspace
    capture: start_output

  - handler: wait
    seconds: 10

  - handler: shell
    command: "meshctl list"
    workdir: /workspace
    capture: list_output

assertions:
  - expr: "${captured.list_output} contains 'my-agent'"
    message: "Agent should be registered"

post_run:
  - handler: shell
    command: "meshctl stop 2>/dev/null || true"
    workdir: /workspace
    ignore_errors: true
  - routine: global.cleanup_workspace
```

## Timeout budgets & the shared build cache

Per-TC `timeout` values assume the shared maven/npm build cache is **warm**:
the suite/runner populates it once, and per-TC workspaces reuse it. Timeouts
are sized for the warm case plus slack — NOT a cold-cache sum of step budgets.
This is the suite's actual, working convention: most existing TCs run at
120–420s with one or two `maven-install`/`npm-install` steps whose individual
step budgets alone would exceed the TC timeout on a cold cache.

When writing new TCs:

- Size the `timeout` for the warm case with reasonable slack. Do NOT budget a
  full cold `maven-install`/`npm-install` (~600s each) unless the TC can
  genuinely run first on a cold cache.
- A few of the newest TCs (uc37 tc08–tc12) carry explicit cold-cache
  step-budget arithmetic in their header comments as extra headroom. That is
  acceptable defensive slack, not the required norm — don't sweep existing
  timeouts up to match, and don't feel obliged to replicate the arithmetic.

## Test Results

Results are stored in `results.db` (SQLite). View recent runs:

```bash
tsuite --history
```

## Troubleshooting

### "No tests match criteria"

- Check that the test path is correct: `tsuite --tc uc01_registry/tc01_agent_registration --docker`
- Use `--dry-run` to see available tests

### Tests fail with package errors

- Rebuild the base image: `cd ../mcp-mesh-lib-test-suites && tsuite --all`
- Check version in `config.yaml` matches built image

### TypeScript tests take too long

- TypeScript agents use `tsx` for transpilation, adding startup overhead
- Increase `timeout` in test.yaml if needed
