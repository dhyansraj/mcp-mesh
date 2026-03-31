package io.mcpmesh.ai.handlers;

import io.mcpmesh.ai.handlers.LlmProviderHandler.*;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.util.*;

@DisplayName("AnthropicHandler")
class AnthropicHandlerTest {

    private AnthropicHandler handler;

    @BeforeAll
    static void installNativeStub() {
        FormatSystemPromptStub.install();
    }

    @AfterAll
    static void uninstallNativeStub() {
        FormatSystemPromptStub.uninstall();
    }

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
        @DisplayName("structured_output is true (native output_format with json_schema)")
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
        @DisplayName("json_mode is true (via output_format json_schema)")
        void jsonModeIsTrue() {
            assertTrue(handler.getCapabilities().get("json_mode"));
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
        @DisplayName("non-null schema returns OUTPUT_MODE_STRICT")
        void nonNullSchemaReturnsStrict() {
            OutputSchema schema = OutputSchema.fromSchema("Test", Map.of(
                "type", "object",
                "properties", Map.of("name", Map.of("type", "string"))
            ));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_STRICT, handler.determineOutputMode(schema));
        }

        @Test
        @DisplayName("any schema always returns strict (native output_format)")
        void anySchemaAlwaysReturnsStrict() {
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

            assertEquals(LlmProviderHandler.OUTPUT_MODE_STRICT, handler.determineOutputMode(simpleSchema));
            assertEquals(LlmProviderHandler.OUTPUT_MODE_STRICT, handler.determineOutputMode(complexSchema));
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
        @DisplayName("with tools contains TOOL CALLING RULES and anti-XML warning")
        void withToolsContainsToolInstructionsAndAntiXml() {
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("get_weather", "Get weather info", Map.of(
                    "type", "object",
                    "properties", Map.of("city", Map.of("type", "string"))
                ))
            );

            String result = handler.formatSystemPrompt("You are helpful.", tools, null);
            assertTrue(result.contains("TOOL CALLING RULES"), "Should contain tool instructions");
            assertTrue(result.contains("NEVER use XML-style syntax"), "Should contain anti-XML warning");
        }

        @Test
        @DisplayName("with schema and no tools contains brief JSON note (strict mode)")
        void withSchemaNoToolsContainsBriefNote() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            Map<String, Object> props = new LinkedHashMap<>();
            props.put("name", Map.of("type", "string", "description", "The name"));
            schema.put("properties", props);
            schema.put("required", List.of("name"));

            OutputSchema outputSchema = OutputSchema.fromSchema("PersonInfo", schema);

            String result = handler.formatSystemPrompt("You are helpful.", null, outputSchema);
            assertTrue(result.contains("structured as JSON matching the PersonInfo format"),
                "Should contain brief schema note");
            assertFalse(result.contains("RESPONSE FORMAT:"),
                "Strict mode should NOT contain detailed RESPONSE FORMAT");
            assertFalse(result.contains("CRITICAL:"),
                "Strict mode should NOT contain CRITICAL instruction (output_format enforces)");
        }

        @Test
        @DisplayName("with both tools and schema contains tool instructions and brief JSON note (strict mode)")
        void withToolsAndSchemaContainsToolInstructionsAndBriefNote() {
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("search", "Search the web", Map.of())
            );

            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of("result", Map.of("type", "string")));

            OutputSchema outputSchema = OutputSchema.fromSchema("SearchResult", schema);

            String result = handler.formatSystemPrompt("Base prompt.", tools, outputSchema);
            assertTrue(result.contains("TOOL CALLING RULES"), "Should contain tool instructions");
            assertTrue(result.contains("structured as JSON matching the SearchResult format"),
                "Should contain brief schema note");
            assertFalse(result.contains("RESPONSE FORMAT:"),
                "Strict mode should NOT contain detailed RESPONSE FORMAT");
            assertFalse(result.contains("DECISION GUIDE:"),
                "Strict mode should NOT contain DECISION GUIDE (output_format enforces schema)");
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
            assertTrue(result.contains("TOOL CALLING RULES"), "Should contain tool instructions");
            assertFalse(result.contains("RESPONSE FORMAT:"), "Should not contain RESPONSE FORMAT");
        }

        @Test
        @DisplayName("schema with empty properties returns brief JSON note (strict mode)")
        void schemaWithEmptyPropertiesReturnsBriefNote() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of());

            OutputSchema outputSchema = OutputSchema.fromSchema("Empty", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);
            assertTrue(result.contains("structured as JSON matching the Empty format"),
                "Should contain brief schema note");
        }

        @Test
        @DisplayName("strict mode uses brief note, no field-level descriptions in prompt")
        void strictModeNoBriefFieldDescriptions() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            Map<String, Object> props = new LinkedHashMap<>();
            props.put("name", Map.of("type", "string", "description", "The name"));
            props.put("age", Map.of("type", "number"));
            schema.put("properties", props);
            schema.put("required", List.of("name"));

            OutputSchema outputSchema = OutputSchema.fromSchema("Person", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);
            assertTrue(result.contains("structured as JSON matching the Person format"),
                "Should contain brief schema note");
            assertFalse(result.contains("name: string (required)"),
                "Strict mode should not contain field descriptions (output_format enforces)");
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
            assertTrue(result.contains("TOOL CALLING RULES"), "Should contain tool instructions");
        }

        @Test
        @DisplayName("empty tools list does not add tool instructions")
        void emptyToolsListNoInstructions() {
            String result = handler.formatSystemPrompt("Base prompt.", List.of(), null);
            assertEquals("Base prompt.", result);
            assertFalse(result.contains("TOOL CALLING RULES"));
        }

        @Test
        @DisplayName("strict mode with schema references schema name in brief note")
        void strictModeReferencesSchemaName() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of("foo", Map.of("type", "string")));

            OutputSchema outputSchema = OutputSchema.fromSchema("NoReq", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);
            assertTrue(result.contains("NoReq format"),
                "Brief note should reference the schema name");
        }
    }
}
