package io.mcpmesh.ai.handlers;

import org.junit.jupiter.api.*;
import org.mockito.ArgumentCaptor;
import org.springframework.ai.anthropic.AnthropicChatOptions;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.google.genai.GoogleGenAiChatOptions;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Verifies the unified fix:
 * <ol>
 *   <li>The provider's DECLARED model (threaded via {@link LlmProviderHandler#OPTION_DECLARED_MODEL})
 *       is set on every request across all three handlers, even with no per-call
 *       {@code model} override (PART 1/2).</li>
 *   <li>A per-call override still wins over the declared model.</li>
 *   <li>OpenAI sampling-param gating: gpt-5 (non-chat) and o-series reasoning
 *       models drop {@code temperature}/{@code top_p} but keep {@code maxCompletionTokens};
 *       gpt-4o / gpt-5-chat-latest keep all (PART 3).</li>
 * </ol>
 */
@DisplayName("declared-model propagation + OpenAI sampling gating")
class ProviderDeclaredModelTest {

    @BeforeAll
    static void installNativeStub() {
        FormatSystemPromptStub.install();
    }

    @AfterAll
    static void uninstallNativeStub() {
        FormatSystemPromptStub.uninstall();
    }

    private static ChatModel mockModel(ArgumentCaptor<Prompt> captor) {
        ChatModel model = mock(ChatModel.class);
        ChatResponse response = new ChatResponse(
            List.of(new Generation(new AssistantMessage("done"))));
        when(model.call(captor.capture())).thenReturn(response);
        return model;
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

    // =====================================================================
    // PART 1/2 — declared-model propagation
    // =====================================================================

    @Nested
    @DisplayName("OpenAI propagation")
    class OpenAiPropagation {
        private final OpenAiHandler handler = new OpenAiHandler();

        @Test
        @DisplayName("declared model (no override) is set on the request")
        void declaredModelSet() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null, declared("gpt-4o"));

            assertEquals("gpt-4o", captor.getValue().getOptions().getModel(),
                "declared model must be set when no per-call override is present");
        }

        @Test
        @DisplayName("declared model is set on the plain-text generateWithMessages path")
        void declaredModelSetPlainText() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithMessages(model, userMessages(), declared("gpt-4o"));

