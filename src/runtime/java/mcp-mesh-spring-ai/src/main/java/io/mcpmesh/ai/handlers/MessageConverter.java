package io.mcpmesh.ai.handlers;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.ToolResponseMessage;
import org.springframework.ai.chat.messages.UserMessage;

import java.util.*;

/**
 * Shared message conversion utilities for LLM handler implementations.
 * Converts raw message maps (from MCP protocol) to Spring AI message types.
 *
 * <p>All three handlers (Anthropic, OpenAI, Gemini) share the same core logic:
 * <ul>
 *   <li>Building a tool_call_id to tool_name mapping from assistant messages</li>
 *   <li>Converting system, user, assistant, and tool role messages</li>
 *   <li>Handling assistant messages with tool_calls (ToolCall list)</li>
 *   <li>Handling tool result messages (ToolResponseMessage)</li>
 * </ul>
 *
 * <p>Gemini has additional requirements: "model" as an alias for "assistant",
 * and consecutive tool responses must be bundled into a single ToolResponseMessage.
 * Use {@link #convertMessagesWithBundledToolResponses} for Gemini.
 */
public final class MessageConverter {

    private static final Logger log = LoggerFactory.getLogger(MessageConverter.class);

    private MessageConverter() {}

    /**
     * Build a mapping of tool call IDs to tool names from assistant messages.
     * This is needed to resolve tool names for tool result messages that may
     * only carry a tool_call_id without an explicit name.
     *
     * @param messages     raw message maps from MCP protocol
     * @param extraRoles   additional role strings to treat as "assistant" (e.g. "model" for Gemini)
     */
    @SuppressWarnings("unchecked")
    public static Map<String, String> buildToolCallIdMap(List<Map<String, Object>> messages, String... extraRoles) {
        Set<String> assistantRoles = new HashSet<>();
        assistantRoles.add("assistant");
        for (String r : extraRoles) {
            assistantRoles.add(r.toLowerCase());
        }

        Map<String, String> toolCallIdToName = new HashMap<>();
        for (Map<String, Object> msg : messages) {
            String role = (String) msg.get("role");
            if (role != null && assistantRoles.contains(role.toLowerCase())) {
                List<Map<String, Object>> toolCalls = (List<Map<String, Object>>) msg.get("tool_calls");
                if (toolCalls != null) {
                    for (Map<String, Object> tc : toolCalls) {
                        String tcId = (String) tc.get("id");
                        Map<String, Object> function = (Map<String, Object>) tc.get("function");
                        if (tcId != null && function != null) {
                            String toolName = (String) function.get("name");
                            if (toolName != null) {
                                toolCallIdToName.put(tcId, toolName);
                            }
                        }
                    }
                }
            }
        }
        return toolCallIdToName;
    }

    /**
     * Convert messages to Spring AI types with system message accumulation.
     * System messages are concatenated and placed at position 0 as a single SystemMessage.
     * Tool responses are added individually (suitable for Anthropic/OpenAI).
     *
     * @param messages raw message maps from MCP protocol
     * @return conversion result containing the system prompt and message list
     */
    public static ConvertedMessages convertMessages(List<Map<String, Object>> messages) {
        Map<String, String> toolCallIdToName = buildToolCallIdMap(messages);
        List<Message> result = new ArrayList<>();
        StringBuilder systemContent = new StringBuilder();

        for (Map<String, Object> msg : messages) {
            String role = (String) msg.get("role");
            String content = (String) msg.get("content");

            if (role == null) {
                continue;
            }

            switch (role.toLowerCase()) {
                case "system" -> {
                    if (content != null && !content.trim().isEmpty()) {
                        if (systemContent.length() > 0) {
                            systemContent.append("\n\n");
                        }
                        systemContent.append(content);
                    }
                }
                case "user" -> {
                    if (content != null && !content.trim().isEmpty()) {
                        result.add(new UserMessage(content));
                    }
                }
                case "assistant" -> {
                    convertAssistantMessage(msg, content, result);
                }
                case "tool" -> {
                    convertToolMessage(msg, content, toolCallIdToName, result);
                }
                default -> {
                    log.warn("Unknown message role '{}', treating as user", role);
                    if (content != null && !content.trim().isEmpty()) {
                        result.add(new UserMessage(content));
                    }
                }
            }
        }

        String systemPrompt = systemContent.length() > 0 ? systemContent.toString() : null;
        if (systemPrompt != null) {
            result.add(0, new SystemMessage(systemPrompt));
        }

        return new ConvertedMessages(systemPrompt, result);
    }

