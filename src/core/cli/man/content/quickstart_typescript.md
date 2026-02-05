# Quick Start

> Get started with MCP Mesh in minutes (TypeScript)

## Prerequisites

```bash
# Node.js 18+
node --version

# Create project directory
mkdir my-mesh-project && cd my-mesh-project
```

## 1. Start the Registry

```bash
# Terminal 1: Start registry
meshctl start --registry-only --debug
```

## 2. Create Your First Agent

```bash
# Terminal 2: Scaffold a TypeScript agent
meshctl scaffold --name greeter --agent-type tool --lang typescript
```

This creates `greeter/src/index.ts`:

```typescript
import { mesh, MeshAgent } from "@mcpmesh/sdk";

const app = new MeshAgent({
  name: "greeter",
  version: "1.0.0",
  httpPort: 8080,
});

app.tool(
  mesh({
    capability: "greeting",
    description: "Greet a user by name",
  }),
  async ({ name }: { name: string }) => {
    return `Hello, ${name}!`;
  }
);

app.run();
```

## 3. Install Dependencies and Run

```bash
# Terminal 2: Install and start
cd greeter
npm install
meshctl start src/index.ts --debug
```

## 4. Test the Agent

```bash
# Terminal 3: Call the agent
meshctl call greeter greeting --params '{"name": "World"}'
# Output: Hello, World!

# Or list running agents
meshctl list
```

## 5. Add a Dependency

Create a second agent that depends on the greeter:

```bash
meshctl scaffold --name assistant --agent-type tool --lang typescript --port 9001
```

Edit `assistant/src/index.ts`:

```typescript
import { mesh, MeshAgent, McpMeshTool } from "@mcpmesh/sdk";

const app = new MeshAgent({
  name: "assistant",
  version: "1.0.0",
  httpPort: 9001,
});

app.tool(
  mesh({
    capability: "smart_greeting",
    description: "Enhanced greeting with time",
    dependencies: ["greeting"],  // Depend on greeter
  }),
  async (
    { name }: { name: string },
    { greeting }: { greeting: McpMeshTool | null }  // Injected!
  ) => {
    if (greeting) {
      const baseGreeting = await greeting({ name });
      return `${baseGreeting} Welcome to MCP Mesh!`;
    }
    return `Hello, ${name}! (greeter unavailable)`;
  }
);

app.run();
```

```bash
# Install and start the assistant
cd assistant
npm install
meshctl start src/index.ts --debug

# Call the smart greeting
meshctl call assistant smart_greeting --params '{"name": "Developer"}'
# Output: Hello, Developer! Welcome to MCP Mesh!
```

## Next Steps

- `meshctl man decorators --typescript` - Learn all mesh functions
- `meshctl man llm --typescript` - Add LLM capabilities
- `meshctl man deployment --typescript` - Deploy to Docker/Kubernetes
- `meshctl man express` - Express REST API integration

## See Also

- `meshctl scaffold --help` - All scaffold options
- `meshctl man prerequisites` - Full setup guide
