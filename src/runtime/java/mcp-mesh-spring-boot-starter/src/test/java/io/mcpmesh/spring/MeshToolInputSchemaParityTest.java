package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.core.AgentSpec;
import jakarta.validation.constraints.NotNull;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1164 MED-2: the registry-advertised input schema must be IDENTICAL to
 * the MCP-served schema.
 *
 * <p>Previously {@link MeshToolRegistry} hand-rolled {@code {"type": ...}} per
 * parameter — a POJO/record param became a bare {@code {"type":"object"}} with
 * no properties and {@code List<Foo>} a bare {@code {"type":"array"}} with no
 * items — while {@link MeshToolWrapper} served the rich victools schema.
 * Everything heartbeat-derived (input_schema_canonical / input_schema_hash for
 * #547 cross-runtime matching, llm_tools definitions delivered to consuming
 * LLM agents) used the impoverished shape. Both sites now call
 * {@link MeshSchemaSupport#buildToolInputSchema}.
 */
@DisplayName("Tool input schema parity — wrapper vs heartbeat (issue #1164 MED-2)")
class MeshToolInputSchemaParityTest {

    public record Order(@NotNull String sku, @NotNull Integer qty) {}

    public static class OrderAgent {
        @MeshTool(capability = "process_order", description = "Process an order")
        public String process(
                @Param(value = "order", description = "the order") Order order,
                @Param("tags") List<String> tags,
                @Param("note") String note) {
            return "ok";
        }
    }

    private static Method method(Class<?> cls, String name) {
        for (Method m : cls.getDeclaredMethods()) {
            if (m.getName().equals(name)) {
                return m;
            }
        }
        throw new AssertionError("no method " + name + " on " + cls);
    }

    /** Resolve a property schema, following a root-level {@code #/$defs/...} ref if present. */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> resolveProperty(Map<String, Object> schema, String propName) {
        Map<String, Object> props = (Map<String, Object>) schema.get("properties");
        assertNotNull(props, "schema must have properties. Got: " + schema);
        Map<String, Object> prop = (Map<String, Object>) props.get(propName);
        assertNotNull(prop, "property '" + propName + "' missing. Got: " + props.keySet());
        Object ref = prop.get("$ref");
        if (ref instanceof String s && s.startsWith("#/$defs/")) {
            Map<String, Object> defs = (Map<String, Object>) schema.get("$defs");
            assertNotNull(defs, "$ref present but no root $defs. Got: " + schema);
            Map<String, Object> resolved = (Map<String, Object>) defs.get(s.substring("#/$defs/".length()));
            assertNotNull(resolved, "dangling ref " + s + ". $defs keys: " + defs.keySet());
            return resolved;
        }
        return prop;
    }

    @Test
    @DisplayName("wrapper-served schema and heartbeat metadata schema are the same generator output")
    void wrapperAndHeartbeatSchemasAreIdentical() {
        OrderAgent bean = new OrderAgent();
        Method m = method(OrderAgent.class, "process");

        MeshToolWrapper wrapper = new MeshToolWrapper(
            "OrderAgent.process", "process_order", "Process an order",
            bean, m, List.of(), JsonMapper.builder().build());

        MeshToolRegistry registry = new MeshToolRegistry();
        registry.registerTool(bean, m, m.getAnnotation(MeshTool.class));

        assertEquals(wrapper.getInputSchema(), registry.getTool("process_order").inputSchema(),
            "heartbeat metadata schema must be byte-for-byte the wrapper-served schema");
    }

    @Test
    @DisplayName("structured param (record) advertises nested properties + required, not bare {type:object}")
    @SuppressWarnings("unchecked")
    void structuredParamSchemaIsRich() {
        MeshToolRegistry registry = new MeshToolRegistry();
        Method m = method(OrderAgent.class, "process");
        registry.registerTool(new OrderAgent(), m, m.getAnnotation(MeshTool.class));

        Map<String, Object> schema = registry.getTool("process_order").inputSchema();

        Map<String, Object> order = resolveProperty(schema, "order");
        Map<String, Object> orderProps = (Map<String, Object>) order.get("properties");
        assertNotNull(orderProps,
            "record param must carry nested properties — bare {type:object} is the bug. Got: " + order);
        assertTrue(orderProps.containsKey("sku"), "Order.sku missing. Got: " + orderProps.keySet());
        assertTrue(orderProps.containsKey("qty"), "Order.qty missing. Got: " + orderProps.keySet());
        List<String> orderRequired = (List<String>) order.get("required");
        assertNotNull(orderRequired, "record fields must be marked required. Got: " + order);
        assertTrue(orderRequired.contains("sku") && orderRequired.contains("qty"),
            "sku+qty required. Got: " + orderRequired);

        Map<String, Object> tags = resolveProperty(schema, "tags");
        assertEquals("array", tags.get("type"));
        assertNotNull(tags.get("items"),
            "List<String> param must carry items — bare {type:array} is the bug. Got: " + tags);

        // Top-level required: all three @Param(required=true by default)
        List<String> required = (List<String>) schema.get("required");
        assertNotNull(required);
        assertTrue(required.containsAll(List.of("order", "tags", "note")),
            "all params required. Got: " + required);

        // @Param description survives the rich generator path.
        Map<String, Object> props = (Map<String, Object>) schema.get("properties");
        Map<String, Object> orderProp = (Map<String, Object>) props.get("order");
        // description sits on the property node (possibly alongside a $ref)
        assertEquals("the order", orderProp.get("description"),
            "@Param description must be preserved. Got: " + orderProp);
    }

    @Test
    @DisplayName("heartbeat ToolSpec carries the rich schema through canonicalization")
    void heartbeatToolSpecCarriesRichCanonicalSchema() {
        MeshToolRegistry registry = new MeshToolRegistry();
        Method m = method(OrderAgent.class, "process");
        registry.registerTool(new OrderAgent(), m, m.getAnnotation(MeshTool.class));

        List<AgentSpec.ToolSpec> specs;
        try {
            specs = registry.getToolSpecs();
        } catch (UnsatisfiedLinkError e) {
            org.junit.jupiter.api.Assumptions.assumeTrue(false,
                "Rust core native library not available: " + e.getMessage());
            return;
        }
        AgentSpec.ToolSpec spec = specs.get(0);

        assertTrue(spec.getInputSchema().contains("\"sku\""),
            "advertised input_schema must contain the nested record field. Got: " + spec.getInputSchema());
        assertNotNull(spec.getInputSchemaCanonical(),
            "canonicalization must handle the richer schema ($defs, required) without choking");
        assertTrue(spec.getInputSchemaCanonical().contains("sku"),
            "canonical schema must retain nested fields. Got: " + spec.getInputSchemaCanonical());
        assertNotNull(spec.getInputSchemaHash(), "input_schema_hash must be present");
        assertTrue(spec.getInputSchemaHash().startsWith("sha256:"),
            "hash format. Got: " + spec.getInputSchemaHash());
    }

    // ── $defs hoisting + collision disambiguation ─────────────────────────

    public static class PkgA {
        public record Item(@NotNull String sku) {}
        public record Wrap(@NotNull Item item) {}
    }

    public static class PkgB {
        public record Item(@NotNull Integer qty) {}
        public record Wrap(@NotNull Item item) {}
    }

    public static class CollisionAgent {
        @MeshTool(capability = "collide", description = "two same-simple-name defs")
        public String collide(@Param("a") PkgA.Wrap a, @Param("b") PkgB.Wrap b) {
            return "ok";
        }
    }

    @Test
    @DisplayName("same-simple-name $defs from different params are disambiguated, refs rewritten")
    @SuppressWarnings("unchecked")
    void defsNameCollisionAcrossParamsIsDisambiguated() {
        Method m = method(CollisionAgent.class, "collide");
        Map<String, Object> schema = MeshSchemaSupport.buildToolInputSchema(m);

        Map<String, Object> defs = (Map<String, Object>) schema.get("$defs");
        assertNotNull(defs, "param $defs must be hoisted to the root schema. Got: " + schema);
        assertTrue(defs.containsKey("Item"), "first Item def kept. Got: " + defs.keySet());
        assertTrue(defs.containsKey("Item_2"),
            "structurally different same-name def must be disambiguated. Got: " + defs.keySet());

        Map<String, Object> itemA = (Map<String, Object>) defs.get("Item");
        Map<String, Object> itemB = (Map<String, Object>) defs.get("Item_2");
        assertTrue(((Map<String, Object>) itemA.get("properties")).containsKey("sku"),
            "Item must be PkgA's body. Got: " + itemA);
        assertTrue(((Map<String, Object>) itemB.get("properties")).containsKey("qty"),
            "Item_2 must be PkgB's body. Got: " + itemB);

        // The second param's subtree must point at the disambiguated def.
        String schemaJson = schema.toString();
        assertTrue(schemaJson.contains("#/$defs/Item_2"),
            "refs in the renamed param's subtree must be rewritten. Got: " + schemaJson);
    }

    public static class CascadeAgent {
        @MeshTool(capability = "cascade", description = "two-level same-name defs")
        public String cascade(@Param("a") List<PkgA.Wrap> a, @Param("b") List<PkgB.Wrap> b) {
            return "ok";
        }
    }

    /**
     * Issue #1164 review follow-up: the rename cascade. With {@code List}
     * params BOTH {@code Wrap} and {@code Item} land in {@code $defs} (the
     * wrapper is no longer inlined in the property node). The two {@code Wrap}
     * bodies are byte-identical BEFORE renaming (both ref {@code #/$defs/Item})
     * and only diverge AFTER the nested {@code Item} rename — a single
     * pre-rename comparison judged them equal, dropped PkgB's {@code Wrap},
     * and silently served PkgA's {@code Item} for param {@code b}.
     */
    @Test
    @DisplayName("two-level same-name def cascade: param B's subtree resolves to PkgB's Item")
    @SuppressWarnings("unchecked")
    void twoLevelDefCascadeResolvesCorrectSubtree() {
        Method m = method(CascadeAgent.class, "cascade");
        Map<String, Object> schema = MeshSchemaSupport.buildToolInputSchema(m);
        Map<String, Object> defs = (Map<String, Object>) schema.get("$defs");
        assertNotNull(defs, "list params must hoist Wrap+Item defs. Got: " + schema);

        // Walk param b: items.$ref → Wrap def → properties.item.$ref → Item def.
        Map<String, Object> itemA = followItemDef(schema, defs, "a");
        Map<String, Object> itemB = followItemDef(schema, defs, "b");

        assertTrue(((Map<String, Object>) itemA.get("properties")).containsKey("sku"),
            "param a must resolve to PkgA's Item (sku). Got: " + itemA);
        assertTrue(((Map<String, Object>) itemB.get("properties")).containsKey("qty"),
            "param b must resolve to PkgB's Item (qty) through the FINAL $defs — "
                + "serving PkgA's Item here is the cascade bug. Got: " + itemB);

        // No orphaned def: every hoisted def must be reachable by some $ref.
        for (String defName : defs.keySet()) {
            assertTrue(schema.toString().contains("#/$defs/" + defName),
                "def '" + defName + "' must be referenced somewhere — an orphaned def "
                    + "means the rename was applied without keeping its referrer. $defs: "
                    + defs.keySet());
        }
    }

    /** Resolve {@code properties.<param>.items.$ref → Wrap.properties.item.$ref → Item}. */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> followItemDef(
            Map<String, Object> schema, Map<String, Object> defs, String param) {
        Map<String, Object> props = (Map<String, Object>) schema.get("properties");
        Map<String, Object> listProp = (Map<String, Object>) props.get(param);
        Map<String, Object> items = (Map<String, Object>) listProp.get("items");
        assertNotNull(items, "List param must carry items. Got: " + listProp);
        Map<String, Object> wrap = resolveRef(items, defs);
        Map<String, Object> wrapProps = (Map<String, Object>) wrap.get("properties");
        assertNotNull(wrapProps, "Wrap def must have properties. Got: " + wrap);
        return resolveRef((Map<String, Object>) wrapProps.get("item"), defs);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> resolveRef(Map<String, Object> node, Map<String, Object> defs) {
        Object ref = node.get("$ref");
        if (ref instanceof String s && s.startsWith("#/$defs/")) {
            Map<String, Object> resolved = (Map<String, Object>) defs.get(s.substring("#/$defs/".length()));
            assertNotNull(resolved, "dangling ref " + s + ". $defs keys: " + defs.keySet());
            return resolved;
        }
        return node;
    }

    // ── @Param description precedence ───────────────────────────────────────

    @com.fasterxml.jackson.annotation.JsonClassDescription("type-derived description")
    public record DescribedPayload(@NotNull String field) {}

    public static class DescAgent {
        @MeshTool(capability = "desc_both", description = "t")
        public String both(
                @Param(value = "p", description = "param-level description") DescribedPayload p) {
            return "ok";
        }

        @MeshTool(capability = "desc_derived_only", description = "t")
        public String derivedOnly(@Param("p") DescribedPayload p) {
            return "ok";
        }
    }

    @Test
    @DisplayName("@Param description wins over the victools/type-derived one; derived kept when @Param is silent")
    @SuppressWarnings("unchecked")
    void paramDescriptionWinsOverDerived() {
        Map<String, Object> both = MeshSchemaSupport.buildToolInputSchema(
            method(DescAgent.class, "both"));
        Map<String, Object> bothProp = (Map<String, Object>)
            ((Map<String, Object>) both.get("properties")).get("p");
        assertEquals("param-level description", bothProp.get("description"),
            "@Param description must beat the type-derived one on the composed schema "
                + "(the legacy heartbeat builder always used @Param here). Got: " + bothProp);

        Map<String, Object> derived = MeshSchemaSupport.buildToolInputSchema(
            method(DescAgent.class, "derivedOnly"));
        Map<String, Object> derivedProp = (Map<String, Object>)
            ((Map<String, Object>) derived.get("properties")).get("p");
        assertEquals("type-derived description", derivedProp.get("description"),
            "with no @Param description, the type-derived one must be kept. Got: " + derivedProp);
    }

    @Test
    @DisplayName("identical defs across params are reused (no spurious suffixes)")
    @SuppressWarnings("unchecked")
    void identicalDefsAreReusedNotDuplicated() throws Exception {
        // Two params of the SAME wrapper type → identical Item defs → single entry.
        class Holder {
            @SuppressWarnings("unused")
            public String twice(@Param("a") PkgA.Wrap a, @Param("b") PkgA.Wrap b) {
                return "ok";
            }
        }
        Method m = method(Holder.class, "twice");
        Map<String, Object> schema = MeshSchemaSupport.buildToolInputSchema(m);
        Map<String, Object> defs = (Map<String, Object>) schema.get("$defs");
        assertNotNull(defs);
        assertTrue(defs.containsKey("Item"));
        assertFalse(defs.containsKey("Item_2"),
            "structurally identical defs must be reused, not renamed. Got: " + defs.keySet());
    }
}
