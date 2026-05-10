package io.mcpmesh.a2a;

/**
 * Base exception type for failures encountered by the A2A consumer client
 * (see {@link A2AClient}).
 *
 * <p>Mirrors the Python runtime's {@code RuntimeError} surface from
 * {@code mesh._a2a_consumer}: protocol-level errors (JSON-RPC error
 * envelopes, malformed responses, transport failures) bubble up as
 * {@code A2AException}; auth and timeout get dedicated subclasses
 * ({@link A2AAuthException}, {@link A2ATimeoutException}) so callers can
 * branch on them with regular {@code try / catch} blocks.
 *
 * <p>Unchecked because the rest of the mesh SDK favours {@link RuntimeException}
 * subtypes (see {@code io.mcpmesh.types.MeshToolCallException}).
 */
public class A2AException extends RuntimeException {

    public A2AException(String message) {
        super(message);
    }

    public A2AException(String message, Throwable cause) {
        super(message, cause);
    }
}
