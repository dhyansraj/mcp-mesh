package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthCheck;
import io.mcpmesh.MeshHealthStatus;
import io.mcpmesh.core.AgentSpec;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/**
 * What the health-check timer does with each verdict (issue #1474).
 *
 * <p>Three invariants asserted here:
 * <ul>
 *   <li>only an explicit UNHEALTHY reaches the runtime as {@code "unhealthy"} —
 *       a throwing check publishes {@code "degraded"} and keeps beating;</li>
 *   <li>the startup seed does NOT publish, so a check that fails during boot
 *       cannot withdraw an agent that has only just registered;</li>
 *   <li>the verdict reaches the runtime on EVERY agent type, route
 *       ({@code api}) and A2A gateways included (RFC #1502 step 3, reversing
 *       #1473's exemption).</li>
 * </ul>
 */
// MeshHealth.degraded is deprecated (issue #1515) and still exercised here: the
// deprecation promises source compatibility until 4.0, so the paths that carry a
// degraded verdict have to keep working. Suppressed rather than rewritten so the
// promise stays under test.
@SuppressWarnings("deprecation")
class MeshHealthCheckSchedulerTest {

    static class Checks {
        volatile MeshHealth next = MeshHealth.healthy();
        volatile boolean explode = false;

        @MeshHealthCheck(ttlSeconds = 1)
        public MeshHealth check() {
            if (explode) {
                throw new IllegalStateException("boom");
            }
            return next;
        }
    }

    private static MeshHealthCheckRegistry registryFor(Checks bean) {
        try {
            Method method = Checks.class.getMethod("check");
            MeshHealthCheckRegistry registry = new MeshHealthCheckRegistry();
            registry.register(bean, method, method.getAnnotation(MeshHealthCheck.class).ttlSeconds());
            return registry;
        } catch (NoSuchMethodException e) {
            throw new AssertionError(e);
        }
    }

