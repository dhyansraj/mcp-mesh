package io.mcpmesh.ai.handlers;

import io.mcpmesh.ai.handlers.LlmProviderHandler.OutputSchema;
import io.mcpmesh.ai.handlers.LlmProviderHandler.ToolDefinition;
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
 * Provider-side application of {@code model_params} onto the per-vendor Spring AI
 * {@code *ChatOptions} (GAP C2).
 *
 * <p>The Java consumer already puts {@code max_tokens}/{@code temperature}/
 * {@code top_p}/{@code model} on the wire; this verifies the PROVIDER reads those
 * keys from the incoming {@code model_params} (threaded through the handler
 * {@code options} map) and applies them to the vendor ChatOptions, INCLUDING the
 * vendor-match guard for the {@code model} override (cross-vendor → fall back to
 * the provider default).
 *
 * <p>Exercises the no-execution path ({@code toolExecutor == null}) so the handler
 * builds a vendor options object and calls {@code model.call(prompt)} — we capture
 * the {@link Prompt} and inspect {@code prompt.getOptions()}.
 */
@DisplayName("provider applies model_params → ChatOptions (GAP C2)")
class ProviderModelParamsTest {

    @BeforeAll
    static void installNativeStub() {
        FormatSystemPromptStub.install();
    }

    @AfterAll
    static void uninstallNativeStub() {
        FormatSystemPromptStub.uninstall();
    }

    /** A mock ChatModel that returns a trivial text response and captures the Prompt. */
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

    @Nested
    @DisplayName("OpenAI")
    class OpenAi {

        private final OpenAiHandler handler = new OpenAiHandler();

        @Test
        @DisplayName("max_tokens/temperature/top_p flow onto OpenAiChatOptions")
        void numericParamsApplied() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            Map<String, Object> options = new LinkedHashMap<>();
            options.put(LlmProviderHandler.OPTION_MAX_TOKENS, 1234);
            options.put(LlmProviderHandler.OPTION_TEMPERATURE, 0.42);
            options.put(LlmProviderHandler.OPTION_TOP_P, 0.9);

            handler.generateWithTools(model, userMessages(), List.of(), null, null, options);

            ChatOptions opts = captor.getValue().getOptions();
            assertInstanceOf(OpenAiChatOptions.class, opts);
            assertEquals(1234, ((OpenAiChatOptions) opts).getMaxCompletionTokens());
            assertEquals(0.42, opts.getTemperature(), 1e-9);
            assertEquals(0.9, opts.getTopP(), 1e-9);
        }