            assertEquals("gpt-4o", captor.getValue().getOptions().getModel());
        }

        @Test
        @DisplayName("per-call override wins over the declared model")
        void overrideWinsOverDeclared() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            Map<String, Object> options = declared("gpt-4o");
            options.put(LlmProviderHandler.OPTION_MODEL, "openai/gpt-4.1");

            handler.generateWithTools(model, userMessages(), List.of(), null, null, options);

            assertEquals("gpt-4.1", captor.getValue().getOptions().getModel(),
                "a same-vendor per-call override must win over the declared model");
        }

        @Test
        @DisplayName("cross-vendor override falls back to the declared model (not null)")
        void crossVendorFallsBackToDeclared() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            Map<String, Object> options = declared("gpt-4o");
            options.put(LlmProviderHandler.OPTION_MODEL, "anthropic/claude-3-5-sonnet-latest");

            handler.generateWithTools(model, userMessages(), List.of(), null, null, options);

            assertEquals("gpt-4o", captor.getValue().getOptions().getModel(),
                "a rejected cross-vendor override falls back to the declared model");
        }
    }

    @Nested
    @DisplayName("Anthropic propagation")
    class AnthropicPropagation {
        private final AnthropicHandler handler = new AnthropicHandler();

        @Test
        @DisplayName("declared model (no override) is set on the request")
        void declaredModelSet() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null,
                declared("claude-3-5-sonnet-latest"));

            assertEquals("claude-3-5-sonnet-latest", captor.getValue().getOptions().getModel());
        }

        @Test
        @DisplayName("declared model is set on the plain-text generateWithMessages path")
        void declaredModelSetPlainText() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithMessages(model, userMessages(), declared("claude-3-5-sonnet-latest"));

            ChatOptions opts = captor.getValue().getOptions();
            assertInstanceOf(AnthropicChatOptions.class, opts);
            assertEquals("claude-3-5-sonnet-latest", opts.getModel());
        }
    }

    @Nested
    @DisplayName("Gemini propagation")
    class GeminiPropagation {
        private final GeminiHandler handler = new GeminiHandler();

        @Test
        @DisplayName("declared model (no override) is set on the GoogleGenAiChatOptions")
        void declaredModelSet() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null,
                declared("gemini-2.0-flash"));

            ChatOptions opts = captor.getValue().getOptions();
            assertInstanceOf(GoogleGenAiChatOptions.class, opts);
            assertEquals("gemini-2.0-flash", opts.getModel());
        }

        @Test
        @DisplayName("declared model is set on the plain-text generateWithMessages path")
        void declaredModelSetPlainText() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithMessages(model, userMessages(), declared("gemini-2.0-flash"));

            assertEquals("gemini-2.0-flash", captor.getValue().getOptions().getModel());
        }
    }

    // =====================================================================
    // Regression — schema-construction failure must NOT drop the declared model
    // on the auto-execute path (toolExecutor != null).
    // =====================================================================

    @Nested
    @DisplayName("schema-failure does not drop the declared model (auto-execute)")
    class SchemaFailureKeepsModel {

        /** A no-op tool executor — non-null so the handler takes the auto-execute path. */
        private final LlmProviderHandler.ToolExecutorCallback noopExecutor = (name, args) -> "";

        /**
         * An OutputSchema whose {@code properties} is a String, not a Map. Both
         * OpenAI's {@code makeStrict()} and Anthropic's {@code sanitize()} cast
         * {@code properties} to a Map and throw ClassCastException — the exact
         * schema-construction failure the fix isolates.
         */
        private LlmProviderHandler.OutputSchema brokenSchema() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", "not-a-map");
            return new LlmProviderHandler.OutputSchema("Broken", schema, false);
        }

        @Test
        @DisplayName("OpenAI: declared model survives a response_format build failure")
        void openAiKeepsModelOnSchemaFailure() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            new OpenAiHandler().generateWithTools(
                model, userMessages(), List.of(), noopExecutor, brokenSchema(), declared("gpt-4o"));

            assertEquals("gpt-4o", captor.getValue().getOptions().getModel(),
                "declared model must still be applied when response_format construction fails");
        }

        @Test
        @DisplayName("Anthropic: declared model survives an output_schema build failure")
        void anthropicKeepsModelOnSchemaFailure() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            new AnthropicHandler().generateWithTools(
                model, userMessages(), List.of(), noopExecutor, brokenSchema(),
                declared("claude-3-5-sonnet-latest"));

            assertEquals("claude-3-5-sonnet-latest", captor.getValue().getOptions().getModel(),
                "declared model must still be applied when output_schema construction fails");
        }
    }

    // =====================================================================
    // PART 3 — OpenAI sampling-param gating
    // =====================================================================

    @Nested
    @DisplayName("OpenAI sampling-param gating")
    class OpenAiGating {
        private final OpenAiHandler handler = new OpenAiHandler();

        private OpenAiChatOptions callWith(String declaredModel) {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            Map<String, Object> options = declared(declaredModel);
            options.put(LlmProviderHandler.OPTION_MAX_TOKENS, 1000);
            options.put(LlmProviderHandler.OPTION_TEMPERATURE, 0.7);
            options.put(LlmProviderHandler.OPTION_TOP_P, 0.9);

            handler.generateWithTools(model, userMessages(), List.of(), null, null, options);
            return (OpenAiChatOptions) captor.getValue().getOptions();
        }

        @Test
        @DisplayName("gpt-5-mini omits temperature/top_p but keeps maxCompletionTokens")
        void gpt5MiniRestricted() {
            OpenAiChatOptions opts = callWith("gpt-5-mini");
            assertNull(opts.getTemperature(), "temperature must be omitted for gpt-5-mini");
            assertNull(opts.getTopP(), "top_p must be omitted for gpt-5-mini");
            assertEquals(1000, opts.getMaxCompletionTokens(), "max_tokens is always applied");
            assertEquals("gpt-5-mini", opts.getModel());
        }

        @Test
        @DisplayName("o3-mini omits temperature/top_p but keeps maxCompletionTokens")
        void o3MiniRestricted() {
            OpenAiChatOptions opts = callWith("o3-mini");
            assertNull(opts.getTemperature());
            assertNull(opts.getTopP());
            assertEquals(1000, opts.getMaxCompletionTokens());
            assertEquals("o3-mini", opts.getModel());
        }

        @Test
        @DisplayName("gpt-4o applies temperature/top_p")
        void gpt4oAllowed() {
            OpenAiChatOptions opts = callWith("gpt-4o");
            assertEquals(0.7, opts.getTemperature(), 1e-9);
            assertEquals(0.9, opts.getTopP(), 1e-9);
            assertEquals(1000, opts.getMaxCompletionTokens());
        }

        @Test
        @DisplayName("gpt-5-chat-latest applies temperature/top_p")
        void gpt5ChatAllowed() {
            OpenAiChatOptions opts = callWith("gpt-5-chat-latest");
            assertEquals(0.7, opts.getTemperature(), 1e-9);
            assertEquals(0.9, opts.getTopP(), 1e-9);
        }
    }

    @Nested
    @DisplayName("restrictsSamplingParams truth table")
    class RestrictsTable {
        @Test
        @DisplayName("restricted models")
        void restricted() {
            assertTrue(OpenAiHandler.restrictsSamplingParams("o1"));
            assertTrue(OpenAiHandler.restrictsSamplingParams("o3-mini"));
            assertTrue(OpenAiHandler.restrictsSamplingParams("o4-mini"));
            assertTrue(OpenAiHandler.restrictsSamplingParams("gpt-5"));
            assertTrue(OpenAiHandler.restrictsSamplingParams("gpt-5-mini"));
            assertTrue(OpenAiHandler.restrictsSamplingParams("gpt-5-nano"));
            assertTrue(OpenAiHandler.restrictsSamplingParams("openai/gpt-5"));
        }

        @Test
        @DisplayName("unrestricted models")
        void unrestricted() {
            assertFalse(OpenAiHandler.restrictsSamplingParams("gpt-4o"));
            assertFalse(OpenAiHandler.restrictsSamplingParams("gpt-4.1"));
            assertFalse(OpenAiHandler.restrictsSamplingParams("gpt-5-chat-latest"));
            assertFalse(OpenAiHandler.restrictsSamplingParams(null));
        }
    }

    // =====================================================================
    // PART 1 — effectiveModel resolution
    // =====================================================================

    @Nested
    @DisplayName("effectiveModel resolution")
    class EffectiveModel {
        @Test
        @DisplayName("override wins over declared")
        void overrideWins() {
            Map<String, Object> o = declared("gpt-4o");
            o.put(LlmProviderHandler.OPTION_MODEL, "openai/gpt-4.1");
            assertEquals("gpt-4.1",
                LlmProviderHandler.effectiveModel(o, "openai", new String[]{"gpt"}));
        }

        @Test
        @DisplayName("declared used when no override")
        void declaredUsed() {
            assertEquals("gpt-4o",
                LlmProviderHandler.effectiveModel(declared("gpt-4o"), "openai", new String[]{"gpt"}));
        }

        @Test
        @DisplayName("cross-vendor override falls back to declared")
        void crossVendorFallsBack() {
            Map<String, Object> o = declared("gpt-4o");
            o.put(LlmProviderHandler.OPTION_MODEL, "anthropic/claude-3-5-sonnet-latest");
            assertEquals("gpt-4o",
                LlmProviderHandler.effectiveModel(o, "openai", new String[]{"gpt"}));
        }

        @Test
        @DisplayName("null when neither override nor declared present")
        void noneNull() {
            assertNull(LlmProviderHandler.effectiveModel(Map.of(), "openai", new String[]{"gpt"}));
            assertNull(LlmProviderHandler.effectiveModel(null, "openai", new String[]{"gpt"}));
        }
    }
}
