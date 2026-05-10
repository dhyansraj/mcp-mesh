package io.mcpmesh.a2a;

/**
 * Raised when an {@link A2AJob} or {@link A2AStream} bridge observes a
 * terminal {@code state=failed} from the upstream A2A producer, OR when
 * the consumer's own polling loop fails terminally (network error,
 * malformed envelope) and the bridge surfaces it as a job failure
 * after attempting upstream cancel.
 *
 * <p>Mirrors the Python runtime's {@code A2AJobFailed} class.
 */
public final class A2AJobFailedException extends A2AJobException {

    public A2AJobFailedException(String message) {
        super(message);
    }

    public A2AJobFailedException(String message, Throwable cause) {
        super(message, cause);
    }
}
