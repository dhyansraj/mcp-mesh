# meshctl man

> View MCP Mesh documentation in the terminal

## Usage

```bash
meshctl man [topic] [options]
```

## Options

| Option         | Description              | Default |
| -------------- | ------------------------ | ------- |
| `--list`       | List all topics          | false   |
| `--typescript` | Show TypeScript examples | false   |
| `--raw`        | Raw markdown output      | false   |

## Examples

### List Topics

```bash
meshctl man --list
```

Output:

```
Available Topics
────────────────

  quickstart (quick, start, hello)
    Get started with MCP Mesh in minutes

  prerequisites (prereq, setup, install)
    System requirements for development

  decorators (decorator)
    Python decorators and TypeScript functions

  dependency-injection (di, injection)
    How DI works, proxy creation, and wiring

  llm (llm-integration)
    LLM agents, @mesh.llm, and tool filtering

  ...
```

### View Topic

```bash
meshctl man decorators
```

### TypeScript Version

```bash
meshctl man decorators --typescript
```

### Raw Markdown

```bash
# For piping to other tools
meshctl man decorators --raw | less
```

## Topics

| Topic                  | Aliases                  | Description         |
| ---------------------- | ------------------------ | ------------------- |
| `quickstart`           | quick, start, hello      | Getting started     |
| `prerequisites`        | prereq, setup            | Requirements        |
| `overview`             | architecture, arch       | Architecture        |
| `capabilities`         | caps                     | Named services      |
| `tags`                 | tag-matching             | Tag system          |
| `decorators`           | decorator                | API reference       |
| `dependency-injection` | di, injection            | DI system           |
| `health`               | health-checks, heartbeat | Health system       |
| `registry`             | reg                      | Registry details    |
| `llm`                  | llm-integration          | LLM features        |
| `proxies`              | proxy, communication     | Proxy types         |
| `fastapi`              | backend                  | FastAPI integration |
| `express`              | route, routes            | Express integration |
| `environment`          | env, config              | Configuration       |
| `deployment`           | deploy                   | Deployment guides   |
| `observability`        | tracing, monitoring      | Monitoring          |
| `testing`              | curl, mcp-api            | Testing agents      |
| `scaffold`             | scaffolding, generate    | Code generation     |
| `cli`                  | commands, call, list     | CLI commands        |

## Use Cases

### Quick Reference

```bash
# Check decorator syntax
meshctl man decorators

# Check environment variables
meshctl man environment
```

### Language-Specific

```bash
# Python examples
meshctl man decorators

# TypeScript examples
meshctl man decorators --typescript
```

### Offline Documentation

```bash
# Save for offline use
meshctl man --list --raw > topics.md
meshctl man decorators --raw > decorators.md
```

### Integration with Pager

```bash
# Use with less
meshctl man llm --raw | less

# Use with bat (if installed)
meshctl man llm --raw | bat -l markdown
```

## See Also

- [CLI Reference](index.md) - All commands
- [Python SDK](../python/index.md) - Python documentation
- [TypeScript SDK](../typescript/index.md) - TypeScript documentation
