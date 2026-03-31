package io.mcpmesh.ai;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.PropertyNamingStrategies;
import tools.jackson.databind.json.JsonMapper;
import io.mcpmesh.core.MeshCoreBridge;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.RecordComponent;
import java.util.*;

/**
 * Parses LLM responses into structured Java objects.
 *
 * <p>Supports:
 * <ul>
 *   <li>Java records (Java 17+)</li>
 *   <li>POJOs with getters/setters</li>
 *   <li>JSON extraction from text responses</li>
 *   <li>Format hint generation for LLM prompts</li>
 * </ul>
 *
 * <h2>Usage</h2>
 * <pre>{@code
 * StructuredOutputParser parser = new StructuredOutputParser();
 *
 * // Parse LLM response
 * AnalysisResult result = parser.parse(llmResponse, AnalysisResult.class);
 *
 * // Generate format hint for prompt
 * String hint = parser.getFormatHint(AnalysisResult.class);
 * }</pre>
 *
 * <h2>Record Support</h2>
 * <pre>{@code
 * public record AnalysisResult(
 *     String summary,
 *     List<String> insights,
 *     double confidence
 * ) {}
 * }</pre>
 */
public class StructuredOutputParser {

    private static final Logger log = LoggerFactory.getLogger(StructuredOutputParser.class);

    private final ObjectMapper objectMapper;

    public StructuredOutputParser() {
        this.objectMapper = createObjectMapper();
    }

    /**
     * Parse LLM response into the target type.
     *
     * @param <T>          The target type
     * @param response     The LLM response (may contain text + JSON)
     * @param responseType The class to deserialize into
     * @return The parsed object
     * @throws StructuredOutputException if parsing fails
     */
    public <T> T parse(String response, Class<T> responseType) {
        if (response == null || response.isBlank()) {
            throw new StructuredOutputException("Empty response");
        }

        // Try to extract JSON from the response
        String json = extractJson(response, responseType.isArray() || Collection.class.isAssignableFrom(responseType));

        if (json == null) {
            throw new StructuredOutputException(
                "Could not find JSON in response. Expected " + responseType.getSimpleName());
        }

        try {
            return objectMapper.readValue(json, responseType);
        } catch (JacksonException e) {
            throw new StructuredOutputException("Failed to parse JSON: " + e.getMessage(), e);
        }
    }

    /**
     * Parse with fallback to empty Optional instead of exception.
     *
     * @param <T>          The target type
     * @param response     The LLM response
     * @param responseType The class to deserialize into
     * @return Optional containing the parsed object, or empty if parsing failed
     */
    public <T> Optional<T> parseOptional(String response, Class<T> responseType) {
        try {
            return Optional.of(parse(response, responseType));
        } catch (StructuredOutputException e) {
            log.warn("Failed to parse structured output: {}", e.getMessage());
            return Optional.empty();
        }
    }

    /**
     * Generate format hint to append to LLM prompt.
     *
     * <p>This helps the LLM understand the expected response format.
     *
     * @param responseType The expected response type
     * @return Format hint string for the prompt
     */
    public String getFormatHint(Class<?> responseType) {
        StringBuilder hint = new StringBuilder();
        hint.append("\n\nRespond with valid JSON matching this schema:\n```json\n");
        hint.append(generateJsonSchema(responseType));
        hint.append("\n```\n");
        return hint.toString();
    }

    /**
     * Generate JSON schema from a class.
     *
     * <p>Supports records and regular POJOs.
     *
     * @param type The class to generate schema for
     * @return JSON schema as a string
     */
    public String generateJsonSchema(Class<?> type) {
        Map<String, Object> schema = buildSchema(type);
        try {
            return objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(schema);
        } catch (JacksonException e) {
            return "{}";
        }
    }

    /**
     * Get the ObjectMapper used for parsing.
     *
     * @return The configured ObjectMapper
     */
    public ObjectMapper getObjectMapper() {
        return objectMapper;
    }

    /**
     * Extract JSON from a text response.
     *
     * <p>Delegates to Rust core for consistent cross-SDK behavior.
     */
    private String extractJson(String response, boolean expectArray) {
        return MeshCoreBridge.extractJson(response);
    }

    private Map<String, Object> buildSchema(Class<?> type) {
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");

        Map<String, Object> properties = new LinkedHashMap<>();
        List<String> required = new ArrayList<>();

        // Handle records (Java 17+)
        if (type.isRecord()) {
            for (RecordComponent component : type.getRecordComponents()) {
                String name = component.getName();
                Class<?> fieldType = component.getType();
                properties.put(name, typeToSchema(fieldType));
                required.add(name);
            }
        } else {
            // Handle regular classes via reflection
            for (java.lang.reflect.Field field : type.getDeclaredFields()) {
                if (java.lang.reflect.Modifier.isStatic(field.getModifiers())) {
                    continue;
                }
                if (java.lang.reflect.Modifier.isTransient(field.getModifiers())) {
                    continue;
                }
                String name = field.getName();
                properties.put(name, typeToSchema(field.getType()));
            }
        }

        schema.put("properties", properties);
        if (!required.isEmpty()) {
            schema.put("required", required);
        }

        return schema;
    }

    private Map<String, Object> typeToSchema(Class<?> type) {
        Map<String, Object> schema = new LinkedHashMap<>();

        if (type == String.class) {
            schema.put("type", "string");
        } else if (type == int.class || type == Integer.class ||
                   type == long.class || type == Long.class) {
            schema.put("type", "integer");
        } else if (type == double.class || type == Double.class ||
                   type == float.class || type == Float.class) {
            schema.put("type", "number");
        } else if (type == boolean.class || type == Boolean.class) {
            schema.put("type", "boolean");
        } else if (type.isArray() || Collection.class.isAssignableFrom(type)) {
            schema.put("type", "array");
            // Try to get generic type - simplified to string for now
            schema.put("items", Map.of("type", "string"));
        } else if (Map.class.isAssignableFrom(type)) {
            schema.put("type", "object");
            schema.put("additionalProperties", true);
        } else if (!type.isPrimitive()) {
            // Complex nested type - recurse
            schema.putAll(buildSchema(type));
        } else {
            schema.put("type", "string");
        }

        return schema;
    }

    private ObjectMapper createObjectMapper() {
        // Jackson 3 uses builder pattern for configuration
        // JSR-310 date/time support is built-in (no module needed)
        return JsonMapper.builder()
            .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
            .build();
    }

    /**
     * Exception thrown when structured output parsing fails.
     */
    public static class StructuredOutputException extends RuntimeException {
        public StructuredOutputException(String message) {
            super(message);
        }

        public StructuredOutputException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
