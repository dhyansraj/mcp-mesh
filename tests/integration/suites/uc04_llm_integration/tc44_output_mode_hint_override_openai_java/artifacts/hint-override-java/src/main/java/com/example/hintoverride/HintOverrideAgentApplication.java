package com.example.hintoverride;

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

import java.util.Map;

/**
 * DEDICATED minimal Java consumer for tc44 — Issue #1112 finding #6.
 *
 * <p>This agent exists ONLY to prove the Java consumer-side {@code outputMode="hint"}
 * override end-to-end against an OpenAI provider, the NORMAL single-tool case.
 *
 * <p>WHY A DEDICATED AGENT (not the shared {@code llm-mesh-agent} analyst): a
 * confirmed PRE-EXISTING bug (#1141, unrelated to output_mode) makes per-funcId
 * LLM-provider proxies bind UNRELIABLY when one agent declares MANY {@code @MeshLlm}
 * functions. The shared analyst has 5 {@code @MeshLlm} tools, so {@code analyzeHint}'s
 * proxy frequently never bound and the override call never reached the provider.
 * This agent declares EXACTLY ONE {@code @MeshLlm} function — the normal case — so
 * its proxy binds reliably (first attempt or two) and sidesteps #1141 entirely.
 *
 * <p>The single {@code analyzeHint} tool mirrors the working {@code analyze} wiring
 * from the analyst (providerSelector capability="llm", filter tags data/tools,
 * filterMode ALL) so it resolves the same Java OpenAI provider (java-gpt-provider).
 * The ONLY behavioral difference vs a plain analyze is {@code outputMode = "hint"}:
 * against an OpenAI provider (auto-selects strict/native response_format), forcing
 * hint makes the provider embed the schema in the prompt and drop response_format
 * while still producing a valid {@link CountryInfo}.
 *
 * <p>RESPONSE MODEL IS ALL-SCALAR ({@link CountryInfo}: country/capital/population,
 * all String) — mirrors tc42's Python {@code CountryInfo}. This is DELIBERATE: under
 * hint mode there is NO native schema enforcement, so loosely-shaped fields (e.g. a
 * {@code List<String>}) may come back as a JSON string and trip Java's strict Jackson
 * deserialization — a SEPARATE, orthogonal hint-mode robustness gap tracked as #1142.
 * All-scalar fields are reliably shaped in hint mode, so this tc proves ONLY the thing
 * under test (is the consumer-side override honored end-to-end) without colliding with
 * #1142.
 */
@MeshAgent(
    name = "hint-override-java",
    version = "1.0.0",
    description = "Dedicated single-@MeshLlm Java consumer forcing outputMode=hint (issue #1112 finding #6)",
    port = 9044
)
@SpringBootApplication
public class HintOverrideAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(HintOverrideAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Hint-Override Java Agent (single @MeshLlm)...");
        SpringApplication.run(HintOverrideAgentApplication.class, args);
    }

    /**
     * The ONLY @MeshLlm function on this agent: a FORCED HINT output mode call
     * returning an ALL-SCALAR {@link CountryInfo} (Issue #1112 finding #6).
     *
     * <p>Provider-selection wiring is intentionally IDENTICAL to the analyst's
     * working {@code analyze} (capability "llm", filter tags data/tools, ALL) — the
     * ONLY difference is {@code outputMode = "hint"}.
     */
    @MeshLlm(
        providerSelector = @Selector(capability = "llm"),
        maxIterations = 5,
        systemPrompt = "classpath:prompts/analyst.ftl",
        contextParam = "ctx",
        filter = @Selector(tags = {"data", "tools"}),
        filterMode = FilterMode.ALL,
        maxTokens = 4096,
        temperature = 0.7,
        // Issue #1112 finding #6: force HINT, overriding the provider's auto mode
        // (OpenAI strict -> hint: schema in prompt, no response_format).
        outputMode = "hint"
    )
    @MeshTool(
        capability = "analyzeHint",
        description = "Country info lookup with forced HINT output mode (all-scalar result)",
        tags = {"analysis", "llm", "java", "hint-override"}
    )
    public CountryInfo analyzeHint(
        @Param(value = "ctx", description = "Analysis context") AnalysisContext ctx,
        MeshLlmAgent llm
    ) {
        log.info("Analyzing (forced HINT mode): {}", ctx.query());

        if (llm == null || !llm.isAvailable()) {
            log.warn("LLM provider not available, returning fallback");
            return fallbackAnalysis(ctx);
        }

        try {
            CountryInfo result = llm.request()
                .user(ctx.query())
                .maxTokens(4096)
                .temperature(0.7)
                .generate(CountryInfo.class);

            var meta = llm.request().lastMeta();
            if (meta != null) {
                log.info("HINT generation completed: {} iterations, {}ms latency",
                    meta.iterations(), meta.latencyMs());
            }

            return result;

        } catch (Exception e) {
            log.error("HINT analysis failed: {}", e.getMessage(), e);
            return fallbackAnalysis(ctx);
        }
    }

    /**
     * Local fallback returning a clearly-identifiable sentinel (country="UNAVAILABLE").
     * {@link CountryInfo} has no {@code source} field, so the unmistakable fallback
     * marker is {@code country="UNAVAILABLE"} (plus capital="UNAVAILABLE"). The tc's
     * anti-fallback assertions reject country=="UNAVAILABLE" so a non-binding proxy
     * fails the test loud rather than passing structurally.
     */
    private CountryInfo fallbackAnalysis(AnalysisContext ctx) {
        return new CountryInfo(
            "UNAVAILABLE",
            "UNAVAILABLE",
            "LLM provider not connected"
        );
    }

    /**
     * Analysis context record (flat, mirrors the analyst).
     */
    public record AnalysisContext(
        String query,
        String dataSource,
        Map<String, Object> parameters
    ) {}

    /**
     * Structured result record — ALL-SCALAR shape (every field a String, NO List /
     * array / nested record). Mirrors tc42's Python {@code CountryInfo}. All-scalar
     * fields are reliably shaped under hint mode (no native schema enforcement), so
     * this proves the override end-to-end without tripping the strict-Jackson-deser
     * gap for loosely-shaped hint output (#1142).
     */
    public record CountryInfo(
        String country,
        String capital,
        String population
    ) {}
}
