package io.mcpmesh.ai.handlers;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Issue #1592: the plain-text path (no tools, no output schema) — the most
 * common {@code @MeshLlm} shape — keeps the vendor's token usage, so the
 * provider reports {@code _mesh_usage} there as Python does. It used to go
 * through {@code generateWithMessages}, which returns only a String.
 */
class PlainTextUsageTest {

    @BeforeAll
    static void installNativeStub() {
        FormatSystemPromptStub.install();
    }

    @AfterAll
    static void uninstallNativeStub() {
        FormatSystemPromptStub.uninstall();
    }

    private static ChatModel modelReporting(int prompt, int completion, String model) {
        ChatModel chatModel = mock(ChatModel.class);
        ChatResponse response = new ChatResponse(
            List.of(new Generation(new AssistantMessage("plain answer"))),
            ChatResponseMetadata.builder().usage(new DefaultUsage(prompt, completion)).model(model).build());
        when(chatModel.call(any(Prompt.class))).thenReturn(response);
        return chatModel;
    }

    private static List<Map<String, Object>> userMessages() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("role", "user");
        m.put("content", "hi");
        return List.of(m);
    }

    private static Map<String, Object> declared(String model) {
        Map<String, Object> o = new LinkedHashMap<>();
        o.put(LlmProviderHandler.OPTION_DECLARED_MODEL, model);
        return o;
    }

    private static void assertCarriesUsage(LlmProviderHandler handler, String declaredModel) {
        LlmProviderHandler.LlmResponse r = handler.generateWithMessagesFull(
            modelReporting(30, 9, "vendor-id"), userMessages(), declared(declaredModel));

        assertEquals("plain answer", r.content());
        assertNotNull(r.usage(), handler.getClass().getSimpleName() + " dropped usage");
        assertEquals(30, r.usage().inputTokens());
        assertEquals(9, r.usage().outputTokens());
        assertEquals("vendor-id", r.usage().model());
        // The String variant stays the same answer.
        assertEquals("plain answer", handler.generateWithMessages(
            modelReporting(30, 9, "vendor-id"), userMessages(), declared(declaredModel)));
    }

    @Test
    void anthropic() {
        assertCarriesUsage(new AnthropicHandler(), "claude-sonnet-4-5");
    }

    @Test
    void openai() {
        assertCarriesUsage(new OpenAiHandler(), "gpt-4o");
    }

    @Test
    void gemini() {
        assertCarriesUsage(new GeminiHandler(), "gemini-2.0-flash");
    }

    @Test
    void generic() {
        assertCarriesUsage(new GenericHandler(), "some-model");
    }
}
