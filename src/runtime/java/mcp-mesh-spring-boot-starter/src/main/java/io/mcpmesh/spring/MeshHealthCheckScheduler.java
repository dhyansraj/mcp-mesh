package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Re-runs the {@link io.mcpmesh.MeshHealthCheck} on a timer and acts on the
 * verdict (issue #1474).
 *
 * <p>Each tick stores the result for {@link MeshHealthController} and reports it
 * to the mesh runtime, where {@code unhealthy} suppresses the heartbeat so the
 * registry withdraws this agent from dependency resolution. The TTL is
 * therefore the detection latency in <b>both</b> directions — outage and
 * recovery. Mirrors Python's {@code update_health_result} refresh task.
 *
 * <h2>Why a ScheduledExecutorService and not {@code @Scheduled}</h2>
 *
 * <p>{@code @Scheduled} needs {@code @EnableScheduling}, which a starter cannot
 * turn on without changing the HOST application: it registers a
 * {@code TaskScheduler} and activates every {@code @Scheduled} method in the
 * user's code, so adding the mesh dependency would start running their jobs.
 * Worse, Spring's default scheduler is a single-threaded pool shared with those
 * jobs — one slow user task would delay the mesh health refresh, and a health
 * refresh that stalls is an agent that cannot be withdrawn. And the period is
 * per-annotation ({@code ttlSeconds}), which {@code fixedDelay} cannot express
 * without a SpEL indirection through a property.
 *
 * <p>One daemon thread we own, with a lifecycle bound to
 * {@link SmartLifecycle}, is the same pattern {@link MeshEventProcessor}
 * already uses for the event loop.
 */
public class MeshHealthCheckScheduler implements SmartLifecycle {

    private static final Logger log = LoggerFactory.getLogger(MeshHealthCheckScheduler.class);

    /** After {@link MeshRuntime} (MAX-100) and {@link MeshEventProcessor} (MAX-50). */
    private static final int LIFECYCLE_PHASE = Integer.MAX_VALUE - 40;

    /**
     * Agent types whose health verdict must never suppress the heartbeat.
     *
     * <p>A route ({@code api}) or A2A agent is a fan-out point that many
     * requests enter through: withdrawing a provider is correct, withdrawing
     * the gateway takes the application down. Python encodes the same asymmetry
     * by giving its API and A2A pipelines no health-refresh loop at all.
     */
    private static final Set<String> NEVER_WITHDRAWN = Set.of("api", "a2a");

    private final MeshRuntime runtime;
    private final MeshHealthCheckRegistry registry;
    private final AtomicBoolean running = new AtomicBoolean(false);

    private volatile ScheduledExecutorService executor;
    private volatile boolean publishToRuntime = true;

    public MeshHealthCheckScheduler(MeshRuntime runtime, MeshHealthCheckRegistry registry) {
        this.runtime = runtime;
        this.registry = registry;
    }

    @Override
    public int getPhase() {
        return LIFECYCLE_PHASE;
    }

    @Override
    public void start() {
        if (!registry.hasHealthCheck()) {
            // Nothing declared — no timer, no thread. This is also what keeps
            // an agent without a health check behaving exactly as before.
            return;
        }
        if (!running.compareAndSet(false, true)) {
            return;
        }

        this.publishToRuntime = !NEVER_WITHDRAWN.contains(agentType());
        int ttl = registry.ttlSeconds();

        if (publishToRuntime) {
            log.info("Health check {} runs every {}s; an unhealthy verdict stops the heartbeat "
                + "and withdraws this agent from dependency resolution",
                registry.registration().describe(), ttl);
        } else {
            log.info("Health check {} runs every {}s and feeds /health and /ready only — the "
                + "heartbeat is never suppressed on an '{}' agent (a gateway is a fan-out "
                + "point; withdrawing it takes the application down)",
                registry.registration().describe(), ttl, agentType());
        }

        // Seed the endpoints immediately, but do NOT publish (Python parity).
        // A check that fails during boot — a pool not warm yet, a lazily-built
        // client — must not withdraw an agent that has only just registered.
        // The first published verdict is one TTL later, once the agent is up.
        refresh(false);

        executor = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "mesh-health-check");
            t.setDaemon(true);
            return t;
        });
        // Fixed DELAY, not rate: a check that takes longer than its TTL (a
        // vendor probe timing out is exactly that) must not queue up back-to-back
        // runs against an already-struggling upstream.
        executor.scheduleWithFixedDelay(
            () -> refresh(true), ttl, ttl, TimeUnit.SECONDS);
    }

    @Override
    public void stop() {
        if (!running.compareAndSet(true, false)) {
            return;
        }
        ScheduledExecutorService ex = executor;
        executor = null;
        if (ex == null) {
            return;
        }
        log.debug("Stopping health-check scheduler");
        ex.shutdownNow();
        try {
            if (!ex.awaitTermination(5, TimeUnit.SECONDS)) {
                log.warn("Health-check thread did not stop within 5s");
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public boolean isRunning() {
        return running.get();
    }

    /**
     * Run the check, store the verdict, and (optionally) report it to the
     * runtime.
     *
     * <p>Never throws: this runs on a scheduled executor, where an escaping
     * exception silently cancels all future runs — the agent would stop
     * refreshing its health forever, with nothing in the logs after the first
     * failure.
     */
    void refresh(boolean publish) {
        MeshHealth health;
        try {
            health = registry.execute();
        } catch (Throwable t) {
            // registry.execute() already converts a throwing check to DEGRADED;
            // reaching here means the conversion itself failed.
            log.warn("Health check refresh failed unexpectedly", t);
            return;
        }
        if (health == null) {
            return;
        }

        registry.store(health);

        if (health.status() == MeshHealthStatus.UNHEALTHY) {
            log.warn("Health check reports UNHEALTHY: {}", health.errors());
        } else {
            log.debug("Health check reports {}", health.status());
        }

        if (!publish || !publishToRuntime) {
            return;
        }
        try {
            runtime.updateHealth(health.status().wireValue());
        } catch (Exception e) {
            log.warn("Failed to report health status '{}' to the mesh runtime: {}",
                health.status(), e.toString());
        }
    }

    private String agentType() {
        try {
            if (runtime != null && runtime.getAgentSpec() != null) {
                String type = runtime.getAgentSpec().getAgentType();
                return type == null ? "" : type;
            }
        } catch (Exception e) {
            log.debug("Could not read agent type: {}", e.toString());
        }
        return "";
    }
}
