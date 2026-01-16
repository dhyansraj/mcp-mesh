# meshctl start

> Start an MCP Mesh agent

## Usage

```bash
meshctl start <file> [options]
```

## Arguments

| Argument | Description                               |
| -------- | ----------------------------------------- |
| `<file>` | Agent file (Python .py or TypeScript .ts) |

## Options

| Option           | Description           | Default        |
| ---------------- | --------------------- | -------------- |
| `--port`         | HTTP port             | Auto           |
| `--host`         | HTTP host             | localhost      |
| `--watch`        | Enable hot reload     | false          |
| `--env-file`     | Load environment file | -              |
| `--log-level`    | Log level             | info           |
| `--registry-url` | Override registry URL | localhost:8000 |

## Examples

### Basic Start

```bash
meshctl start my_agent.py
```

### With Hot Reload

```bash
# Automatically restart on file changes
meshctl start my_agent.py --watch
```

### TypeScript Agent

```bash
meshctl start my_agent.ts
```

### Custom Port

```bash
meshctl start my_agent.py --port 9090
```

### With Environment File

```bash
# Create .env file
cat > .env << 'EOF'
MCP_MESH_REGISTRY_URL=http://localhost:8000
ANTHROPIC_API_KEY=your-key
EOF

# Start with environment
meshctl start my_agent.py --env-file .env
```

### Debug Mode

```bash
meshctl start my_agent.py --log-level debug
```

### Multiple Agents

```bash
# Terminal 1
meshctl start system_agent.py --port 8080

# Terminal 2
meshctl start hello_agent.py --port 9090
```

## Auto-Start Registry

When you start the first agent, the registry starts automatically:

```bash
# Registry starts automatically on port 8000
meshctl start my_agent.py
```

To disable auto-start:

```bash
export MCP_MESH_REGISTRY_AUTO_START=false
meshctl start my_agent.py
```

## Hot Reload

The `--watch` flag enables automatic restart when files change:

```bash
meshctl start my_agent.py --watch
```

Watched patterns:

- `*.py` - Python files
- `*.ts` - TypeScript files
- `*.jinja2`, `*.hbs` - Templates

## Output

```
🚀 Starting agent: my_agent.py
📡 Registry: http://localhost:8000
🔧 Agent: my-agent @ http://localhost:9090
✅ Agent registered successfully
📋 Capabilities: greeting, helper
```

## Troubleshooting

### Port Already in Use

```bash
# Find process using port
lsof -i :9090

# Kill process
kill -9 <PID>
```

### Registry Not Found

```bash
# Check registry is running
curl http://localhost:8000/health

# Start registry manually
meshctl registry start
```

### TypeScript Not Running

```bash
# Ensure ts-node is installed
npm install -g ts-node typescript

# Or use npx
npx ts-node my_agent.ts
```

## See Also

- [call](call.md) - Call tools
- [list](list.md) - List agents
- [Environment Variables](../environment-variables.md) - Configuration
