package com.example.vertex;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * vertex-ai-agent (Java) — Minimal Gemini-via-Vertex-AI Spring Boot agent.
 *
 * <p>Demonstrates calling Google Gemini through Vertex AI (IAM auth) instead of
 * AI Studio, using Spring AI's {@code spring-ai-starter-model-vertex-ai-gemini}.
 *
 * <p>The only differences from a Gemini AI Studio agent are:
 * <ul>
 *   <li>{@code provider = "vertex_ai"} on {@code @MeshLlm} (vs {@code "gemini"})</li>
 *   <li>auth: GCP ADC + {@code spring.ai.vertex.ai.gemini.project-id} +
 *       {@code spring.ai.vertex.ai.gemini.location} (vs {@code GOOGLE_AI_GEMINI_API_KEY})</li>
 * </ul>
 *
 * <p>Mesh-side prompt shaping is identical for both backends — the same
 * {@code GeminiHandler} is selected for both {@code "gemini"} and
 * {@code "vertex_ai"} provider strings.
 *
 * <p>The {@code provider = "vertex_ai"} value is significant: with just
 * {@code provider = "gemini"}, the runtime would prefer the AI Studio
 * ({@code googleAiGeminiChatModel}) bean if it were also configured. Setting
 * {@code "vertex_ai"} explicitly forces the Vertex AI path.
 *
 * <h2>Prerequisites</h2>
 * <ul>
 *   <li>GCP project with the Vertex AI API enabled</li>
 *   <li>An identity with {@code roles/aiplatform.user}</li>
 *   <li>Application Default Credentials configured (via
 *       {@code gcloud auth application-default login} or
 *       {@code GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json})</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # In src/main/resources/application.yml, set project + location, OR override
 * # at runtime via env vars (Spring Boot auto-binds SPRING_AI_VERTEX_AI_GEMINI_PROJECT_ID
 * # and SPRING_AI_VERTEX_AI_GEMINI_LOCATION):
 * export SPRING_AI_VERTEX_AI_GEMINI_PROJECT_ID=my-gcp-project
 * export SPRING_AI_VERTEX_AI_GEMINI_LOCATION=us-central1
 *
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this agent
 * cd examples/java/vertex-ai-agent
 * mvn spring-boot:run
 *
 * # Smoke-test
 * curl -s http://localhost:9042/mcp \
 *   -H 'Content-Type: application/json' \
 *   -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
 *        "params":{"name":"capitalOf","arguments":{"country":"France"}}}' | jq .
 * </pre>
 */
@MeshAgent(
    name = "vertex-ai-agent-java",
    version = "1.0.0",
    description = "Gemini via Vertex AI (IAM auth) demo agent — Java",
    port = 9042
)
@SpringBootApplication
public class VertexAiAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(VertexAiAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting vertex-ai-agent (Java)…");
        SpringApplication.run(VertexAiAgentApplication.class, args);
    }

    /** Structured response: country + capital. */
    public record CapitalInfo(String name, String capital) {}

    /**
     * Look up a country's capital via Gemini on Vertex AI.
     *
     * <p>The {@code provider = "vertex_ai"} forces SpringAiLlmProvider to use
     * {@code vertexAiGeminiChatModel} even if the AI Studio bean is also present.
     */
    @MeshLlm(
        provider = "vertex_ai",
        maxIterations = 1,
        systemPrompt =
            "You answer geography questions concisely. " +
            "Return the country name and its capital as structured JSON.",
        maxTokens = 256,
        temperature = 0.0
    )
    @MeshTool(
        capability = "capital_lookup",
        description = "Return the capital of a country as a structured CapitalInfo object",
        tags = {"geography", "llm", "vertex"}
    )
    public CapitalInfo capitalOf(
        @Param(value = "country", description = "Country to look up") String country,
        MeshLlmAgent llm
    ) {
        return llm.request()
            .user("What is the capital of " + country + "?")
            .generate(CapitalInfo.class);
    }
}
