package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as an LLM-powered tool with automatic tool discovery.
 *
 * <p>Methods annotated with {@code @MeshLlm} have access to an injected
 * {@code MeshLlmAgent} that can generate responses by routing to an LLM
 * provider agent in the mesh.
 *
 * <h2>Mesh Delegation</h2>
 * <p>The LLM call is always routed to a provider agent in the mesh. Use
 * {@link #providerSelector()} to pick which provider should serve the request.
 * <pre>{@code
 * @MeshLlm(
 *     providerSelector = @Selector(
 *         capability = "llm",
 *         tags = {"+claude", "+anthropic"}
 *     ),
 *     maxIterations = 5,
 *     systemPrompt = "classpath://prompts/analyst.ftl"
 * )
 * @MeshTool(capability = "analyze")
 * public AnalysisResult analyze(AnalysisContext ctx, MeshLlmAgent llm) {
 *     return llm.generate("Analyze the data", AnalysisResult.class);
 * }
 * }</pre>
 *
 * <h2>Response model vs tool output</h2>
 * <p>Three types are involved in an LLM-powered tool, and they are independent:
 * <ul>
 *   <li>The {@code Class<T>} passed to {@code llm.generate(..., T.class)} is the
 *       <b>response model</b> — the schema the LLM must <i>emit</i>, which the
 *       provider's structured-output schema is built from and which the result
 *       is validated/deserialized against.</li>
 *   <li>{@link MeshTool#outputType()} is the tool's published {@code outputSchema}
 *       — what <i>callers</i> receive.</li>
 *   <li>The method's return type is what the method actually returns.</li>
 * </ul>
 * <p>Because they are separate, a tool can have the LLM emit only a focused
 * subset of fields while the tool returns a fuller payload that combines those
 * LLM-produced fields with deterministic, function-computed fields:
 * <pre>{@code
 * public record AnalystOutput(String summary, java.util.List<String> riskFlags) {}      // LLM emits this (focused)
 * public record RunDailyResult(String email, String date, double totalValue,
 *                              String summary, java.util.List<String> riskFlags) {}      // tool returns this
 *
 * @MeshLlm(
 *     providerSelector = @Selector(capability = "llm", tags = {"+openai"}),
 *     systemPrompt = "classpath://prompts/analyst.ftl"
 * )
 * @MeshTool(capability = "analysis.run_daily", outputType = RunDailyResult.class)        // tool outputSchema
 * public RunDailyResult runDaily(RunDailyContext ctx, MeshLlmAgent llm) {
 *     AnalystOutput analyst = llm.generate("Analyze the portfolio", AnalystOutput.class); // LLM emits the focused schema
 *     return new RunDailyResult(ctx.email(), today(), ctx.totalValue(),
 *                               analyst.summary(), analyst.riskFlags());                   // tool returns the full payload
 * }
 * }</pre>
 *
 * <h2>System Prompts</h2>
 * <p>System prompts can be:
 * <ul>
 *   <li>Inline strings</li>
 *   <li>{@code file://path/to/template.ftl} - File system Freemarker template</li>
 *   <li>{@code classpath://prompts/template.ftl} - Classpath Freemarker template</li>
 * </ul>
 *
 * @see MeshLlmProvider
 * @see FilterMode
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface MeshLlm {

    /**
     * Selector for the mesh-delegated LLM provider.
     *
     * <p>Required. Use tags such as {@code "+claude"} or {@code "+openai"} to
     * pick a specific provider when multiple are registered for the
     * {@code "llm"} capability.
     */
    Selector providerSelector() default @Selector;

    /**
     * Maximum iterations for the agentic loop.
     *
     * <p>Each iteration allows the LLM to make tool calls.
     */
    int maxIterations() default MeshLlmDefaults.MAX_ITERATIONS;

    /**
     * System prompt for the LLM.
     *
     * <p>Can be:
     * <ul>
     *   <li>Plain text string</li>
     *   <li>{@code file://path.ftl} for Freemarker file</li>
     *   <li>{@code classpath://path.ftl} for bundled template</li>
     * </ul>
     */
    String systemPrompt() default "";

    /**
     * Parameter name for context injection in templates.
     *
     * <p>The parameter with this name will be available as a variable
     * in Freemarker templates.
     */
    String contextParam() default "ctx";

    /**
     * Tool filters for discovery.
     *
     * <p>Only tools matching these selectors will be available to the LLM.
     */
    Selector[] filter() default {};

    /**
     * How to apply tool filters.
     */
    FilterMode filterMode() default FilterMode.ALL;

    /**
     * Optional per-tool model override.
     *
     * <p>When set (non-empty), this model string (e.g.
     * {@code "anthropic/claude-3-5-sonnet-latest"}) is sent to the provider via
     * {@code model_params.model}. The provider honors it when the override's
     * vendor matches its own vendor, otherwise it logs a warning and falls back
     * to the provider's default model — mirroring Python's vendor-checked
     * behavior.
     *
     * <p>A per-call override supplied via the proxy's {@code modelParams(Map)}
     * escape hatch (key {@code "model"}) takes precedence over this annotation
     * value.
     *
     * <p>If unset (empty string), no {@code model} is sent on the wire and the
     * provider uses the model declared on its own {@code @MeshLlmProvider}.
     */
    String model() default "";

    /**
     * Maximum tokens for LLM response.
     *
     * <p>If unset ({@code -1}), the provider's own default is used — no
     * {@code max_tokens} is sent on the wire.
     */
    int maxTokens() default MeshLlmDefaults.MAX_TOKENS_UNSET;

    /**
     * Temperature for LLM generation.
     *
     * <p>Higher values (0.7-1.0) are more creative,
     * lower values (0.0-0.3) are more deterministic.
     *
     * <p>If unset ({@code NaN}), the provider's own default is used — no
     * {@code temperature} is sent on the wire.
     */
    double temperature() default MeshLlmDefaults.TEMPERATURE_UNSET;

    /**
     * Enable parallel tool execution.
     *
     * <p>When true, multiple tool calls from a single LLM response
     * will be executed concurrently using CompletableFuture.
     * Default is false (sequential execution).
     */
    boolean parallelToolCalls() default false;

    /**
     * Structured-output mode the provider should apply for this consumer.
     *
     * <p>Allowed values:
     * <ul>
     *   <li>{@code "strict"} — schema-enforced structured output
     *       (response_format / responseSchema / native output_format).</li>
     *   <li>{@code "hint"} — prompt-based JSON instructions.</li>
     *   <li>{@code "text"} — plain text, no structured-output enforcement.</li>
     * </ul>
     *
     * <p>If unset ({@link MeshLlmDefaults#OUTPUT_MODE_UNSET}), the provider
     * auto-selects the mode per vendor/schema (its existing behavior) and no
     * {@code output_mode} is sent on the wire. An invalid value is ignored and
     * treated as unset.
     */
    String outputMode() default MeshLlmDefaults.OUTPUT_MODE_UNSET;
}
