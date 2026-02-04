package io.mcpmesh.ai.handlers;

import io.mcpmesh.ai.handlers.LlmProviderHandler.*;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.util.*;

@DisplayName("OpenAiHandler")
class OpenAiHandlerTest {

    private OpenAiHandler handler;

    @BeforeEach
    void setUp() {
        handler = new OpenAiHandler();
    }

    @Nested
    @DisplayName("vendor")
    class VendorTests {

        @Test
        @DisplayName("getVendor returns 'openai'")
        void getVendorReturnsOpenai() {
            assertEquals("openai", handler.getVendor());
        }

        @Test
        @DisplayName("getAliases returns ['gpt']")
        void getAliasesReturnsGpt() {
            String[] aliases = handler.getAliases();
            assertArrayEquals(new String[]{"gpt"}, aliases);
        }
    }

    @Nested
    @DisplayName("getCapabilities")
    class CapabilitiesTests {

        @Test
        @DisplayName("native_tool_calling is true")
        void nativeToolCallingIsTrue() {
            assertTrue(handler.getCapabilities().get("native_tool_calling"));
        }

        @Test
        @DisplayName("structured_output is true")
        void structuredOutputIsTrue() {
            assertTrue(handler.getCapabilities().get("structured_output"));
        }

        @Test
        @DisplayName("streaming is true")
        void streamingIsTrue() {
            assertTrue(handler.getCapabilities().get("streaming"));
        }

        @Test
        @DisplayName("vision is true")
        void visionIsTrue() {
            assertTrue(handler.getCapabilities().get("vision"));
        }

        @Test
        @DisplayName("json_mode is true")
        void jsonModeIsTrue() {
            assertTrue(handler.getCapabilities().get("json_mode"));
        }
    }

    @Nested
    @DisplayName("determineOutputMode")
    class DetermineOutputModeTests {

        @Test
        @DisplayName("null schema returns OUTPUT_MODE_TEXT")
        void nullSchemaReturnsText() {
            assertEquals(LlmProviderHandler.OUTPUT_MODE_TEXT, handler.determineOutputMode(null));
        }

        @Test
        @DisplayName("non-null schema returns OUTPUT_MODE_STRICT")
        void nonNullSchemaReturnsStrict() {
            OutputSchema schema = OutputSchema.fromSchema("Test", Map.of(
                "type", "object",
                "properties", Map.of("value", Map.of("type", "string"))
            ));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_STRICT, handler.determineOutputMode(schema));
        }
    }

    @Nested
    @DisplayName("formatSystemPrompt")
    class FormatSystemPromptTests {

        @Test
        @DisplayName("base prompt only returns prompt unchanged")
        void basePromptOnlyReturnsUnchanged() {
            String result = handler.formatSystemPrompt("You are a helpful assistant.", null, null);
            assertEquals("You are a helpful assistant.", result);
        }

        @Test
        @DisplayName("with tools contains TOOL CALLING INSTRUCTIONS but not XML warning")
        void withToolsContainsInstructionsNoXmlWarning() {
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("get_weather", "Get weather info", Map.of(
                    "type", "object",
                    "properties", Map.of("city", Map.of("type", "string"))
                ))
            );

            String result = handler.formatSystemPrompt("You are helpful.", tools, null);
            assertTrue(result.contains("TOOL CALLING INSTRUCTIONS"), "Should contain tool instructions");
            assertFalse(result.contains("XML"), "Should NOT contain XML warning");
        }

        @Test
        @DisplayName("with schema contains brief JSON note mentioning schema name")
        void withSchemaContainsBriefNote() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of("name", Map.of("type", "string")));

            OutputSchema outputSchema = OutputSchema.fromSchema("PersonInfo", schema);

            String result = handler.formatSystemPrompt("You are helpful.", null, outputSchema);
            assertTrue(result.contains("structured as JSON matching the PersonInfo format"),
                "Should contain brief JSON note with schema name");
        }

        @Test
        @DisplayName("with schema does NOT contain RESPONSE FORMAT (unlike Claude)")
        void withSchemaNoDetailedResponseFormat() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of("name", Map.of("type", "string")));

            OutputSchema outputSchema = OutputSchema.fromSchema("Test", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);
            assertFalse(result.contains("RESPONSE FORMAT:"),
                "Should NOT contain detailed RESPONSE FORMAT section");
        }

        @Test
        @DisplayName("text mode with null schema returns just base prompt")
        void textModeReturnsBasePrompt() {
            String result = handler.formatSystemPrompt("You are helpful.", null, null);
            assertEquals("You are helpful.", result);
        }

        @Test
        @DisplayName("with tools AND schema contains both tool instructions and JSON note")
        void withToolsAndSchemaContainsBoth() {
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("search", "Search the web", Map.of())
            );

            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of("result", Map.of("type", "string")));

            OutputSchema outputSchema = OutputSchema.fromSchema("SearchResult", schema);

            String result = handler.formatSystemPrompt("Base prompt.", tools, outputSchema);
            assertTrue(result.contains("TOOL CALLING INSTRUCTIONS"),
                "Should contain tool instructions");
            assertTrue(result.contains("structured as JSON matching the SearchResult format"),
                "Should contain JSON note");
        }

        @Test
        @DisplayName("null base prompt treated as empty string")
        void nullBasePromptTreatedAsEmpty() {
            String result = handler.formatSystemPrompt(null, null, null);
            assertEquals("", result);
        }

        @Test
        @DisplayName("empty tools list does not add tool instructions")
        void emptyToolsListNoInstructions() {
            String result = handler.formatSystemPrompt("Base prompt.", List.of(), null);
            assertEquals("Base prompt.", result);
            assertFalse(result.contains("TOOL CALLING INSTRUCTIONS"));
        }
    }
}
