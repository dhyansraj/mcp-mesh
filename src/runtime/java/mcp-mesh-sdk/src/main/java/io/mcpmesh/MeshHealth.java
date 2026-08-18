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
        // Null-tolerant, not List.copyOf: a null error string must not throw
        // out of the canonical constructor either — every other path
        // (withError, a direct `new MeshHealth(...)`) funnels through here.
        errors = errors == null || errors.isEmpty()
            ? List.of()
            : List.copyOf(errors.stream().filter(Objects::nonNull).toList());
    }

    /** Healthy, with no detail. */
    public static MeshHealth healthy() {
        return new MeshHealth(MeshHealthStatus.HEALTHY, null, null);
    }

    /**
     * Impaired but still serving — keeps heartbeating and stays in resolution.
     *
     * @param errors reasons, rendered into {@code /health}; nulls are dropped
     * @deprecated since 3.7.0 (issue #1515). The question a health check answers
     *     is binary — stay in dependency resolution, or withdraw — and this
     *     factory gives the same answer {@link #healthy()} does: the agent
     *     keeps heartbeating and consumers keep routing to it. It differs only
     *     in the status code of {@code /health}, which nothing probes.
     *     <p>Use {@link #healthy()} for an impairment you can serve through,
     *     recording the detail with {@link #withCheck(String, Object)} so an
     *     operator still sees it, and {@link #unhealthy(String...)} for one you
     *     cannot. To report an INDETERMINATE probe — one cut short, so it
     *     concluded nothing — throw: the runtime records that itself and keeps
     *     the agent in resolution.
     *     <p>Behaviour is unchanged and this still compiles and runs; it emits
     *     a one-time runtime warning. Removal no earlier than 4.0.
     */
    @Deprecated(since = "3.7.0")
    public static MeshHealth degraded(String... errors) {
        return new MeshHealth(MeshHealthStatus.DEGRADED, null, cleanErrors(errors));
    }

    /**
     * Cannot serve — suppresses the heartbeat, so the registry withdraws this
     * agent and consumers fail over to another provider.
     *
     * @param errors reasons, rendered into {@code /health} and {@code /ready};
     *               nulls are dropped
     */
    public static MeshHealth unhealthy(String... errors) {
        return new MeshHealth(MeshHealthStatus.UNHEALTHY, null, cleanErrors(errors));
    }

    /**
     * The {@link #checks()} key the runtime sets when it could not READ the
     * status it was given, as opposed to acting on one it could.
     *
     * <p>Same key and same {@code false} value TypeScript's
     * {@code normalizeHealthResult} uses, so {@code /health} reads identically
     * on both runtimes. It is also what tells the deprecation warning apart
     * from a real selection: a {@code DEGRADED} carrying this marker is the
     * runtime's verdict about an unreadable string, not the author's about
     * their upstream, and warning at them would be pointing at an API they
     * never used.
     */
    public static final String UNREADABLE_STATUS_CHECK = "health_check_status_value";

    /**
     * Build from a wire status string.
     *
     * <p>A value that cannot be read — including null — becomes the runtime's
     * own indeterminate verdict: {@link MeshHealthStatus#DEGRADED}, so the
     * agent keeps heartbeating and stays in resolution, carrying
     * {@link #UNREADABLE_STATUS_CHECK} and an error naming the value so an
     * operator sees on {@code /health} that the status was the problem.
     * Deliberately not {@link MeshHealthStatus#UNHEALTHY}: withdrawing an agent
     * because its status string could not be parsed is a far worse failure than
     * keeping it.
     *
     * @param status wire value: {@code healthy} / {@code degraded} / {@code unhealthy}
     * @param errors reasons; nulls are dropped
     */
    public static MeshHealth of(String status, String... errors) {
        MeshHealthStatus parsed = MeshHealthStatus.parseWire(status);
        if (parsed == null) {
            List<String> reasons = new ArrayList<>(cleanErrors(errors));
            reasons.add("Unrecognized health status: " + status);
            return new MeshHealth(
                MeshHealthStatus.DEGRADED, Map.of(UNREADABLE_STATUS_CHECK, false), reasons);
        }
        return new MeshHealth(parsed, null, cleanErrors(errors));
    }

    /**
     * Whether this verdict is one the RUNTIME assigned because it could not
     * read the status it was handed, rather than one the author selected.
     *
     * <p>Only {@link #of(String, String...)} produces one — every other route
     * to {@code DEGRADED} on this type ({@link #degraded(String...)},
     * {@link #withStatus(MeshHealthStatus)}, the canonical constructor) is a
     * choice — and it is the one the deprecation warning must skip.
     */
    public boolean isUnreadableStatus() {
        return status == MeshHealthStatus.DEGRADED
            && Boolean.FALSE.equals(checks.get(UNREADABLE_STATUS_CHECK));
    }

    /**
     * Drop nulls (and a null array) instead of letting {@link List#of} throw.
     *
     * <p>{@code unhealthy(null)} used to raise a {@link NullPointerException}
     * out of the health check, which the runtime then recorded as DEGRADED —
     * so an agent that explicitly declared itself unable to serve kept
     * heartbeating. The requested STATUS is what routing depends on; a missing
     * error string is a cosmetic defect and must not change it.
     */
    private static List<String> cleanErrors(String... errors) {
        if (errors == null || errors.length == 0) {
            return List.of();
        }
        List<String> cleaned = new ArrayList<>(errors.length);
        for (String error : errors) {
            if (error != null) {
                cleaned.add(error);
            }
        }
        return cleaned;
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
