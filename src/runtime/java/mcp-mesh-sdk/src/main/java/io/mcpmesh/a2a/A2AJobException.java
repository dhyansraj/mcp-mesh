package io.mcpmesh.a2a;

/**
 * Base exception for terminal failures of an {@link A2AJob} or
 * {@link A2AStream} bridge — i.e. the upstream task either reached
 * {@code state=failed} / {@code state=canceled}, or mesh-side
 * cancellation was propagated upstream during the bridge.
 *
 * <p>Distinct from the more generic {@link A2AException} (which covers
 * protocol-level errors — JSON-RPC error envelopes, malformed
 * responses, transport failures) so callers can branch on terminal
 * outcomes vs. transport errors with regular {@code try / catch}.
 *
 * <p>Mirrors the Python runtime's {@code A2AJobError} class from
 * {@code mesh._a2a_consumer} (issue #910 Phase 3).
 */
public class A2AJobException extends A2AException {

    public A2AJobException(String message) {
        super(message);
    }

    public A2AJobException(String message, Throwable cause) {
        super(message, cause);
    }
}
