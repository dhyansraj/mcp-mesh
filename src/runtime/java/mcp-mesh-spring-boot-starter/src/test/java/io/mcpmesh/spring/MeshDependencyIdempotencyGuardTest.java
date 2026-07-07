package io.mcpmesh.spring;

import io.mcpmesh.Param;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.lang.reflect.Type;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Idempotency guard on the dependency-apply path (#1314).
 *
 * <p>The Rust core re-emits {@code dependency_available} for every
 * believed-delivered edge on an independent ~10s wall-clock tick to self-heal
 * dropped applies. Those re-emits carry the SAME resolution. Without a guard
 * the SDK would re-fetch the proxy and rewrite the wrapper's injected slot (and
 * repoint the shared per-capability handle) every 10s for a no-op. These tests
 * assert the guard short-circuits an unchanged re-apply while a genuine change
 * (endpoint, function, or agentId) still updates.
 */
class MeshDependencyIdempotencyGuardTest {

    @SuppressWarnings("unused")
    static class Tool {
        public String lookup(@Param("q") String q, McpMeshTool<String> db) {
            return (db != null && db.isAvailable()) ? "resolved" : "degraded";
        }
    }

    private static Method find(Class<?> cls, String name) {
        for (Method m : cls.getDeclaredMethods()) {
            if (m.getName().equals(name)) return m;
        }
        throw new AssertionError("not found: " + name);
    }

    private static MeshToolWrapper newWrapper() {
        return new MeshToolWrapper(
            "Tool.lookup",
            "lookup",
            "test",
            new Tool(),
            find(Tool.class, "lookup"),
            List.of("db_cap"),
            JsonMapper.builder().build());
    }

    /** Counts every getOrCreateProxy invocation so a skipped apply is observable. */
    static class CountingProxyFactory extends McpMeshToolProxyFactory {
        final AtomicInteger calls = new AtomicInteger();

        CountingProxyFactory() {
            super(new McpHttpClient());
        }

        @Override
        public <T> McpMeshTool<T> getOrCreateProxy(String endpoint, String functionName, Type returnType) {
            calls.incrementAndGet();
            return super.getOrCreateProxy(endpoint, functionName, returnType);
        }
    }

    // ---- Registry per-slot signature guard -----------------------------------

    @Test
    void identicalReapply_isNoOp() {
        CountingProxyFactory factory = new CountingProxyFactory();
        MeshToolWrapperRegistry registry = new MeshToolWrapperRegistry(factory);
        registry.registerWrapper(newWrapper());
        String key = MeshToolWrapperRegistry.buildDependencyKey("Tool.lookup", 0);

        registry.updateDependency(key, "http://localhost:1", "remote_fn", "agent-a");
        registry.updateDependency(key, "http://localhost:1", "remote_fn", "agent-a");

        assertEquals(1, factory.calls.get(),
            "second apply with an identical signature must short-circuit (no proxy fetch)");
    }

    @Test
    void differentEndpoint_updates() {
        CountingProxyFactory factory = new CountingProxyFactory();
        MeshToolWrapperRegistry registry = new MeshToolWrapperRegistry(factory);
        registry.registerWrapper(newWrapper());
        String key = MeshToolWrapperRegistry.buildDependencyKey("Tool.lookup", 0);

        registry.updateDependency(key, "http://localhost:1", "remote_fn", "agent-a");
        registry.updateDependency(key, "http://localhost:2", "remote_fn", "agent-a");

        assertEquals(2, factory.calls.get(), "a different endpoint is a genuine change");
    }

    @Test
    void differentAgentId_updates() {
        CountingProxyFactory factory = new CountingProxyFactory();
        MeshToolWrapperRegistry registry = new MeshToolWrapperRegistry(factory);
        registry.registerWrapper(newWrapper());
        String key = MeshToolWrapperRegistry.buildDependencyKey("Tool.lookup", 0);

        // Same endpoint/function, agent_id-only change (composes with #1315).
        registry.updateDependency(key, "http://localhost:1", "remote_fn", "agent-a");
        registry.updateDependency(key, "http://localhost:1", "remote_fn", "agent-b");

        assertEquals(2, factory.calls.get(),
            "an agent_id-only change must still update");
    }

    @Test
    void removalThenReadd_updates() {
        CountingProxyFactory factory = new CountingProxyFactory();
        MeshToolWrapperRegistry registry = new MeshToolWrapperRegistry(factory);
        registry.registerWrapper(newWrapper());
        String key = MeshToolWrapperRegistry.buildDependencyKey("Tool.lookup", 0);

        registry.updateDependency(key, "http://localhost:1", "remote_fn", "agent-a");
        registry.markDependencyUnavailable(key);
        // Re-add of the SAME resolution must re-wire — the removal cleared the
        // stored signature, so this is not treated as a no-op.
        registry.updateDependency(key, "http://localhost:1", "remote_fn", "agent-a");

        assertEquals(2, factory.calls.get(),
            "re-add after removal must update even with the same signature");
    }

    // ---- Shared-handle guard (McpMeshToolProxy.updateEndpoint) ----------------

    @Test
    void updateEndpoint_shortCircuitsUnchanged() {
        McpMeshToolProxy<?> proxy = new McpMeshToolProxy<>("db_cap", new McpHttpClient());

        assertTrue(proxy.updateEndpoint("http://localhost:1", "remote_fn"),
            "first apply changes the endpoint");
        assertFalse(proxy.updateEndpoint("http://localhost:1", "remote_fn"),
            "identical re-apply is a no-op repoint");
        assertTrue(proxy.updateEndpoint("http://localhost:2", "remote_fn"),
            "a different endpoint repoints");
    }

    @Test
    void updateEndpoint_reappliesAfterUnavailable() {
        McpMeshToolProxy<?> proxy = new McpMeshToolProxy<>("db_cap", new McpHttpClient());

        assertTrue(proxy.updateEndpoint("http://localhost:1", "remote_fn"));
        proxy.markUnavailable();
        // Availability flipped false, so the same endpoint/function is a real
        // change back to available — must repoint.
        assertTrue(proxy.updateEndpoint("http://localhost:1", "remote_fn"),
            "re-apply after markUnavailable must repoint (availability changed)");
    }
}
