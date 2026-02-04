package io.mcpmesh.ai.handlers;

import io.mcpmesh.ai.handlers.LlmProviderHandler.*;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.util.*;

@DisplayName("AnthropicHandler")
class AnthropicHandlerTest {

    private AnthropicHandler handler;

    @BeforeEach
    void setUp() {
        handler = new AnthropicHandler();
    }

    @Nested
    @DisplayName("vendor")
    class VendorTests {

        @Test
        @DisplayName("getVendor returns 'anthropic'")
        void getVendorReturnsAnthropic() {
            assertEquals("anthropic", handler.getVendor());
        }

        @Test
        @DisplayName("getAliases returns ['claude']")
        void getAliasesReturnsClaude() {
            String[] aliases = handler.getAliases();
            assertArrayEquals(new String[]{"claude"}, aliases);
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
        @DisplayName("structured_output is false (uses HINT, not native response_format)")
        void structuredOutputIsFalse() {
            assertFalse(handler.getCapabilities().get("structured_output"));
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
        @DisplayName("json_mode is false")
        void jsonModeIsFalse() {
            assertFalse(handler.getCapabilities().get("json_mode"));
        }

        @Test
        @DisplayName("prompt_caching is false")
        void promptCachingIsFalse() {
            assertFalse(handler.getCapabilities().get("prompt_caching"));
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
        @DisplayName("non-null schema returns OUTPUT_MODE_HINT")
        void nonNullSchemaReturnsHint() {
            OutputSchema schema = OutputSchema.fromSchema("Test", Map.of(
                "type", "object",
                "properties", Map.of("name", Map.of("type", "string"))
            ));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_HINT, handler.determineOutputMode(schema));
        }

        @Test
        @DisplayName("any schema always returns hint, never strict")
        void anySchemaAlwaysReturnsHint() {
            OutputSchema simpleSchema = new OutputSchema("Simple", Map.of(
                "type", "object",
                "properties", Map.of("x", Map.of("type", "string"))
            ), true);

            OutputSchema complexSchema = new OutputSchema("Complex", Map.of(
                "type", "object",
                "properties", Map.of(
                    "a", Map.of("type", "string"),
                    "b", Map.of("type", "number"),
                    "c", Map.of("type", "string"),
                    "d", Map.of("type", "string"),
                    "e", Map.of("type", "string")
                )
            ), false);

            assertEquals(LlmProviderHandler.OUTPUT_MODE_HINT, handler.determineOutputMode(simpleSchema));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_HINT, handler.determineOutputMode(complexSchema));
            assertNotEquals(LlmProviderHandler.OUTPUT_MODE_STRICT, handler.determineOutputMode(simpleSchema));
            assertNotEquals(LlmProviderHandler.OUTPUT_MODE_STRICT, handler.determineOutputMode(complexSchema));
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
        @DisplayName("with tools contains TOOL CALLING INSTRUCTIONS and anti-XML warning")
        void withToolsContainsToolInstructionsAndAntiXml() {
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("get_weather", "Get weather info", Map.of(
                    "type", "object",
                    "properties", Map.of("city", Map.of("type", "string"))
                ))
            );

            String result = handler.formatSystemPrompt("You are helpful.", tools, null);
            assertTrue(result.contains("TOOL CALLING INSTRUCTIONS"), "Should contain tool instructions");
            assertTrue(result.contains("NEVER use XML-style syntax"), "Should contain anti-XML warning");
        }

        @Test
        @DisplayName("with schema and no tools contains RESPONSE FORMAT and field descriptions")
        void withSchemaNoToolsContainsResponseFormat() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            Map<String, Object> props = new LinkedHashMap<>();
            props.put("name", Map.of("type", "string", "description", "The name"));
            schema.put("properties", props);
            schema.put("required", List.of("name"));

            OutputSchema outputSchema = OutputSchema.fromSchema("PersonInfo", schema);

            String result = handler.formatSystemPrompt("You are helpful.", null, outputSchema);
            assertTrue(result.contains("RESPONSE FORMAT:"), "Should contain RESPONSE FORMAT");
            assertTrue(result.contains("name: string (required)"), "Should contain field description");
            assertTrue(result.contains("CRITICAL: Your response must be ONLY the raw JSON object"),
                "Should contain critical JSON instruction");
        }

