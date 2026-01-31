package io.mcpmesh.ai;

import io.mcpmesh.ai.handlers.LlmProviderHandler;
import io.mcpmesh.ai.handlers.LlmProviderHandlerRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Spring AI LLM provider for direct LLM calls.
 *
 * <p>Manages ChatClient instances for different LLM providers (Claude, OpenAI, etc.).
 * Used when {@code @MeshLlm(provider = "claude")} is specified (direct mode).
 *
 * <h2>Supported Providers</h2>
 * <ul>
 *   <li>{@code "claude"}, {@code "anthropic"} - Anthropic Claude models</li>
 *   <li>{@code "openai"}, {@code "gpt"} - OpenAI GPT models</li>
 * </ul>
 *
 * <h2>Configuration</h2>
 * <p>Requires API keys in environment:
 * <ul>
 *   <li>{@code ANTHROPIC_API_KEY} - For Claude models</li>
 *   <li>{@code OPENAI_API_KEY} - For OpenAI models</li>
 * </ul>
 *
 * <p>Or in application.yml:
 * <pre>
 * spring:
 *   ai:
 *     anthropic:
 *       api-key: ${ANTHROPIC_API_KEY}
 *     openai:
 *       api-key: ${OPENAI_API_KEY}
 * </pre>
 */
public class SpringAiLlmProvider {

    private static final Logger log = LoggerFactory.getLogger(SpringAiLlmProvider.class);

    private final Map<String, ChatClient> clients = new ConcurrentHashMap<>();

    @Autowired(required = false)
    private ChatModel anthropicChatModel;

    @Autowired(required = false)
    private ChatModel openAiChatModel;

    /**
     * Get a ChatClient for the specified provider.
     *
     * @param provider The provider name (claude, anthropic, openai, gpt)
     * @return The ChatClient for the provider
     * @throws IllegalArgumentException if the provider is unknown or not configured
     */
    public ChatClient getClient(String provider) {
        return clients.computeIfAbsent(provider.toLowerCase(), this::createClient);
    }

    /**
     * Check if a provider is available.
     *
     * @param provider The provider name
     * @return true if the provider is configured and available
     */
    public boolean isProviderAvailable(String provider) {
        String normalizedProvider = provider.toLowerCase();
        return switch (normalizedProvider) {
            case "claude", "anthropic" -> anthropicChatModel != null;
            case "openai", "gpt" -> openAiChatModel != null;
            default -> false;
        };
    }

    /**
     * Generate a text response using the specified provider.
     *
     * @param provider     The LLM provider name
     * @param systemPrompt The system prompt
     * @param userPrompt   The user prompt
     * @return The generated response
     */
    public String generate(String provider, String systemPrompt, String userPrompt) {
        ChatClient client = getClient(provider);

        ChatClient.ChatClientRequestSpec requestSpec = client.prompt();

        // Only set system prompt if it's non-empty (Spring AI rejects empty strings)
        if (systemPrompt != null && !systemPrompt.isEmpty()) {
            requestSpec.system(systemPrompt);
        }

        ChatClient.CallResponseSpec response = requestSpec
            .user(userPrompt)
            .call();

        return response.content();
    }

    /**
     * Generate a structured response using the specified provider.
     *
     * @param <T>          The response type
     * @param provider     The LLM provider name
     * @param systemPrompt The system prompt
     * @param userPrompt   The user prompt
     * @param responseType The class to deserialize the response into
     * @return The parsed response
     */
    public <T> T generate(String provider, String systemPrompt, String userPrompt,
                          Class<T> responseType) {
        ChatClient client = getClient(provider);

        ChatClient.ChatClientRequestSpec requestSpec = client.prompt();

        // Only set system prompt if it's non-empty (Spring AI rejects empty strings)
        if (systemPrompt != null && !systemPrompt.isEmpty()) {
            requestSpec.system(systemPrompt);
        }

        return requestSpec
            .user(userPrompt)
            .call()
            .entity(responseType);
    }

    /**
     * Generate a response with full message history.
     *
     * <p>This method supports multi-turn conversations by accepting a list of
     * messages with roles (system, user, assistant). Uses vendor-specific
     * handlers for optimal message formatting.
     *
     * @param provider The LLM provider name (e.g., "anthropic", "openai")
     * @param messages List of messages with role and content
     * @return The generated response
     */
    public String generateWithMessages(String provider, List<Map<String, Object>> messages) {
        return generateWithMessages(provider, messages, Map.of());
    }

    /**
     * Generate a response with full message history and options.
     *
     * <p>Delegates to a vendor-specific handler for optimal message formatting.
     *
     * @param provider The LLM provider name
     * @param messages List of messages with role and content
     * @param options  Generation options (max_tokens, temperature, etc.)
     * @return The generated response
     */
    public String generateWithMessages(String provider, List<Map<String, Object>> messages,
                                        Map<String, Object> options) {
        // Get vendor-specific handler
        LlmProviderHandler handler = LlmProviderHandlerRegistry.getHandler(provider);

        log.debug("Using {} for provider '{}' with {} messages",
            handler.getClass().getSimpleName(), provider, messages.size());

        // Get the ChatModel for this provider
        ChatModel model = getModelForProvider(provider);

        // Delegate to handler for vendor-specific processing
        return handler.generateWithMessages(model, messages, options);
    }

    /**
     * Get the ChatModel for a provider.
     *
     * @param provider The provider name
     * @return The configured ChatModel
     * @throws IllegalStateException if the model is not configured
     */
    public ChatModel getModelForProvider(String provider) {
        return switch (provider.toLowerCase()) {
            case "claude", "anthropic" -> {
                if (anthropicChatModel == null) {
                    throw new IllegalStateException("Anthropic ChatModel not configured. " +
                        "Add spring-ai-anthropic dependency and set ANTHROPIC_API_KEY");
                }
                yield anthropicChatModel;
            }
            case "openai", "gpt" -> {
                if (openAiChatModel == null) {
                    throw new IllegalStateException("OpenAI ChatModel not configured. " +
                        "Add spring-ai-openai dependency and set OPENAI_API_KEY");
                }
                yield openAiChatModel;
            }
            default -> {
                // Try anthropic as default fallback
                if (anthropicChatModel != null) {
                    log.warn("Unknown provider '{}', falling back to Anthropic", provider);
                    yield anthropicChatModel;
                }
                if (openAiChatModel != null) {
                    log.warn("Unknown provider '{}', falling back to OpenAI", provider);
                    yield openAiChatModel;
                }
                throw new IllegalArgumentException("No ChatModel available for provider: " + provider);
            }
        };
    }

    private ChatClient createClient(String provider) {
        ChatModel model = switch (provider) {
            case "claude", "anthropic" -> {
                if (anthropicChatModel == null) {
                    throw new IllegalStateException(
                        "Anthropic ChatModel not configured. Add spring-ai-anthropic dependency and set ANTHROPIC_API_KEY");
                }
                yield anthropicChatModel;
            }
            case "openai", "gpt" -> {
                if (openAiChatModel == null) {
                    throw new IllegalStateException(
                        "OpenAI ChatModel not configured. Add spring-ai-openai dependency and set OPENAI_API_KEY");
                }
                yield openAiChatModel;
            }
            default -> throw new IllegalArgumentException("Unknown LLM provider: " + provider +
                ". Supported: claude, anthropic, openai, gpt");
        };

        log.info("Creating ChatClient for provider: {}", provider);
        return ChatClient.create(model);
    }
}
