package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as an LLM-powered tool with automatic tool discovery.
 *
 * <p>Methods annotated with {@code @MeshLlm} have access to an injected
 * {@code MeshLlmAgent} that can generate responses using LLM capabilities.
 *
 * <h2>LLM Provider Modes</h2>
 *
 * <h3>Direct Mode (Spring AI)</h3>
 * <p>Uses Spring AI clients directly. Requires appropriate API keys.
 * <pre>{@code
 * @MeshLlm(
 *     provider = "claude",  // or "openai"
 *     maxIterations = 3,
 *     systemPrompt = "You are a helpful assistant."
 * )
 * @MeshTool(capability = "chat")
 * public String chat(@Param("message") String message, MeshLlmAgent llm) {
 *     return llm.generate(message);
 * }
 * }</pre>
 *
 * <h3>Mesh Delegation Mode</h3>
 * <p>Routes to an LLM provider agent in the mesh.
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
     * Direct LLM provider name for Spring AI.
     *
     * <p>Supported values: "claude", "anthropic", "openai", "gpt".
     * Leave empty to use {@link #providerSelector()} for mesh delegation.
     */
    String provider() default "";

    /**
     * Selector for mesh-delegated LLM provider.
     *
     * <p>Used when {@link #provider()} is empty.
     */
    Selector providerSelector() default @Selector;

    /**
     * Maximum iterations for the agentic loop.
     *
     * <p>Each iteration allows the LLM to make tool calls.
     */
    int maxIterations() default 1;

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
     * Maximum tokens for LLM response.
     */
    int maxTokens() default 4096;

    /**
     * Temperature for LLM generation.
     *
     * <p>Higher values (0.7-1.0) are more creative,
     * lower values (0.0-0.3) are more deterministic.
     */
    double temperature() default 0.7;
}
