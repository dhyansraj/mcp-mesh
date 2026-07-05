package io.mcpmesh.types;

/**
 * Thrown when a {@link io.mcpmesh.McpMeshService} view is below its declared
 * availability floor ({@code minAvailable}).
 *
 * <p>When fewer than {@code minAvailable} of the view's methods currently
 * resolve to a provider, EVERY facade call fails with this exception rather
 * than delegating — a consumer-local circuit breaker with no wire effect. It
 * carries the view interface name and the current/required availability counts
 * so the failure is actionable.
 *
 * <p>Distinct from {@link MeshToolUnavailableException}, which is thrown by a
 * single unresolved capability proxy. A view whose floor is satisfied delegates
 * normally, and an individual optional-missing method may still raise
 * {@code MeshToolUnavailableException} for its own call.
 */
public class MeshServiceUnavailableException extends RuntimeException {

    private final String service;
    private final int methodsAvailable;
    private final int methodsTotal;
    private final int minAvailable;

    public MeshServiceUnavailableException(
            String service, int methodsAvailable, int methodsTotal, int minAvailable) {
        super("Mesh service view unavailable (" + service + "): "
            + methodsAvailable + "/" + methodsTotal + " method(s) resolved, "
            + "below the declared minAvailable=" + minAvailable + " floor");
        this.service = service;
        this.methodsAvailable = methodsAvailable;
        this.methodsTotal = methodsTotal;
        this.minAvailable = minAvailable;
    }

    /**
     * Get the service-view interface name that was below its floor.
     *
     * @return The view interface name
     */
    public String getService() {
        return service;
    }

    /**
     * Get the number of view methods currently resolving to a provider.
     *
     * @return The available-method count
     */
    public int getMethodsAvailable() {
        return methodsAvailable;
    }

    /**
     * Get the total number of dependency-bound view methods.
     *
     * @return The total method count
     */
    public int getMethodsTotal() {
        return methodsTotal;
    }

    /**
     * Get the declared availability floor.
     *
     * @return The {@code minAvailable} floor
     */
    public int getMinAvailable() {
        return minAvailable;
    }
}
