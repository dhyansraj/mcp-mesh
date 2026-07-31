package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.Collection;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Two overloaded {@code @MeshTool} methods in ONE class must fail the boot
 * (issue #1448).
 *
 * <p>A funcId is {@code FQCN.methodName} with no parameter types, so both
 * overloads compute the same one and the second used to EVICT the first from
 * every funcId-keyed map — with no error and no warning. The duplicate-capability
 * guard in {@code MeshToolRegistry#registerTool} does not fire (it is keyed by
 * capability, and overloads may declare different ones) and the MCP-name guard in
 * {@code MeshMcpServerConfiguration} cannot fire either, because it scans the
 * funcId-keyed handler map the eviction already collapsed. The heartbeat then
 * advertised BOTH capabilities under one {@code function_name}, one of them with
 * no MCP tool behind it, and the merged dependency list could deliver one
 * overload's resolution into the other's slot.
 *
 * <p>The discriminator is the handler {@link Method}, not wrapper identity —
 * re-registering the SAME declaration (prototype scope, context refresh,
 * repeated post-processing) must still replace cleanly (issue #1445).
 */
@DisplayName("MeshToolWrapperRegistry: overloaded @MeshTool methods in one class")
class MeshToolWrapperRegistryOverloadTest {

    private static final String FUNC_ID = OverloadedAnalyzer.class.getName() + ".analyze";

    @Test
    @DisplayName("Two overloads sharing a funcId are refused, naming both signatures")
    void overloadsAreRefusedNamingBothSignatures() throws Exception {
        MeshToolWrapperRegistry registry = registry();
        OverloadedAnalyzer bean = new OverloadedAnalyzer();
        registry.registerWrapper(wrapper(bean, stringOverload(), "analyze_string"));

        IllegalStateException ex = assertThrows(IllegalStateException.class,
            () -> registry.registerWrapper(wrapper(bean, intOverload(), "analyze_int")),
            "a second, genuinely different declaration on the same funcId must not "
                + "silently evict the first");

        assertTrue(ex.getMessage().contains(stringOverload().toString()),
            "error must name the first colliding method in full. Got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains(intOverload().toString()),
            "error must name the second colliding method in full. Got: " + ex.getMessage());
    }

    @Test
    @DisplayName("The error is actionable: rename or split, not a nonexistent name attribute")
    void errorNamesTheRemedy() throws Exception {
        MeshToolWrapperRegistry registry = registry();
        OverloadedAnalyzer bean = new OverloadedAnalyzer();
        registry.registerWrapper(wrapper(bean, stringOverload(), "analyze_string"));

        IllegalStateException ex = assertThrows(IllegalStateException.class,
            () -> registry.registerWrapper(wrapper(bean, intOverload(), "analyze_int")));

        assertTrue(ex.getMessage().contains("rename"),
            "@MeshTool has no name attribute — the only remedies are renaming a method "
                + "or splitting the class. Got: " + ex.getMessage());
    }

    @Test
    @DisplayName("Re-registering the SAME method replaces cleanly — no false positive (#1445)")
    void sameMethodFreshWrapperReplaces() throws Exception {
        MeshToolWrapperRegistry registry = registry();
        // Two FRESH wrapper instances over the same declaration, from two
        // INDEPENDENT reflective lookups: Method.equals is value-based, so the
        // guard must read these as one declaration registered twice.
        MeshToolWrapper stale = wrapper(new OverloadedAnalyzer(), stringOverload(), "analyze_string");
        MeshToolWrapper fresh = wrapper(new OverloadedAnalyzer(), stringOverload(), "analyze_string");
        registry.registerWrapper(stale);

        assertDoesNotThrow(() -> registry.registerWrapper(fresh),
            "a prototype-scoped bean, a context refresh or a repeated post-processing "
                + "pass re-registers the same declaration — that must still replace");
        assertSame(fresh, registry.getWrapper(FUNC_ID), "the replacement must win");
        assertSame(fresh, registry.getWrapperByMethodName("analyze"),
            "and the bare-name index must not have been poisoned");
    }

    @Test
    @DisplayName("A handler with a null Method carries no identity to compare — it does not throw")
    void nullMethodDoesNotThrow() throws Exception {
        MeshToolWrapperRegistry incomingIsNull = registry();
        incomingIsNull.registerWrapper(wrapper(new OverloadedAnalyzer(), stringOverload(), "analyze_string"));
        assertDoesNotThrow(() -> incomingIsNull.registerWrapper(
            nullMethodWrapper(new OverloadedAnalyzer(), intOverload(), "analyze_int")));

        MeshToolWrapperRegistry previousIsNull = registry();
        previousIsNull.registerWrapper(
            nullMethodWrapper(new OverloadedAnalyzer(), stringOverload(), "analyze_string"));
        assertDoesNotThrow(() -> previousIsNull.registerWrapper(
            wrapper(new OverloadedAnalyzer(), intOverload(), "analyze_int")));
    }

    @Test
    @DisplayName("No capability is left advertised with no MCP tool behind it")
    void noDeclarationIsDroppedSilently() throws Exception {
        MeshToolWrapperRegistry registry = registry();
        OverloadedAnalyzer bean = new OverloadedAnalyzer();
        MeshToolWrapper first = wrapper(bean, stringOverload(), "analyze_string");
        registry.registerWrapper(first);

        assertThrows(IllegalStateException.class,
            () -> registry.registerWrapper(wrapper(bean, intOverload(), "analyze_int")));

        // The pre-fix end state: the funcId-keyed maps (wrappers, handlers) kept
        // only the LAST overload while handlersByCapability kept BOTH — so
        // 'analyze_string' was advertised to the registry with no MCP tool behind
        // it. Every advertised capability must resolve to a handler the MCP
        // server actually serves.
        Collection<McpToolHandler> served = registry.getAllHandlers();
        for (Map.Entry<String, McpToolHandler> entry : registry.getHandlersByCapability().entrySet()) {
            assertTrue(served.contains(entry.getValue()),
                "capability '" + entry.getKey() + "' is advertised but its handler is not "
                    + "served by the MCP server — a declaration was dropped silently");
        }
        assertSame(first, registry.getWrapper(FUNC_ID),
            "the first declaration must survive the rejected one intact");
        assertSame(first, registry.getHandler(FUNC_ID));
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    private static MeshToolWrapperRegistry registry() {
        return new MeshToolWrapperRegistry(new McpMeshToolProxyFactory());
    }

    private static MeshToolWrapper wrapper(Object bean, Method method, String capability) {
        return new MeshToolWrapper(FUNC_ID, capability, "test", bean, method,
            List.of(), JsonMapper.builder().build());
    }

    /** A handler that reports no {@link Method} — e.g. a non-{@code @MeshTool} handler. */
    private static MeshToolWrapper nullMethodWrapper(Object bean, Method method, String capability) {
        return new MeshToolWrapper(FUNC_ID, capability, "test", bean, method,
                List.of(), JsonMapper.builder().build()) {
            @Override
            public Method getMethod() {
                return null;
            }
        };
    }

    private static Method stringOverload() throws NoSuchMethodException {
        return OverloadedAnalyzer.class.getMethod("analyze", String.class);
    }

    private static Method intOverload() throws NoSuchMethodException {
        return OverloadedAnalyzer.class.getMethod("analyze", int.class);
    }

    /** ONE class, two {@code @MeshTool} overloads — different capabilities. */
    public static class OverloadedAnalyzer {

        @MeshTool(capability = "analyze_string", description = "analyze a query")
        public String analyze(@Param("q") String q) {
            return "string:" + q;
        }

        @MeshTool(capability = "analyze_int", description = "analyze a number")
        public String analyze(@Param("n") int n) {
            return "int:" + n;
        }
    }
}
