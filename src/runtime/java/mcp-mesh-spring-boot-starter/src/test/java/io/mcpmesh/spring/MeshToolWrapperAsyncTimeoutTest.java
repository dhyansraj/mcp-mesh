package io.mcpmesh.spring;

import io.mcpmesh.JobContext;
import io.mcpmesh.Param;
import io.mcpmesh.spring.tracing.TraceContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1164 MED-5: async tool timeout symmetry.
 *
 * <p>Previously the inbound path hard-coded a 30s {@code future.get} while the
 * claim path awaited unbounded, and the timed-out future was never cancelled.
 * Now both paths award the job's actual budget (propagated
 * {@code X-Mesh-Timeout} / claim {@code max_duration}), fall back to a sane
 * default only when absent, and cancel the future on timeout (freeing the
 * dispatch thread and making a late {@code complete()} a no-op — NOT
 * interrupting the running work; {@code CompletableFuture.cancel}'s
 * {@code mayInterruptIfRunning} has no effect per its javadoc).
 *
 * <p>The inbound await additionally shaves a proportional margin —
 * {@code min(}{@link MeshToolWrapper#ASYNC_AWAIT_MARGIN_SECS}{@code ,
 * budget/10)}, floor 1s — off a present budget so the structured timeout
 * error reaches the caller before the caller's socket read timeout fires,
 * without a fixed margin eating most of a small budget (a 3s budget keeps
 * 3s, accepting the socket race, instead of collapsing to 1s).
 */
@DisplayName("Async tool await budget — inbound + claim path (issue #1164 MED-5)")
class MeshToolWrapperAsyncTimeoutTest {

    public static class AsyncAgent {
        volatile CompletableFuture<String> lastFuture;

        public CompletableFuture<String> neverDone(@Param("x") String x) {
            lastFuture = new CompletableFuture<>();
            return lastFuture;
        }

        public CompletableFuture<String> quick(@Param("x") String x) {
            return CompletableFuture.completedFuture("done:" + x);
        }
    }

    private static Method method(String name) {
        for (Method m : AsyncAgent.class.getDeclaredMethods()) {
            if (m.getName().equals(name)) {
                return m;
            }
        }
        throw new AssertionError("no method " + name);
    }

    private static MeshToolWrapper wrapper(AsyncAgent bean, String methodName) {
        return new MeshToolWrapper(
            "AsyncAgent." + methodName, methodName, "test",
            bean, method(methodName), List.of(), JsonMapper.builder().build());
    }

    @AfterEach
    void tearDown() {
        TraceContext.clear();
        TraceContext.clearPropagatedHeaders();
    }

    // ── Budget selection (unit) ─────────────────────────────────────────────

    @Test
    @DisplayName("budget > 30s wins over the 30s default (minus margin); absent/invalid budget falls back")
    void effectiveBudgetSelection() {
        // X-Mesh-Timeout=120 must bound the await near 120s — NOT fail at 30s.
        // The margin (min(cap, budget/10)) keeps the structured timeout error
        // ahead of the caller's socket read timeout, which would otherwise
        // fire at the same instant.
        assertEquals(120L - MeshToolWrapper.ASYNC_AWAIT_MARGIN_SECS,
            MeshToolWrapper.effectiveAsyncAwaitSecs(120L));
        // Mid-range budgets: proportional margin below the cap.
        assertEquals(18L, MeshToolWrapper.effectiveAsyncAwaitSecs(20L));
        assertEquals(9L, MeshToolWrapper.effectiveAsyncAwaitSecs(10L));
        // Small budgets (< 10s) keep their whole window — a fixed 2s margin
        // previously ate 2/3 of a 3s budget; accepting the socket-timeout
        // race is the better trade at this scale.
        assertEquals(3L, MeshToolWrapper.effectiveAsyncAwaitSecs(3L));
        assertEquals(2L, MeshToolWrapper.effectiveAsyncAwaitSecs(2L));
        assertEquals(1L, MeshToolWrapper.effectiveAsyncAwaitSecs(1L));
        // Absent header → the 30s default (no margin: nothing to race against).
        assertEquals(MeshToolWrapper.ASYNC_TIMEOUT_SECONDS, MeshToolWrapper.effectiveAsyncAwaitSecs(null));
        // Defensive: non-positive budgets fall back too.
        assertEquals(MeshToolWrapper.ASYNC_TIMEOUT_SECONDS, MeshToolWrapper.effectiveAsyncAwaitSecs(0L));
        assertEquals(MeshToolWrapper.ASYNC_TIMEOUT_SECONDS, MeshToolWrapper.effectiveAsyncAwaitSecs(-5L));
    }

