package io.mcpmesh.a2a;

/**
 * Raised when an {@link A2AJob} or {@link A2AStream} bridge observes a
 * terminal {@code state=canceled} (or the UK spelling
 * {@code cancelled}) from the upstream A2A producer, OR when mesh-side
 * cancellation (via {@link io.mcpmesh.JobController#isCancelled()})
 * was propagated upstream via {@code tasks/cancel} during a bridge.
 *
 * <p>Mirrors the Python runtime's {@code A2AJobCanceled} class.
 */
public final class A2AJobCanceledException extends A2AJobException {

    public A2AJobCanceledException(String message) {
        super(message);
    }

    public A2AJobCanceledException(String message, Throwable cause) {
        super(message, cause);
    }
}