        @Test
        @DisplayName("with both tools and schema contains DECISION GUIDE and TOOL CALLING INSTRUCTIONS and RESPONSE FORMAT")
        void withToolsAndSchemaContainsDecisionGuide() {
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("search", "Search the web", Map.of())
            );

            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of("result", Map.of("type", "string")));

            OutputSchema outputSchema = OutputSchema.fromSchema("SearchResult", schema);

            String result = handler.formatSystemPrompt("Base prompt.", tools, outputSchema);
            assertTrue(result.contains("DECISION GUIDE:"), "Should contain DECISION GUIDE");
            assertTrue(result.contains("TOOL CALLING INSTRUCTIONS"), "Should contain tool instructions");
            assertTrue(result.contains("RESPONSE FORMAT:"), "Should contain RESPONSE FORMAT");
        }

        @Test
        @DisplayName("text mode with null schema has no JSON instructions")
        void textModeNoJsonInstructions() {
            String result = handler.formatSystemPrompt("You are helpful.", null, null);
            assertFalse(result.contains("RESPONSE FORMAT:"), "Should not contain RESPONSE FORMAT");
            assertFalse(result.contains("JSON"), "Should not contain JSON instructions");
            assertFalse(result.contains("CRITICAL"), "Should not contain CRITICAL instruction");
        }

        @Test
        @DisplayName("text mode with tools adds tool instructions but no JSON format")
        void textModeWithToolsNoJsonFormat() {
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("calc", "Calculate", Map.of())
            );

            String result = handler.formatSystemPrompt("You are helpful.", tools, null);
            assertTrue(result.contains("TOOL CALLING INSTRUCTIONS"), "Should contain tool instructions");
            assertFalse(result.contains("RESPONSE FORMAT:"), "Should not contain RESPONSE FORMAT");
        }

        @Test
        @DisplayName("schema with empty properties returns generic JSON instruction")
        void schemaWithEmptyPropertiesReturnsGenericJson() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of());

            OutputSchema outputSchema = OutputSchema.fromSchema("Empty", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);
            assertTrue(result.contains("Respond with valid JSON"), "Should contain generic JSON instruction");
        }

        @Test
        @DisplayName("field descriptions format: required vs optional with description")
        void fieldDescriptionsFormat() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            Map<String, Object> props = new LinkedHashMap<>();
            props.put("name", Map.of("type", "string", "description", "The name"));
            props.put("age", Map.of("type", "number"));
            schema.put("properties", props);
            schema.put("required", List.of("name"));

            OutputSchema outputSchema = OutputSchema.fromSchema("Person", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);
            assertTrue(result.contains("name: string (required) - The name"),
                "Should format required field with description");
            assertTrue(result.contains("age: number (optional)"),
                "Should format optional field without description");
        }

        @Test
        @DisplayName("null base prompt treated as empty string")
        void nullBasePromptTreatedAsEmpty() {
            String result = handler.formatSystemPrompt(null, null, null);
            assertEquals("", result);
        }

        @Test
        @DisplayName("null base prompt with tools starts with tool instructions")
        void nullBasePromptWithTools() {
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("test_tool", "A test tool", Map.of())
            );

            String result = handler.formatSystemPrompt(null, tools, null);
            assertTrue(result.contains("TOOL CALLING INSTRUCTIONS"), "Should contain tool instructions");
        }

        @Test
        @DisplayName("empty tools list does not add tool instructions")
        void emptyToolsListNoInstructions() {
            String result = handler.formatSystemPrompt("Base prompt.", List.of(), null);
            assertEquals("Base prompt.", result);
            assertFalse(result.contains("TOOL CALLING INSTRUCTIONS"));
        }

        @Test
        @DisplayName("schema without required field treats all fields as optional")
        void schemaWithoutRequiredFieldAllOptional() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of("foo", Map.of("type", "string")));

            OutputSchema outputSchema = OutputSchema.fromSchema("NoReq", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);
            assertTrue(result.contains("foo: string (optional)"),
                "Should mark field as optional when required list is absent");
        }
    }
}
