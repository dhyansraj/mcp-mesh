# vertex-ai-agent

Minimal example of calling Google Gemini through **Vertex AI** (IAM auth)
from a mesh agent. Same Gemini model family as the AI Studio path — only
the model prefix and auth env vars change.

## What it shows

- `model="vertex_ai/gemini-2.0-flash"` on `@mesh.llm_provider`
- A Pydantic structured-output return type (`CapitalInfo`)
- Mesh's HINT-mode prompt shaping is applied automatically (same as for
  `gemini/*`), so structured output works alongside tool use without
  triggering Gemini's response_format-with-tools deadlock.

## Prerequisites

1. A GCP project with the **Vertex AI API** enabled
2. An identity (user account or service account) with the `roles/aiplatform.user` role
3. Application Default Credentials configured — either:
   - User flow: `gcloud auth application-default login`
   - Service account: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`
4. **Install mesh with the `vertex` extra** — pulls in `google-auth` which LiteLLM
   needs to read ADC for `vertex_ai/*` model strings:
   ```bash
   pip install 'mcp-mesh[vertex]'
   ```

## Run locally

```bash
# Project + location: required if using user ADC (gcloud auth application-default login).
# If using a service account JSON, project is auto-derived but location is still recommended.
export VERTEXAI_PROJECT=my-gcp-project
export VERTEXAI_LOCATION=us-central1

# Start the registry in another terminal first, then:
meshctl start examples/python/vertex-ai-agent/main.py
```

## Try it

```bash
# Once registered, call the tool through any mesh client. For a quick
# smoke test, hit the agent's MCP HTTP endpoint directly:
curl -s http://localhost:9040/mcp \
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

```python
model="gemini/gemini-2.0-flash"   # was: vertex_ai/gemini-2.0-flash
```

```bash
export GOOGLE_API_KEY=...         # instead of ADC + VERTEXAI_*
```

The `mcp-mesh[vertex]` extra is not needed for the AI Studio path — `pip install mcp-mesh` is sufficient. No other code changes required.
