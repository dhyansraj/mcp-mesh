package io.mcpmesh.spring;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;

/**
 * Two {@code @MeshTool} methods with the same NAME in different classes must not
 * share a registry slot (issue #1437).
 *
 * <p>{@code wrappersByMethodName} keyed on the bare method name with no class
 * qualifier at all — the weakest key in the package. It is fallback-only, behind
 * the funcId lookup in {@code resolveWrapper}, which is what kept it from being
 * a routine failure; but when the fallback did fire it answered with whichever
 * wrapper registered last, and a dependency resolution addressed to one tool was
 * wired into the other tool's slot.
 *
 * <p>The name has to stay addressable — it is the wire-facing fallback for a
 * core that names a slot by function name alone — so the fix is a collision
 * guard, not a rename: a name claimed by two wrappers resolves to neither, and
 * both stay addressable by function id and by {@link Method}.
 */
@DisplayName("MeshToolWrapperRegistry: same method name in different classes")
class MeshToolWrapperRegistryMethodNameCollisionTest {

    @Test
    @DisplayName("A bare method name claimed by two classes resolves to neither")
    void collidingMethodNameResolvesToNeither() throws Exception {
        MeshToolWrapperRegistry registry = registry();
        MeshToolWrapper first = wrapper(FirstAnalyzer.class, new FirstAnalyzer(), "first_analyze");
        MeshToolWrapper second = wrapper(SecondAnalyzer.class, new SecondAnalyzer(), "second_analyze");
        registry.registerWrapper(first);
        registry.registerWrapper(second);

        assertNull(registry.getWrapperByMethodName("analyze"),
            "'analyze' names both wrappers — it must not resolve to the one that "
                + "happened to register last");
    }

    @Test
    @DisplayName("Both colliding wrappers stay addressable by funcId and by Method")
    void bothWrappersStayAddressable() throws Exception {
        MeshToolWrapperRegistry registry = registry();
        MeshToolWrapper first = wrapper(FirstAnalyzer.class, new FirstAnalyzer(), "first_analyze");
        MeshToolWrapper second = wrapper(SecondAnalyzer.class, new SecondAnalyzer(), "second_analyze");
        registry.registerWrapper(first);
        registry.registerWrapper(second);

        assertSame(first, registry.getWrapper(FirstAnalyzer.class.getName() + ".analyze"));
        assertSame(second, registry.getWrapper(SecondAnalyzer.class.getName() + ".analyze"));
        // A FRESH reflective copy — Method.equals is value-based, which is what
        // makes a Method-keyed index usable from a caller that re-looked it up.
        assertSame(first, registry.getWrapperByMethod(analyzeOf(FirstAnalyzer.class)));
        assertSame(second, registry.getWrapperByMethod(analyzeOf(SecondAnalyzer.class)));
    }

    @Test
    @DisplayName("A dependency addressed by the colliding name is not wired into the wrong tool")
    void collidingNameDoesNotMisrouteADependency() throws Exception {
        MeshToolWrapperRegistry registry = registry();
        FirstAnalyzer firstBean = new FirstAnalyzer();
        SecondAnalyzer secondBean = new SecondAnalyzer();
        registry.registerWrapper(wrapper(FirstAnalyzer.class, firstBean, "first_analyze"));
        MeshToolWrapper second = wrapper(SecondAnalyzer.class, secondBean, "second_analyze");
        registry.registerWrapper(second);

        // The wire fallback: a composite key naming the tool by bare method name.
        // 'second' registered last, so on the unguarded map it took this apply —
        // silently wiring FIRST's dependency into SECOND's slot 0.
        registry.updateDependency("analyze:dep_0", "http://provider", "lookup");

        second.invoke(Map.of("q", "x"));
        assertEquals(1, secondBean.received.size());
        assertNull(secondBean.received.get(0),
            "the second tool's slot must not receive a resolution addressed to an "
                + "ambiguous name");
    }

    @Test
    @DisplayName("An unambiguous method name still resolves — the fallback still works")
    void unambiguousMethodNameStillResolves() throws Exception {
        MeshToolWrapperRegistry registry = registry();
        FirstAnalyzer bean = new FirstAnalyzer();
        MeshToolWrapper only = wrapper(FirstAnalyzer.class, bean, "first_analyze");
        registry.registerWrapper(only);

        assertSame(only, registry.getWrapperByMethodName("analyze"));

        registry.updateDependency("analyze:dep_0", "http://provider", "lookup");
        only.invoke(Map.of("q", "x"));
        assertEquals("lookup", capabilityOf(bean.received.get(0)),
            "the bare-name fallback must still deliver when the name names one tool");
    }

