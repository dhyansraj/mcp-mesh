# meshctl CLI Reference

> Command-line tool for MCP Mesh development and deployment

## Installation

**Supported platforms:** macOS, Linux (Windows users: use WSL or Git Bash)

=== "npm (Recommended)"

    ```bash
    npm install -g @mcpmesh/cli
    ```

=== "Homebrew"

    ```bash
    brew install dhyansraj/tap/meshctl
    ```

=== "curl"

    ```bash
    curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash
    ```

Verify installation:

```bash
meshctl --version
```

## Commands

| Command      | Description                                     |
| ------------ | ----------------------------------------------- |
| `start`      | Start agents with mesh runtime                  |
| `stop`       | Stop detached agents and registry               |
| `list`       | List running agents                             |
| `status`     | Show detailed agent status                      |
| `call`       | Call an MCP tool on an agent                    |
| `trace`      | Display distributed call trace                  |
| `logs`       | View agent logs (detached mode)                 |
| `audit`      | Inspect dependency-resolution decisions         |
| `schema`     | Diff canonical schemas by content hash          |
| `entity`     | Manage trusted entity CAs for registration      |
| `job`        | Inspect and reclaim background jobs             |
| `registry`   | Drain, resume, and inspect the registry         |
| `scaffold`   | Generate new agent from template                |
| `man`        | Show built-in documentation                     |
| `config`     | Manage meshctl configuration                    |
| `completion` | Generate shell autocompletion                   |

## Quick Reference

### Start Agents

```bash
meshctl start my_agent.py              # Start Python agent
meshctl start src/index.ts             # Start TypeScript agent
meshctl start -w my_agent.py           # Hot reload on changes
meshctl start -d my_agent.py           # Detached (background)
meshctl start --debug my_agent.py      # Debug logging
meshctl start --registry-only          # Start registry only
meshctl start agent1.py agent2.ts      # Multiple agents
```

### Call Tools

```bash
meshctl call get_weather                    # Auto-discover agent
meshctl call add '{"a": 1, "b": 2}'         # With JSON args
meshctl call --trace get_weather            # With tracing
meshctl call weather-agent-7f3a:get_weather # Specific agent
```

### Inspect Mesh

```bash
meshctl list                   # List healthy agents
meshctl list --all             # Include unhealthy
meshctl list --verbose         # Per-tool detail incl. unavailable-capability reasons
meshctl list --tools           # List all tools
meshctl list --tools=add       # Show tool schema
meshctl list --show-framework  # Reveal hidden __mesh_* synthetic tools
meshctl list --services        # Dot-namespaced capabilities grouped as services
meshctl status                 # Show wiring details
meshctl status my-agent        # Specific agent
```

!!! note "Framework tools are hidden by default"
    `--tools` hides the entire `__mesh_*` synthetic family (job, media, and other framework internals). Pass `--show-framework` to include them.

!!! note "Capability availability"
    When an agent is healthy but a capability has a broken `required` dependency chain, its `meshctl list` row is flagged in red with `(N capabilities unavailable)`. `--verbose` expands each affected tool with its reason (`[unavailable: required dep '…' unresolved]`), and the `--tools` table marks the row with a trailing red `unavailable`.

### Scaffold Agents

```bash
meshctl scaffold                              # Interactive wizard
meshctl scaffold --name my-agent              # Python agent
meshctl scaffold --name my-agent -l ts        # TypeScript agent
meshctl scaffold --compose                    # Generate docker-compose
meshctl scaffold --compose --observability    # With tracing stack
```

### View Documentation

```bash
meshctl man --list              # List all topics
meshctl man decorators          # Python decorators
meshctl man decorators -t       # TypeScript version
meshctl man deployment          # Deployment guide
meshctl man upgrading           # Version upgrade guide
```

### Manage Background Agents

```bash
meshctl logs my-agent           # View logs
meshctl logs my-agent -f        # Follow logs
meshctl stop my-agent           # Stop specific agent
meshctl stop                    # Stop all + registry
```

### Inspect Background Jobs

```bash
meshctl job status 01HXY...     # Full job state (claim_epoch, owner, lease)
meshctl job status 01HXY... --json
meshctl job reclaim 01HXY...    # Clear owner/lease so the job is claimable again
```

`meshctl job status` reads the registry row directly and surfaces the fencing/lease fields (`claim_epoch`, `owner`, `attempt_count`, `lease_expires_at`) used for post-incident forensics. `meshctl job reclaim` forces the lease-expiry path for one job — useful for fencing drills or evicting a job from a replica you are about to drain. Terminal jobs cannot be reclaimed.

### Operate the Registry

```bash
meshctl registry drain --wait   # Stop new job claims; block until claims drain
meshctl registry drain          # Enter drain mode without waiting
meshctl registry status         # Show drain state and remaining live claims
meshctl registry resume         # Resume normal dispatch (queued jobs claimable)
```

Drain mode makes registry upgrades/restarts safe: while draining, the registry stops handing out new job claims (queued jobs stay queued — no attempt is burned), but running jobs keep renewing their leases and complete normally, and new submissions are still accepted. `live_claims` counts non-terminal jobs that still have an owner. Drain state is in-memory only — restarting the registry clears it.

## Detailed Help

Each command has comprehensive built-in help with examples:

```bash
meshctl --help              # All commands
meshctl start --help        # Start options
meshctl call --help         # Call options
meshctl scaffold --help     # Scaffold options
meshctl man --help          # Man page options
```

## Environment Variables

| Variable                | Description                             | Default                 |
| ----------------------- | --------------------------------------- | ----------------------- |
| `MCP_MESH_REGISTRY_URL` | Registry URL                            | `http://localhost:8000` |
| `MCP_MESH_LOG_LEVEL`    | Log level (TRACE/DEBUG/INFO/WARN/ERROR) | `INFO`                  |
| `MCP_MESH_HTTP_PORT`    | Agent HTTP port                         | Auto-assigned           |

See [Environment Variables](../environment-variables.md) for the full list.