    /**
     * Convert messages to Spring AI types with Gemini-specific behavior:
     * <ul>
     *   <li>"model" is treated as an alias for "assistant"</li>
     *   <li>Consecutive tool responses are bundled into a single ToolResponseMessage</li>
     *   <li>System messages are accumulated into a single system instruction</li>
     * </ul>
     *
     * @param messages raw message maps from MCP protocol
     * @return conversion result containing the system prompt and message list
     */
    @SuppressWarnings("unchecked")
    public static ConvertedMessages convertMessagesWithBundledToolResponses(List<Map<String, Object>> messages) {
        Map<String, String> toolCallIdToName = buildToolCallIdMap(messages, "model");
        List<Message> result = new ArrayList<>();
        StringBuilder systemContent = new StringBuilder();

        List<ToolResponseMessage.ToolResponse> pendingToolResponses = new ArrayList<>();

        Runnable flushPendingToolResponses = () -> {
            if (!pendingToolResponses.isEmpty()) {
                log.debug("Bundling {} tool responses into single ToolResponseMessage", pendingToolResponses.size());
                result.add(ToolResponseMessage.builder()
                    .responses(new ArrayList<>(pendingToolResponses))
                    .build());
                pendingToolResponses.clear();
            }
        };

        for (Map<String, Object> msg : messages) {
            String role = (String) msg.get("role");
            String content = (String) msg.get("content");

            if (role == null) {
                continue;
            }

            switch (role.toLowerCase()) {
                case "system" -> {
                    flushPendingToolResponses.run();
                    if (content != null && !content.trim().isEmpty()) {
                        if (systemContent.length() > 0) {
                            systemContent.append("\n\n");
                        }
                        systemContent.append(content);
                    }
                }
                case "user" -> {
                    flushPendingToolResponses.run();
                    if (content != null && !content.trim().isEmpty()) {
                        result.add(new UserMessage(content));
                    }
                }
                case "assistant", "model" -> {
                    flushPendingToolResponses.run();
                    convertAssistantMessage(msg, content, result);
                }
                case "tool" -> {
                    String toolCallId = (String) msg.get("tool_call_id");
                    if (toolCallId == null) {
                        log.warn("Tool message missing tool_call_id, skipping");
                        continue;
                    }
                    String toolName = (String) msg.get("name");
                    if (toolName == null) {
                        toolName = toolCallIdToName.get(toolCallId);
                    }
                    if (toolName == null) {
                        toolName = "unknown_tool";
                        log.warn("Could not determine tool name for tool_call_id: {} - Gemini may reject this", toolCallId);
                    }
                    String responseData = content != null ? content : "";
                    log.debug("Converted tool result: id={}, name={}, contentLength={}",
                        toolCallId, toolName, responseData.length());

                    pendingToolResponses.add(
                        new ToolResponseMessage.ToolResponse(toolCallId, toolName, responseData));
                }
                default -> {
                    flushPendingToolResponses.run();
                    log.warn("Unknown message role '{}', treating as user", role);
                    if (content != null && !content.trim().isEmpty()) {
                        result.add(new UserMessage(content));
                    }
                }
            }
        }

        flushPendingToolResponses.run();

        String systemPrompt = systemContent.length() > 0 ? systemContent.toString() : null;
        if (systemPrompt != null) {
            result.add(0, new SystemMessage(systemPrompt));
        }

        return new ConvertedMessages(systemPrompt, result);
    }

    /**
     * Convert an assistant message (with optional tool_calls) and add to result list.
     */
    @SuppressWarnings("unchecked")
    private static void convertAssistantMessage(Map<String, Object> msg, String content, List<Message> result) {
        List<Map<String, Object>> toolCalls = (List<Map<String, Object>>) msg.get("tool_calls");
        if (toolCalls != null && !toolCalls.isEmpty()) {
            List<AssistantMessage.ToolCall> springToolCalls = new ArrayList<>();
            for (Map<String, Object> tc : toolCalls) {
                String tcId = (String) tc.get("id");
                String tcType = (String) tc.getOrDefault("type", "function");
                @SuppressWarnings("unchecked")
                Map<String, Object> function = (Map<String, Object>) tc.get("function");
                if (function != null) {
                    String tcName = (String) function.get("name");
                    String tcArgs = (String) function.get("arguments");
                    if (tcId != null && tcName != null) {
                        springToolCalls.add(new AssistantMessage.ToolCall(
                            tcId, tcType, tcName, tcArgs != null ? tcArgs : "{}"
                        ));
                    }
                }
            }
            log.debug("Converted assistant message with {} tool calls", springToolCalls.size());
            result.add(AssistantMessage.builder()
                .content(content != null ? content : "")
                .toolCalls(springToolCalls)
                .build());
        } else if (content != null && !content.trim().isEmpty()) {
            result.add(new AssistantMessage(content));
        }
    }

    /**
     * Convert a tool result message and add to result list as an individual ToolResponseMessage.
     */
    private static void convertToolMessage(
            Map<String, Object> msg, String content,
            Map<String, String> toolCallIdToName, List<Message> result) {

        String toolCallId = (String) msg.get("tool_call_id");
        if (toolCallId == null) {
            log.warn("Tool message missing tool_call_id, skipping");
            return;
        }
        String toolName = (String) msg.get("name");
        if (toolName == null) {
            toolName = toolCallIdToName.get(toolCallId);
        }
        if (toolName == null) {
            toolName = "unknown_tool";
            log.warn("Could not determine tool name for tool_call_id: {}", toolCallId);
        }
        String responseData = content != null ? content : "";
        log.debug("Converted tool result: id={}, name={}, contentLength={}",
            toolCallId, toolName, responseData.length());

        ToolResponseMessage.ToolResponse toolResponse =
            new ToolResponseMessage.ToolResponse(toolCallId, toolName, responseData);
        result.add(ToolResponseMessage.builder()
            .responses(List.of(toolResponse))
            .build());
    }

    /**
     * Result of message conversion.
     *
     * @param systemPrompt extracted system prompt (null if no system messages)
     * @param messages     list of Spring AI messages (includes SystemMessage at index 0 if systemPrompt is non-null)
     */
    public record ConvertedMessages(
        String systemPrompt,
        List<Message> messages
    ) {}
}
