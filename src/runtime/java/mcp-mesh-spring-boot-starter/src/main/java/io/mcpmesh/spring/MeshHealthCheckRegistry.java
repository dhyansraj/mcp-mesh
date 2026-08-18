package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthCheck;
import io.mcpmesh.MeshHealthStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * Holds the agent's single {@link MeshHealthCheck} and the latest verdict it
 * produced (issue #1474).
 *
 * <p>Two readers share this one result so they can never disagree:
 * {@link MeshHealthController} renders it on {@code /health} and {@code /ready},
 * and {@link MeshHealthCheckScheduler} publishes it to the mesh runtime, where
 * an unhealthy verdict suppresses the heartbeat.
 *
 * <p>Mirrors the storage half of Python's {@code health_check_manager} — with
 * the cache dropped. Python caches the result under {@code health_check_ttl} and
 * then explicitly invalidates that cache before every refresh, so the cache only
 * ever serves the endpoints between ticks. The scheduler here already runs on
 * exactly that period and stores what it computed, so the endpoints read the
 * same value with no expiry logic at all.
 */
public class MeshHealthCheckRegistry {

    private static final Logger log = LoggerFactory.getLogger(MeshHealthCheckRegistry.class);

    /** Python's {@code health_check_ttl} default. */
    public static final int DEFAULT_TTL_SECONDS = 15;

    /** Overrides {@link MeshHealthCheck#ttlSeconds()} when set. */
    public static final String TTL_ENV_VAR = "MCP_MESH_HEALTH_CHECK_TTL";

    private volatile Registration registration;
    private volatile Result latest;

    /** One discovered health check. */
    public record Registration(Object bean, Method method, int ttlSeconds) {
        public String describe() {
            return method.getDeclaringClass().getName() + "#" + method.getName();
        }
    }

    /** The most recent verdict plus when it was computed. */
    public record Result(MeshHealth health, Instant timestamp) {}

    /**
     * Record the agent's health check.
     *
     * @throws IllegalStateException when a second one is declared — Python
     *     allows exactly one {@code health_check} per agent, and silently
     *     picking one of two here would make routing depend on bean order.
     */
    public void register(Object bean, Method method, int ttlSeconds) {
        Registration existing = this.registration;
        if (existing != null) {
            throw new IllegalStateException(
                "Two @MeshHealthCheck methods found (" + existing.describe() + " and "
                    + method.getDeclaringClass().getName() + "#" + method.getName()
                    + "). An agent has exactly one health check — it is a single verdict "
                    + "about whether this agent should keep receiving traffic. Combine the "
                    + "probes into one method returning MeshHealth.");
        }
        method.setAccessible(true);
        this.registration = new Registration(bean, method, ttlSeconds);
        log.info("Registered @MeshHealthCheck {} (ttl={}s)",
            this.registration.describe(), ttlSeconds);
    }

    public boolean hasHealthCheck() {
        return registration != null;
    }

    public Registration registration() {
        return registration;
    }

    /** Effective refresh period: the annotation value, or {@link #TTL_ENV_VAR}. */
    public int ttlSeconds() {
        return ttlSeconds(System.getenv(TTL_ENV_VAR));
    }

    /**
     * The env-free core of {@link #ttlSeconds()}, so the resolution rules can be
     * driven directly instead of depending on the ambient environment (which the
     * JDK gives no supported way to set from a test).
     *
     * @param override raw {@link #TTL_ENV_VAR} value, or null for "not set"
     */
    int ttlSeconds(String override) {
        Registration reg = registration;
        int ttl = reg != null ? reg.ttlSeconds() : DEFAULT_TTL_SECONDS;
        if (override != null && !override.isBlank()) {
            try {
                int parsed = Integer.parseInt(override.trim());
                if (parsed >= 1) {
                    return parsed;
                }
                log.warn("{}={} is below the 1s minimum — using {}s", TTL_ENV_VAR, override, ttl);
            } catch (NumberFormatException e) {
                log.warn("{}={} is not an integer — using {}s", TTL_ENV_VAR, override, ttl);
            }
        }
        return ttl >= 1 ? ttl : DEFAULT_TTL_SECONDS;
    }

    /** The latest verdict, or null before the first run. */
    public Result latest() {
        return latest;
    }

    public void store(MeshHealth health) {
        this.latest = new Result(health, Instant.now());
    }

    /**
     * Run the registered check and convert whatever it returned into a
     * {@link MeshHealth}.
     *
     * <p>Never throws. A check that <b>throws</b> becomes {@link
     * MeshHealthStatus#DEGRADED}, not unhealthy, so the agent keeps
     * heartbeating — a buggy health check must not be able to withdraw a
     * working agent from the mesh. Same rule and same {@code checks} /
     * {@code errors} keys as Python's {@code _execute_health_check}.
     *
     * @return the verdict, or null when no check is registered
     */
    public MeshHealth execute() {
        Registration reg = registration;
        if (reg == null) {
            return null;
        }
        try {
            Object raw = reg.method().invoke(reg.bean());
            return coerce(raw);
        } catch (InvocationTargetException e) {
            Throwable cause = e.getCause() != null ? e.getCause() : e;
            log.warn("@MeshHealthCheck {} threw — reporting degraded (the agent keeps "
                + "heartbeating): {}", reg.describe(), cause.toString());
            return new MeshHealth(
                MeshHealthStatus.DEGRADED,
                Map.of("health_check_execution", false),
                List.of("Health check failed: " + cause));
        } catch (Exception e) {
            log.warn("@MeshHealthCheck {} could not be invoked — reporting degraded: {}",
                reg.describe(), e.toString());
            return new MeshHealth(
                MeshHealthStatus.DEGRADED,
                Map.of("health_check_execution", false),
                List.of("Health check failed: " + e));
        }
    }

    /**
     * {@code degraded} as a RETURN VALUE is deprecated (issue #1515).
     *
     * <p>The question a health check answers is binary: stay in dependency
     * resolution, or withdraw. {@code DEGRADED} and {@code HEALTHY} are the same
     * answer to it, so the third word buys a 503 on an endpoint nothing probes
     * and costs the failure rate of a name that reads like withdrawal to
     * everyone who picks it when their upstream is down.
     *
     * <p>The BEHAVIOUR is unchanged, deliberately: remapping it to
     * {@code UNHEALTHY} would fix the common intent and silently withdraw every
     * agent whose author used the word correctly.
     *
     * <p>Warned once per process, not once per refresh — the check re-runs every
     * TTL (15s by default), and a per-tick line would be several thousand
     * identical warnings a day from an agent doing what its author intended.
     */
    private static volatile boolean degradedReturnWarned = false;

    private static void warnDegradedReturnOnce() {
        if (degradedReturnWarned) {
            return;
        }
        degradedReturnWarned = true;
        log.warn("@MeshHealthCheck returned degraded — this agent stays in dependency "
            + "resolution and consumers will keep routing to it. Return "
            + "MeshHealth.unhealthy(...) to withdraw.");
    }

    /** Re-arm the once-per-process deprecation warning. Tests only. */
    static void resetDegradedReturnWarning() {
        degradedReturnWarned = false;
    }

    /**
     * Convert a health-check return value. The accepted shapes are enforced at
     * boot by {@link MeshHealthCheckBeanPostProcessor}, so the fallback here is
     * defence in depth, not a supported path — and it degrades rather than
     * withdrawing.
     *
     * <p>The runtime-assigned {@code DEGRADED} below does NOT warn — nothing the
     * author can act on happened. Only a {@code DEGRADED} the author SELECTED
     * does, and this is the single chokepoint for that:
     * {@link MeshHealth#degraded(String...)},
     * {@code withStatus(MeshHealthStatus.DEGRADED)},
     * {@code new MeshHealth(DEGRADED, ...)} and
     * {@link MeshHealth#of(String, String...)} given a readable
     * {@code "degraded"} all pass through here.
     *
     * <p>{@code of()} is the one route that can reach the {@link MeshHealth}
     * branch WITHOUT a selection: it maps a status string it cannot read to
     * {@code DEGRADED} too, so {@code return MeshHealth.of(vendorStatus)} with
     * {@code vendorStatus} of {@code "down"} would otherwise warn an author
     * about {@code degraded()}, an API they never called. Those verdicts carry
     * {@link MeshHealth#UNREADABLE_STATUS_CHECK} and are skipped here.
     */
    static MeshHealth coerce(Object raw) {
        if (raw instanceof MeshHealth health) {
            if (health.status() == MeshHealthStatus.DEGRADED && !health.isUnreadableStatus()) {
                warnDegradedReturnOnce();
            }
            return health;
        }
        if (raw instanceof Boolean ok) {
            // Python parity: True → healthy, False → unhealthy.
            return ok
                ? MeshHealth.healthy().withCheck("health_check", true)
                : MeshHealth.unhealthy("Health check returned false")
                    .withCheck("health_check", false);
        }
        return new MeshHealth(
            MeshHealthStatus.DEGRADED,
            Map.of("health_check_return_type", false),
            List.of("Invalid return type: " + (raw == null ? "null" : raw.getClass().getName())));
    }
}
