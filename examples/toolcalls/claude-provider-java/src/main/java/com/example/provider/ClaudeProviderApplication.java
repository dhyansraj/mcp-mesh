package com.example.provider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlmProvider;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Zero-code LLM provider agent using @MeshLlmProvider.
 *
 * <p>This example shows:
 * <ul>
 *   <li>@MeshLlmProvider - Zero-code LLM provider</li>
 *   <li>Exposes capability="llm" to the mesh</li>
 *   <li>Wraps Spring AI Anthropic client</li>
 *   <li>Other agents can delegate LLM calls to this provider</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # Set API key
 * export ANTHROPIC_API_KEY=your-key-here
 *
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this provider agent
 * cd examples/toolcalls/claude-provider-java
 * mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "claude-provider-java",
    version = "1.0.0",
    description = "Claude LLM provider for mesh (Java)",
    port = 9110
)
@MeshLlmProvider(
    model = "anthropic/claude-sonnet-4-5",
    capability = "llm",
    tags = {"llm", "claude", "anthropic", "java", "provider"},
    version = "1.0.0"
)
@SpringBootApplication
public class ClaudeProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(ClaudeProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting Claude Provider Agent (Java)...");
        log.info("This agent provides LLM capability to the mesh");
        log.info("Other agents can delegate LLM calls to this provider");
        SpringApplication.run(ClaudeProviderApplication.class, args);
    }
}
