package io.mcpmesh.ai.handlers;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Generic/fallback LLM provider handler.
 *
 * <p>Used when no vendor-specific handler is registered. Implements
 * conservative defaults that should work with most LLM APIs:
 * <ul>
 *   <li>Standard message format conversion</li>
 *   <li>No vendor-specific optimizations</li>
 *   <li>Minimal assumptions about capabilities</li>
 * </ul>
 *
 * <h2>When Used</h2>
 * <p>This handler is selected when:
 * <ul>
 *   <li>Vendor is null or empty</li>
 *   <li>Vendor is "unknown"</li>
 *   <li>No handler is registered for the vendor</li>
 * </ul>
 *
 * @see LlmProviderHandler
 * @see LlmProviderHandlerRegistry
 */
public class GenericHandler implements LlmProviderHandler {

    private static final Logger log = LoggerFactory.getLogger(GenericHandler.class);

    @Override
    public String getVendor() {
        return "generic";
    }

    @Override
    public String generateWithMessages(
            ChatModel model,
            List<Map<String, Object>> messages,
            Map<String, Object> options) {

        log.debug("GenericHandler: Processing {} messages (fallback mode)", messages.size());

        // Convert to Spring AI messages using conservative approach
        List<Message> springMessages = convertMessages(messages);

        log.debug("GenericHandler: Converted to {} Spring AI messages", springMessages.size());

        // Create prompt with messages
        Prompt prompt = new Prompt(springMessages);

        // Call the model
        ChatResponse response = model.call(prompt);

        String content = response.getResult().getOutput().getContent();
        log.debug("GenericHandler: Generated response ({} chars)",
            content != null ? content.length() : 0);

        return content;
    }

    @Override
    public Map<String, Boolean> getCapabilities() {
        // Conservative defaults - assume minimal capabilities
        return Map.of(
            "native_tool_calling", true,
            "structured_output", false,  // Don't assume JSON mode
            "streaming", false,          // Don't assume streaming
            "vision", false,
            "json_mode", false
        );
    }

    /**
     * Convert generic messages to Spring AI Message objects.
     *
     * <p>Uses the most common/standard message format that works
     * with most LLM APIs.
     */
    private List<Message> convertMessages(List<Map<String, Object>> messages) {
        List<Message> result = new ArrayList<>();

        for (Map<String, Object> msg : messages) {
            String role = (String) msg.get("role");
            String content = (String) msg.get("content");

            if (role == null || content == null || content.trim().isEmpty()) {
                continue;
            }

            Message springMessage = switch (role.toLowerCase()) {
                case "system" -> new SystemMessage(content);
                case "user" -> new UserMessage(content);
                case "assistant" -> new AssistantMessage(content);
                case "tool", "function" -> {
                    // Generic tool result handling
                    yield new UserMessage("[Tool/Function Result]\n" + content);
                }
                default -> {
                    log.warn("Unknown message role '{}', treating as user", role);
                    yield new UserMessage(content);
                }
            };

            result.add(springMessage);
        }

        return result;
    }
}
