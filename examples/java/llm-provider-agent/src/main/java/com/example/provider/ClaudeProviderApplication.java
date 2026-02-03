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
 * <h2>How It Works</h2>
 * <pre>
 * 1. This agent registers with capability="llm" and tags=["llm", "claude", "anthropic", "provider"]
 * 2. Other agents with @MeshLlm(providerSelector = @Selector(capability = "llm")) discover this provider
 * 3. LLM requests are routed to this agent via mesh
 * 4. This agent forwards requests to Claude API via Spring AI
 * 5. Responses are returned through mesh to the calling agent
 * </pre>
 *
 * <h2>Architecture</h2>
 * <pre>
 * Consumer Agent                    Provider Agent (this)
 * (@MeshLlm)                        (@MeshLlmProvider)
 *     |                                   |
 *     +-- providerSelector: llm --------> +-- capability: llm
 *     |                                   |
 *     +-- generate("prompt") -----------> +-- receive request
 *     |                                   |
 *     |                                   +-- call Spring AI
 *     |                                   |
 *     |                                   +-- call Claude API
 *     |                                   |
 *     +<-- response ----------------------+
 * </pre>
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
 * cd examples/java/llm-provider-agent
 * mvn spring-boot:run
 *
 * # Verify provider is registered
 * meshctl list
 * # Output: claude-provider  healthy  http://localhost:9110
 *
 * meshctl list -t
 * # Output: llm  Generate text with Claude
 *
 * # Test directly
 * meshctl call llm '{"prompt": "Hello, how are you?"}'
 *
 * # Or run a consumer agent that uses mesh delegation
 * cd examples/java/llm-mesh-agent
 * mvn spring-boot:run
 * </pre>
 *
 * <h2>Benefits of Provider Pattern</h2>
 * <ul>
 *   <li>Centralized API key management - only provider needs the key</li>
 *   <li>Rate limiting at provider level</li>
 *   <li>Switch LLM providers without redeploying consumers</li>
 *   <li>Multiple consumers share single provider</li>
 *   <li>Logging and monitoring at provider level</li>
 * </ul>
 */
@MeshAgent(
    name = "claude-provider",
    version = "1.0.0",
    description = "Claude LLM provider for mesh",
    port = 9110
)
@MeshLlmProvider(
    model = "anthropic/claude-sonnet-4-5",
    capability = "llm",
    tags = {"llm", "claude", "anthropic", "provider"},
    version = "1.0.0"
)
@SpringBootApplication
public class ClaudeProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(ClaudeProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting Claude Provider Agent...");
        log.info("This agent provides LLM capability to the mesh");
        log.info("Other agents can delegate LLM calls to this provider");
        SpringApplication.run(ClaudeProviderApplication.class, args);
    }

    // No implementation needed - @MeshLlmProvider handles everything!
    //
    // The MeshLlmProviderProcessor automatically:
    // 1. Creates a tool named "llm" with capability="llm"
    // 2. Registers with the mesh registry
    // 3. Handles incoming generate requests
    // 4. Forwards to Spring AI ChatClient
    // 5. Returns responses through the mesh
}
