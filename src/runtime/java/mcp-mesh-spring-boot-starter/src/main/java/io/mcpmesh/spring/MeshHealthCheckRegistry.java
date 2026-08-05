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
        Registration reg = registration;
        int ttl = reg != null ? reg.ttlSeconds() : DEFAULT_TTL_SECONDS;
        String override = System.getenv(TTL_ENV_VAR);
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
     * Convert a health-check return value. The accepted shapes are enforced at
     * boot by {@link MeshHealthCheckBeanPostProcessor}, so the fallback here is
     * defence in depth, not a supported path — and it degrades rather than
     * withdrawing.
     */
    static MeshHealth coerce(Object raw) {
        if (raw instanceof MeshHealth health) {
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
