# Run Agents (Python)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/local-development/03-running-agents/">TypeScript Run Agents</a></span>
</div>

> Start agents with `meshctl start`

## Basic Usage

```bash
# Start a single agent
meshctl start main.py
```

The registry starts automatically on port 8000 if not already running. If a registry is already running (e.g., in Docker), agents connect to it instead.

## Multiple Agents

```bash
# Start multiple agents at once (mixed languages supported)
meshctl start agent1.py agent2.py agent3.ts
```

## Hot Reload

Auto-restart agents when code changes:

```bash
meshctl start -w main.py
meshctl start --watch main.py
```

## Debug Mode

Enable verbose logging:

```bash
meshctl start --debug main.py

# Or set specific log level
meshctl start --log-level DEBUG main.py

# Available levels: TRACE, DEBUG, INFO, WARN, ERROR
```

## Background Mode

Run agents in the background (detached):

```bash
# Start in background
meshctl start -d main.py

# View logs
meshctl logs my-agent -f

# Stop background agents
meshctl stop --all
```

## Environment Variables

Share configuration across agents:

```bash
# Load from .env file
meshctl start --env-file .env main.py

# Or pass individual variables
meshctl start --env OPENAI_API_KEY=sk-... main.py
```

## Registry Options

```bash
# Start registry only (no agents)
meshctl start --registry-only

# Use custom registry port
meshctl start --registry-port 9000 main.py

# Connect to external registry
meshctl start --registry-url http://remote:8000 main.py
```

## Common Patterns

```bash
# Development: hot reload + debug
meshctl start -w --debug main.py

# CI/Testing: background + quiet
meshctl start -d --quiet main.py

# Production-like: custom registry
meshctl start --registry-url http://registry:8000 main.py
```

## All Options

```bash
meshctl start --help
```

Key flags:

| Flag              | Description                                 |
| ----------------- | ------------------------------------------- |
| `-w, --watch`     | Hot reload on file changes                  |
| `-d, --detach`    | Run in background                           |
| `--debug`         | Enable debug mode                           |
| `--log-level`     | Set log level (TRACE/DEBUG/INFO/WARN/ERROR) |
| `--env-file`      | Load environment from file                  |
| `--env`           | Set individual env var                      |
| `--registry-only` | Start registry without agents               |
| `--registry-port` | Registry port (default: 8000)               |

## Next Steps

Continue to [Inspect the Mesh](./04-inspecting-mesh.md) →
