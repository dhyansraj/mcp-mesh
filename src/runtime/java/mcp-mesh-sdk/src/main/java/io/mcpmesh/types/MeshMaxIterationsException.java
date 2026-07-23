package io.mcpmesh.types;

/**
 * Thrown when a provider-managed LLM agentic loop exhausts its
 * {@code max_iterations} cap without reaching a final response (issue #1355).
 *
 * <p>Exhaustion is a loud, typed failure on the mainline provider-managed-loop
 * path — never a fabricated answer returned on the success channel. Per the
 * #1247 envelope contract, {@code content} is always the answer string, so the
 * exhaustion discriminant rides a namespaced sibling field
 * ({@code _mesh_stop_reason: "max_iterations"}) on the reply envelope; the
 * consumer reads it and raises this exception instead of returning the prior
 * assistant text. The human-readable message lives only here — never on the
 * wire.
 *
 * <p>Parity: mirrors Python's {@code MaxIterationsError(iteration_count,
 * max_allowed)} and TypeScript's {@code MaxIterationsError}. Carries the same
 * two counts for actionable diagnostics.
 */
public class MeshMaxIterationsException extends RuntimeException {

    private final int iterationCount;
    private final int maxAllowed;

    public MeshMaxIterationsException(int iterationCount, int maxAllowed) {
        super("Exceeded maximum " + maxAllowed + " iterations without reaching final response");
        this.iterationCount = iterationCount;
        this.maxAllowed = maxAllowed;
    }

    /**
     * Get the number of iterations that were attempted.
     *
     * @return The iteration count
     */
    public int getIterationCount() {
        return iterationCount;
    }

    /**
     * Get the maximum number of iterations allowed.
     *
     * @return The configured cap
     */
    public int getMaxAllowed() {
        return maxAllowed;
    }
}
