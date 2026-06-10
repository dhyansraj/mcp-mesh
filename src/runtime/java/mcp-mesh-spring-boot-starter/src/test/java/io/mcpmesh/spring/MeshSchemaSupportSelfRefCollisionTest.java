package io.mcpmesh.spring;

import io.mcpmesh.core.MeshObjectMappers;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1164 LOW: {@code rewriteRootSelfRefs} keyed the new root def by the
 * type's simple name, shadowing a pre-existing same-simple-name {@code $defs}
 * entry from another package — whose internal refs then silently resolved to
 * the WRONG body. The collision must be disambiguated, the root refs rewritten
 * to the disambiguated name, and the pre-existing def preserved untouched.
 */
@DisplayName("MeshSchemaSupport.rewriteRootSelfRefs — $defs name collision (issue #1164 LOW)")
class MeshSchemaSupportSelfRefCollisionTest {

    /** Simple name intentionally collides with the crafted $defs entry below. */
    public record TreeNode(String value) {}

    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    @Test
    @DisplayName("pre-existing same-simple-name def is preserved; root def disambiguated")
    void collisionIsDisambiguated() throws Exception {
        // Simulates a victools output where the root type self-references ("#")
        // AND a nested type from another package already produced a $defs entry
        // named "TreeNode".
        JsonNode root = MAPPER.readTree("""
            {
              "type": "object",
              "properties": {
                "self": { "$ref": "#" },
                "other": { "$ref": "#/$defs/TreeNode" }
              },
              "$defs": {
                "TreeNode": { "type": "string", "description": "the OTHER package's TreeNode" }
              }
            }
            """);

        JsonNode out = MeshSchemaSupport.rewriteRootSelfRefs(root, TreeNode.class);

        // Root must point at the DISAMBIGUATED def, not shadow the existing one.
        assertEquals("#/$defs/TreeNode_2", out.path("$ref").asString(""),
            "root ref must use the disambiguated name. Got: " + out);

        JsonNode defs = out.get("$defs");
        assertNotNull(defs);

        // Pre-existing def preserved byte-for-byte.
        JsonNode existing = defs.get("TreeNode");
        assertNotNull(existing, "pre-existing TreeNode def must survive. Got: " + defs);
        assertEquals("string", existing.path("type").asString(""),
            "pre-existing def body must be untouched. Got: " + existing);

        // New def carries the root body with `#` refs rewritten to the new name.
        JsonNode renamed = defs.get("TreeNode_2");
        assertNotNull(renamed, "disambiguated def must exist. Got: " + defs);
        assertEquals("#/$defs/TreeNode_2",
            renamed.path("properties").path("self").path("$ref").asString(""),
            "self refs must point at the disambiguated def. Got: " + renamed);
        // Refs into the OLD def keep pointing at the preserved entry.
        assertEquals("#/$defs/TreeNode",
            renamed.path("properties").path("other").path("$ref").asString(""),
            "refs to the pre-existing def must remain intact. Got: " + renamed);
    }

    @Test
    @DisplayName("no collision → behavior unchanged (named after the simple name)")
    void noCollisionUsesSimpleName() throws Exception {
        JsonNode root = MAPPER.readTree("""
            {
              "type": "object",
              "properties": { "self": { "$ref": "#" } }
            }
            """);
        JsonNode out = MeshSchemaSupport.rewriteRootSelfRefs(root, TreeNode.class);
        assertEquals("#/$defs/TreeNode", out.path("$ref").asString(""));
        assertNotNull(out.get("$defs").get("TreeNode"));
    }
}
