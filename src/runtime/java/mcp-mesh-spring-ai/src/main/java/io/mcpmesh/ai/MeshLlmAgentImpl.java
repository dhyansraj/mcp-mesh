package io.mcpmesh.ai;

import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Implementation of MeshLlmAgent using Spring AI.
 *
 * <p>Supports both direct mode (using local Spring AI ChatClient) and
 * mesh delegation mode (routing to remote LLM provider agents).
 */
public class MeshLlmAgentImpl implements MeshLlmAgent {

    private static final Logger log = LoggerFactory.getLogger(MeshLlmAgentImpl.class);

    private final String functionId;
    private final SpringAiLlmProvider llmProvider;
    private final String provider;
    private final String systemPrompt;
    private final int maxIterations;
    private final List<ToolInfo> availableTools;
    private volatile boolean available;

    /**
     * Create an LLM agent for direct mode (using Spring AI).
     */
    public MeshLlmAgentImpl(String functionId, SpringAiLlmProvider llmProvider,
                            String provider, String systemPrompt, int maxIterations) {
        this.functionId = functionId;
        this.llmProvider = llmProvider;
        this.provider = provider;
        this.systemPrompt = systemPrompt;
        this.maxIterations = maxIterations;
        this.availableTools = new ArrayList<>();
        this.available = llmProvider.isProviderAvailable(provider);
    }

    @Override
    public String generate(String prompt) {
        if (!available) {
            throw new IllegalStateException("LLM agent not available: " + functionId);
        }

        log.debug("Generating response for prompt: {}", prompt);

        // For simple generation without tools, use direct call
        return llmProvider.generate(provider, systemPrompt, prompt);
    }

    @Override
    public <T> T generate(String prompt, Class<T> responseType) {
        if (!available) {
            throw new IllegalStateException("LLM agent not available: " + functionId);
        }

        log.debug("Generating structured response ({}) for prompt: {}",
            responseType.getSimpleName(), prompt);

        return llmProvider.generate(provider, systemPrompt, prompt, responseType);
    }

    @Override
    public CompletableFuture<String> generateAsync(String prompt) {
        return CompletableFuture.supplyAsync(() -> generate(prompt));
    }

    @Override
    public <T> CompletableFuture<T> generateAsync(String prompt, Class<T> responseType) {
        return CompletableFuture.supplyAsync(() -> generate(prompt, responseType));
    }

    @Override
    public List<ToolInfo> getAvailableTools() {
        return new ArrayList<>(availableTools);
    }

    @Override
    public boolean isAvailable() {
        return available;
    }

    @Override
    public String getProvider() {
        return provider;
    }

    /**
     * Update the list of available tools for agentic loops.
     */
    public void updateTools(List<ToolInfo> tools) {
        this.availableTools.clear();
        this.availableTools.addAll(tools);
    }

    /**
     * Set availability status.
     */
    public void setAvailable(boolean available) {
        this.available = available;
    }
}
