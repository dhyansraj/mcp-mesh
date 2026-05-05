package com.example.consumer;

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
 * Mesh-delegated LLM agent testing parallel tool execution with Gemini.
 *
 * <p>This example demonstrates:
 * <ul>
 *   <li>Mesh delegation to a Gemini LLM provider — selected via tags</li>
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
 * ConsumerGemini (@MeshLlm, mesh-delegated, parallelToolCalls=true)
 *      |
 *      +-- discovers tools from mesh (tags: "financial", "slow-tool")
 *      |
 *      +-- delegates to a Gemini LLM provider in the mesh
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
 * # Start a Gemini LLM provider (e.g., examples/llm-provider/gemini_provider.py)
 * meshctl start -d examples/llm-provider/gemini_provider.py
 *
 * # Start the slow tool agent
 * meshctl start -d examples/parallel-tools/slow-tool-java
 *
 * # Run this agent
 * meshctl start examples/parallel-tools/consumer-gemini-java -d
 *
 * # Test parallel execution
 * meshctl call parallelAnalyze '{"ctx": {"query": "Analyze AAPL stock", "ticker": "AAPL"}}'
 * </pre>
 */
@MeshAgent(
    name = "consumer-gemini-java",
    version = "1.0.0",
    description = "Mesh-delegated LLM agent testing parallel tool execution with Gemini",
    port = 9000
)
@SpringBootApplication
public class ConsumerGeminiApplication {

    private static final Logger log = LoggerFactory.getLogger(ConsumerGeminiApplication.class);

    public static void main(String[] args) {
        log.info("Starting Consumer Gemini Agent...");
        SpringApplication.run(ConsumerGeminiApplication.class, args);
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
     * AI-powered stock analysis with parallel tool execution using a Gemini
     * LLM provider in the mesh.
     *
     * <p>The {@code providerSelector} pins the request to a Gemini provider
     * via the {@code +gemini} tag. The {@code parallelToolCalls = true}
     * setting enables the LLM to call multiple tools simultaneously.
     *
     * @param ctx Analysis context with query and ticker
     * @param llm Injected LLM agent proxy (delegates to mesh provider)
     * @return Structured stock analysis result
     */
    @MeshLlm(
        providerSelector = @Selector(capability = "llm", tags = {"+gemini"}),
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
