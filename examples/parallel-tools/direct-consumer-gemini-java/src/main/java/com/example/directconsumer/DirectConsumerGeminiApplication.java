package com.example.directconsumer;

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

import java.util.List;

/**
 * Direct-mode LLM agent testing parallel tool execution with Gemini.
 *
 * <p>This example demonstrates:
 * <ul>
 *   <li>Direct provider mode - provider = "google/gemini-2.0-flash" (no providerSelector)</li>
 *   <li>parallelToolCalls = true - enables concurrent tool calls</li>
 *   <li>Tool filtering by tags - discovers slow financial tools from the mesh</li>
 *   <li>Structured output - parses LLM responses to Java records</li>
 * </ul>
 *
 * <h2>Architecture</h2>
 * <pre>
 * User Request (ticker)
 *      |
 *      v
 * DirectConsumerGemini (@MeshLlm, direct mode, parallelToolCalls=true)
 *      |
 *      +-- discovers tools from mesh (tags: "financial", "slow-tool")
 *      |
 *      +-- calls Gemini directly (no mesh LLM provider needed)
 *      |        |
 *      |        +-- LLM calls all 3 tools simultaneously:
 *      |        |     - get_stock_price
 *      |        |     - get_company_info
 *      |        |     - get_market_sentiment
 *      |        |
 *      |        +-- All 3 results returned together (~3s vs ~9s)
 *      |        |
 *      |        +-- LLM synthesizes final response
 *      |
 *      v
 * StockAnalysis (structured result)
 * </pre>
 *
 * <h2>Running</h2>
 * <pre>
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Start the slow tool agent
 * meshctl start -d examples/parallel-tools/slow-tool-java
 *
 * # Run this agent (no separate LLM provider needed)
 * GOOGLE_API_KEY=... meshctl start examples/parallel-tools/direct-consumer-gemini-java -d
 *
 * # Test parallel execution
 * meshctl call parallelAnalyze '{"ctx": {"query": "Analyze AAPL stock", "ticker": "AAPL"}}'
 * </pre>
 */
@MeshAgent(
    name = "direct-consumer-gemini-java",
    version = "1.0.0",
    description = "Direct-mode LLM agent testing parallel tool execution with Gemini",
    port = 9000
)
@SpringBootApplication
public class DirectConsumerGeminiApplication {

    private static final Logger log = LoggerFactory.getLogger(DirectConsumerGeminiApplication.class);

    public static void main(String[] args) {
        log.info("Starting Direct Consumer Gemini Agent...");
        SpringApplication.run(DirectConsumerGeminiApplication.class, args);
    }

    /**
     * Analysis context record.
     */
    public record AnalysisContext(
        String query,
        String ticker
    ) {}

    /**
     * Structured stock analysis result record.
     *
     * <p>The LLM is instructed to return JSON matching this structure.
     */
    public record StockAnalysis(
        String summary,
        List<String> insights,
        String ticker,
        List<String> data_sources
    ) {}

    /**
     * AI-powered stock analysis with parallel tool execution using Gemini directly.
     *
     * <p>The {@code provider = "google/gemini-2.0-flash"} setting uses the LLM directly
     * without requiring a separate provider agent in the mesh.
     * The {@code parallelToolCalls = true} setting enables the LLM to call
     * multiple tools simultaneously.
     *
     * @param ctx Analysis context with query and ticker
     * @param llm Injected LLM agent proxy (direct provider)
     * @return Structured stock analysis result
     */
    @MeshLlm(
        provider = "google/gemini-2.0-flash",
        maxIterations = 5,
        parallelToolCalls = true,
        systemPrompt = "classpath:prompts/system.ftl",
        contextParam = "ctx",
        filter = @Selector(tags = {"financial", "slow-tool"}),
        filterMode = FilterMode.ALL,
        maxTokens = 4096,
        temperature = 0.7
    )
    @MeshTool(
        capability = "parallel_analyze",
        description = "AI-powered stock analysis with parallel tool execution",
        tags = {"analysis", "llm", "parallel-test"}
    )
    public StockAnalysis parallelAnalyze(
        @Param(value = "ctx", description = "Analysis context") AnalysisContext ctx,
        MeshLlmAgent llm
    ) {
        log.info("Parallel analyzing: {} (ticker: {})", ctx.query(), ctx.ticker());

        if (llm == null || !llm.isAvailable()) {
            log.warn("LLM provider not available, returning fallback");
            return fallbackAnalysis(ctx);
        }

        try {
            return llm.request()
                .user(ctx.query())
                .maxTokens(4096)
                .generate(StockAnalysis.class);
        } catch (Exception e) {
            log.error("Parallel analysis failed: {}", e.getMessage(), e);
            return fallbackAnalysis(ctx);
        }
    }

    private StockAnalysis fallbackAnalysis(AnalysisContext ctx) {
        return new StockAnalysis(
            "Unable to analyze - LLM unavailable",
            List.of("No data available"),
            ctx.ticker() != null ? ctx.ticker() : "UNKNOWN",
            List.of()
        );
    }
}
