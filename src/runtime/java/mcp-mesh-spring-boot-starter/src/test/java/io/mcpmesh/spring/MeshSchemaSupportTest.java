package io.mcpmesh.spring;

import io.mcpmesh.core.MeshCoreBridge;
import jakarta.validation.constraints.NotNull;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
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
}
