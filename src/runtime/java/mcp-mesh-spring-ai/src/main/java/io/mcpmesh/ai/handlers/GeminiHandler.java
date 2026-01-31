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
 * LLM provider handler for Google Gemini models.
 *
 * <p>Handles Gemini-specific message formatting and features:
 * <ul>
 *   <li>Full multi-turn conversation support</li>
 *   <li>Large context window support</li>
 *   <li>System instruction handling</li>
 *   <li>Multimodal capabilities (future)</li>
 * </ul>
 *
 * <h2>Message Format</h2>
 * <p>Gemini uses a "contents" array with "parts" for each message.
 * Spring AI handles the translation.
 *
 * @see LlmProviderHandler
 */
public class GeminiHandler implements LlmProviderHandler {

    private static final Logger log = LoggerFactory.getLogger(GeminiHandler.class);

    @Override
    public String getVendor() {
        return "gemini";
    }

    @Override
    public String[] getAliases() {
        return new String[]{"google"};
    }

    @Override
    public String generateWithMessages(
            ChatModel model,
            List<Map<String, Object>> messages,
            Map<String, Object> options) {

        log.debug("GeminiHandler: Processing {} messages", messages.size());

        // Convert to Spring AI messages
        List<Message> springMessages = convertMessages(messages);

        log.debug("GeminiHandler: Converted to {} Spring AI messages", springMessages.size());

        // Create prompt with messages
        Prompt prompt = new Prompt(springMessages);

        // Call the model
        ChatResponse response = model.call(prompt);

        String content = response.getResult().getOutput().getContent();
        log.debug("GeminiHandler: Generated response ({} chars)",
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
            "large_context", true  // Gemini-specific
        );
    }

    /**
     * Convert generic messages to Spring AI Message objects.
     *
     * <p>Gemini handles system instructions separately but Spring AI
     * abstracts this. Key considerations:
     * <ul>
     *   <li>System content becomes "system_instruction"</li>
     *   <li>User/model roles map to contents array</li>
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
                    // Gemini uses system_instruction, collect all system messages
                    if (systemContent.length() > 0) {
                        systemContent.append("\n\n");
                    }
                    systemContent.append(content);
                }
                case "user" -> result.add(new UserMessage(content));
                case "assistant", "model" -> result.add(new AssistantMessage(content));
                case "tool" -> {
                    // Tool results as function response
                    result.add(new UserMessage("[Function Result]\n" + content));
                }
                default -> {
                    log.warn("Unknown message role '{}', treating as user", role);
                    result.add(new UserMessage(content));
                }
            }
        }

        // Insert system instruction at the beginning if present
        if (systemContent.length() > 0) {
            result.add(0, new SystemMessage(systemContent.toString()));
        }

        return result;
    }
}