        @Test
        @DisplayName("same-vendor model override is applied (openai/gpt-4o → gpt-4o)")
        void sameVendorModelApplied() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null,
                Map.of(LlmProviderHandler.OPTION_MODEL, "openai/gpt-4o"));

            ChatOptions opts = captor.getValue().getOptions();
            assertEquals("gpt-4o", opts.getModel(),
                "same-vendor model override must be applied (vendor-stripped)");
        }

        @Test
        @DisplayName("cross-vendor model override is rejected → provider default (model stays null)")
        void crossVendorModelRejected() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null,
                Map.of(LlmProviderHandler.OPTION_MODEL, "anthropic/claude-3-5-sonnet-latest"));

            ChatOptions opts = captor.getValue().getOptions();
            assertNull(opts.getModel(),
                "cross-vendor model override must be ignored — provider keeps its own default model");
        }

        @Test
        @DisplayName("absent params leave the options defaults untouched (no force-set nulls)")
        void absentParamsUntouched() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null, Map.of());

            ChatOptions opts = captor.getValue().getOptions();
            assertNull(((OpenAiChatOptions) opts).getMaxCompletionTokens(),
                "absent max_tokens must not be force-set");
            assertNull(opts.getTemperature(), "absent temperature must not be force-set");
            assertNull(opts.getTopP(), "absent top_p must not be force-set");
            assertNull(opts.getModel(), "absent model must not be force-set");
        }
    }

    @Nested
    @DisplayName("Anthropic")
    class Anthropic {

        private final AnthropicHandler handler = new AnthropicHandler();

        @Test
        @DisplayName("max_tokens/temperature/top_p flow onto AnthropicChatOptions")
        void numericParamsApplied() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            Map<String, Object> options = new LinkedHashMap<>();
            options.put(LlmProviderHandler.OPTION_MAX_TOKENS, 2048);
            options.put(LlmProviderHandler.OPTION_TEMPERATURE, 0.15);
            options.put(LlmProviderHandler.OPTION_TOP_P, 0.8);

            handler.generateWithTools(model, userMessages(), List.of(), null, null, options);

            ChatOptions opts = captor.getValue().getOptions();
            assertInstanceOf(AnthropicChatOptions.class, opts);
            assertEquals(2048, opts.getMaxTokens());
            assertEquals(0.15, opts.getTemperature(), 1e-9);
            assertEquals(0.8, opts.getTopP(), 1e-9);
        }

        @Test
        @DisplayName("same-vendor model override is applied (alias 'claude' also matches)")
        void sameVendorModelApplied() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null,
                Map.of(LlmProviderHandler.OPTION_MODEL, "claude/claude-3-5-sonnet-latest"));

            ChatOptions opts = captor.getValue().getOptions();
            assertEquals("claude-3-5-sonnet-latest", opts.getModel(),
                "the 'claude' alias must match the anthropic vendor and apply the model");
        }

        @Test
        @DisplayName("cross-vendor model override is rejected → provider default (model stays null)")
        void crossVendorModelRejected() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null,
                Map.of(LlmProviderHandler.OPTION_MODEL, "openai/gpt-4o"));

            ChatOptions opts = captor.getValue().getOptions();
            assertNull(opts.getModel(),
                "cross-vendor model override must be ignored — Anthropic keeps its own default model");
        }
    }

    @Nested
    @DisplayName("Gemini")
    class Gemini {

        private final GeminiHandler handler = new GeminiHandler();

        // A plain mock(ChatModel.class) is NOT a VertexAiGeminiChatModel, so the
        // handler takes the Google AI Studio (GenAI) branch and produces
        // GoogleGenAiChatOptions. The Vertex branch needs the concrete
        // VertexAiGeminiChatModel and is out of scope for this unit harness.

        @Test
        @DisplayName("max_tokens→maxOutputTokens/temperature/top_p flow onto GoogleGenAiChatOptions")
        void numericParamsApplied() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            Map<String, Object> options = new LinkedHashMap<>();
            options.put(LlmProviderHandler.OPTION_MAX_TOKENS, 777);
            options.put(LlmProviderHandler.OPTION_TEMPERATURE, 0.33);
            options.put(LlmProviderHandler.OPTION_TOP_P, 0.7);

            handler.generateWithTools(model, userMessages(), List.of(), null, null, options);

            ChatOptions opts = captor.getValue().getOptions();
            assertInstanceOf(GoogleGenAiChatOptions.class, opts);
            GoogleGenAiChatOptions g = (GoogleGenAiChatOptions) opts;
            assertEquals(777, g.getMaxOutputTokens(), "max_tokens maps to maxOutputTokens");
            assertEquals(0.33, g.getTemperature(), 1e-9);
            assertEquals(0.7, g.getTopP(), 1e-9);
        }

        @Test
        @DisplayName("same-vendor model override is applied (gemini/... and google/...)")
        void sameVendorModelApplied() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null,
                Map.of(LlmProviderHandler.OPTION_MODEL, "gemini/gemini-2.0-flash"));

            assertEquals("gemini-2.0-flash", captor.getValue().getOptions().getModel(),
                "same-vendor 'gemini/' override must be applied (vendor-stripped)");

            ArgumentCaptor<Prompt> captor2 = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model2 = mockModel(captor2);
            handler.generateWithTools(model2, userMessages(), List.of(), null, null,
                Map.of(LlmProviderHandler.OPTION_MODEL, "google/gemini-2.0-flash"));
            assertEquals("gemini-2.0-flash", captor2.getValue().getOptions().getModel(),
                "the 'google' alias must match the gemini vendor and apply the model");
        }

        @Test
        @DisplayName("vertex_ai/... override is accepted on the GenAI branch (FIX 2)")
        void vertexQualifiedOverrideAccepted() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null,
                Map.of(LlmProviderHandler.OPTION_MODEL, "vertex_ai/gemini-1.5-pro"));

            assertEquals("gemini-1.5-pro", captor.getValue().getOptions().getModel(),
                "a vertex_ai-qualified override routes through GeminiHandler and must be accepted");
        }

        @Test
        @DisplayName("cross-vendor model override is rejected → provider default (model stays null)")
        void crossVendorModelRejected() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithTools(model, userMessages(), List.of(), null, null,
                Map.of(LlmProviderHandler.OPTION_MODEL, "openai/gpt-4o"));

            assertNull(captor.getValue().getOptions().getModel(),
                "cross-vendor model override must be ignored — Gemini keeps its own default model");
        }

        @Test
        @DisplayName("plain-text generateWithMessages applies model_params (FIX 3)")
        void plainTextPathAppliesParams() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            Map<String, Object> options = new LinkedHashMap<>();
            options.put(LlmProviderHandler.OPTION_MAX_TOKENS, 512);
            options.put(LlmProviderHandler.OPTION_MODEL, "gemini/gemini-2.0-flash");

            handler.generateWithMessages(model, userMessages(), options);

            ChatOptions opts = captor.getValue().getOptions();
            assertInstanceOf(GoogleGenAiChatOptions.class, opts);
            assertEquals(512, ((GoogleGenAiChatOptions) opts).getMaxOutputTokens());
            assertEquals("gemini-2.0-flash", opts.getModel());
        }

        @Test
        @DisplayName("plain-text generateWithMessages with no params builds a no-options prompt")
        void plainTextPathNoParams() {
            ArgumentCaptor<Prompt> captor = ArgumentCaptor.forClass(Prompt.class);
            ChatModel model = mockModel(captor);

            handler.generateWithMessages(model, userMessages(), Map.of());

            assertNull(captor.getValue().getOptions(),
                "no model_params → plain Prompt(messages) with no ChatOptions");
        }
    }

    @Nested
    @DisplayName("resolveModelOverride (vendor-match guard)")
    class ResolveModelOverride {

        @Test
        @DisplayName("matching vendor returns the bare model name")
        void matchReturnsBareName() {
            assertEquals("gpt-4o",
                LlmProviderHandler.resolveModelOverride(
                    Map.of("model", "openai/gpt-4o"), "openai", new String[]{"gpt"}));
        }

        @Test
        @DisplayName("alias match returns the bare model name")
        void aliasMatchReturnsBareName() {
            assertEquals("claude-3-5-sonnet-latest",
                LlmProviderHandler.resolveModelOverride(
                    Map.of("model", "claude/claude-3-5-sonnet-latest"), "anthropic", new String[]{"claude"}));
        }

        @Test
        @DisplayName("cross-vendor returns null (fall back to default)")
        void crossVendorReturnsNull() {
            assertNull(LlmProviderHandler.resolveModelOverride(
                Map.of("model", "anthropic/claude-3-5-sonnet-latest"), "openai", new String[]{"gpt"}));
        }

        @Test
        @DisplayName("bare model name (no vendor prefix) is assumed to target this provider")
        void bareNameAssumedMatch() {
            assertEquals("gpt-4o",
                LlmProviderHandler.resolveModelOverride(
                    Map.of("model", "gpt-4o"), "openai", new String[]{"gpt"}));
        }

        @Test
        @DisplayName("absent / null / blank model returns null")
        void absentReturnsNull() {
            assertNull(LlmProviderHandler.resolveModelOverride(null, "openai", null));
            assertNull(LlmProviderHandler.resolveModelOverride(Map.of(), "openai", null));
            assertNull(LlmProviderHandler.resolveModelOverride(
                Map.of("model", "  "), "openai", null));
        }
    }

    @Nested
    @DisplayName("numeric option extractors")
    class NumericExtractors {

        @Test
        @DisplayName("max_tokens parses Number and numeric String")
        void maxTokens() {
            assertEquals(100, LlmProviderHandler.maxTokensOption(Map.of("max_tokens", 100)));
            assertEquals(100, LlmProviderHandler.maxTokensOption(Map.of("max_tokens", "100")));
            assertNull(LlmProviderHandler.maxTokensOption(Map.of()));
            assertNull(LlmProviderHandler.maxTokensOption(null));
        }

        @Test
        @DisplayName("temperature parses Number, ignores NaN")
        void temperature() {
            assertEquals(0.3, LlmProviderHandler.temperatureOption(Map.of("temperature", 0.3)), 1e-9);
            assertEquals(0.3, LlmProviderHandler.temperatureOption(Map.of("temperature", "0.3")), 1e-9);
            assertNull(LlmProviderHandler.temperatureOption(Map.of("temperature", Double.NaN)));
            assertNull(LlmProviderHandler.temperatureOption(Map.of()));
        }

        @Test
        @DisplayName("hasAnyModelParam detects presence of any C2 key")
        void hasAnyModelParam() {
            assertFalse(LlmProviderHandler.hasAnyModelParam(null));
            assertFalse(LlmProviderHandler.hasAnyModelParam(Map.of()));
            assertTrue(LlmProviderHandler.hasAnyModelParam(Map.of("max_tokens", 1)));
            assertTrue(LlmProviderHandler.hasAnyModelParam(Map.of("model", "openai/gpt-4o")));
        }
    }
}
