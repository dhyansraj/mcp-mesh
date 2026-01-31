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
 * LLM provider handler for OpenAI GPT models.
 *
 * <p>Handles OpenAI-specific message formatting and features:
 * <ul>
 *   <li>Full multi-turn conversation support</li>
 *   <li>Multiple system messages supported</li>
 *   <li>Strict JSON mode with response_format</li>
 *   <li>Function calling support</li>
 * </ul>
 *
 * <h2>Message Format</h2>
 * <p>OpenAI accepts messages in any order with explicit roles.
 * System messages can appear anywhere but typically at the start.
 *
 * @see LlmProviderHandler
 */
public class OpenAiHandler implements LlmProviderHandler {

    private static final Logger log = LoggerFactory.getLogger(OpenAiHandler.class);

    @Override
    public String getVendor() {
        return "openai";
    }

    @Override
    public String[] getAliases() {
        return new String[]{"gpt"};
    }

    @Override
    public String generateWithMessages(
            ChatModel model,
            List<Map<String, Object>> messages,
            Map<String, Object> options) {

        log.debug("OpenAiHandler: Processing {} messages", messages.size());

        // Convert to Spring AI messages
        List<Message> springMessages = convertMessages(messages);

        log.debug("OpenAiHandler: Converted to {} Spring AI messages", springMessages.size());

        // Create prompt with messages
        Prompt prompt = new Prompt(springMessages);

        // Call the model
        ChatResponse response = model.call(prompt);

        String content = response.getResult().getOutput().getContent();
        log.debug("OpenAiHandler: Generated response ({} chars)",
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
            "json_mode", true
        );
    }

    /**
     * Convert generic messages to Spring AI Message objects.
     *
     * <p>OpenAI is flexible with message ordering but prefers:
     * <ul>
     *   <li>System messages at the start</li>
     *   <li>Clear role attribution for each message</li>
     * </ul>
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
                case "tool" -> {
                    // Tool results in OpenAI format
                    // Note: Full tool_call_id support would need ToolResponseMessage
                    yield new UserMessage("[Tool Result]\n" + content);
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
