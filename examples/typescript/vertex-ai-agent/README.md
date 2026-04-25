# vertex-ai-agent (TypeScript)

Minimal example of calling Google Gemini through **Vertex AI** (IAM auth)
from a TypeScript mesh agent. Same Gemini model family as the AI Studio
path — only the model prefix and auth env vars change.

## What it shows

- `model="vertex_ai/gemini-2.0-flash"` on `agent.addLlmProvider`
- A Zod structured-output schema (`CapitalInfo`)
- Mesh's HINT-mode prompt shaping is applied automatically (same as for
  `gemini/*`), so structured output works alongside tool use without
  triggering Gemini's response_format-with-tools deadlock.

## Prerequisites

1. A GCP project with the **Vertex AI API** enabled
2. An identity (user account or service account) with the
   `roles/aiplatform.user` role
3. Application Default Credentials configured — either:
   - User flow: `gcloud auth application-default login`
   - Service account: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`
4. Node.js 18+. The `@ai-sdk/google-vertex` package is already a dep of
   `@mcpmesh/sdk` so no extra install is needed.

## Run locally

```bash
cd examples/typescript/vertex-ai-agent
npm install

# Required: project + location for Vercel SDK's @ai-sdk/google-vertex.
export GOOGLE_VERTEX_PROJECT=my-gcp-project
export GOOGLE_VERTEX_LOCATION=us-central1

# Start the registry in another terminal first, then:
npm start
```

## Try it

```bash
# Once registered, call the tool through any mesh client. For a quick
# smoke test, hit the agent's MCP HTTP endpoint directly:
curl -s http://localhost:9041/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"tools/call",
    "params":{"name":"capital_of","arguments":{"country":"France"}}
  }' | jq .
```

You should see a structured response like:

```json
{ "name": "France", "capital": "Paris" }
```

## Switching to AI Studio

To run the same agent against Google AI Studio instead, change two things:

```typescript
model: "gemini/gemini-2.0-flash"   // was: "vertex_ai/gemini-2.0-flash"
```

```bash
export GOOGLE_GENERATIVE_AI_API_KEY=AIza...   # instead of ADC + GOOGLE_VERTEX_*
```

No other code changes required.

## Env var conventions across runtimes

Each runtime follows its own ecosystem's naming convention for Vertex AI:

| Runtime              | SDK            | Project                | Location               |
| -------------------- | -------------- | ---------------------- | ---------------------- |
| Python               | LiteLLM        | `VERTEXAI_PROJECT`     | `VERTEXAI_LOCATION`    |
| **TypeScript (this)** | **Vercel AI SDK** | `GOOGLE_VERTEX_PROJECT`| `GOOGLE_VERTEX_LOCATION` |
| Java                 | Spring AI      | `spring.ai.vertex.ai.gemini.project-id` | `spring.ai.vertex.ai.gemini.location` |

`GOOGLE_APPLICATION_CREDENTIALS` (or `gcloud auth application-default login`)
works for ADC across all three.
