package com.example.provider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlmProvider;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Zero-code LLM provider agent for Google Gemini.
 *
 * <p>This agent provides Gemini capability to the mesh. Consumer agents
 * can delegate LLM calls to this provider without needing their own API key.
 *
 * <h2>Prerequisites</h2>
 * <ul>
 *   <li>Google AI API key (from https://aistudio.google.com/apikey)</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # Set API key (same as Python/LiteLLM)
 * export GEMINI_API_KEY=your-api-key
 *
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this provider agent
 * cd examples/java/gemini-provider-agent
 * MESH_NATIVE_LIB_PATH=... mvn spring-boot:run
 *
 * # Verify provider is registered
 * meshctl list
 * </pre>
 */
@MeshAgent(
    name = "gemini-provider",
    version = "1.0.0",
    description = "Google Gemini LLM provider for mesh",
    port = 9112
)
@MeshLlmProvider(
    model = "gemini/gemini-2.0-flash",
    capability = "llm",
    tags = {"llm", "gemini", "google", "vertex-ai", "provider"},
    version = "1.0.0"
)
@SpringBootApplication
public class GeminiProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(GeminiProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting Gemini Provider Agent...");
        log.info("This agent provides Google Gemini capability to the mesh");
        SpringApplication.run(GeminiProviderApplication.class, args);
    }
}
