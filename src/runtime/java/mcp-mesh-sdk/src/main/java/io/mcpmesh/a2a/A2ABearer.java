package io.mcpmesh.a2a;

/**
 * Bearer-token credential for an outbound A2A call.
 *
 * <p>Provide either a literal token via {@link #of(String)} or the name
 * of an environment variable via {@link #fromEnv(String)}. The header is
 * resolved at call time (per request, just before the HTTP send) so
 * rotating the env var between calls picks up the new value without
 * reconstructing the surrounding {@link A2AClient}.
 *
 * <p>Mirrors {@code mesh._a2a_consumer.A2ABearer} from the Python
 * runtime (issue #908 Phase 1).
 *
 * <h2>Example</h2>
 * <pre>{@code
 * A2AClient client = new A2AClient(
 *     "http://upstream.example.com/agents/date",
 *     "get-date",
 *     A2ABearer.fromEnv("UPSTREAM_TOKEN"));
 * }</pre>
 */
public final class A2ABearer {

    private final String token;
    private final String tokenEnv;

    private A2ABearer(String token, String tokenEnv) {
        this.token = token;
        this.tokenEnv = tokenEnv;
    }

    /**
     * Use a literal bearer token.
     *
     * @param token the bearer credential, must be non-null and non-blank
     */
    public static A2ABearer of(String token) {
        if (token == null || token.trim().isEmpty()) {
            throw new IllegalArgumentException("A2ABearer.of: token must be non-blank");
        }
        return new A2ABearer(token, null);
    }

    /**
     * Resolve the bearer token from the named environment variable on
     * each call.
     *
     * @param envVar the environment variable name, must be non-null and non-blank
     */
    public static A2ABearer fromEnv(String envVar) {
        if (envVar == null || envVar.trim().isEmpty()) {
            throw new IllegalArgumentException("A2ABearer.fromEnv: envVar must be non-blank");
        }
        return new A2ABearer(null, envVar);
    }

    /**
     * Build the {@code Authorization} header value at call time.
     *
     * @return the {@code Bearer <token>} string suitable for
     *         {@code Authorization} headers.
     * @throws A2AAuthException if neither the literal token nor the
     *         configured env var resolves to a non-blank value.
     */
    public String authorizationHeader() {
        String resolved = token;
        if (resolved == null && tokenEnv != null) {
            resolved = System.getenv(tokenEnv);
        }
        if (resolved == null || resolved.trim().isEmpty()) {
            throw new A2AAuthException(
                "A2ABearer: no token available (token_env="
                    + (tokenEnv == null ? "<unset>" : "'" + tokenEnv + "'")
                    + ", explicit_token="
                    + (token != null ? "set" : "unset")
                    + ")");
        }
        return "Bearer " + resolved;
    }
}
