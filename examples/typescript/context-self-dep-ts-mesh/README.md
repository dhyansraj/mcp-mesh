# context-self-dep-ts-mesh

MCP Mesh LLM agent generated using meshctl scaffold.

## Quick Start

```bash
# Install dependencies
npm install

# Run the agent (development)
npm run dev

# Run the agent (production)
npm start
```

## Project Structure

```
context-self-dep-ts-mesh/
├── src/
│   └── index.ts        # Agent implementation with mesh.llm()
├── prompts/
│   └── context-self-dep-ts-mesh.hbs # Handlebars prompt template
├── package.json        # Dependencies
├── tsconfig.json       # TypeScript config
├── Dockerfile          # Container build
└── helm-values.yaml    # Kubernetes deployment
```

## LLM Configuration

This agent uses `mesh.llm()` which:
- Requests an LLM provider from the mesh (tags: ["llm","+claude"])
- Loads system prompt from `prompts/context-self-dep-ts-mesh.hbs`
- Supports agentic loops with max 1 iterations
- Can access other mesh tools via filter: `all`

## Customizing the Prompt

Edit `prompts/context-self-dep-ts-mesh.hbs` to customize the LLM behavior.
Handlebars template syntax with context variables:

```handlebars
{{inputText}}     - Access context field
{{#if condition}} - Conditional blocks
{{#each items}}   - Iterate arrays
```

## Docker

```bash
docker build -t context-self-dep-ts-mesh:latest .
docker run -p 9021:9021 context-self-dep-ts-mesh:latest
```

## Documentation

- Run `meshctl man llm` for LLM integration guide
- Run `meshctl man decorators --typescript` for decorator reference
