package io.mcpmesh;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * The result of a {@link MeshHealthCheck} (issue #1474).
 *
 * <p>Carries the same three things Python's {@code health_check} dict does,
 * because they feed the same two consumers: a {@code status} that decides
 * whether the agent stays in dependency resolution, and {@code checks} +
 * {@code errors} that {@code /health} reports so an operator can see <i>which</i>
 * probe failed and why.
 *
 * <p>A record rather than a {@code Map<String, Object>}: the status is the field
 * the mesh acts on, and a map makes it a string that can be misspelled into
 * silence. Here a wrong status does not compile. The detail stays a map because
 * it genuinely is open-ended — one provider's {@code anthropic_api_reachable} is
 * another's {@code pool_connections_free} — and it is rendered straight into the
 * {@code /health} JSON body.
 *
 * <p>Instances are immutable; the {@code with*} methods return copies, so a
 * check reads as a chain:
 *
 * <pre>{@code
 * return MeshHealth.unhealthy("ANTHROPIC_API_KEY not set")
 *     .withCheck("anthropic_api_key_present", false);
 * }</pre>
 *
 * @param status the verdict — the only field that affects mesh routing
 * @param checks per-probe detail, rendered into {@code /health}; never null
 * @param errors human-readable failure reasons, rendered into {@code /health}
 *               and {@code /ready}; never null
 */
public record MeshHealth(
    MeshHealthStatus status,
    Map<String, Object> checks,
    List<String> errors) {

    public MeshHealth {
        Objects.requireNonNull(status, "status");
        checks = checks == null || checks.isEmpty()
            ? Map.of()
            : Collections.unmodifiableMap(new LinkedHashMap<>(checks));
        errors = errors == null || errors.isEmpty()
            ? List.of()
            : List.copyOf(errors);
    }

    /** Healthy, with no detail. */
    public static MeshHealth healthy() {
        return new MeshHealth(MeshHealthStatus.HEALTHY, null, null);
    }

    /**
     * Impaired but still serving — keeps heartbeating and stays in resolution.
     *
     * @param errors reasons, rendered into {@code /health}
     */
    public static MeshHealth degraded(String... errors) {
        return new MeshHealth(MeshHealthStatus.DEGRADED, null, List.of(errors));
    }

    /**
     * Cannot serve — suppresses the heartbeat, so the registry withdraws this
     * agent and consumers fail over to another provider.
     *
     * @param errors reasons, rendered into {@code /health} and {@code /ready}
     */
    public static MeshHealth unhealthy(String... errors) {
        return new MeshHealth(MeshHealthStatus.UNHEALTHY, null, List.of(errors));
    }

    /**
     * Build from a wire status string, mapping anything unrecognized to
     * {@link MeshHealthStatus#DEGRADED} rather than unhealthy.
     *
     * @param status wire value: {@code healthy} / {@code degraded} / {@code unhealthy}
     */
    public static MeshHealth of(String status, String... errors) {
        return new MeshHealth(MeshHealthStatus.fromWire(status), null, List.of(errors));
    }

    /** A copy with one more entry in {@link #checks()}. */
    public MeshHealth withCheck(String name, Object value) {
        Map<String, Object> merged = new LinkedHashMap<>(checks);
        merged.put(name, value);
        return new MeshHealth(status, merged, errors);
    }

    /** A copy with {@code additional} merged into {@link #checks()}. */
    public MeshHealth withChecks(Map<String, Object> additional) {
        if (additional == null || additional.isEmpty()) {
            return this;
        }
        Map<String, Object> merged = new LinkedHashMap<>(checks);
        merged.putAll(additional);
        return new MeshHealth(status, merged, errors);
    }

    /** A copy with one more entry in {@link #errors()}. */
    public MeshHealth withError(String error) {
        List<String> merged = new ArrayList<>(errors);
        merged.add(error);
        return new MeshHealth(status, checks, merged);
    }

    /** A copy carrying a different verdict. */
    public MeshHealth withStatus(MeshHealthStatus newStatus) {
        return new MeshHealth(newStatus, checks, errors);
    }

    /** Whether this verdict keeps the agent in dependency resolution. */
    public boolean isServing() {
        return status != MeshHealthStatus.UNHEALTHY;
    }
}
