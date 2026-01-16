# meshctl call

> Call a tool on a mesh agent

## Usage

```bash
meshctl call <tool> [options]
```

## Arguments

| Argument | Description       |
| -------- | ----------------- |
| `<tool>` | Tool name to call |

## Options

| Option      | Description                      | Default       |
| ----------- | -------------------------------- | ------------- |
| `--agent`   | Specific agent name              | Auto-discover |
| `--json`    | Output as JSON                   | false         |
| `--raw`     | Raw output (no formatting)       | false         |
| `--timeout` | Request timeout (seconds)        | 30            |
| `<param>`   | Tool parameters as `--key value` | -             |

## Examples

### Simple Call

```bash
meshctl call hello
```

### With Arguments

```bash
meshctl call hello --name "World"
```

### Multiple Arguments

```bash
meshctl call calculate --x 10 --y 20 --operation add
```

### JSON Arguments

```bash
meshctl call process --data '{"key": "value", "items": [1, 2, 3]}'
```

### Specific Agent

```bash
# Call tool on specific agent
meshctl call hello --agent hello-agent
```

### JSON Output

```bash
# Get raw JSON response
meshctl call hello --name "World" --json
```

### With Timeout

```bash
# Longer timeout for slow operations
meshctl call heavy_computation --timeout 120
```

## Output Formats

### Default (Pretty)

```bash
$ meshctl call hello --name "World"
Hello, World!
```

### JSON Format

```bash
$ meshctl call hello --name "World" --json
{
  "content": [
    {
      "type": "text",
      "text": "Hello, World!"
    }
  ],
  "isError": false
}
```

### Raw Format

```bash
$ meshctl call hello --name "World" --raw
Hello, World!
```

## Tool Discovery

meshctl automatically finds the agent providing the tool:

```bash
# Finds agent with 'greeting' capability automatically
meshctl call greeting
```

If multiple agents provide the same tool:

```bash
# Specify which agent to use
meshctl call greeting --agent preferred-agent
```

## Error Handling

### Tool Not Found

```
❌ Error: Tool 'unknown_tool' not found
Available tools: hello, goodbye, calculate
```

### Agent Not Available

```
❌ Error: No agent provides 'greeting' capability
Run 'meshctl list' to see available agents
```

### Invalid Arguments

```
❌ Error: Missing required argument 'name'
Usage: meshctl call hello --name <string>
```

## Advanced Usage

### Chaining Calls

```bash
# Get date, then use in greeting
DATE=$(meshctl call get_date --raw)
meshctl call hello --greeting "Today is $DATE"
```

### JSON Processing

```bash
# Process JSON output with jq
meshctl call list_users --json | jq '.content[0].text | fromjson | .users'
```

### Scripting

```bash
#!/bin/bash
RESULT=$(meshctl call calculate --x 10 --y 20 --json)
if [ "$(echo $RESULT | jq '.isError')" = "false" ]; then
    echo "Success: $(echo $RESULT | jq -r '.content[0].text')"
fi
```

## See Also

- [start](start.md) - Start agents
- [list](list.md) - List agents
- [Testing](../02-local-development/05-testing.md) - Testing with curl
