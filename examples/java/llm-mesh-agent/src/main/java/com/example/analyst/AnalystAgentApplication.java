package com.example.analyst;

import io.mcpmesh.FilterMode;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshLlm;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.MeshLlmAgent;
import io.mcpmesh.types.MeshLlmAgent.Message;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
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
 * # Test with meshctl (no dataSource needed - LLM autonomously selects tools)
 * meshctl call analyze '{"ctx": {"query": "What is the weather in San Francisco?"}}'
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
     * <p>Tools are discovered automatically from the mesh based on the filter selector.
     * The LLM autonomously decides which tools to call based on the query - no explicit
     * dataSource hint is needed (following the MCP spec pattern where LLM selects tools
     * based on tool descriptions and input schemas).
     *
     * @param ctx Analysis context with query (dataSource is optional and ignored)
     * @param llm Injected LLM agent proxy (delegates to mesh provider)
     * @return Structured analysis result
     */
    @MeshLlm(
        // Delegate to LLM provider via mesh (not direct API call)
        // Uses capability-only selection so analyst works with any LLM provider
        providerSelector = @Selector(capability = "llm"),
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
            // Use fluent builder API for clean, readable code
            // Builder supports: messages, context, options, and structured output
            // Note: LLM autonomously selects tools based on the query - no dataSource hint needed
            AnalysisResult result = llm.request()
                .user(ctx.query())
                .maxTokens(4096)
                .temperature(0.7)
                .generate(AnalysisResult.class);

            // Log metadata from the generation
            var meta = llm.request().lastMeta();
            if (meta != null) {
                log.info("Generation completed: {} iterations, {}ms latency",
                    meta.iterations(), meta.latencyMs());
            }

            return result;

        } catch (Exception e) {
            log.error("Analysis failed: {}", e.getMessage(), e);
            return fallbackAnalysis(ctx);
        }
    }

    /**
     * Simple chat endpoint using mesh LLM with fluent builder.
     *
     * <p>Demonstrates the fluent builder for simple text generation.
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
            // Use fluent builder for clean code
            response = llm.request()
                .user(message)
                .temperature(0.7)
                .generate();
            source = "mesh:llm";
        } else {
            response = "I'm sorry, the LLM service is currently unavailable.";
            source = "fallback";
        }

        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        return new ChatResponse(response, timestamp, source);
    }

    /**
     * Multi-turn conversation with message history support.
     *
     * <p>Demonstrates loading chat history from a database (simulated) and
     * continuing the conversation. This is a common pattern when building
     * chat applications where history is stored in Redis, PostgreSQL, etc.
     *
     * <h2>Example Usage</h2>
     * <pre>
     * meshctl call chatWithHistory '{
     *   "sessionId": "user-123",
     *   "message": "What was my previous question?"
     * }'
     * </pre>
     *
     * @param sessionId Session ID for retrieving chat history
     * @param message   Current user message
     * @param llm       Injected LLM agent proxy
     * @return Chat response with context
     */
    @MeshLlm(
        providerSelector = @Selector(capability = "llm"),
        maxIterations = 3,
        systemPrompt = "You are a helpful assistant with memory of the conversation.",
        maxTokens = 2048,
        temperature = 0.7
    )
    @MeshTool(
        capability = "chatWithHistory",
        description = "Multi-turn chat with conversation history",
        tags = {"chat", "llm", "java", "history"}
    )
    public ChatResponse chatWithHistory(
        @Param(value = "sessionId", description = "Session ID for history lookup") String sessionId,
        @Param(value = "message", description = "Current user message") String message,
        MeshLlmAgent llm
    ) {
        log.info("Chat with history - session: {}, message: {}", sessionId, message);

        String response;
        String source;

        if (llm != null && llm.isAvailable()) {
            // Simulate loading chat history from Redis/database
            // In production: List<Message> history = Message.fromMaps(redis.getHistory(sessionId));
            List<Message> history = loadChatHistory(sessionId);

            log.info("Loaded {} history messages for session {}", history.size(), sessionId);

            // Use fluent builder with message history
            // This pattern supports 100s of messages efficiently
            response = llm.request()
                .system("You are a helpful assistant. Remember the conversation context.")
                .messages(history)      // Bulk add history from DB/Redis
                .user(message)          // Current message
                .maxTokens(2048)
                .temperature(0.7)
                .generate();

            source = "mesh:llm";
        } else {
            response = "I'm sorry, the LLM service is currently unavailable.";
            source = "fallback";
        }

        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        return new ChatResponse(response, timestamp, source);
    }

    /**
     * Simulate loading chat history from a database.
     *
     * <p>In production, this would query Redis, PostgreSQL, or another store:
     * <pre>{@code
     * List<Map<String, String>> rawHistory = redis.lrange("chat:" + sessionId, 0, -1);
     * return Message.fromMaps(rawHistory);
     * }</pre>
     */
    private List<Message> loadChatHistory(String sessionId) {
        // Simulate a few turns of conversation history
        List<Message> history = new ArrayList<>();

        // Simulated history (in production, this comes from Redis/DB)
        if (sessionId != null && sessionId.startsWith("demo")) {
            history.add(Message.user("Hello, I'm interested in data analysis."));
            history.add(Message.assistant("Hello! I'd be happy to help with data analysis. What kind of data are you working with?"));
            history.add(Message.user("I have sales data from Q4 2024."));
            history.add(Message.assistant("Great! Q4 sales data can reveal interesting trends. What specific insights are you looking for? For example: trends, comparisons, anomalies, or forecasts?"));
        }

        return history;
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
