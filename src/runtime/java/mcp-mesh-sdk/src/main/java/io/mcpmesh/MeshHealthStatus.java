package io.mcpmesh;

/**
 * The three health verdicts a {@link MeshHealthCheck} can produce (issue #1474).
 *
 * <p>The wire values match Python's {@code HealthStatusType} and the Rust core's
 * {@code HealthStatus} exactly, so a Java agent, a Python agent and the registry
 * all mean the same thing by each word.
 */
public enum MeshHealthStatus {

    /** Fully operational. The agent heartbeats and stays in resolution. */
    HEALTHY("healthy"),

    /**
     * Where the RUNTIME puts a verdict it could not trust: a check that threw,
     * a check it could not invoke, an unusable return type, and a status string
     * it could not parse. The agent keeps heartbeating and stays in resolution —
     * an indeterminate probe concluded nothing about the upstream, and
     * withdrawing a working agent over one is the worse failure.
     *
     * <p>The enum constant is not deprecated: it names the verdict the runtime
     * assigns and the one {@code /health} reports. SELECTING it from a health
     * check is deprecated (issue #1515) — see
     * {@link MeshHealth#degraded(String...)}. It is indistinguishable from
     * {@link #HEALTHY} on every mesh path, so the runtime warns once and keeps
     * the agent serving.
     */
    DEGRADED("degraded"),

    /**
     * Cannot serve requests. The <b>only</b> verdict that suppresses the
     * heartbeat and withdraws the agent from dependency resolution.
     */
    UNHEALTHY("unhealthy");

    private final String wireValue;

    MeshHealthStatus(String wireValue) {
        this.wireValue = wireValue;
    }

    /** The lowercase cross-runtime wire form ({@code "healthy"}, ...). */
    public String wireValue() {
        return wireValue;
    }

    @Override
    public String toString() {
        return wireValue;
    }

    /**
     * Parse a wire value, mapping anything unrecognized to {@link #DEGRADED}.
     *
     * <p>Deliberately NOT {@link #UNHEALTHY}: withdrawing an agent from the mesh
     * because its status string could not be read is a far worse failure than
     * keeping it. Mirrors Python's {@code publish_health_status_to_core}.
     *
     * <p>Total, so it cannot report WHICH of the two things happened — a status
     * the author wrote as {@code "degraded"}, or one the runtime could not read.
     * Callers that must tell those apart use {@link #parseWire(String)}; this is
     * for the ones that just need a verdict.
     *
     * @param value wire value; may be null
     * @return the matching status, or {@link #DEGRADED}
     */
    public static MeshHealthStatus fromWire(String value) {
        MeshHealthStatus parsed = parseWire(value);
        return parsed != null ? parsed : DEGRADED;
    }

    /**
     * Parse a wire value, reporting an unreadable one DISTINCTLY.
     *
     * <p>{@link #fromWire(String)} folds "the author wrote degraded" and "the
     * runtime could not read this" into the same constant, and the two must not
     * be treated the same: only the first is a choice the author made, and only
     * the first is deprecated (issue #1515). Returning null for the second is
     * what lets {@link MeshHealth#of(String, String...)} record it as the
     * runtime's own indeterminate verdict rather than as a selection, so the
     * deprecation warning cannot fire at an author who never used the API.
     *
     * @param value wire value; may be null
     * @return the matching status, or null when there is none
     */
    public static MeshHealthStatus parseWire(String value) {
        if (value != null) {
            for (MeshHealthStatus status : values()) {
                if (status.wireValue.equalsIgnoreCase(value.trim())) {
                    return status;
                }
            }
        }
        return null;
    }
}
