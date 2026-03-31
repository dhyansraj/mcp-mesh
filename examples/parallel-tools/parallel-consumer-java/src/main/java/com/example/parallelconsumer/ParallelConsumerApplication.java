package com.example.parallelconsumer;

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
 * LLM agent testing parallel tool execution.
 *
 * <p>This example demonstrates:
 * <ul>
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
 * ParallelConsumer (@MeshLlm, parallelToolCalls=true)
 *      |
 *      +-- discovers tools from mesh (tags: "financial", "slow-tool")
 *      |
 *      +-- calls LLM Provider via mesh
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
 * # Start an LLM provider
 * meshctl start -d examples/llm-provider/claude_provider.py
 *
 * # Start the slow tool agent
 * meshctl start -d examples/parallel-tools/slow-tool-java
 *
 * # Run this agent
 * meshctl start examples/parallel-tools/parallel-consumer-java -d
 *
 * # Test parallel execution
 * meshctl call parallel_analyze '{"ctx": {"query": "Analyze AAPL stock", "ticker": "AAPL"}}'
 * </pre>
 */
@MeshAgent(
    name = "parallel-consumer-java",
    version = "1.0.0",
    description = "LLM agent testing parallel tool execution",
    port = 9000
)
@SpringBootApplication
public class ParallelConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(ParallelConsumerApplication.class);

    public static void main(String[] args) {
        log.info("Starting Parallel Consumer Agent...");
        SpringApplication.run(ParallelConsumerApplication.class, args);
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
     * AI-powered stock analysis with parallel tool execution.
     *
     * <p>The {@code parallelToolCalls = true} setting enables the LLM to call
     * multiple tools simultaneously. Combined with the slow financial tools
     * (each taking ~3s), this demonstrates a ~3x speedup from parallel execution.
     *
     * @param ctx Analysis context with query and ticker
     * @param llm Injected LLM agent proxy (delegates to mesh provider)
     * @return Structured stock analysis result
     */
    @MeshLlm(
        providerSelector = @Selector(capability = "llm"),
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
            StockAnalysis result = llm.request()
                .user(ctx.query())
                .maxTokens(4096)
                .generate(StockAnalysis.class);

            var meta = llm.request().lastMeta();
            if (meta != null) {
                log.info("Generation completed: {} iterations, {}ms latency",
                    meta.iterations(), meta.latencyMs());
            }

            return result;

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
