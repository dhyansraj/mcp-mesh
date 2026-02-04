package io.mcpmesh.ai.handlers;

import io.mcpmesh.ai.handlers.LlmProviderHandler.OutputSchema;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.util.*;

@DisplayName("OutputSchema")
class OutputSchemaTest {

    // =========================================================================
    // fromSchema tests
    // =========================================================================

    @Nested
    @DisplayName("fromSchema")
    class FromSchema {

        @Test
        @DisplayName("creates OutputSchema with correct name and schema")
        void createsWithCorrectNameAndSchema() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "name", Map.of("type", "string")
                )
            );

            OutputSchema output = OutputSchema.fromSchema("TestSchema", schema);

            assertEquals("TestSchema", output.name());
            assertSame(schema, output.schema());
        }

        @Test
        @DisplayName("detects simple schema (< 5 fields, no nesting)")
        void detectsSimpleSchema() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "name", Map.of("type", "string"),
                    "age", Map.of("type", "integer"),
                    "active", Map.of("type", "boolean")
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Simple", schema);

            assertTrue(output.simple());
        }

        @Test
        @DisplayName("detects complex schema (5+ fields)")
        void detectsComplexSchemaByFieldCount() {
            Map<String, Object> properties = new LinkedHashMap<>();
            properties.put("field1", Map.of("type", "string"));
            properties.put("field2", Map.of("type", "string"));
            properties.put("field3", Map.of("type", "string"));
            properties.put("field4", Map.of("type", "string"));
            properties.put("field5", Map.of("type", "string"));

            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", properties
            );

            OutputSchema output = OutputSchema.fromSchema("Complex", schema);

            assertFalse(output.simple());
        }

        @Test
        @DisplayName("detects nested objects as complex")
        void detectsNestedObjectsAsComplex() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "address", Map.of(
                        "type", "object",
                        "properties", Map.of(
                            "street", Map.of("type", "string")
                        )
                    )
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Nested", schema);

            assertFalse(output.simple());
        }

        @Test
        @DisplayName("detects $ref references as complex")
        void detectsRefAsComplex() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "related", Map.of("$ref", "#/$defs/OtherModel")
                )
            );

            OutputSchema output = OutputSchema.fromSchema("WithRef", schema);

            assertFalse(output.simple());
        }

        @Test
        @DisplayName("detects arrays with object items as complex")
        void detectsArrayWithObjectItemsAsComplex() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "items", Map.of(
                        "type", "array",
                        "items", Map.of("type", "object", "properties", Map.of())
                    )
                )
            );

            OutputSchema output = OutputSchema.fromSchema("ArrayComplex", schema);

            assertFalse(output.simple());
        }

        @Test
        @DisplayName("empty properties map is simple")
        void emptyPropertiesIsSimple() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of()
            );

            OutputSchema output = OutputSchema.fromSchema("Empty", schema);

            assertTrue(output.simple());
        }

        @Test
        @DisplayName("no properties key at all is simple")
        void noPropertiesKeyIsSimple() {
            Map<String, Object> schema = Map.of("type", "object");

            OutputSchema output = OutputSchema.fromSchema("NoProps", schema);

            assertTrue(output.simple());
        }
    }

    // =========================================================================
    // sanitize tests
    // =========================================================================

    @Nested
    @DisplayName("sanitize")
    class Sanitize {

        @Test
        @DisplayName("removes unsupported validation keywords")
        @SuppressWarnings("unchecked")
        void removesUnsupportedKeywords() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", Map.of(
                "age", new LinkedHashMap<>(Map.of(
                    "type", "integer",
                    "minimum", 0,
                    "maximum", 150,
                    "exclusiveMinimum", 0,
                    "exclusiveMaximum", 200
                ))
            ));
            schema.put("minLength", 1);
            schema.put("maxLength", 100);
            schema.put("pattern", "^[a-z]+$");
            schema.put("multipleOf", 2);
            schema.put("minItems", 1);
            schema.put("maxItems", 10);

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> sanitized = output.sanitize();

            assertFalse(sanitized.containsKey("minLength"));
            assertFalse(sanitized.containsKey("maxLength"));
            assertFalse(sanitized.containsKey("pattern"));
            assertFalse(sanitized.containsKey("multipleOf"));
            assertFalse(sanitized.containsKey("minItems"));
            assertFalse(sanitized.containsKey("maxItems"));

            Map<String, Object> ageSchema = (Map<String, Object>)
                ((Map<String, Object>) sanitized.get("properties")).get("age");
            assertFalse(ageSchema.containsKey("minimum"));
            assertFalse(ageSchema.containsKey("maximum"));
            assertFalse(ageSchema.containsKey("exclusiveMinimum"));
            assertFalse(ageSchema.containsKey("exclusiveMaximum"));
            assertEquals("integer", ageSchema.get("type"));
        }

        @Test
        @DisplayName("preserves type, properties, required, description, $defs")
        void preservesStructuralKeywords() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("description", "A test schema");
            schema.put("required", List.of("name"));
            schema.put("properties", Map.of(
                "name", Map.of("type", "string", "description", "The name")
            ));
            schema.put("$defs", Map.of(
                "Sub", Map.of("type", "object")
            ));

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> sanitized = output.sanitize();

            assertEquals("object", sanitized.get("type"));
            assertEquals("A test schema", sanitized.get("description"));
            assertEquals(List.of("name"), sanitized.get("required"));
            assertNotNull(sanitized.get("properties"));
            assertNotNull(sanitized.get("$defs"));
        }

        @Test
        @DisplayName("recursively sanitizes nested object properties")
        @SuppressWarnings("unchecked")
        void recursivelySanitizesNestedProperties() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "address", Map.of(
                        "type", "object",
                        "properties", Map.of(
                            "zip", new LinkedHashMap<>(Map.of(
                                "type", "string",
                                "pattern", "^\\d{5}$",
                                "minLength", 5
                            ))
                        )
                    )
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> sanitized = output.sanitize();

            Map<String, Object> addressProps = (Map<String, Object>)
                ((Map<String, Object>)
                    ((Map<String, Object>) sanitized.get("properties")).get("address"))
                    .get("properties");
            Map<String, Object> zipSchema = (Map<String, Object>) addressProps.get("zip");

            assertFalse(zipSchema.containsKey("pattern"));
            assertFalse(zipSchema.containsKey("minLength"));
            assertEquals("string", zipSchema.get("type"));
        }

        @Test
        @DisplayName("recursively sanitizes array items")
        @SuppressWarnings("unchecked")
        void recursivelySanitizesArrayItems() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "tags", Map.of(
                        "type", "array",
                        "items", new LinkedHashMap<>(Map.of(
                            "type", "string",
                            "minLength", 1,
                            "maxLength", 50
                        ))
                    )
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> sanitized = output.sanitize();

            Map<String, Object> tagsSchema = (Map<String, Object>)
                ((Map<String, Object>) sanitized.get("properties")).get("tags");
            Map<String, Object> itemsSchema = (Map<String, Object>) tagsSchema.get("items");

            assertFalse(itemsSchema.containsKey("minLength"));
            assertFalse(itemsSchema.containsKey("maxLength"));
            assertEquals("string", itemsSchema.get("type"));
        }

        @Test
        @DisplayName("recursively sanitizes $defs")
        @SuppressWarnings("unchecked")
        void recursivelySanitizesDefs() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "$defs", Map.of(
                    "Score", new LinkedHashMap<>(Map.of(
                        "type", "integer",
                        "minimum", 0,
                        "maximum", 100
                    ))
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> sanitized = output.sanitize();

            Map<String, Object> scoreDef = (Map<String, Object>)
                ((Map<String, Object>) sanitized.get("$defs")).get("Score");

            assertFalse(scoreDef.containsKey("minimum"));
            assertFalse(scoreDef.containsKey("maximum"));
            assertEquals("integer", scoreDef.get("type"));
        }

        @Test
        @DisplayName("does not mutate the original schema map")
        void doesNotMutateOriginalSchema() {
            Map<String, Object> innerProp = new LinkedHashMap<>(Map.of(
                "type", "integer",
                "minimum", 0
            ));
            Map<String, Object> properties = new LinkedHashMap<>();
            properties.put("age", innerProp);

            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("properties", properties);
            schema.put("minLength", 1);

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            output.sanitize();

            assertTrue(schema.containsKey("minLength"), "Original schema should still have minLength");
            assertTrue(innerProp.containsKey("minimum"), "Original nested schema should still have minimum");
        }
    }

    // =========================================================================
    // makeStrict(addAllRequired=true) tests -- OpenAI-style
    // =========================================================================

    @Nested
    @DisplayName("makeStrict(addAllRequired=true)")
    class MakeStrictAllRequired {

        @Test
        @DisplayName("adds additionalProperties: false to root object")
        void addsAdditionalPropertiesFalse() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "name", Map.of("type", "string")
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(true);

            assertEquals(false, strict.get("additionalProperties"));
        }

        @Test
        @DisplayName("adds all properties to required array")
        @SuppressWarnings("unchecked")
        void addsAllPropertiesToRequired() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", new LinkedHashMap<>(Map.of(
                    "name", Map.of("type", "string"),
                    "age", Map.of("type", "integer"),
                    "active", Map.of("type", "boolean")
                ))
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(true);

            List<String> required = (List<String>) strict.get("required");
            assertNotNull(required);
            assertTrue(required.contains("name"));
            assertTrue(required.contains("age"));
            assertTrue(required.contains("active"));
            assertEquals(3, required.size());
        }

        @Test
        @DisplayName("recursively processes nested objects")
        @SuppressWarnings("unchecked")
        void recursivelyProcessesNestedObjects() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "address", Map.of(
                        "type", "object",
                        "properties", Map.of(
                            "street", Map.of("type", "string"),
                            "city", Map.of("type", "string")
                        )
                    )
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(true);

            Map<String, Object> addressSchema = (Map<String, Object>)
                ((Map<String, Object>) strict.get("properties")).get("address");

            assertEquals(false, addressSchema.get("additionalProperties"));
            List<String> addressRequired = (List<String>) addressSchema.get("required");
            assertNotNull(addressRequired);
            assertTrue(addressRequired.contains("street"));
            assertTrue(addressRequired.contains("city"));
        }

        @Test
        @DisplayName("recursively processes $defs")
        @SuppressWarnings("unchecked")
        void recursivelyProcessesDefs() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of("name", Map.of("type", "string")),
                "$defs", Map.of(
                    "Address", Map.of(
                        "type", "object",
                        "properties", Map.of(
                            "street", Map.of("type", "string")
                        )
                    )
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(true);

            Map<String, Object> addressDef = (Map<String, Object>)
                ((Map<String, Object>) strict.get("$defs")).get("Address");

            assertEquals(false, addressDef.get("additionalProperties"));
            List<String> defRequired = (List<String>) addressDef.get("required");
            assertNotNull(defRequired);
            assertTrue(defRequired.contains("street"));
        }

        @Test
        @DisplayName("recursively processes array items that are objects")
        @SuppressWarnings("unchecked")
        void recursivelyProcessesArrayItems() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "people", Map.of(
                        "type", "array",
                        "items", Map.of(
                            "type", "object",
                            "properties", Map.of(
                                "name", Map.of("type", "string"),
                                "age", Map.of("type", "integer")
                            )
                        )
                    )
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(true);

            Map<String, Object> peopleSchema = (Map<String, Object>)
                ((Map<String, Object>) strict.get("properties")).get("people");
            Map<String, Object> itemsSchema = (Map<String, Object>) peopleSchema.get("items");

            assertEquals(false, itemsSchema.get("additionalProperties"));
            List<String> itemRequired = (List<String>) itemsSchema.get("required");
            assertNotNull(itemRequired);
            assertTrue(itemRequired.contains("name"));
            assertTrue(itemRequired.contains("age"));
        }

        @Test
        @DisplayName("also sanitizes (removes validation keywords)")
        void alsoSanitizes() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("minimum", 0);
            schema.put("properties", Map.of(
                "count", new LinkedHashMap<>(Map.of(
                    "type", "integer",
                    "maximum", 999
                ))
            ));

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(true);

            assertFalse(strict.containsKey("minimum"));

            @SuppressWarnings("unchecked")
            Map<String, Object> countSchema = (Map<String, Object>)
                ((Map<String, Object>) strict.get("properties")).get("count");
            assertFalse(countSchema.containsKey("maximum"));
        }

        @Test
        @DisplayName("infers type object when properties exists but type is missing")
        void infersTypeObjectWhenMissing() {
            Map<String, Object> schema = Map.of(
                "properties", Map.of(
                    "name", Map.of("type", "string")
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(true);

            assertEquals("object", strict.get("type"));
            assertEquals(false, strict.get("additionalProperties"));
        }
    }

    // =========================================================================
    // makeStrict(addAllRequired=false) tests -- Claude-style
    // =========================================================================

    @Nested
    @DisplayName("makeStrict(addAllRequired=false)")
    class MakeStrictNoRequired {

        @Test
        @DisplayName("adds additionalProperties: false to root object")
        void addsAdditionalPropertiesFalse() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "name", Map.of("type", "string")
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(false);

            assertEquals(false, strict.get("additionalProperties"));
        }

        @Test
        @DisplayName("does not add all properties to required")
        void doesNotAddAllRequired() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "name", Map.of("type", "string"),
                    "age", Map.of("type", "integer")
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(false);

            assertNull(strict.get("required"));
        }

        @Test
        @DisplayName("preserves existing required array without expanding it")
        @SuppressWarnings("unchecked")
        void preservesExistingRequired() {
            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("type", "object");
            schema.put("required", List.of("name"));
            schema.put("properties", Map.of(
                "name", Map.of("type", "string"),
                "age", Map.of("type", "integer")
            ));

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(false);

            List<String> required = (List<String>) strict.get("required");
            assertEquals(List.of("name"), required);
        }

        @Test
        @DisplayName("recursively processes nested objects")
        @SuppressWarnings("unchecked")
        void recursivelyProcessesNestedObjects() {
            Map<String, Object> schema = Map.of(
                "type", "object",
                "properties", Map.of(
                    "address", Map.of(
                        "type", "object",
                        "properties", Map.of(
                            "city", Map.of("type", "string")
                        )
                    )
                )
            );

            OutputSchema output = OutputSchema.fromSchema("Test", schema);
            Map<String, Object> strict = output.makeStrict(false);

            Map<String, Object> addressSchema = (Map<String, Object>)
                ((Map<String, Object>) strict.get("properties")).get("address");

            assertEquals(false, addressSchema.get("additionalProperties"));
            assertNull(addressSchema.get("required"));
        }
    }
}