    /** A running runtime of the given agent type, recording every published status. */
    private static MeshRuntime runtimeOf(String agentType, List<String> published) {
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.isRunning()).thenReturn(true);
        AgentSpec spec = new AgentSpec();
        spec.setName("provider");
        spec.setAgentType(agentType);
        when(runtime.getAgentSpec()).thenReturn(spec);
        when(runtime.updateHealth(anyString())).thenAnswer(inv -> {
            published.add(inv.getArgument(0));
            return true;
        });
        return runtime;
    }

    @Test
    void aHealthyVerdictIsStoredAndPublished() {
        List<String> published = Collections.synchronizedList(new ArrayList<>());
        Checks bean = new Checks();
        MeshHealthCheckRegistry registry = registryFor(bean);
        MeshHealthCheckScheduler scheduler =
            new MeshHealthCheckScheduler(runtimeOf("mcp_agent", published), registry);

        scheduler.refresh(true);

        assertEquals(MeshHealthStatus.HEALTHY, registry.latest().health().status());
        assertEquals(List.of("healthy"), published);
    }

    @Test
    void anUnhealthyVerdictIsPublishedAsUnhealthy() {
        // This is the whole mechanism: "unhealthy" is what stops the heartbeat.
        List<String> published = Collections.synchronizedList(new ArrayList<>());
        Checks bean = new Checks();
        bean.next = MeshHealth.unhealthy("vendor 503");
        MeshHealthCheckRegistry registry = registryFor(bean);

        new MeshHealthCheckScheduler(runtimeOf("mcp_agent", published), registry).refresh(true);

        assertEquals(List.of("unhealthy"), published);
        assertEquals(List.of("vendor 503"), registry.latest().health().errors());
    }

    @Test
    void aThrowingCheckPublishesDegradedSoTheAgentKeepsBeating() {
        List<String> published = Collections.synchronizedList(new ArrayList<>());
        Checks bean = new Checks();
        bean.explode = true;
        MeshHealthCheckRegistry registry = registryFor(bean);

        new MeshHealthCheckScheduler(runtimeOf("mcp_agent", published), registry).refresh(true);

        assertEquals(List.of("degraded"), published,
            "a buggy health check must not withdraw a working agent");
        assertEquals(MeshHealthStatus.DEGRADED, registry.latest().health().status());
    }

    @Test
    void aDegradedVerdictIsPublishedAsDegraded() {
        List<String> published = Collections.synchronizedList(new ArrayList<>());
        Checks bean = new Checks();
        bean.next = MeshHealth.degraded("high latency");
        MeshHealthCheckRegistry registry = registryFor(bean);

        new MeshHealthCheckScheduler(runtimeOf("mcp_agent", published), registry).refresh(true);

        assertEquals(List.of("degraded"), published);
    }

    @Test
    @Timeout(30)
    void theStartupSeedFeedsTheEndpointsButDoesNotWithdrawTheAgent() throws Exception {
        // Python parity: the agent registers and becomes visible first; only the
        // first refresh, one TTL later, can withdraw it. A vendor client built
        // lazily on the first call would otherwise fail its own boot probe and
        // take the agent out before it ever served anything.
        List<String> published = Collections.synchronizedList(new ArrayList<>());
        Checks bean = new Checks();
        bean.next = MeshHealth.unhealthy("not warm yet");
        MeshHealthCheckRegistry registry = registryFor(bean);
        MeshHealthCheckScheduler scheduler =
            new MeshHealthCheckScheduler(runtimeOf("mcp_agent", published), registry);

        scheduler.start();
        try {
            waitUntil(() -> registry.latest() != null);
            assertEquals(MeshHealthStatus.UNHEALTHY, registry.latest().health().status(),
                "the seed must reach /health and /ready");
            assertTrue(published.isEmpty(), "the seed must not publish to the runtime");

            // ttlSeconds=1 — the first scheduled tick publishes.
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
            while (published.isEmpty() && System.nanoTime() < deadline) {
                Thread.sleep(50);
            }
            assertEquals(List.of("unhealthy"), published,
                "the first scheduled refresh must publish the verdict");
        } finally {
            scheduler.stop();
        }
        assertFalse(scheduler.isRunning());
    }

    @Test
    @Timeout(30)
    void recoveryIsPublishedWithoutARestart() throws Exception {
        List<String> published = Collections.synchronizedList(new ArrayList<>());
        Checks bean = new Checks();
        bean.next = MeshHealth.unhealthy("vendor down");
        MeshHealthCheckRegistry registry = registryFor(bean);
        MeshHealthCheckScheduler scheduler =
            new MeshHealthCheckScheduler(runtimeOf("mcp_agent", published), registry);

        scheduler.start();
        try {
            waitUntil(() -> published.contains("unhealthy"));
            bean.next = MeshHealth.healthy();
            waitUntil(() -> published.contains("healthy"));
        } finally {
            scheduler.stop();
        }

        assertTrue(published.indexOf("unhealthy") < published.indexOf("healthy"));
    }

    @Test
    void aFailingCheckPausesAGatewaysHeartbeatToo() throws Exception {
        // RFC #1502 step 3 reverses #1473's route/A2A exemption. The exemption
        // existed because withdrawing a fan-out point "takes the application
        // down"; step 2 removed that harm. Heartbeat suppression stops
        // registry traffic ONLY — the HTTP server keeps running, resolved
        // dependencies are retained (#1131), and /ready reports the mesh
        // runtime rather than the verdict, so the agent stays in its Service
        // endpoints and keeps taking ingress. A gateway that reports
        // unavailable stops being DISCOVERED; it does not go dark.
        for (String agentType : List.of("api", "a2a")) {
            List<String> published = Collections.synchronizedList(new ArrayList<>());
            Checks bean = new Checks();
            bean.next = MeshHealth.unhealthy("upstream down");
            MeshHealthCheckRegistry registry = registryFor(bean);
            MeshHealthCheckScheduler scheduler =
                new MeshHealthCheckScheduler(runtimeOf(agentType, published), registry);

            scheduler.start();
            try {
                scheduler.refresh(true);
                assertEquals(List.of("unhealthy"), published,
                    "'" + agentType + "' agent must suppress its heartbeat like any "
                        + "other agent type — the hook means the same thing everywhere");
                assertEquals(MeshHealthStatus.UNHEALTHY, registry.latest().health().status(),
                    "'" + agentType + "' agent must still reflect the verdict on /health");
            } finally {
                scheduler.stop();
            }
        }
    }

    @Test
    void noHealthCheckMeansNoTimerAndNoPublishing() {
        List<String> published = Collections.synchronizedList(new ArrayList<>());
        MeshHealthCheckRegistry empty = new MeshHealthCheckRegistry();
        MeshHealthCheckScheduler scheduler =
            new MeshHealthCheckScheduler(runtimeOf("mcp_agent", published), empty);

        scheduler.start();
        try {
            assertFalse(scheduler.isRunning(), "no check declared — nothing to schedule");
            scheduler.refresh(true);
            assertTrue(published.isEmpty());
            assertNull(empty.latest());
        } finally {
            scheduler.stop();
        }
    }

    @Test
    @Timeout(30)
    void startDoesNotBlockOnASlowHealthCheck() throws Exception {
        // A scaffolded provider's check is an HTTP call to a vendor. Running the
        // startup seed on the Spring lifecycle thread would stall application
        // boot for as long as the vendor takes to answer — a hung vendor would
        // hang the boot outright.
        java.util.concurrent.CountDownLatch entered = new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release = new java.util.concurrent.CountDownLatch(1);

        class SlowChecks {
            @MeshHealthCheck(ttlSeconds = 1)
            public MeshHealth check() {
                entered.countDown();
                try {
                    release.await();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                return MeshHealth.healthy();
            }
        }
        SlowChecks bean = new SlowChecks();
        MeshHealthCheckRegistry registry = new MeshHealthCheckRegistry();
        registry.register(bean, SlowChecks.class.getMethod("check"), 1);

        MeshHealthCheckScheduler scheduler = new MeshHealthCheckScheduler(
            runtimeOf("mcp_agent", Collections.synchronizedList(new ArrayList<>())), registry);

        long start = System.nanoTime();
        scheduler.start();
        long startMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start);

        try {
            assertTrue(entered.await(10, TimeUnit.SECONDS), "the seed must still run");
            assertTrue(startMs < 2000,
                "start() blocked on the health check for " + startMs + "ms");
        } finally {
            release.countDown();
            scheduler.stop();
        }
    }

    @Test
    void anErrorFromPublishingDoesNotKillTheRefreshLoop() {
        // A ScheduledExecutorService silently cancels ALL future runs when a
        // task throws. catch(Exception) would let an Error through — and the
        // agent would stop refreshing its health permanently, with nothing in
        // the logs after the first failure and no recovery short of a restart.
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.isRunning()).thenReturn(true);
        AgentSpec spec = new AgentSpec();
        spec.setAgentType("mcp_agent");
        when(runtime.getAgentSpec()).thenReturn(spec);
        when(runtime.updateHealth(anyString()))
            .thenThrow(new UnsatisfiedLinkError("mesh_update_health"));

        MeshHealthCheckRegistry registry = registryFor(new Checks());
        MeshHealthCheckScheduler scheduler = new MeshHealthCheckScheduler(runtime, registry);

        assertDoesNotThrow(() -> scheduler.refresh(true));
        assertNotNull(registry.latest(), "the verdict is still stored for /health");
        // And the next tick still runs.
        assertDoesNotThrow(() -> scheduler.refresh(true));
    }

    @Test
    void aFailingPublishDoesNotKillTheRefreshLoop() {
        // An escaping exception on a ScheduledExecutorService silently cancels
        // every future run — the agent would stop refreshing forever, with
        // nothing in the logs after the first failure.
        MeshRuntime runtime = mock(MeshRuntime.class);
        when(runtime.isRunning()).thenReturn(true);
        AgentSpec spec = new AgentSpec();
        spec.setAgentType("mcp_agent");
        when(runtime.getAgentSpec()).thenReturn(spec);
        when(runtime.updateHealth(anyString())).thenThrow(new RuntimeException("handle closed"));

        MeshHealthCheckRegistry registry = registryFor(new Checks());
        MeshHealthCheckScheduler scheduler = new MeshHealthCheckScheduler(runtime, registry);

        assertDoesNotThrow(() -> scheduler.refresh(true));
        assertNotNull(registry.latest(), "the verdict is still stored for /health");
    }

    private static void waitUntil(java.util.function.BooleanSupplier condition) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20);
        while (!condition.getAsBoolean()) {
            assertTrue(System.nanoTime() < deadline, "condition not met within 20s");
            Thread.sleep(50);
        }
    }
}
