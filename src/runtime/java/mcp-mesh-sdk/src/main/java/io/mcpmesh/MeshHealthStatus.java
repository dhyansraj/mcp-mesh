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
     * Working, but impaired. Still heartbeats and stays in resolution — the
     * mesh does not withdraw an agent that says it can still serve.
     *
     * <p>Also where the runtime puts a verdict it could not trust: a check that
     * threw, and a status string it could not parse.
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
     * @param value wire value; may be null
     * @return the matching status, or {@link #DEGRADED}
     */
    public static MeshHealthStatus fromWire(String value) {
        if (value != null) {
            for (MeshHealthStatus status : values()) {
                if (status.wireValue.equalsIgnoreCase(value.trim())) {
                    return status;
                }
            }
        }
        return DEGRADED;
    }
}
