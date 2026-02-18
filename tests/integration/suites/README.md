# Test Suites Development Guide

Quick reference for writing and debugging MCP Mesh integration tests.

## Directory Structure

```
suites/
├── uc01_registry/
│   ├── artifacts/           # UC-level shared artifacts (mounted at /uc-artifacts)
│   │   ├── py-simple-agent/
│   │   └── ts-simple-agent/
│   ├── tc01_agent_registration/
│   │   ├── artifacts/       # TC-level artifacts (mounted at /artifacts)
│   │   └── test.yaml
│   └── tc02_agent_discovery/
│       └── test.yaml
```

## Key Patterns

### 1. Artifact Mounting

- **TC-level**: `/artifacts` → `suites/<uc>/<tc>/artifacts/`
- **UC-level**: `/uc-artifacts` → `suites/<uc>/artifacts/`

### 2. Version Placeholders

Use `__PLACEHOLDER__` syntax in artifacts, replace with sed after copy:

```yaml
- handler: shell
  command: |
    cp -r /uc-artifacts/ts-agent /workspace/
    sed -i "s/__SDK_VERSION__/${config.packages.sdk_typescript_version}/g" /workspace/ts-agent/package.json
```

### 3. Running Agents

**Always use `meshctl start` from `/workspace`:**

```yaml
- handler: shell
  command: "meshctl start my-agent/main.py -d"
  workdir: /workspace
```

Why:

- `meshctl start` auto-starts registry if not running
- Expects `.venv` in CWD (created by `setup_for_python_agent` at `/workspace/.venv`)
- Use `-d` for detached mode

### 4. Standard Pre-run

```yaml
pre_run:
  - routine: global.setup_for_python_agent
    params:
      meshctl_version: "${config.packages.cli_version}"
      mcpmesh_version: "${config.packages.sdk_python_version}"
```

### 5. Standard Post-run

```yaml
post_run:
  - handler: shell
    command: "meshctl stop 2>/dev/null || true"
    workdir: /workspace
    ignore_errors: true
  - routine: global.cleanup_workspace
```

## Agent Code Requirements

### Python

```python
@mesh.agent(
    name="my-agent",
    http_port=9000,      # Set port here, not via --port flag
    auto_run=True,
)
class MyAgent:
    pass
```

### TypeScript

```typescript
const agent = mesh(server, {
  name: "my-agent",
  port: 9001, // Set port here
});
```

## Debugging

### Run single test verbose:

```bash
./venv/bin/tsuite --tc uc01_registry/tc01_agent_registration --docker -v
```

### Test manually in container:

```bash
docker run --rm -it \
  -v $(pwd)/suites/uc01_registry/artifacts:/uc-artifacts:ro \
  tsuite-mesh:0.9.5 bash
```

### Common issues:

- **"prerequisite check failed"**: Run from `/workspace`, not agent directory
- **"Connection refused"**: Use `meshctl start` not `python main.py`
- **npm version errors**: Check `__SDK_VERSION__` was replaced

## Config Variables

Available in test.yaml via `${config.X}`:

| Variable                                 | Example |
| ---------------------------------------- | ------- |
| `config.packages.cli_version`            | 0.9.5   |
| `config.packages.sdk_python_version`     | 0.9.5   |
| `config.packages.sdk_typescript_version` | 0.9.5   |

## Issue Reporting Policy

**No workarounds.** If tests fail due to real issues in MCP Mesh:

1. Do not implement workarounds in test code
2. Document the issue clearly
3. Create a GitHub issue at [mcp-mesh](https://github.com/anthropics/mcp-mesh/issues)
4. Mark the test as skipped with a reference to the issue

This ensures test suites expose real bugs rather than hiding them.
