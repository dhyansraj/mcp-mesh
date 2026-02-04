package io.mcpmesh.ai.handlers;

import io.mcpmesh.ai.handlers.LlmProviderHandler.*;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.util.*;

/**
 * Tests for {@link GeminiHandler}.
 *
 * <p>Validates vendor identity, capabilities, output mode selection,
 * and system prompt formatting with tools and structured output schemas.
 */
class GeminiHandlerTest {

    private GeminiHandler handler;

    @BeforeEach
    void setUp() {
        handler = new GeminiHandler();
    }

    @Nested
    @DisplayName("Vendor Identity")
    class VendorTests {

        @Test
        @DisplayName("getVendor returns 'gemini'")
        void getVendor_returnsGemini() {
            assertEquals("gemini", handler.getVendor());
        }

        @Test
        @DisplayName("getAliases returns ['google']")
        void getAliases_returnsGoogle() {
            String[] aliases = handler.getAliases();
            assertArrayEquals(new String[]{"google"}, aliases);
        }
    }

    @Nested
    @DisplayName("Capabilities")
    class CapabilitiesTests {

        private Map<String, Boolean> capabilities;

        @BeforeEach
        void setUp() {
            capabilities = handler.getCapabilities();
        }

        @Test
        @DisplayName("native_tool_calling is true")
        void nativeToolCalling_isTrue() {
            assertTrue(capabilities.get("native_tool_calling"));
        }

        @Test
        @DisplayName("structured_output is true (via prompt hints)")
        void structuredOutput_isTrue() {
            assertTrue(capabilities.get("structured_output"));
        }

        @Test
        @DisplayName("streaming is true")
        void streaming_isTrue() {
            assertTrue(capabilities.get("streaming"));
        }

        @Test
        @DisplayName("vision is true")
        void vision_isTrue() {
            assertTrue(capabilities.get("vision"));
        }

        @Test
        @DisplayName("json_mode is false (Spring AI bug)")
        void jsonMode_isFalse() {
            assertFalse(capabilities.get("json_mode"));
        }

        @Test
        @DisplayName("large_context is true")
        void largeContext_isTrue() {
            assertTrue(capabilities.get("large_context"));
        }
    }

    @Nested
    @DisplayName("determineOutputMode")
    class DetermineOutputModeTests {

        @Test
        @DisplayName("null schema returns OUTPUT_MODE_TEXT")
        void nullSchema_returnsText() {
            assertEquals(LlmProviderHandler.OUTPUT_MODE_TEXT, handler.determineOutputMode(null));
        }

        @Test
        @DisplayName("non-null schema returns OUTPUT_MODE_HINT (Spring AI bug workaround)")
        void nonNullSchema_returnsHint() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of("answer", Map.of("type", "string"))
            );
            OutputSchema outputSchema = OutputSchema.fromSchema("TestSchema", schema);

