package io.mcpmesh.ai.handlers;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.chat.prompt.Prompt;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * LLM provider handler for Anthropic Claude models.
 *
 * <p>Handles Claude-specific message formatting and features:
 * <ul>
 *   <li>Full multi-turn conversation support</li>
 *   <li>System message handling (Claude prefers single system message)</li>
 *   <li>Prompt caching support (future)</li>
 *   <li>Claude-specific output modes</li>
 * </ul>
 *
 * <h2>Message Format</h2>
 * <p>Claude expects messages in alternating user/assistant format with
 * an optional system message at the start.
 *
 * @see LlmProviderHandler
 */
public class AnthropicHandler implements LlmProviderHandler {

    private static final Logger log = LoggerFactory.getLogger(AnthropicHandler.class);

    @Override
    public String getVendor() {
        return "anthropic";
    }

    @Override
    public String[] getAliases() {
        return new String[]{"claude"};
    }

    @Override
    public String generateWithMessages(
            ChatModel model,
            List<Map<String, Object>> messages,
            Map<String, Object> options) {

        log.debug("AnthropicHandler: Processing {} messages", messages.size());

        // Convert to Spring AI messages
        List<Message> springMessages = convertMessages(messages);

        log.debug("AnthropicHandler: Converted to {} Spring AI messages", springMessages.size());

        // Create prompt with messages
        Prompt prompt = new Prompt(springMessages);

        // Call the model
        ChatResponse response = model.call(prompt);

        String content = response.getResult().getOutput().getText();
        log.debug("AnthropicHandler: Generated response ({} chars)",
            content != null ? content.length() : 0);

        return content;
    }

    @Override
    public Map<String, Boolean> getCapabilities() {
        return Map.of(
            "native_tool_calling", true,
            "structured_output", true,
            "streaming", true,
            "vision", true,
            "json_mode", true,
            "prompt_caching", true  // Claude-specific
        );
    }

    /**
     * Convert generic messages to Spring AI Message objects.
     *
     * <p>Claude prefers:
     * <ul>
     *   <li>Single system message at the start</li>
     *   <li>Alternating user/assistant messages</li>
     *   <li>Messages should not be empty</li>
     * </ul>
     */
    private List<Message> convertMessages(List<Map<String, Object>> messages) {
        List<Message> result = new ArrayList<>();
        StringBuilder systemContent = new StringBuilder();

        for (Map<String, Object> msg : messages) {
            String role = (String) msg.get("role");
            String content = (String) msg.get("content");

            if (role == null || content == null || content.trim().isEmpty()) {
                continue;
            }

            switch (role.toLowerCase()) {
                case "system" -> {
                    // Collect all system messages into one (Claude prefers single system)
                    if (systemContent.length() > 0) {
                        systemContent.append("\n\n");
                    }
                    systemContent.append(content);
                }
                case "user" -> result.add(new UserMessage(content));
                case "assistant" -> result.add(new AssistantMessage(content));
                case "tool" -> {
                    // Tool results are typically sent as user messages in Claude
                    // Format: [Tool Result] content
                    result.add(new UserMessage("[Tool Result]\n" + content));
                }
                default -> {
                    log.warn("Unknown message role '{}', treating as user", role);
                    result.add(new UserMessage(content));
                }
            }
        }

        // Insert system message at the beginning if present
        if (systemContent.length() > 0) {
            result.add(0, new SystemMessage(systemContent.toString()));
        }

        return result;
    }
}
