package io.mcpmesh.ai.handlers;

import io.mcpmesh.ai.handlers.LlmProviderHandler.OutputSchema;
import io.mcpmesh.ai.handlers.LlmProviderHandler.ToolDefinition;
import org.junit.jupiter.api.*;

import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for the consumer-supplied {@code output_mode} override (issue #1112).
 *
 * <p>Covers the {@link LlmProviderHandler#determineOutputMode(OutputSchema, String)}
 * override overload and the effect of the resolved mode on the structured-output
 * system-prompt produced by {@link LlmProviderHandler#formatSystemPromptViaCore}.
 * No real LLM calls — the formatting is exercised through {@link FormatSystemPromptStub}.
 */
@DisplayName("output_mode override (#1112)")
class OutputModeOverrideTest {

    @BeforeAll
    static void installNativeStub() {
        FormatSystemPromptStub.install();
    }

    @AfterAll
    static void uninstallNativeStub() {
        FormatSystemPromptStub.uninstall();
    }

    private static OutputSchema schema() {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("type", "object");
        Map<String, Object> props = new LinkedHashMap<>();
        props.put("name", Map.of("type", "string", "description", "The name"));
        s.put("properties", props);
        s.put("required", List.of("name"));
        return OutputSchema.fromSchema("PersonInfo", s);
    }

    @Nested
    @DisplayName("determineOutputMode(schema, override)")
    class OverrideOverload {

        private final OpenAiHandler openai = new OpenAiHandler();
        private final AnthropicHandler anthropic = new AnthropicHandler();
        private final GeminiHandler gemini = new GeminiHandler();

        @Test
        @DisplayName("valid 'strict' override is returned verbatim")
        void validStrictReturned() {
            assertEquals(LlmProviderHandler.OUTPUT_MODE_STRICT,
                openai.determineOutputMode(schema(), "strict"));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_STRICT,
                anthropic.determineOutputMode(schema(), "strict"));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_STRICT,
                gemini.determineOutputMode(schema(), "strict"));
        }

        @Test
        @DisplayName("valid 'hint' override is returned verbatim, replacing auto-selection")
        void validHintReturned() {
            // OpenAI/Anthropic auto-select strict; the override flips them to hint.
            assertEquals(LlmProviderHandler.OUTPUT_MODE_HINT,
                openai.determineOutputMode(schema(), "hint"));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_HINT,
                anthropic.determineOutputMode(schema(), "hint"));
        }

        @Test
        @DisplayName("valid 'text' override is returned verbatim even with a schema")
        void validTextReturned() {
            assertEquals(LlmProviderHandler.OUTPUT_MODE_TEXT,
                openai.determineOutputMode(schema(), "text"));
        }

        @Test
        @DisplayName("unset override delegates to per-vendor auto-selection")
        void unsetDelegatesToAuto() {
            // openai auto-selects strict for a schema; gemini auto-selects hint.
            assertEquals(openai.determineOutputMode(schema()),
                openai.determineOutputMode(schema(), ""));
            assertEquals(openai.determineOutputMode(schema()),
                openai.determineOutputMode(schema(), null));
            assertEquals(gemini.determineOutputMode(schema()),
                gemini.determineOutputMode(schema(), ""));
        }

        @Test
        @DisplayName("null-schema + unset override stays text (byte-identical to auto)")
        void nullSchemaUnsetStaysText() {
            assertEquals(LlmProviderHandler.OUTPUT_MODE_TEXT,
                openai.determineOutputMode(null, ""));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_TEXT,
                openai.determineOutputMode(null, null));
        }

        @Test
        @DisplayName("invalid override is ignored and falls back to auto-selection")
        void invalidFallsBackToAuto() {
            assertEquals(openai.determineOutputMode(schema()),
                openai.determineOutputMode(schema(), "bogus"));
            assertEquals(gemini.determineOutputMode(schema()),
                gemini.determineOutputMode(schema(), "STRICT")); // case-sensitive → invalid
        }
    }

    @Nested
    @DisplayName("outputModeOverride(options)")
    class OptionsExtraction {

        @Test
        @DisplayName("absent / null options return unset")
        void absentReturnsUnset() {
            assertEquals(LlmProviderHandler.OUTPUT_MODE_UNSET,
                LlmProviderHandler.outputModeOverride(null));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_UNSET,
                LlmProviderHandler.outputModeOverride(Map.of()));
        }

        @Test
        @DisplayName("present option is read through")
        void presentReadThrough() {
            assertEquals("hint",
                LlmProviderHandler.outputModeOverride(Map.of("output_mode", "hint")));
        }
    }

    @Nested
    @DisplayName("effective mode selects the structured-output prompt path")
    class PromptPathSelection {

        private final OpenAiHandler openai = new OpenAiHandler();
        private final List<ToolDefinition> noTools = List.of();

        @Test
        @DisplayName("hint override produces detailed JSON prompt instructions (OpenAI auto = strict)")
        void hintOverrideProducesHintInstructions() {
            // Auto (strict) gives only a brief note; the hint override must inject
            // explicit JSON formatting instructions instead.
            String strict = openai.formatSystemPromptViaCore("Base.", noTools, schema(),
                openai.determineOutputMode(schema(), ""));
            String hint = openai.formatSystemPromptViaCore("Base.", noTools, schema(),
                openai.determineOutputMode(schema(), "hint"));

            assertFalse(strict.contains("OUTPUT FORMAT:"),
                "strict (auto) should not contain hint OUTPUT FORMAT block");
            assertTrue(hint.contains("OUTPUT FORMAT:"),
                "hint override should inject prompt-based JSON instructions");
            assertNotEquals(strict, hint, "hint must differ from strict");
        }

        @Test
        @DisplayName("text override produces no JSON instructions even with a schema")
        void textOverrideProducesNoJsonInstructions() {
            // text mode: caller suppresses the schema, so no JSON instructions.
            String text = openai.formatSystemPromptViaCore("Base.", noTools, null,
                openai.determineOutputMode(schema(), "text"));
            assertEquals("Base.", text);
        }

        @Test
        @DisplayName("strict override produces a brief schema note (response_format enforces)")
        void strictOverrideProducesBriefNote() {
            String strict = openai.formatSystemPromptViaCore("Base.", noTools, schema(),
                openai.determineOutputMode(schema(), "strict"));
            assertTrue(strict.contains("PersonInfo"),
                "strict mode should reference the schema name in a brief note");
            assertFalse(strict.contains("OUTPUT FORMAT:"),
                "strict mode should not contain hint-mode JSON instructions");
        }
    }
}
