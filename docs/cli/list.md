# meshctl list

> List registered agents and their capabilities

## Usage

```bash
meshctl list [options]
```

## Options

| Option         | Description          | Default |
| -------------- | -------------------- | ------- |
| `--capability` | Filter by capability | -       |
| `--tag`        | Filter by tag        | -       |
| `--namespace`  | Filter by namespace  | all     |
| `--json`       | Output as JSON       | false   |
| `--watch`      | Watch for changes    | false   |

## Examples

### List All Agents

```bash
meshctl list
```

Output:

```
┌──────────────┬───────────┬──────────────────┬─────────┐
│ Agent        │ Port      │ Capabilities     │ Status  │
├──────────────┼───────────┼──────────────────┼─────────┤
│ system-agent │ 8080      │ date_service     │ healthy │
│ hello-agent  │ 9090      │ greeting         │ healthy │
│ llm-provider │ 8081      │ llm              │ healthy │
└──────────────┴───────────┴──────────────────┴─────────┘
```

### Filter by Capability

```bash
meshctl list --capability llm
```

### Filter by Tag

```bash
meshctl list --tag claude
```

### Filter by Namespace

```bash
meshctl list --namespace production
```

### JSON Output

```bash
meshctl list --json
```

Output:

```json
{
  "agents": [
    {
      "name": "hello-agent",
      "host": "localhost",
      "port": 9090,
      "namespace": "default",
      "status": "healthy",
      "capabilities": {
        "greeting": {
          "version": "1.0.0",
          "tags": ["social"]
        }
      }
    }
  ]
}
```

### Watch Mode

```bash
# Live updates when agents change
meshctl list --watch
```

## Detailed View

For more details about specific agents:

```bash
meshctl status
```

Output:

```
Agent: hello-agent
├── Host: localhost:9090
├── Namespace: default
├── Status: healthy
├── Last Heartbeat: 5s ago
└── Capabilities:
    └── greeting (v1.0.0)
        ├── Tags: social, basic
        └── Dependencies: date_service
```

## Use Cases

### Find LLM Providers

```bash
meshctl list --capability llm --json | jq '.agents[] | {name, tags: .capabilities.llm.tags}'
```

### Check Production Agents

```bash
meshctl list --namespace production --json | jq '.agents[] | {name, status}'
```

### Monitor Health

```bash
# Watch for status changes
meshctl list --watch
```

## Scripting

### Get Agent Count

```bash
meshctl list --json | jq '.agents | length'
```

### Get Unhealthy Agents

```bash
meshctl list --json | jq '.agents[] | select(.status != "healthy")'
```

### Find Agent by Capability

```bash
AGENT=$(meshctl list --capability greeting --json | jq -r '.agents[0].name')
echo "Found agent: $AGENT"
```

## See Also

- [start](start.md) - Start agents
- [call](call.md) - Call tools
- [Registry](../concepts/registry.md) - Registry details
