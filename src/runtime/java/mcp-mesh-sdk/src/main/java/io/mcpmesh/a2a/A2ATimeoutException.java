package io.mcpmesh.a2a;

/**
 * Raised by {@link A2AClient#send} when a polled task does not reach a
 * terminal state ({@code completed} / {@code failed} / {@code canceled})
 * within the user-supplied timeout.
 *
 * <p>Equivalent to the Python runtime's {@code TimeoutError} surface from
 * {@code mesh._a2a_consumer}.
 */
public final class A2ATimeoutException extends A2AException {

    public A2ATimeoutException(String message) {
        super(message);
    }

    public A2ATimeoutException(String message, Throwable cause) {
        super(message, cause);
    }
}
