package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthStatus;
import io.mcpmesh.MeshStartupCheck;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Holds the agent's single {@link MeshStartupCheck} and runs it on demand
 * (RFC #1502).
 *
 * <p>The sibling of {@link MeshHealthCheckRegistry}, with two structural
 * differences that both follow from what {@code startupProbe} does:
 *
 * <ul>
 *   <li><b>No stored latest result and no scheduler.</b> A {@code startupProbe}
 *       stops polling after its first success, so the check runs a handful of
 *       times at most. A cached verdict would only add a way for
 *       {@code /startupz} to answer with a result older than the probe that
 *       asked for it.</li>
 *   <li><b>A throw FAILS.</b> {@link MeshHealthCheckRegistry#execute} records a
 *       throw as {@link MeshHealthStatus#DEGRADED} so a buggy probe cannot
 *       withdraw a working provider. Here the question is whether a
 *       possibly-misconfigured agent may come up at all, and an indeterminate
 *       answer at boot is not a reason to let it through.</li>
 * </ul>
 */
public class MeshStartupCheckRegistry {

    private static final Logger log = LoggerFactory.getLogger(MeshStartupCheckRegistry.class);

    private volatile Registration registration;

    /** One discovered startup check. */
    public record Registration(Object bean, Method method) {
        public String describe() {
            return method.getDeclaringClass().getName() + "#" + method.getName();
        }
    }

    /** A startup verdict: whether the agent may come up, plus why not. */
    public record Verdict(boolean passed, Map<String, Object> checks, List<String> errors) {

        public static Verdict pass() {
            return new Verdict(true, Map.of(), List.of());
        }

        public static Verdict fail(String error, Map<String, Object> checks) {
            return new Verdict(false, checks, List.of(error));
        }
    }

    /**
     * Record the agent's startup check.
     *
     * @throws IllegalStateException when a second one is declared — silently
     *     picking one of two would make whether the pod comes up depend on bean
     *     order.
     */
    public void register(Object bean, Method method) {
        Registration existing = this.registration;
        if (existing != null) {
            throw new IllegalStateException(
                "Two @MeshStartupCheck methods found (" + existing.describe() + " and "
                    + method.getDeclaringClass().getName() + "#" + method.getName()
                    + "). An agent has exactly one startup check — it is a single verdict "
                    + "about whether this agent is configured well enough to start. Combine "
                    + "the probes into one method returning MeshHealth.");
        }
        method.setAccessible(true);
        this.registration = new Registration(bean, method);
        log.info("Registered @MeshStartupCheck {}", this.registration.describe());
    }

    public boolean hasStartupCheck() {
        return registration != null;
    }

    public Registration registration() {
        return registration;
    }

    /**
     * Run the registered check and reduce whatever it returned to a verdict.
     *
     * <p>Never throws. An agent that declared no check passes — default-true is
     * what makes this purely additive.
     */
    public Verdict execute() {
        Registration reg = registration;
        if (reg == null) {
            return Verdict.pass();
        }
        Object raw;
        try {
            raw = reg.method().invoke(reg.bean());
        } catch (InvocationTargetException e) {
            Throwable cause = e.getCause() != null ? e.getCause() : e;
            log.warn("@MeshStartupCheck {} threw — failing the startup probe: {}",
                reg.describe(), cause.toString());
            return Verdict.fail("Startup check failed: " + cause,
                Map.of("startup_check_execution", false));
        } catch (Exception e) {
            log.warn("@MeshStartupCheck {} could not be invoked — failing the startup probe: {}",
                reg.describe(), e.toString());
            return Verdict.fail("Startup check failed: " + e,
                Map.of("startup_check_execution", false));
        }
        return coerce(raw);
    }

    /**
     * Convert a startup-check return value. The accepted shapes are enforced at
     * boot by {@link MeshStartupCheckBeanPostProcessor}, so the fallback here is
     * defence in depth — and unlike the health path it fails rather than
     * degrading, because there is no partial credit for "am I configured".
     */
    static Verdict coerce(Object raw) {
        if (raw instanceof Boolean ok) {
            return ok
                ? new Verdict(true, Map.of("startup_check", true), List.of())
                : Verdict.fail("Startup check returned false",
                    Map.of("startup_check", false));
        }
        if (raw instanceof MeshHealth health) {
            if (health.status() == MeshHealthStatus.HEALTHY) {
                return new Verdict(true, health.checks(), List.of());
            }
            List<String> errors = health.errors().isEmpty()
                ? List.of("Startup check reported '" + health.status().wireValue() + "'")
                : health.errors();
            return new Verdict(false, health.checks(), errors);
        }
        String typeName = raw == null ? "null" : raw.getClass().getName();
        Map<String, Object> checks = new LinkedHashMap<>();
        checks.put("startup_check_return_type", false);
        return Verdict.fail("Invalid return type: " + typeName
            + ". A startup check returns boolean or " + MeshHealth.class.getName() + ".", checks);
    }
}
