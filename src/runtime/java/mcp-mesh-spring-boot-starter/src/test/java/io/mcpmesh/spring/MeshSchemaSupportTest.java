package io.mcpmesh.spring;

import io.mcpmesh.core.MeshCoreBridge;
import jakarta.validation.constraints.NotNull;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Tests for {@link MeshSchemaSupport}.
 *
 * <p>Verifies cross-runtime schema hash equality: a Java record with
 * {@code @NotNull} fields must normalize to the same canonical hash as
 * Pydantic ({@code name: str}) and Zod ({@code z.string()}) shapes.
 *
 * <p>Tests that depend on the Rust core native library are guarded with
 * {@link Assumptions#assumeTrue(boolean, String)} so they skip cleanly in
 * environments where the native lib is not available.
 */
@DisplayName("MeshSchemaSupport — JakartaValidation + cross-runtime hash")
class MeshSchemaSupportTest {

    /** Record exercising @NotNull on String fields plus a primitive (always required). */
    public record Employee(
        @NotNull String name,
        @NotNull String dept,
        double salary
    ) {}

    @Test
    @DisplayName("@NotNull String fields drop the null branch in raw schema")
    void notNullStringHasNoNullBranch() {
        String rawJson = MeshSchemaSupport.generateRawSchemaJson(Employee.class);
        assertNotNull(rawJson, "Raw schema should not be null");

        // Sanity: @NotNull-annotated fields should NOT have "null" anywhere in their
        // type. Without JakartaValidationModule, victools emits ["string","null"] for
        // each String field due to NULLABLE_FIELDS_BY_DEFAULT.
        // The Employee schema has only @NotNull String + double fields, so the entire
        // serialized schema should contain no "null" type token.
        assertTrue(
            !rawJson.contains("\"null\""),
            "Raw schema should not contain a 'null' type token for @NotNull fields. Got: " + rawJson
        );
    }

    /** Self-referencing record exercising the root-self-ref rewrite (issue #547). */
    public record TreeNode(@NotNull String value, @NotNull List<TreeNode> children) {}

    @Test
    @DisplayName("Self-referencing record wraps root in $defs (no bare '#' ref)")
    void recursiveTypeProducesNamedDefsEntry() throws Exception {
        String rawJson = MeshSchemaSupport.generateRawSchemaJson(TreeNode.class);
        assertNotNull(rawJson, "Raw schema should not be null");

        ObjectMapper mapper = io.mcpmesh.core.MeshObjectMappers.create();
        JsonNode root = mapper.readTree(rawJson);

        // Root must be a $ref into its own $defs entry — never the bare "#".
        assertTrue(root.has("$ref"),
            "Root should be wrapped as $ref. Got: " + rawJson);
        assertEquals("#/$defs/TreeNode", root.path("$ref").asString(""),
            "Root ref should point to named def, got: " + rawJson);

        // The bare root self-ref "#" must be gone everywhere.
        assertFalse(rawJson.contains("\"$ref\":\"#\""),
            "Schema should contain no bare root self-ref ('#'). Got: " + rawJson);

        // The named def exists and contains the recursive reference.
        JsonNode defs = root.get("$defs");
        assertNotNull(defs, "Expected $defs object. Got: " + rawJson);
        JsonNode treeDef = defs.get("TreeNode");
        assertNotNull(treeDef, "Expected $defs.TreeNode. Got: " + rawJson);
        assertEquals("#/$defs/TreeNode",
            treeDef.path("properties").path("children").path("items").path("$ref").asString(""),
            "Recursive child ref should point to named def. Got: " + rawJson);
    }

    @Test
    @DisplayName("Recursive TreeNode normalizes without 'non-local $ref kept' WARN")
    void recursiveTypeNormalizesCleanly() {
        String rawJson = MeshSchemaSupport.generateRawSchemaJson(TreeNode.class);
        assertNotNull(rawJson, "Raw schema should not be null");

        MeshCoreBridge.NormalizeResult result;
        try {
            result = MeshCoreBridge.normalizeSchema(rawJson, "java");
        } catch (UnsatisfiedLinkError e) {
            Assumptions.assumeTrue(false, "Rust core native library not available: " + e.getMessage());
            return;
        }

        // Normalizer should NOT emit the "[non-local $ref kept: #]" warning.
        for (String w : result.warnings()) {
            assertFalse(w.contains("non-local $ref kept"),
                "Unexpected normalizer WARN: " + w
                    + "\nRaw JSON: " + rawJson
                    + "\nCanonical: " + result.canonicalJson());
            assertFalse(w.contains("$ref kept: #") && !w.contains("/"),
                "Unexpected bare root-ref WARN: " + w
                    + "\nRaw JSON: " + rawJson);
        }

        // Canonical $defs should carry the structural-hash rename.
        String canonical = result.canonicalJson();
        assertNotNull(canonical, "Canonical JSON should not be null");
        assertTrue(canonical.contains("Recursive_"),
            "Canonical should rename cyclic def to Recursive_<hash>. Got: " + canonical);
    }

    @Test
    @DisplayName("@NotNull Employee record produces canonical hash matching Pydantic/Zod")
    void notNullFieldsProduceCrossRuntimeMatchingHash() {
        String rawJson = MeshSchemaSupport.generateRawSchemaJson(Employee.class);
        assertNotNull(rawJson, "Raw schema should not be null");

        MeshCoreBridge.NormalizeResult result;
        try {
            result = MeshCoreBridge.normalizeSchema(rawJson, "java");
        } catch (UnsatisfiedLinkError e) {
            Assumptions.assumeTrue(false, "Rust core native library not available: " + e.getMessage());
            return;
        }

        assertEquals("OK", result.verdict(),
            "Normalize verdict should be OK. Warnings: " + result.warnings()
                + "\nRaw JSON: " + rawJson);
        assertEquals(
            "sha256:48882e31915113ed70ee620b2245bfcf856e4e146e2eb6e37700809d7338e732",
            result.hash(),
            "Java @NotNull Employee record must produce the canonical hash that "
                + "matches Pydantic 'name: str' and Zod z.string() shapes.\n"
                + "Raw JSON: " + rawJson
                + "\nCanonical: " + result.canonicalJson()
        );
    }

    // =========================================================================
    // inlineRefs — issue #1112 finding 5 (Approach B)
    // =========================================================================

    /** Recursively assert no $ref / $defs / definitions key appears anywhere. */
    @SuppressWarnings("unchecked")
    private static void assertNoRefsOrDefs(Object node) {
        if (node instanceof Map<?, ?> m) {
            for (Map.Entry<String, Object> e : ((Map<String, Object>) m).entrySet()) {
                assertFalse("$ref".equals(e.getKey()), "Unexpected $ref at: " + m);
                assertFalse("$defs".equals(e.getKey()), "Unexpected $defs at: " + m);
                assertFalse("definitions".equals(e.getKey()), "Unexpected definitions at: " + m);
                assertNoRefsOrDefs(e.getValue());
            }
        } else if (node instanceof List<?> l) {
            for (Object item : l) {
                assertNoRefsOrDefs(item);
            }
        }
    }

    private static Map<String, Object> map(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((String) kv[i], kv[i + 1]);
        }
        return m;
    }

    private static List<Object> list(Object... items) {
        List<Object> l = new ArrayList<>();
        for (Object o : items) {
            l.add(o);
        }
        return l;
    }

    @Test
    @DisplayName("inlineRefs(null) returns null")
    void inlineRefsNullSafe() {
        assertNull(MeshSchemaSupport.inlineRefs(null));
    }

    @Test
    @DisplayName("flat schema with no refs is unchanged except $defs dropped")
    @SuppressWarnings("unchecked")
    void inlineRefsFlatSchema() {
        Map<String, Object> schema = map(
            "type", "object",
            "properties", map(
                "name", map("type", "string"),
                "age", map("type", "integer")
            ),
            "required", list("name", "age"),
            "$defs", map("Unused", map("type", "string"))
        );
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);

        assertEquals("object", out.get("type"));
        assertFalse(out.containsKey("$defs"), "Root $defs should be dropped");
        Map<String, Object> props = (Map<String, Object>) out.get("properties");
        assertEquals("string", ((Map<String, Object>) props.get("name")).get("type"));
        assertEquals("integer", ((Map<String, Object>) props.get("age")).get("type"));
        assertEquals(list("name", "age"), out.get("required"));
    }

    @Test
    @DisplayName("single nested object $ref is inlined; no $ref/$defs remain")
    @SuppressWarnings("unchecked")
    void inlineRefsSingleNested() {
        Map<String, Object> schema = map(
            "type", "object",
            "properties", map(
                "address", map("$ref", "#/$defs/Address")
            ),
            "$defs", map(
                "Address", map(
                    "type", "object",
                    "properties", map(
                        "city", map("type", "string"),
                        "zip", map("type", "string")
                    )
                )
            )
        );
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);
        assertNoRefsOrDefs(out);

        Map<String, Object> address =
            (Map<String, Object>) ((Map<String, Object>) out.get("properties")).get("address");
        assertEquals("object", address.get("type"));
        Map<String, Object> addrProps = (Map<String, Object>) address.get("properties");
        assertEquals("string", ((Map<String, Object>) addrProps.get("city")).get("type"));
        assertEquals("string", ((Map<String, Object>) addrProps.get("zip")).get("type"));
    }

    @Test
    @DisplayName("List<Record> -> items.{$ref} is inlined")
    @SuppressWarnings("unchecked")
    void inlineRefsArrayItemsRef() {
        Map<String, Object> schema = map(
            "type", "object",
            "properties", map(
                "lines", map(
                    "type", "array",
                    "items", map("$ref", "#/$defs/LineItem")
                )
            ),
            "$defs", map(
                "LineItem", map(
                    "type", "object",
                    "properties", map("sku", map("type", "string"))
                )
            )
        );
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);
        assertNoRefsOrDefs(out);

        Map<String, Object> lines =
            (Map<String, Object>) ((Map<String, Object>) out.get("properties")).get("lines");
        Map<String, Object> items = (Map<String, Object>) lines.get("items");
        assertEquals("object", items.get("type"));
        Map<String, Object> itemProps = (Map<String, Object>) items.get("properties");
        assertEquals("string", ((Map<String, Object>) itemProps.get("sku")).get("type"));
    }

    @Test
    @DisplayName("same def referenced twice -> independent deep copies")
    @SuppressWarnings("unchecked")
    void inlineRefsDeepCopyIndependence() {
        Map<String, Object> schema = map(
            "type", "object",
            "properties", map(
                "from", map("$ref", "#/$defs/Point"),
                "to", map("$ref", "#/$defs/Point")
            ),
            "$defs", map(
                "Point", map(
                    "type", "object",
                    "properties", map("x", map("type", "integer"))
                )
            )
        );
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);
        assertNoRefsOrDefs(out);

        Map<String, Object> props = (Map<String, Object>) out.get("properties");
        Map<String, Object> from = (Map<String, Object>) props.get("from");
        Map<String, Object> to = (Map<String, Object>) props.get("to");

        // Mutate one inlined copy; the other must be untouched (deep copy).
        ((Map<String, Object>) from.get("properties")).put("y", map("type", "integer"));
        assertTrue(((Map<String, Object>) from.get("properties")).containsKey("y"));
        assertFalse(((Map<String, Object>) to.get("properties")).containsKey("y"),
            "Second inline site must be an independent deep copy");
    }

    @Test
    @DisplayName("nullable anyOf:[{$ref},{type:null}] inlines the $ref inside anyOf")
    @SuppressWarnings("unchecked")
    void inlineRefsAnyOf() {
        Map<String, Object> schema = map(
            "type", "object",
            "properties", map(
                "maybe", map("anyOf", list(
                    map("$ref", "#/$defs/Inner"),
                    map("type", "null")
                ))
            ),
            "$defs", map(
                "Inner", map(
                    "type", "object",
                    "properties", map("v", map("type", "string"))
                )
            )
        );
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);
        assertNoRefsOrDefs(out);

        Map<String, Object> maybe =
            (Map<String, Object>) ((Map<String, Object>) out.get("properties")).get("maybe");
        List<Object> anyOf = (List<Object>) maybe.get("anyOf");
        Map<String, Object> first = (Map<String, Object>) anyOf.get(0);
        assertEquals("object", first.get("type"));
        assertTrue(((Map<String, Object>) first.get("properties")).containsKey("v"));
        assertEquals("null", ((Map<String, Object>) anyOf.get(1)).get("type"));
    }

    @Test
    @DisplayName("$ref with sibling description -> inlined def + description overlaid")
    @SuppressWarnings("unchecked")
    void inlineRefsSiblingKeysOverlaid() {
        Map<String, Object> schema = map(
            "type", "object",
            "properties", map(
                "addr", map(
                    "$ref", "#/$defs/Address",
                    "description", "home address"
                )
            ),
            "$defs", map(
                "Address", map(
                    "type", "object",
                    "properties", map("city", map("type", "string"))
                )
            )
        );
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);
        assertNoRefsOrDefs(out);

        Map<String, Object> addr =
            (Map<String, Object>) ((Map<String, Object>) out.get("properties")).get("addr");
        assertEquals("object", addr.get("type"));
        assertEquals("home address", addr.get("description"));
        assertTrue(((Map<String, Object>) addr.get("properties")).containsKey("city"));
    }

    @Test
    @DisplayName("recursive type terminates with bounded {type:object} placeholder")
    @SuppressWarnings("unchecked")
    void inlineRefsCycleGuard() {
        // Node -> { value: string, child: Node }
        Map<String, Object> schema = map(
            "$ref", "#/$defs/Node",
            "$defs", map(
                "Node", map(
                    "type", "object",
                    "properties", map(
                        "value", map("type", "string"),
                        "child", map("$ref", "#/$defs/Node")
                    )
                )
            )
        );
        // Must not StackOverflow.
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);
        assertNoRefsOrDefs(out);

        assertEquals("object", out.get("type"));
        Map<String, Object> props = (Map<String, Object>) out.get("properties");
        assertEquals("string", ((Map<String, Object>) props.get("value")).get("type"));
        Map<String, Object> child = (Map<String, Object>) props.get("child");
        // The recursive ref collapses to a bounded placeholder.
        assertEquals("object", child.get("type"));
        assertFalse(child.containsKey("properties"),
            "Cycle placeholder should be bounded (no further expansion)");
    }

    @Test
    @DisplayName("enum field preserved through inlining")
    @SuppressWarnings("unchecked")
    void inlineRefsPreservesEnum() {
        Map<String, Object> schema = map(
            "type", "object",
            "properties", map(
                "status", map("$ref", "#/$defs/Status")
            ),
            "$defs", map(
                "Status", map(
                    "type", "string",
                    "enum", list("OPEN", "CLOSED")
                )
            )
        );
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);
        assertNoRefsOrDefs(out);

        Map<String, Object> status =
            (Map<String, Object>) ((Map<String, Object>) out.get("properties")).get("status");
        assertEquals("string", status.get("type"));
        assertEquals(list("OPEN", "CLOSED"), status.get("enum"));
    }

    @Test
    @DisplayName("resolves #/definitions/<Name> pointers too")
    @SuppressWarnings("unchecked")
    void inlineRefsDefinitionsPointer() {
        Map<String, Object> schema = map(
            "type", "object",
            "properties", map(
                "addr", map("$ref", "#/definitions/Address")
            ),
            "definitions", map(
                "Address", map(
                    "type", "object",
                    "properties", map("city", map("type", "string"))
                )
            )
        );
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);
        assertNoRefsOrDefs(out);
        assertFalse(out.containsKey("definitions"), "Root definitions should be dropped");

        Map<String, Object> addr =
            (Map<String, Object>) ((Map<String, Object>) out.get("properties")).get("addr");
        assertTrue(((Map<String, Object>) addr.get("properties")).containsKey("city"));
    }

    // End-to-end: real victools generator output through inlineRefs.
    public record Address(@NotNull String street, @NotNull String city) {}
    public record Company(@NotNull String name, @NotNull Address headquarters) {}
    public record OrgChart(@NotNull Company company, @NotNull List<Address> sites) {}

    @Test
    @DisplayName("E2E: real generator output through inlineRefs has no $ref/$defs, nested props present")
    @SuppressWarnings("unchecked")
    void inlineRefsEndToEndWithRealGenerator() {
        JsonNode node = MeshSchemaSupport.generator().generateSchema(OrgChart.class);
        ObjectMapper mapper = io.mcpmesh.core.MeshObjectMappers.create();
        Map<String, Object> schema =
            mapper.convertValue(node, new TypeReference<Map<String, Object>>() {});

        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);
        assertNoRefsOrDefs(out);

        // Deeply-nested field: OrgChart.company.headquarters.{street,city}
        Map<String, Object> rootProps = (Map<String, Object>) out.get("properties");
        assertNotNull(rootProps, "Root properties present. Got: " + out);
        Map<String, Object> company = (Map<String, Object>) rootProps.get("company");
        Map<String, Object> companyProps = (Map<String, Object>) company.get("properties");
        Map<String, Object> hq = (Map<String, Object>) companyProps.get("headquarters");
        Map<String, Object> hqProps = (Map<String, Object>) hq.get("properties");
        assertTrue(hqProps.containsKey("street"),
            "Nested Address.street should be inlined. Got: " + out);
        assertTrue(hqProps.containsKey("city"),
            "Nested Address.city should be inlined. Got: " + out);

        // Array of records: sites.items.properties present too.
        Map<String, Object> sites = (Map<String, Object>) rootProps.get("sites");
        Map<String, Object> siteItems = (Map<String, Object>) sites.get("items");
        assertTrue(((Map<String, Object>) siteItems.get("properties")).containsKey("street"),
            "Array item Address.street should be inlined. Got: " + out);
    }

    @Test
    @DisplayName("E2E: self-referencing root model (buildJsonSchema path) terminates, no $ref remains")
    @SuppressWarnings("unchecked")
    void inlineRefsSelfReferencingRootModel() {
        // Mirror MeshLlmAgentProxy.buildJsonSchema exactly: generateSchema ->
        // rewriteRootSelfRefs -> convertValue -> inlineRefs. victools emits the
        // self-referencing root as a bare "#" ref; without the rewrite that "#"
        // would survive inlineRefs verbatim (not self-contained).
        JsonNode node = MeshSchemaSupport.generator().generateSchema(TreeNode.class);
        node = MeshSchemaSupport.rewriteRootSelfRefs(node, TreeNode.class);
        ObjectMapper mapper = io.mcpmesh.core.MeshObjectMappers.create();
        Map<String, Object> schema =
            mapper.convertValue(node, new TypeReference<Map<String, Object>>() {});

        // (a) Must terminate (no StackOverflow on the recursive root).
        Map<String, Object> out = MeshSchemaSupport.inlineRefs(schema);

        // (b) NO $ref of ANY form remains (including a bare "#").
        assertNoRefsOrDefs(out);

        // Top-level properties present (root content was inlined, not left as a ref).
        assertEquals("object", out.get("type"));
        Map<String, Object> props = (Map<String, Object>) out.get("properties");
        assertNotNull(props, "Root properties present. Got: " + out);
        assertTrue(props.containsKey("value"), "value field present. Got: " + out);
        assertTrue(props.containsKey("children"), "children field present. Got: " + out);

        // (c) The recursion is cut by a bounded {"type":"object"} placeholder where
        // children -> items would otherwise recurse into TreeNode again.
        Map<String, Object> children = (Map<String, Object>) props.get("children");
        assertEquals("array", children.get("type"));
        Map<String, Object> items = (Map<String, Object>) children.get("items");
        assertEquals("object", items.get("type"),
            "Recursive child should collapse to bounded placeholder. Got: " + out);
        assertFalse(items.containsKey("properties"),
            "Cycle placeholder should be bounded (no further expansion). Got: " + out);
    }
}
