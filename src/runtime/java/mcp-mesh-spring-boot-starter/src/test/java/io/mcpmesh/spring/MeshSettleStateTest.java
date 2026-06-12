package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.Param;
import io.mcpmesh.types.McpMeshTool;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Settling-window dependency grace tests (issue #1193).
 *
 * <p>Cross-runtime contract (mirrors the Python
 * {@code test_settle_window.py} and TypeScript
 * {@code settle-window.spec.ts} suites):
 * <ul>
 *   <li>(a) a call firing while a declared dep is unresolved blocks —
 *       bounded by the remaining settle budget — and proceeds EARLY when
 *       the resolution lands (event-driven, never a sleep);</li>
 *   <li>(b) on timeout the call proceeds with {@code null} exactly as
 *       today (defensive user code untouched);</li>
 *   <li>(c)/(d) the settled latch is permanent (window expiry OR all
 *       declared deps resolved) — subsequent calls never wait;</li>
 *   <li>(e) {@code MCP_MESH_SETTLE_TIMEOUT=0} disables the grace
 *       entirely;</li>
 *   <li>(h) the settled steady-state call path never touches the wait
 *       primitives (waitCount stays 0).</li>
 * </ul>
 *
 * <p>Fix-round additions: per-consumer-slot keying (a shared capability
 * must not wake the wrong consumer), MeshJob declared-index/slot-ordinal
 * skew, and default-disabled {@link MeshSettleState#resetForTests()}.
 */
class MeshSettleStateTest {

    @AfterEach
    void resetSettleState() {
        // Installs a DISABLED (timeout=0) state so subsequent test classes
        // in this JVM never inherit a live window.
        MeshSettleState.resetForTests();
    }

    // ---- env knob parsing ---------------------------------------------------

    @Test
    void timeoutKnob_defaultsTo20Seconds() {
        assertEquals(20.0, MeshSettleState.readTimeoutSeconds(null));
        assertEquals(20.0, MeshSettleState.readTimeoutSeconds(""));
        assertEquals(20.0, MeshSettleState.SETTLE_TIMEOUT_DEFAULT_SECONDS);
    }

    @Test
    void timeoutKnob_parsesFloatSeconds() {
        assertEquals(3.5, MeshSettleState.readTimeoutSeconds("3.5"));
        assertEquals(0.0, MeshSettleState.readTimeoutSeconds("0"));
    }

    @Test
    void timeoutKnob_fallsBackOnInvalidValues() {
        assertEquals(20.0, MeshSettleState.readTimeoutSeconds("-5"));
        assertEquals(20.0, MeshSettleState.readTimeoutSeconds("abc"));
        assertEquals(20.0, MeshSettleState.readTimeoutSeconds("NaN"));
    }

    @Test
    void resetForTests_installsDisabledStateByDefault() {
        MeshSettleState.resetForTests();
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("some_cap");
        // timeout=0 → permanently settled, zero waits possible.
        assertTrue(state.isSettled(),
            "default test reset must install a disabled (timeout=0) window");
        long start = System.nanoTime();
        state.awaitDependency("some_cap", "some_cap");
        assertTrue((System.nanoTime() - start) / 1_000_000 < 50);
        assertEquals(0, state.getWaitCount());
    }

    // ---- state-level behavior -----------------------------------------------

    @Test
    void awaitDependency_unblocksEarlyWhenResolutionArrivesMidWait() throws Exception {
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("db_cap");

        Thread resolver = new Thread(() -> {
            try {
                Thread.sleep(150);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            state.markResolved("db_cap");
        });
        resolver.start();

        long start = System.nanoTime();
        state.awaitDependency("db_cap", "db_cap");
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        resolver.join(2000);

        // Unblocked by the resolution event, not the 10s budget ceiling.
        assertTrue(elapsedMs < 5000, "expected early unblock, waited " + elapsedMs + "ms");
        assertTrue(elapsedMs >= 100, "expected an actual wait, got " + elapsedMs + "ms");
        assertTrue(state.isSettled(), "single declared dep resolved -> eager latch");
        assertEquals(1, state.getWaitCount());
    }

    @Test
    void settledByWindowExpiry_latchIsPermanent() throws Exception {
        MeshSettleState.resetForTests(0.05);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("db_cap");
        Thread.sleep(80);

        assertTrue(state.isSettled());
        long start = System.nanoTime();
        state.awaitDependency("db_cap", "db_cap"); // remaining budget is 0 -> no wait
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        assertTrue(elapsedMs < 50, "settled agent must not wait, waited " + elapsedMs + "ms");
        assertEquals(0, state.getWaitCount());
    }

    @Test
    void settledByAllResolved_neverWaits() {
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("cap_a");
        state.registerDeclared("cap_b");

        state.markResolved("cap_a");
        assertFalse(state.isSettled(), "cap_b still unresolved");
        state.markResolved("cap_b");
        assertTrue(state.isSettled(), "all declared resolved -> eager latch");

        long start = System.nanoTime();
        state.awaitDependency("cap_a", "cap_a");
        assertTrue((System.nanoTime() - start) / 1_000_000 < 50);
        assertEquals(0, state.getWaitCount());
    }

    @Test
    void zeroTimeout_disablesGraceEntirely() {
        MeshSettleState.resetForTests(0.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("db_cap");

        assertTrue(state.isSettled());
        long start = System.nanoTime();
        state.awaitDependency("db_cap", "db_cap");
        assertTrue((System.nanoTime() - start) / 1_000_000 < 50);
        assertEquals(0, state.getWaitCount());
    }

    @Test
    void resolvedAtLeastOnce_isSticky() {
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("db_cap");
        state.markResolved("db_cap");

        // Settle measures INITIAL convergence; later unavailability does not
        // re-open the window (there is no unmark API by design).
        assertTrue(state.isSettled());
        assertTrue(state.isResolved("db_cap"));
    }

    // ---- MeshToolWrapper integration -----------------------------------------

    @SuppressWarnings("unused")
    static class Tool {
        public String lookup(@Param("q") String q, McpMeshTool<String> db) {
            // Defensive user idiom — must keep working unchanged.
            return (db != null && db.isAvailable()) ? "resolved" : "degraded";
        }

        public String lookupB(@Param("q") String q, McpMeshTool<String> db) {
            return (db != null && db.isAvailable()) ? "resolved" : "degraded";
        }

        // MeshJob-consuming shape: the job dependency is declared FIRST,
        // so db_cap sits at DECLARED index 1 but McpMeshTool slot 0.
        public String lookupWithJob(MeshJob job, McpMeshTool<String> db, @Param("q") String q) {
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
        return newWrapper("Tool.lookup", "lookup", List.of("db_cap"));
    }

    private static MeshToolWrapper newWrapper(String funcId, String method, List<String> deps) {
        return new MeshToolWrapper(
            funcId,
            method,
            "test",
            new Tool(),
            find(Tool.class, method),
            deps,
            JsonMapper.builder().build());
    }

    private static McpMeshToolProxy availableProxy() {
        McpMeshToolProxy proxy = new McpMeshToolProxy("db_cap", new McpHttpClient());
        proxy.updateEndpoint("http://localhost:1", "remote_fn");
        return proxy;
    }

    @Test
    void wrapperInvoke_proceedsEarlyWithRealProxyWhenResolutionArrivesMidWait() throws Exception {
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        // Per-consumer-slot composite key (funcId:dep_N) — what the
        // registry declares for tool wrappers.
        state.registerDeclared("Tool.lookup:dep_0");
        MeshToolWrapper wrapper = newWrapper();

        // updateDependency writes the slot, THEN counts the latch down
        // internally — the woken call re-reads a populated slot.
        Thread resolver = new Thread(() -> {
            try {
                Thread.sleep(150);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            wrapper.updateDependency(0, availableProxy());
        });
        resolver.start();

        long start = System.nanoTime();
        Object result = wrapper.invoke(Map.of("q", "x"));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        resolver.join(2000);

        assertEquals("resolved", result, "woken call must re-read the REAL proxy");
        assertTrue(elapsedMs < 5000, "unblocked by event, not budget; waited " + elapsedMs + "ms");
        assertTrue(state.getWaitCount() >= 1);
        assertTrue(state.isSettled(), "slot resolution flips the per-slot declared key");
    }

    @Test
    void wrapperInvoke_timesOutToTodayBehaviorWithNullDep() throws Exception {
        MeshSettleState.resetForTests(0.3);
        MeshSettleState.getInstance().registerDeclared("Tool.lookup:dep_0");
        MeshToolWrapper wrapper = newWrapper();

        long start = System.nanoTime();
        Object result = wrapper.invoke(Map.of("q", "x"));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;

        assertEquals("degraded", result, "defensive user code runs with null dep");
        assertTrue(elapsedMs >= 200, "expected a wait toward the budget, got " + elapsedMs + "ms");
    }

    @Test
    void wrapperInvoke_waitsOnAvailabilityNotJustNull() throws Exception {
        // Java proxies may exist-but-unavailable rather than null — the
        // wait must trigger for an unavailable proxy too (an unavailable
        // proxy also does NOT count the slot as resolved).
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("Tool.lookup:dep_0");
        MeshToolWrapper wrapper = newWrapper();

        // Pre-inject an EXISTING but unavailable proxy.
        McpMeshToolProxy unavailable = new McpMeshToolProxy("db_cap", new McpHttpClient());
        wrapper.updateDependency(0, unavailable);
        assertFalse(state.isResolved("Tool.lookup:dep_0"),
            "unavailable proxy must not mark the slot resolved");

        Thread resolver = new Thread(() -> {
            try {
                Thread.sleep(150);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            wrapper.updateDependency(0, availableProxy());
        });
        resolver.start();

        Object result = wrapper.invoke(Map.of("q", "x"));
        resolver.join(2000);

        assertEquals("resolved", result);
        assertTrue(state.getWaitCount() >= 1, "unavailable proxy must trigger the wait");
    }

    @Test
    void steadyState_settledCallPathNeverTouchesWaitPrimitives() throws Exception {
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("Tool.lookup:dep_0");
        MeshToolWrapper wrapper = newWrapper();

        wrapper.updateDependency(0, availableProxy());
        assertTrue(state.isSettled());

        for (int i = 0; i < 3; i++) {
            long start = System.nanoTime();
            assertEquals("resolved", wrapper.invoke(Map.of("q", "x")));
            assertTrue((System.nanoTime() - start) / 1_000_000 < 100);
        }
        assertEquals(0, state.getWaitCount(),
            "settled steady-state must never touch the wait primitives");
    }

    @Test
    void perSlotKeying_sharedCapabilityDoesNotWakeTheWrongConsumer() throws Exception {
        // Tools A and B both depend on "db_cap". Under capability-level
        // keying, A's resolution event woke B's waiter before B's slot was
        // written — B proceeded with null. Per-slot composite keys mean
        // B's waiter only wakes when B's OWN slot resolves.
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        state.registerDeclared("Tool.lookup:dep_0");
        state.registerDeclared("Tool.lookupB:dep_0");
        MeshToolWrapper wrapperA = newWrapper("Tool.lookup", "lookup", List.of("db_cap"));
        MeshToolWrapper wrapperB = newWrapper("Tool.lookupB", "lookupB", List.of("db_cap"));

        Thread resolver = new Thread(() -> {
            try {
                Thread.sleep(150);
                wrapperA.updateDependency(0, availableProxy()); // A first
                Thread.sleep(250);
                wrapperB.updateDependency(0, availableProxy()); // B later
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        });
        resolver.start();

        long start = System.nanoTime();
        Object resultB = wrapperB.invoke(Map.of("q", "x"));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        resolver.join(3000);

        // The old capability-keyed latch woke B at ~150ms with a null slot
        // → "degraded". Per-slot keying keeps B waiting for ITS event.
        assertEquals("resolved", resultB,
            "B must wake on its OWN slot's resolution, not A's");
        assertTrue(elapsedMs >= 300, "B waited past A's event; got " + elapsedMs + "ms");
        assertTrue(elapsedMs < 5000, "B unblocked by its event, not the budget");
        assertTrue(state.isSettled(), "both per-slot keys resolved -> eager latch");
    }

    @Test
    void meshJobFirstDependencyList_waitsOnTheRightCapabilityAndSettles() throws Exception {
        // dependencies = ["job_cap", "db_cap"] with params
        // (MeshJob, McpMeshTool, @Param): db_cap is DECLARED index 1 but
        // McpMeshTool SLOT 0. The wait must key on dep_1 (db_cap), the
        // job slot must be excluded from the declared settle set, and the
        // declared-index update must land in slot 0.
        MeshSettleState.resetForTests(10.0);
        MeshSettleState state = MeshSettleState.getInstance();
        MeshToolWrapper wrapper = newWrapper(
            "Tool.lookupWithJob", "lookupWithJob", List.of("job_cap", "db_cap"));

        // Registry-level declaration: only the db-backed slot, keyed by
        // DECLARED index (dep_1) — job_cap contributes no settle key.
        MeshToolWrapperRegistry registry =
            new MeshToolWrapperRegistry(new McpMeshToolProxyFactory(new McpHttpClient()));
        registry.registerWrapper(wrapper);
        assertEquals(List.of(1), wrapper.getSettleDepIndices(),
            "only the McpMeshTool-backed declared index participates in settle");

        // Resolve db_cap through the registry funnel with its DECLARED
        // index, exactly as the event processor does.
        Thread resolver = new Thread(() -> {
            try {
                Thread.sleep(150);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            registry.updateDependency(
                "Tool.lookupWithJob:dep_1", "http://localhost:1", "remote_fn");
        });
        resolver.start();

        long start = System.nanoTime();
        Object result = wrapper.invoke(Map.of("q", "x"));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        resolver.join(2000);

        assertEquals("resolved", result,
            "declared-index update must land in the McpMeshTool slot");
        assertTrue(elapsedMs < 5000, "no full-window burn; waited " + elapsedMs + "ms");
        assertTrue(elapsedMs >= 100, "an actual wait happened; got " + elapsedMs + "ms");
        assertTrue(state.isSettled(),
            "db resolution settles the agent — job_cap is not a declared settle key");
    }

    @Test
    void meshJobDependencyEvent_neverCorruptsTheProxySlot() {
        // A resolution event for the JOB capability (declared index 0)
        // must not write into — or evict — the McpMeshTool slot.
        MeshSettleState.resetForTests(10.0);
        MeshToolWrapper wrapper = newWrapper(
            "Tool.lookupWithJob", "lookupWithJob", List.of("job_cap", "db_cap"));

        wrapper.updateDependency(1, availableProxy()); // db lands in slot 0
        wrapper.updateDependency(0, null);             // job event: ignored

        assertTrue(wrapper.areDependenciesAvailable(),
            "job-index update must not evict the db proxy from slot 0");
    }
}