            assertEquals(LlmProviderHandler.OUTPUT_MODE_HINT, handler.determineOutputMode(outputSchema));
        }
    }

    @Nested
    @DisplayName("formatSystemPrompt")
    class FormatSystemPromptTests {

        @Test
        @DisplayName("base prompt only - no tools, no schema - returns unchanged")
        void basePromptOnly_returnsUnchanged() {
            String basePrompt = "You are a helpful assistant.";
            String result = handler.formatSystemPrompt(basePrompt, null, null);
            assertEquals(basePrompt, result);
        }

        @Test
        @DisplayName("with tools, no schema - contains TOOL CALLING INSTRUCTIONS")
        void withTools_containsToolInstructions() {
            String basePrompt = "You are a helpful assistant.";
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("get_weather", "Get weather data", Map.of(
                    "type", "object",
                    "properties", Map.of("city", Map.of("type", "string"))
                ))
            );

            String result = handler.formatSystemPrompt(basePrompt, tools, null);

            assertTrue(result.contains("TOOL CALLING INSTRUCTIONS:"),
                "Should contain tool calling instructions");
            assertTrue(result.startsWith(basePrompt),
                "Should start with the base prompt");
        }

        @Test
        @DisplayName("with schema, no tools - contains RESPONSE FORMAT and example JSON")
        void withSchema_containsResponseFormat() {
            String basePrompt = "You are a helpful assistant.";
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            Map<String, Object> properties = new LinkedHashMap<>();
            properties.put("city", Map.of("type", "string"));
            properties.put("temperature", Map.of("type", "number"));
            schema.put("properties", properties);
            OutputSchema outputSchema = OutputSchema.fromSchema("WeatherResponse", schema);

            String result = handler.formatSystemPrompt(basePrompt, null, outputSchema);

            assertTrue(result.contains("RESPONSE FORMAT"),
                "Should contain RESPONSE FORMAT section");
            assertTrue(result.contains("\"<your city here>\""),
                "Should contain string example for city");
            assertTrue(result.contains("0"),
                "Should contain number example value 0");
        }

        @Test
        @DisplayName("with both tools AND schema - contains TOOL INSTRUCTIONS, DECISION GUIDE, and RESPONSE FORMAT")
        void withToolsAndSchema_containsAll() {
            String basePrompt = "You are a helpful assistant.";
            List<ToolDefinition> tools = List.of(
                new ToolDefinition("get_weather", "Get weather data", Map.of(
                    "type", "object",
                    "properties", Map.of("city", Map.of("type", "string"))
                ))
            );
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of("answer", Map.of("type", "string")));
            OutputSchema outputSchema = OutputSchema.fromSchema("Answer", schema);

            String result = handler.formatSystemPrompt(basePrompt, tools, outputSchema);

            assertTrue(result.contains("TOOL CALLING INSTRUCTIONS:"),
                "Should contain tool calling instructions");
            assertTrue(result.contains("DECISION GUIDE:"),
                "Should contain DECISION GUIDE");
            assertTrue(result.contains("RESPONSE FORMAT"),
                "Should contain RESPONSE FORMAT");
        }

        @Test
        @DisplayName("schema with various field types produces correct example values")
        void schemaWithVariousTypes_producesCorrectExamples() {
            Map<String, Object> properties = new LinkedHashMap<>();
            properties.put("name", Map.of("type", "string"));
            properties.put("count", Map.of("type", "number"));
            properties.put("tags", Map.of("type", "array"));
            properties.put("active", Map.of("type", "boolean"));
            properties.put("metadata", Map.of("type", "object"));

            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", properties);
            OutputSchema outputSchema = new OutputSchema("MultiType", schema, false);

            String result = handler.formatSystemPrompt("Base prompt.", null, outputSchema);

            assertTrue(result.contains("\"<your name here>\""),
                "String field should use '<your name here>' example");
            assertTrue(result.contains("\"count\": 0"),
                "Number field should use 0 as example");
            assertTrue(result.contains("[\"item1\", \"item2\"]"),
                "Array field should use [\"item1\", \"item2\"] example");
            assertTrue(result.contains("\"active\": true"),
                "Boolean field should use true as example");
            assertTrue(result.contains("\"metadata\": {}"),
                "Object field should use {} as example");
        }

        @Test
        @DisplayName("schema with integer type produces 0 as example")
        void schemaWithIntegerType_producesZero() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of("age", Map.of("type", "integer")));
            OutputSchema outputSchema = OutputSchema.fromSchema("Person", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);

            assertTrue(result.contains("\"age\": 0"),
                "Integer field should use 0 as example");
        }

        @Test
        @DisplayName("contains anti-wrapping instruction with schema name")
        void containsAntiWrappingInstruction() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of("result", Map.of("type", "string"))
            );
            OutputSchema outputSchema = OutputSchema.fromSchema("MyResult", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);

            assertTrue(result.contains("Do NOT wrap the response in a type name key"),
                "Should contain anti-wrapping instruction");
            assertTrue(result.contains("\"MyResult\""),
                "Anti-wrapping instruction should reference the schema name");
        }

        @Test
        @DisplayName("text mode (null schema) - no JSON instructions added")
        void textMode_noJsonInstructions() {
            String result = handler.formatSystemPrompt("You are helpful.", List.of(), null);
            assertFalse(result.contains("RESPONSE FORMAT"),
                "Text mode should not contain RESPONSE FORMAT");
            assertFalse(result.contains("JSON"),
                "Text mode should not contain JSON instructions");
        }

        @Test
        @DisplayName("DECISION GUIDE is NOT added when only schema is present (no tools)")
        void decisionGuide_notAddedWithoutTools() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of("answer", Map.of("type", "string"))
            );
            OutputSchema outputSchema = OutputSchema.fromSchema("Answer", schema);

            String result = handler.formatSystemPrompt("Base.", null, outputSchema);

            assertFalse(result.contains("DECISION GUIDE:"),
                "DECISION GUIDE should NOT be present without tools");
            assertTrue(result.contains("RESPONSE FORMAT"),
                "RESPONSE FORMAT should still be present");
        }

        @Test
        @DisplayName("null base prompt is handled gracefully")
        void nullBasePrompt_handledGracefully() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of("answer", Map.of("type", "string"))
            );
            OutputSchema outputSchema = OutputSchema.fromSchema("Answer", schema);

            String result = handler.formatSystemPrompt(null, null, outputSchema);

            assertNotNull(result);
            assertTrue(result.contains("RESPONSE FORMAT"),
                "Should still contain RESPONSE FORMAT with null base prompt");
        }

        @Test
        @DisplayName("empty tools list does not add TOOL CALLING INSTRUCTIONS")
        void emptyToolsList_noToolInstructions() {
            String result = handler.formatSystemPrompt("Base.", List.of(), null);
            assertFalse(result.contains("TOOL CALLING INSTRUCTIONS:"),
                "Empty tools list should not add tool instructions");
        }
    }
}
