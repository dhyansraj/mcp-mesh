package io.mcpmesh.ai.handlers;

import io.mcpmesh.core.FormatSystemPromptFn;
import io.mcpmesh.core.MeshCoreBridge;
import tools.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Pure-Java reimplementation of the Rust {@code format_system_prompt} logic.
 *
 * <p>Registered via {@link MeshCoreBridge#setFormatSystemPromptOverride} so
 * that handler unit tests can run without the native Rust library (e.g. in CI).
 *
 * <p>The implementation mirrors {@code src/runtime/core/src/provider.rs} and
 * must be kept in sync when the Rust logic changes.
 */
final class FormatSystemPromptStub implements FormatSystemPromptFn {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    // -----------------------------------------------------------------------
    // Constants (mirrored from provider.rs)
    // -----------------------------------------------------------------------

    private static final String BASE_TOOL_INSTRUCTIONS =
        "\n\nIMPORTANT TOOL CALLING RULES:\n"
        + "- You have access to tools that you can call to gather information\n"
        + "- Make ONE tool call at a time\n"
        + "- After receiving tool results, you can make additional calls if needed\n"
        + "- Once you have all needed information, provide your final response\n";

    private static final String CLAUDE_ANTI_XML_INSTRUCTION =
        "- NEVER use XML-style syntax like <invoke name=\"tool_name\"/>\n";

    private static final String MEDIA_PARAM_INSTRUCTIONS =
        "\n\nMEDIA PARAMETERS: Some tools accept media URIs (file://, s3://) in "
        + "parameters marked with x-media-type. If you received images or media in "
        + "this conversation, pass the media URI to the appropriate tool parameter.";

    private static final String DECISION_GUIDE =
        "\nDECISION GUIDE:\n"
        + "- If your answer requires real-time data (weather, calculations, etc.), "
        + "call the appropriate tool FIRST, then format your response as JSON.\n"
        + "- If your answer is general knowledge (like facts, explanations, definitions), "
        + "directly return your response as JSON WITHOUT calling tools.\n"
        + "- After calling a tool and receiving results, STOP calling tools and "
        + "return your final JSON response.\n";

    private static final String GENERIC_TOOL_INSTRUCTIONS =
        "\n\nTOOL CALLING RULES:\n"
        + "- You can call tools to gather information\n"
        + "- Make one tool call at a time\n"
        + "- Wait for tool results before making additional calls\n"
        + "- Use standard JSON function calling format\n"
        + "- Provide your final response after gathering needed information\n";

    // -----------------------------------------------------------------------
    // Singleton + registration helpers
    // -----------------------------------------------------------------------

    static final FormatSystemPromptStub INSTANCE = new FormatSystemPromptStub();

    /** Register the stub so MeshCoreBridge uses it instead of native code. */
    static void install() {
        MeshCoreBridge.setFormatSystemPromptOverride(INSTANCE);
    }

    /** Remove the stub and restore native behaviour. */
    static void uninstall() {
        MeshCoreBridge.setFormatSystemPromptOverride(null);
    }

    // -----------------------------------------------------------------------
    // Vendor config (mirrors VendorConfig in provider.rs)
    // -----------------------------------------------------------------------

    private record VendorConfig(
        String name,
        boolean antiXmlInstruction,
        boolean useGenericToolInstructions,
        String hintStyle
    ) {}

    private static VendorConfig vendorConfig(String provider) {
        return switch (provider.toLowerCase()) {
            case "anthropic", "claude" -> new VendorConfig(
                "anthropic", true, false, "detailed");
            case "openai", "gpt" -> new VendorConfig(
                "openai", false, false, "example");
            case "gemini", "google" -> new VendorConfig(
                "gemini", false, false, "example");
            default -> new VendorConfig(
                "generic", false, true, "full_schema");
        };
    }

    // -----------------------------------------------------------------------
    // FormatSystemPromptFn implementation
    // -----------------------------------------------------------------------

    @Override
    public String apply(String provider, String basePrompt, boolean hasTools,
                        boolean hasMediaParams, String schemaJson,
                        String schemaName, String outputMode) {

        VendorConfig config = vendorConfig(provider);
        StringBuilder result = new StringBuilder(basePrompt != null ? basePrompt : "");

        // Tool instructions
        if (hasTools) {
            if (config.useGenericToolInstructions()) {
                result.append(GENERIC_TOOL_INSTRUCTIONS);
            } else if (config.antiXmlInstruction()) {
                String toolInstr = BASE_TOOL_INSTRUCTIONS;
                String marker = "- Make ONE tool call at a time\n";
                int pos = toolInstr.indexOf(marker);
                if (pos >= 0) {
                    int insertAt = pos + marker.length();
                    toolInstr = toolInstr.substring(0, insertAt)
                        + CLAUDE_ANTI_XML_INSTRUCTION
                        + toolInstr.substring(insertAt);
                }
                result.append(toolInstr);
            } else {
                result.append(BASE_TOOL_INSTRUCTIONS);
            }
        }

        // Media parameters
        if (hasMediaParams) {
            result.append(MEDIA_PARAM_INSTRUCTIONS);
        }

        // Output mode formatting
        if ("text".equals(outputMode)) {
            return result.toString();
        }

        if ("strict".equals(outputMode)) {
            String name = (schemaName != null) ? schemaName : "output";
            result.append("\n\nYour final response will be structured as JSON matching the ")
                  .append(name)
                  .append(" format.");
            return result.toString();
        }

        if ("hint".equals(outputMode) && schemaJson != null) {
            Map<String, Object> schema = parseSchema(schemaJson);
            if (schema != null) {
                String name = (schemaName != null) ? schemaName : "output";
                String hint = switch (config.hintStyle()) {
                    case "detailed" -> formatHintDetailed(schema, name, hasTools);
                    case "example" -> formatHintExample(schema, hasTools);
                    default -> formatHintFullSchema(schema);
                };
                result.append(hint);
            }
        }

        return result.toString();
    }

    // -----------------------------------------------------------------------
    // Hint formatting helpers
    // -----------------------------------------------------------------------

    @SuppressWarnings("unchecked")
    private String formatHintDetailed(Map<String, Object> schema, String schemaName, boolean hasTools) {
        StringBuilder sb = new StringBuilder();

        if (hasTools) {
            sb.append(DECISION_GUIDE);
        }

        sb.append("\nRESPONSE FORMAT:\nYou MUST respond with valid JSON matching the ")
          .append(schemaName)
          .append(" schema:\n{\n");

        Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
        List<String> required = schema.get("required") instanceof List
            ? (List<String>) schema.get("required")
            : List.of();

        if (properties != null) {
            for (Map.Entry<String, Object> entry : properties.entrySet()) {
                String fieldName = entry.getKey();
                Map<String, Object> fieldSchema = (Map<String, Object>) entry.getValue();

                String baseType = fieldSchema.getOrDefault("type", "any").toString();
                String fieldType;
                if ("array".equals(baseType)) {
                    Map<String, Object> items = (Map<String, Object>) fieldSchema.get("items");
                    if (items != null && items.get("type") != null) {
                        fieldType = "array of " + items.get("type");
                    } else {
                        fieldType = baseType;
                    }
                } else {
                    fieldType = baseType;
                }

                String reqMarker = required.contains(fieldName) ? " (required)" : " (optional)";
                String desc = (String) fieldSchema.get("description");
                String descText = (desc != null && !desc.isEmpty()) ? " - " + desc : "";
                sb.append("  - ").append(fieldName).append(": ")
                  .append(fieldType).append(reqMarker).append(descText).append("\n");
            }
        }

        // Example format block
        sb.append("}\n\nExample format:\n");
        if (properties != null && !properties.isEmpty()) {
            Map<String, String> examples = new LinkedHashMap<>();
            for (Map.Entry<String, Object> entry : properties.entrySet()) {
                Map<String, Object> fieldSchema = (Map<String, Object>) entry.getValue();
                String typeStr = fieldSchema.getOrDefault("type", "value").toString();
                String exampleVal;
                if ("array".equals(typeStr)) {
                    Map<String, Object> items = (Map<String, Object>) fieldSchema.get("items");
                    String itemType = (items != null) ? (String) items.get("type") : null;
                    if ("string".equals(itemType)) {
                        exampleVal = "[\"string1\",\"string2\"]";
                    } else if ("integer".equals(itemType) || "number".equals(itemType)) {
                        exampleVal = "[1,2]";
                    } else {
                        exampleVal = "\"<" + typeStr + ">\"";
                    }
                } else {
                    exampleVal = "\"<" + typeStr + ">\"";
                }
                examples.put(entry.getKey(), exampleVal);
            }
            try {
                // Use proper JSON serialization for the example
                Map<String, Object> exampleMap = new LinkedHashMap<>();
                for (Map.Entry<String, Object> entry : properties.entrySet()) {
                    Map<String, Object> fieldSchema = (Map<String, Object>) entry.getValue();
                    String typeStr = fieldSchema.getOrDefault("type", "value").toString();
                    exampleMap.put(entry.getKey(), "<" + typeStr + ">");
                }
                sb.append(MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(exampleMap));
            } catch (Exception e) {
                sb.append("{}");
            }
        }
        sb.append("\n");

        sb.append("\nCRITICAL: Your response must be ONLY the raw JSON object.\n")
          .append("- DO NOT wrap in markdown code fences (```json or ```)\n")
          .append("- DO NOT include any text before or after the JSON\n")
          .append("- Start directly with { and end with }");

        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private String formatHintExample(Map<String, Object> schema, boolean hasTools) {
        StringBuilder sb = new StringBuilder();
        sb.append("\n\nOUTPUT FORMAT:\n");

        if (hasTools) {
            sb.append("DECISION GUIDE:\n");
            sb.append("- If your answer requires real-time data (weather, calculations, etc.), ")
              .append("call the appropriate tool FIRST, then format your response as JSON.\n");
            sb.append("- If your answer is general knowledge (like facts, explanations, definitions), ")
              .append("directly return your response as JSON WITHOUT calling tools.\n\n");
        }

        sb.append("Your FINAL response must be ONLY valid JSON (no markdown, no code blocks) ")
          .append("with this exact structure:\n");
        sb.append(buildJsonExample(schema));
        sb.append("\n\nReturn ONLY the JSON object with actual values. ")
          .append("Do not include the schema definition, markdown formatting, or code blocks.");

        // Anti-wrapping instruction (matches the Gemini tests)
        Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
        if (properties != null && !properties.isEmpty()) {
            // Find the schema name from the calling context -- not available here,
            // so we use a generic anti-wrapping message
        }

        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private String buildJsonExample(Map<String, Object> schema) {
        Map<String, Object> properties = (Map<String, Object>) schema.get("properties");
        if (properties == null || properties.isEmpty()) {
            return "{}";
        }

        List<Map.Entry<String, Object>> items = List.copyOf(properties.entrySet());
        StringBuilder sb = new StringBuilder("{\n");
        for (int i = 0; i < items.size(); i++) {
            Map.Entry<String, Object> entry = items.get(i);
            String name = entry.getKey();
            @SuppressWarnings("unchecked")
            Map<String, Object> prop = (Map<String, Object>) entry.getValue();
            String propType = prop.getOrDefault("type", "string").toString();

            String exampleValue = switch (propType) {
                case "string" -> "\"<your " + name + " here>\"";
                case "number", "integer" -> "0";
                case "array" -> "[\"item1\", \"item2\"]";
                case "boolean" -> "true";
                case "object" -> "{}";
                default -> "null";
            };

            String comma = (i < items.size() - 1) ? "," : "";
            sb.append("  \"").append(name).append("\": ").append(exampleValue)
              .append(comma).append("\n");
        }
        sb.append("}");
        return sb.toString();
    }

    private String formatHintFullSchema(Map<String, Object> schema) {
        String schemaStr;
        try {
            schemaStr = MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(schema);
        } catch (Exception e) {
            schemaStr = "{}";
        }
        return "\n\nIMPORTANT: Return your final response as valid JSON matching this exact schema:\n"
            + schemaStr
            + "\n\nRules:\n- Return ONLY the JSON object, no markdown, no additional text\n"
            + "- Ensure all required fields are present\n"
            + "- Match the schema exactly\n"
            + "- Use double quotes for strings\n"
            + "- Do not include comments";
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    @SuppressWarnings("unchecked")
    private static Map<String, Object> parseSchema(String schemaJson) {
        try {
            return MAPPER.readValue(schemaJson, Map.class);
        } catch (Exception e) {
            return null;
        }
    }
}
