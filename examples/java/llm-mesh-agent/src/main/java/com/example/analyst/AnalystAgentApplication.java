package com.example.analyst;

import io.mcpmesh.FilterMode;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

/**
 * MCP Mesh agent demonstrating @MeshLlm with mesh delegation.
 *
 * <p>This example shows:
 * <ul>
 *   <li>@MeshLlm with providerSelector - delegate LLM calls to mesh provider</li>
 *   <li>Tool filtering - discover tools from mesh based on tags</li>
 *   <li>Agentic loop - LLM calls tools, gets results, continues</li>
 *   <li>Freemarker templates - system prompts with context injection</li>
 *   <li>Structured output - parse LLM responses to Java records</li>
 * </ul>
 *
 * <h2>Architecture</h2>
 * <pre>
 * User Request
 *      |
 *      v
 * AnalystAgent (@MeshLlm)
 *      |
 *      +-- discovers tools from mesh (tag filter: "data", "tools")
 *      |
 *      +-- calls LLM Provider via mesh (providerSelector)
 *      |        |
 *      |        +-- LLM decides to call tools
 *      |        |
 *      |        +-- AnalystAgent executes tool calls via mesh
 *      |        |
 *      |        +-- Results returned to LLM
 *      |        |
 *      |        +-- LLM generates final response
 *      |
 *      v
 * Structured Result (AnalysisResult record)
 * </pre>
 *
 * <h2>Running</h2>
 * <pre>
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Start an LLM provider (exposes capability="llm")
 * meshctl start -d examples/llm-provider/claude_provider.py
 * # Or: cd examples/java/llm-provider-agent && mvn spring-boot:run
 *
 * # Start some data tools (optional, for agentic loop)
 * meshctl start -d examples/data-tools/data_service.py
 *
 * # Run this agent
 * cd examples/java/llm-mesh-agent
 * mvn spring-boot:run
 *
 * # Test with meshctl
 * meshctl call analyze '{"query": "What is the current weather?"}'
 * </pre>
 */
@MeshAgent(
    name = "analyst",
    version = "1.0.0",
    description = "AI-powered data analyst with mesh delegation",
    port = 9002
)
@SpringBootApplication
public class AnalystAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(AnalystAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Analyst Agent...");
        SpringApplication.run(AnalystAgentApplication.class, args);
    }

    /**
     * Analyze data using LLM with mesh delegation.
     *
     * <p>The {@code llm} parameter is automatically injected by the mesh
     * and routes to an LLM provider agent matching the selector.
     *
     * @param ctx Analysis context with query and parameters
     * @param llm Injected LLM agent proxy (delegates to mesh provider)
     * @return Structured analysis result
     */
    @MeshLlm(
        // Delegate to LLM provider via mesh (not direct API call)
        providerSelector = @Selector(
            capability = "llm",
            tags = {"+claude", "+anthropic"}  // Prefer Claude/Anthropic providers
        ),
        // Agentic loop settings
        maxIterations = 5,
        // System prompt from Freemarker template
        systemPrompt = "classpath:prompts/analyst.ftl",
        // Context parameter for template injection
        contextParam = "ctx",
        // Discover tools from mesh matching these tags
        filter = @Selector(tags = {"data", "tools"}),
        filterMode = FilterMode.ALL,
        // LLM parameters
        maxTokens = 4096,
        temperature = 0.7
    )
    @MeshTool(
        capability = "analyze",
        description = "AI-powered data analysis with agentic tool use",
        tags = {"analysis", "llm", "java"}
    )
    public AnalysisResult analyze(
        @Param(value = "ctx", description = "Analysis context") AnalysisContext ctx,
        MeshLlmAgent llm
    ) {
        log.info("Analyzing: {}", ctx.query());

        if (llm == null || !llm.isAvailable()) {
            log.warn("LLM provider not available, returning fallback");
            return fallbackAnalysis(ctx);
        }

        try {
            // Generate structured response using LLM with agentic loop
            String userPrompt = String.format(
                "Analyze the following query: %s\n\nData source: %s",
                ctx.query(),
                ctx.dataSource() != null ? ctx.dataSource() : "not specified"
            );

            // LLM agent handles:
            // 1. System prompt rendering with context
            // 2. Tool discovery from mesh
            // 3. Agentic loop (call tools, get results, continue)
            // 4. Parse response to record type
            return llm.generate(userPrompt, AnalysisResult.class);

        } catch (Exception e) {
            log.error("Analysis failed: {}", e.getMessage(), e);
            return fallbackAnalysis(ctx);
        }
    }

    /**
     * Simple chat endpoint using mesh LLM.
     *
     * <p>Simpler version without structured output - just returns text.
     *
     * @param message User message
     * @param llm     Injected LLM agent proxy
     * @return LLM response text
     */
    @MeshLlm(
        providerSelector = @Selector(capability = "llm"),
        maxIterations = 1,
        systemPrompt = "You are a helpful assistant.",
        maxTokens = 1024,
        temperature = 0.7
    )
    @MeshTool(
        capability = "chat",
        description = "Simple chat using mesh LLM",
        tags = {"chat", "llm", "java"}
    )
    public ChatResponse chat(
        @Param(value = "message", description = "User message") String message,
        MeshLlmAgent llm
    ) {
        log.info("Chat message: {}", message);

        String response;
        String source;

        if (llm != null && llm.isAvailable()) {
            response = llm.generate(message);  // Returns String (text)
            source = "mesh:llm";
        } else {
            response = "I'm sorry, the LLM service is currently unavailable.";
            source = "fallback";
        }

        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        return new ChatResponse(response, timestamp, source);
    }

    private AnalysisResult fallbackAnalysis(AnalysisContext ctx) {
        return new AnalysisResult(
            "Analysis unavailable - LLM provider not connected",
            List.of("LLM service is not available", "Please check mesh connectivity"),
            0.0,
            "fallback"
        );
    }

    /**
     * Analysis context record.
     */
    public record AnalysisContext(
        String query,
        String dataSource,
        Map<String, Object> parameters
    ) {}

    /**
     * Structured analysis result record.
     *
     * <p>The LLM is instructed to return JSON matching this structure.
     */
    public record AnalysisResult(
        String summary,
        List<String> insights,
        double confidence,
        String source
    ) {}

    /**
     * Simple chat response record.
     */
    public record ChatResponse(
        String response,
        String timestamp,
        String source
    ) {}
}
