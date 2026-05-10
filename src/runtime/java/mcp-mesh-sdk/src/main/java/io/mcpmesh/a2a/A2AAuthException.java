package io.mcpmesh.a2a;

/**
 * Raised by {@link A2ABearer#authorizationHeader()} when neither the
 * literal token nor the configured environment variable yields a
 * non-empty bearer value at call time.
 *
 * <p>Distinct from the generic {@link A2AException} so callers that wire
 * a credential at boot can surface a clearer "credential missing /
 * misconfigured" error to operators instead of a generic protocol
 * failure.
 */
public final class A2AAuthException extends A2AException {

    public A2AAuthException(String message) {
        super(message);
    }

    public A2AAuthException(String message, Throwable cause) {
        super(message, cause);
    }
}