    @Test
    @DisplayName("Re-registering the same tool replaces it — it does not collide with itself")
    void reRegisteringSameFuncIdReplacesRatherThanCollides() throws Exception {
        MeshToolWrapperRegistry registry = registry();
        FirstAnalyzer staleBean = new FirstAnalyzer();
        FirstAnalyzer freshBean = new FirstAnalyzer();
        // Two FRESH wrapper instances for the SAME funcId (same class, same method).
        MeshToolWrapper stale = wrapper(FirstAnalyzer.class, staleBean, "first_analyze");
        MeshToolWrapper fresh = wrapper(FirstAnalyzer.class, freshBean, "first_analyze");
        registry.registerWrapper(stale);
        registry.registerWrapper(fresh);

        // Every other index in registerWrapper replaces on a bare put; the
        // bare-name index must not be the one map that treats a re-registration
        // as a collision and poisons the name forever.
        assertSame(fresh, registry.getWrapperByMethodName("analyze"),
            "a re-registration of the same funcId must replace the mapping, not "
                + "make the name ambiguous");

        registry.updateDependency("analyze:dep_0", "http://provider", "lookup");
        fresh.invoke(Map.of("q", "x"));
        assertEquals("lookup", capabilityOf(freshBean.received.get(0)),
            "the resolution must land on the replacement bean");

        stale.invoke(Map.of("q", "x"));
        assertNull(staleBean.received.get(0),
            "the replaced wrapper's slot must stay unwired — the apply went to the "
                + "replacement, not to the instance it superseded");
    }

    // ─────────────────────────────────────────────────────────────────
    // Harness
    // ─────────────────────────────────────────────────────────────────

    private static MeshToolWrapperRegistry registry() {
        return new MeshToolWrapperRegistry(new StubProxyFactory());
    }

    private static MeshToolWrapper wrapper(Class<?> type, Object bean, String capability)
            throws Exception {
        Method method = analyzeOf(type);
        return new MeshToolWrapper(
            type.getName() + ".analyze",
            capability,
            "test",
            bean,
            method,
            List.of("lookup"),
            JsonMapper.builder().build());
    }

    private static Method analyzeOf(Class<?> type) throws NoSuchMethodException {
        return type.getMethod("analyze", String.class, McpMeshTool.class);
    }

    private static String capabilityOf(Object dep) {
        return dep == null ? null : ((McpMeshTool<?>) dep).getCapability();
    }

    /** Hands back a stub proxy labelled with the resolved function name. */
    static class StubProxyFactory extends McpMeshToolProxyFactory {
        StubProxyFactory() {
            super(new McpHttpClient());
        }

        @Override
        public McpMeshTool getOrCreateProxy(String endpoint, String functionName) {
            return new StubProxy(functionName);
        }

        @Override
        @SuppressWarnings("unchecked")
        public <T> McpMeshTool<T> getOrCreateProxy(String endpoint, String functionName,
                                                   Type returnType) {
            return (McpMeshTool<T>) new StubProxy(functionName);
        }
    }

    static class StubProxy implements McpMeshTool<String> {
        private final String capability;
        StubProxy(String capability) { this.capability = capability; }
        @Override public String call() { return capability; }
        @Override public String call(Map<String, Object> params) { return capability; }
        @Override public String call(Object... args) { return capability; }
        @Override public CompletableFuture<String> callAsync() { return CompletableFuture.completedFuture(capability); }
        @Override public CompletableFuture<String> callAsync(Map<String, Object> params) { return CompletableFuture.completedFuture(capability); }
        @Override public CompletableFuture<String> callAsync(Object... keyValuePairs) { return CompletableFuture.completedFuture(capability); }
        @Override public String getCapability() { return capability; }
        @Override public String getEndpoint() { return "http://" + capability; }
        @Override public String getFunctionName() { return capability; }
        @Override public boolean isAvailable() { return true; }
    }

    /** Two DIFFERENT classes, both with a tool method named {@code analyze}. */
    public static class FirstAnalyzer {
        final List<McpMeshTool<?>> received = new ArrayList<>();

        @MeshTool(capability = "first_analyze", dependencies = @Selector(capability = "lookup"))
        public Object analyze(@Param("q") String q, McpMeshTool<String> lookup) {
            received.clear();
            received.add(lookup);
            return Map.of("q", q);
        }
    }

    public static class SecondAnalyzer {
        final List<McpMeshTool<?>> received = new ArrayList<>();

        @MeshTool(capability = "second_analyze", dependencies = @Selector(capability = "lookup"))
        public Object analyze(@Param("q") String q, McpMeshTool<String> lookup) {
            received.clear();
            received.add(lookup);
            return Map.of("q", q);
        }
    }
}
