package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

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
 * registry withdraws this agent from dependency resolution. The TTL is the
 * <b>cadence</b> of that check, not the end-to-end latency in either
 * direction: withdrawal costs up to one TTL plus the registry's staleness
 * window once heartbeats stop, and recovery costs up to one TTL plus the
 * heartbeat resume and re-register round trip. Mirrors Python's
 * {@code update_health_result} refresh task.
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

    private final MeshRuntime runtime;
    private final MeshHealthCheckRegistry registry;
    private final AtomicBoolean running = new AtomicBoolean(false);

    private volatile ScheduledExecutorService executor;

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

        int ttl = registry.ttlSeconds();

        // EVERY agent type publishes, route and A2A gateways included (RFC
        // #1502 step 3). #1473 exempted them because withdrawing a fan-out
        // point "takes the application down" — step 2 removed that harm.
        // Heartbeat suppression stops registry traffic ONLY: the servlet
        // container keeps serving, resolved dependencies are retained (#1131),
        // and /ready reports the mesh runtime rather than the verdict, so the
        // pod stays in its Service endpoints and keeps taking ingress. A
        // gateway that reports unavailable stops being DISCOVERED; it does not
        // go dark. The hook means the same thing on every agent type — "I am
        // not available" — and mesh does the same thing with it everywhere:
        // it stops wiring that agent. What differs is topology, not meaning.
        log.info("Health check {} runs every {}s; an unhealthy verdict stops the heartbeat "
            + "and withdraws this agent from dependency resolution",
            registry.registration().describe(), ttl);

        executor = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "mesh-health-check");
            t.setDaemon(true);
            return t;
        });

        // Seed the endpoints, but do NOT publish (Python parity). A check that
        // fails during boot — a pool not warm yet, a lazily-built client — must
        // not withdraw an agent that has only just registered. The first
        // PUBLISHED verdict is one TTL later, once the agent is up.
        //
        // Submitted to the executor rather than run inline: a scaffolded
        // provider's check is an HTTP call to a vendor, and running it on the
        // Spring lifecycle thread would stall application startup for as long
        // as that vendor takes to answer — a hung vendor would hang the boot.
        // It shares the single-threaded executor with the periodic task, so the
        // seed still strictly precedes the first scheduled refresh.
        executor.execute(() -> refresh(false));

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
     * Run the check, store the verdict, and (unless this is the startup seed)
     * report it to the runtime.
     *
     * <p>Never throws — {@code Throwable}, not {@code Exception}. This runs on
     * a {@link java.util.concurrent.ScheduledExecutorService}, which silently
     * cancels all future runs when a task throws. A single {@code Error} (an
     * {@code UnsatisfiedLinkError} from the native handle, an
     * {@code OutOfMemoryError} in a user check) would therefore stop health
     * refreshes permanently, with nothing in the logs after the first failure
     * and no recovery short of a restart — the worst possible failure for a
     * mechanism whose entire job is to notice failures.
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

        if (!publish) {
            return;
        }
        try {
            runtime.updateHealth(health.status().wireValue());
        } catch (Throwable t) {
            // Throwable, not Exception: see the method comment — an Error
            // escaping here would cancel every future refresh silently.
            log.warn("Failed to report health status '{}' to the mesh runtime: {}",
                health.status(), t.toString());
        }
    }
}
