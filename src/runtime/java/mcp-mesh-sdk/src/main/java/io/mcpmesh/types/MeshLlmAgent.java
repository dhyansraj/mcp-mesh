package io.mcpmesh.types;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Interface for LLM-powered agentic capabilities.
 *
 * <p>Instances are injected into methods annotated with {@code @MeshLlm}.
 * The agent handles the agentic loop: LLM generation, tool calling, and
 * response parsing.
 *
 * <h2>Usage Examples</h2>
 *
 * <h3>Simple Text Generation</h3>
 * <pre>{@code
 * @MeshLlm(provider = "claude")
 * @MeshTool(capability = "chat")
 * public String chat(@Param("message") String message, MeshLlmAgent llm) {
 *     return llm.generate(message);
 * }
 * }</pre>
 *
 * <h3>Structured Output</h3>
 * <pre>{@code
 * @MeshLlm(
 *     providerSelector = @Selector(capability = "llm"),
 *     systemPrompt = "You are a data analyst."
 * )
 * @MeshTool(capability = "analyze")
 * public AnalysisResult analyze(DataContext ctx, MeshLlmAgent llm) {
 *     return llm.generate("Analyze this data", AnalysisResult.class);
 * }
 * }</pre>
 *
 * <h3>With Tool Calling</h3>
 * <pre>{@code
 * @MeshLlm(
 *     provider = "claude",
 *     maxIterations = 5,
 *     filter = @Selector(tags = {"data", "api"})
 * )
 * @MeshTool(capability = "research")
 * public ResearchResult research(@Param("query") String query, MeshLlmAgent llm) {
 *     // LLM will call available tools and synthesize results
 *     return llm.generate("Research: " + query, ResearchResult.class);
 * }
 * }</pre>
 *
 * @see io.mcpmesh.MeshLlm
 * @see io.mcpmesh.MeshLlmProvider
 */
public interface MeshLlmAgent {

    /**
     * Generate a text response from the LLM.
     *
     * <p>The LLM may call available tools during generation if
     * {@code maxIterations > 1} is configured.
     *
     * @param prompt The user prompt
     * @return The LLM's text response
     */
    String generate(String prompt);

    /**
     * Generate a structured response from the LLM.
     *
     * <p>The response is parsed into the specified type using Jackson.
     * Works best with Java records.
     *
     * @param <T>          The expected response type
     * @param prompt       The user prompt
     * @param responseType The class to deserialize the response into
     * @return The parsed response object
     */
    <T> T generate(String prompt, Class<T> responseType);

    /**
     * Generate a text response asynchronously.
     *
     * @param prompt The user prompt
     * @return A future that completes with the response
     */
    CompletableFuture<String> generateAsync(String prompt);

    /**
     * Generate a structured response asynchronously.
     *
     * @param <T>          The expected response type
     * @param prompt       The user prompt
     * @param responseType The class to deserialize the response into
     * @return A future that completes with the parsed response
     */
    <T> CompletableFuture<T> generateAsync(String prompt, Class<T> responseType);

    /**
     * Get the list of tools available to this LLM agent.
     *
     * @return List of available tool information
     */
    List<ToolInfo> getAvailableTools();

    /**
     * Check if the LLM provider is available.
     *
     * @return true if the provider is connected, false otherwise
     */
    boolean isAvailable();

    /**
     * Get the provider name (for direct mode) or endpoint (for mesh mode).
     *
     * @return Provider identifier
     */
    String getProvider();

    /**
     * Information about an available tool.
     */
    record ToolInfo(
        String name,
        String description,
        String capability,
        String agentId,
        Map<String, Object> inputSchema
    ) {}
}