    // ── Inbound path behavior ───────────────────────────────────────────────

    @Test
    @DisplayName("inbound X-Mesh-Timeout bounds the await; timed-out future is cancelled")
    void inboundTimeoutBoundsAwaitAndCancelsFuture() {
        AsyncAgent bean = new AsyncAgent();
        MeshToolWrapper w = wrapper(bean, "neverDone");

        // 1s budget propagated from the caller.
        TraceContext.setPropagatedHeaders(Map.of("x-mesh-timeout", "1"));

        long start = System.nanoTime();
        RuntimeException ex = assertThrows(RuntimeException.class,
            () -> w.invoke(Map.of("x", "v")));
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;

        assertTrue(ex.getMessage().contains("timed out after 1 seconds"),
            "failure message must carry the actual budget used. Got: " + ex.getMessage());
        assertTrue(elapsedMs < 15_000,
            "await must be bounded by the 1s header budget, not the 30s default (took " + elapsedMs + "ms)");
        assertNotNull(bean.lastFuture);
        assertTrue(bean.lastFuture.isCancelled(),
            "timed-out future must be cancelled so dependent stages abort and a late complete() is a no-op");
    }

    @Test
    @DisplayName("budget larger than the default lets a quick future complete normally")
    void largeBudgetCompletesNormally() throws Exception {
        AsyncAgent bean = new AsyncAgent();
        MeshToolWrapper w = wrapper(bean, "quick");

        TraceContext.setPropagatedHeaders(Map.of("x-mesh-timeout", "120"));
        assertEquals("done:v", w.invoke(Map.of("x", "v")));
    }

    @Test
    @DisplayName("absent header → default budget still awaits and returns")
    void absentHeaderUsesDefaultAndCompletes() throws Exception {
        AsyncAgent bean = new AsyncAgent();
        MeshToolWrapper w = wrapper(bean, "quick");
        assertEquals("done:v", w.invoke(Map.of("x", "v")));
    }

    @Test
    @DisplayName("awaitIfFuture timeout cancels and reports the budget")
    void awaitIfFutureCancelsOnTimeout() {
        CompletableFuture<String> cf = new CompletableFuture<>();
        RuntimeException ex = assertThrows(RuntimeException.class,
            () -> MeshToolWrapper.awaitIfFuture(cf, 1L));
        assertTrue(ex.getMessage().contains("1 seconds"), "Got: " + ex.getMessage());
        assertTrue(cf.isCancelled());
    }

    // ── Claim path behavior ─────────────────────────────────────────────────

    @Test
    @DisplayName("claim path awaits with the job's max_duration budget and cancels on timeout")
    void claimPathUsesJobDeadlineAndCancels() throws Exception {
        CompletableFuture<Object> cf = new CompletableFuture<>();
        RuntimeException ex = assertThrows(RuntimeException.class, () ->
            JobContext.withJob("job-1", 1L, () ->
                JobsRuntimeManager.awaitFutureWithJobBudget(cf, "report_gen")));
        assertTrue(ex.getMessage().contains("timed out after 1 seconds"),
            "failure message must carry the actual budget. Got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("report_gen"),
            "failure message must name the capability. Got: " + ex.getMessage());
        assertTrue(cf.isCancelled(), "timed-out claim-path future must be cancelled");
    }

    @Test
    @DisplayName("claim path without a deadline uses the 24h ceiling (no longer fully unbounded)")
    void claimPathNoDeadlineHasCeiling() throws Exception {
        assertEquals(86_400L, JobsRuntimeManager.NO_DEADLINE_AWAIT_CEILING_SECS,
            "no-deadline ceiling is a leak backstop, not a policy timeout");
        // Completed future returns immediately regardless.
        CompletableFuture<Object> cf = CompletableFuture.completedFuture("v");
        assertEquals("v", JobsRuntimeManager.awaitFutureWithJobBudget(cf, "cap"));
    }
}
