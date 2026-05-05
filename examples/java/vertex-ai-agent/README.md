# vertex-ai-agent (Java)

Minimal Spring Boot example of running a Gemini provider agent backed by
**Vertex AI** (IAM auth). Same Gemini model family as the AI Studio path —
only the provider's `model` string and auth config change.

## What it shows

- `@MeshLlmProvider(model = "vertex_ai/gemini-2.0-flash")` to bind the
  IAM-backed `vertexAiGeminiChatModel` Spring AI bean
- A Java record (`CapitalInfo`) as the structured output type on the
  consumer side
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

# Configure project + location. Both are REQUIRED — application.yml has no
# fallback defaults, so Spring Boot fails fast at startup if these are unset
# (rather than deferring failure to the first Vertex API call with a
# placeholder project id). Spring Boot relaxed binding maps them onto
# `spring.ai.vertex.ai.gemini.project-id` / `.location`.
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

To run the same provider against Google AI Studio instead:

1. Replace the dependency in `pom.xml`:
   ```xml
   <dependency>
     <groupId>org.springframework.ai</groupId>
     <artifactId>spring-ai-starter-model-google-genai</artifactId>
     <version>${spring-ai.version}</version>
   </dependency>
   ```
2. Change the provider's `model` string:
   ```java
   @MeshLlmProvider(model = "gemini/gemini-2.0-flash", …)   // was: vertex_ai/gemini-2.0-flash
   ```
3. Configure the API key:
   ```bash
   export GOOGLE_AI_GEMINI_API_KEY=AIza…
   ```

Consumer agents are unchanged — they keep their existing
`@MeshLlm(providerSelector = @Selector(capability = "llm", tags = {"+gemini"}))`
selector.

## Env var conventions across runtimes

Each runtime follows its own ecosystem's naming convention for Vertex AI:

| Runtime              | SDK            | Project                                    | Location                                   |
| -------------------- | -------------- | ------------------------------------------ | ------------------------------------------ |
| Python               | LiteLLM        | `VERTEXAI_PROJECT`                         | `VERTEXAI_LOCATION`                        |
| TypeScript           | Vercel AI SDK  | `GOOGLE_VERTEX_PROJECT`                    | `GOOGLE_VERTEX_LOCATION`                   |
| **Java (this)**      | **Spring AI** | `spring.ai.vertex.ai.gemini.project-id`<br/>(or env: `SPRING_AI_VERTEX_AI_GEMINI_PROJECT_ID`) | `spring.ai.vertex.ai.gemini.location`<br/>(or env: `SPRING_AI_VERTEX_AI_GEMINI_LOCATION`) |

`GOOGLE_APPLICATION_CREDENTIALS` (or `gcloud auth application-default login`)
works for ADC across all three.
