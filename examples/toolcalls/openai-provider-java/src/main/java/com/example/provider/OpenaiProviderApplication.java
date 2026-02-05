package com.example.provider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlmProvider;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Zero-code LLM provider agent for OpenAI GPT.
 *
 * <p>This agent provides GPT capability to the mesh. Consumer agents
 * can delegate LLM calls to this provider without needing OpenAI API keys.
 *
 * <h2>Running</h2>
 * <pre>
 * # Set API key
 * export OPENAI_API_KEY=your-key-here
 *
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this provider agent
 * cd examples/toolcalls/openai-provider-java
 * mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "openai-provider-java",
    version = "1.0.0",
    description = "OpenAI GPT LLM provider for mesh (Java)",
    port = 9111
)
@MeshLlmProvider(
    model = "openai/gpt-4o",
    capability = "llm",
    tags = {"llm", "gpt", "openai", "java", "provider"},
    version = "1.0.0"
)
@SpringBootApplication
public class OpenaiProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(OpenaiProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting OpenAI Provider Agent (Java)...");
        log.info("This agent provides OpenAI GPT capability to the mesh");
        SpringApplication.run(OpenaiProviderApplication.class, args);
    }
}
