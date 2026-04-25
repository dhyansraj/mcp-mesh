# vertex-ai-agent (Java)

Minimal Spring Boot example of calling Google Gemini through **Vertex AI**
(IAM auth) from a mesh agent. Same Gemini model family as the AI Studio
path — only the `provider` value and auth config change.

## What it shows

- `@MeshLlm(provider = "vertex_ai")` to force Vertex AI even if AI Studio is
  also configured (otherwise `provider = "gemini"` prefers AI Studio)
- A Java record (`CapitalInfo`) as the structured output type
- Mesh's `GeminiHandler` routing automatically applies HINT-mode prompt
  shaping when structured output is combined with tools

## Prerequisites

1. A GCP project with the **Vertex AI API** enabled
2. An identity (user account or service account) with the
   `roles/aiplatform.user` role
3. Application Default Credentials configured — either:
   - User flow: `gcloud auth application-default login`
   - Service account: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`
4. Java 17+ and Maven 3.9+

## Run locally

```bash
cd examples/java/vertex-ai-agent

# Configure project + location. Either edit src/main/resources/application.yml
# or override via env vars (Spring Boot binds them through relaxed binding):
export SPRING_AI_VERTEX_AI_GEMINI_PROJECT_ID=my-gcp-project
export SPRING_AI_VERTEX_AI_GEMINI_LOCATION=us-central1

# Start the registry in another terminal first, then:
mvn spring-boot:run
```

## Try it

```bash
# Once registered, call the tool through any mesh client. For a quick
# smoke test, hit the agent's MCP HTTP endpoint directly:
curl -s http://localhost:9042/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"tools/call",
    "params":{"name":"capitalOf","arguments":{"country":"France"}}
  }' | jq .
```

You should see a structured response like:

```json
{ "name": "France", "capital": "Paris" }
```

## Switching to AI Studio

To run the same agent against Google AI Studio instead:

1. Replace the dependency in `pom.xml`:
   ```xml
   <dependency>
     <groupId>org.springframework.ai</groupId>
     <artifactId>spring-ai-starter-model-google-genai</artifactId>
     <version>${spring-ai.version}</version>
   </dependency>
   ```
2. Change the annotation:
   ```java
   @MeshLlm(provider = "gemini", …)   // was: provider = "vertex_ai"
   ```
3. Configure the API key:
   ```bash
   export GOOGLE_AI_GEMINI_API_KEY=AIza…
   ```

## Env var conventions across runtimes

Each runtime follows its own ecosystem's naming convention for Vertex AI:

| Runtime              | SDK            | Project                                    | Location                                   |
| -------------------- | -------------- | ------------------------------------------ | ------------------------------------------ |
| Python               | LiteLLM        | `VERTEXAI_PROJECT`                         | `VERTEXAI_LOCATION`                        |
| TypeScript           | Vercel AI SDK  | `GOOGLE_VERTEX_PROJECT`                    | `GOOGLE_VERTEX_LOCATION`                   |
| **Java (this)**      | **Spring AI** | `spring.ai.vertex.ai.gemini.project-id`<br/>(or env: `SPRING_AI_VERTEX_AI_GEMINI_PROJECT_ID`) | `spring.ai.vertex.ai.gemini.location`<br/>(or env: `SPRING_AI_VERTEX_AI_GEMINI_LOCATION`) |

`GOOGLE_APPLICATION_CREDENTIALS` (or `gcloud auth application-default login`)
works for ADC across all three.
