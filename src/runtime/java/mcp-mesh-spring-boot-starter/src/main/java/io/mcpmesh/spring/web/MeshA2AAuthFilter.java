package io.mcpmesh.spring.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Bearer-token authentication gate for {@code @MeshA2A} surfaces (spec §6).
 *
 * <p>Applies only to {@code POST {path}} where {@code path} matches a
 * registered surface AND that surface declared {@code auth="bearer"}. The
 * agent-card endpoint ({@code GET {path}/.well-known/agent.json}) is always
 * reachable without auth (spec §6.2 + conformance checklist) so clients can
 * discover the authentication scheme before authenticating.
 *
 * <h2>Phase 1 semantics</h2>
 *
 * <p>The filter checks the {@code Authorization} header for:
 * <ol>
 *   <li>presence (a missing header is rejected);</li>
 *   <li>a {@code Bearer} scheme prefix (case-insensitive);</li>
 *   <li>a non-empty token after the {@code Bearer } prefix
 *       (whitespace-only counts as empty).</li>
 * </ol>
 *
 * <p>The filter MUST NOT validate the token value — no signature check, no
 * issuer/audience check, no expiry check. Value-level validation is Phase 2+
 * (spec §6.2 + Appendix B item 4).
 *
 * <h2>Error shape</h2>
 *
 * <p>Rejections return HTTP 401 with a JSON-RPC envelope carrying
 * {@code error.code = -32001} and {@code id = null} (the request body is
 * never parsed at this stage). The {@code -32001} code sits in the
 * implementation-defined {@code -32000} … {@code -32099} server-error range
 * and matches the Python producer exactly for cross-runtime parity.
 */
public class MeshA2AAuthFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(MeshA2AAuthFilter.class);

    /** Implementation-defined server-error code for authentication failures. */
    public static final int JSONRPC_AUTH_ERROR = -32001;

    private static final String AUTH_HEADER = "Authorization";
    private static final String BEARER_PREFIX = "Bearer ";

    private final MeshA2ARegistry registry;

    public MeshA2AAuthFilter(MeshA2ARegistry registry) {
        this.registry = registry;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        if (!"POST".equalsIgnoreCase(request.getMethod())) {
            chain.doFilter(request, response);
            return;
        }

        String path = normalizePath(request);
        MeshA2ARegistry.SurfaceMetadata surface = registry.getByPath(path);
        if (surface == null || !surface.bearerAuth()) {
            // Either not an A2A surface or no bearer gate configured —
            // the dispatcher (or other controllers) own this request.
            chain.doFilter(request, response);
            return;
        }

        String authz = request.getHeader(AUTH_HEADER);
        if (authz == null || authz.isEmpty()) {
            writeAuthError(response,
                "Authentication required: missing Authorization: Bearer <token> header");
            return;
        }
        // Case-insensitive prefix check on "Bearer ".
        if (authz.length() < BEARER_PREFIX.length()
            || !authz.substring(0, BEARER_PREFIX.length()).equalsIgnoreCase(BEARER_PREFIX)) {
            writeAuthError(response,
                "Authentication required: missing Authorization: Bearer <token> header");
            return;
        }
        String token = authz.substring(BEARER_PREFIX.length()).strip();
        if (token.isEmpty()) {
            writeAuthError(response,
                "Authentication required: empty bearer token in Authorization header");
            return;
        }

        // Phase 1: presence check only — DO NOT validate token value.
        // Value validation (signature/issuer/audience) is Phase 2 scope.
        chain.doFilter(request, response);
    }

    private void writeAuthError(HttpServletResponse response, String message) throws IOException {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        // Hand-rolled JSON to avoid an ObjectMapper dependency on the
        // filter path — the shape is fixed and small.
        String escapedMessage = escapeJsonString(message);
        String body = "{\"jsonrpc\":\"2.0\",\"error\":{\"code\":" + JSONRPC_AUTH_ERROR
            + ",\"message\":\"" + escapedMessage + "\"},\"id\":null}";
        response.getWriter().write(body);
        response.getWriter().flush();
    }

    private static String normalizePath(HttpServletRequest request) {
        String uri = request.getRequestURI();
        if (uri == null || uri.isEmpty()) {
            return "/";
        }
        String contextPath = request.getContextPath();
        if (contextPath != null && !contextPath.isEmpty() && uri.startsWith(contextPath)) {
            uri = uri.substring(contextPath.length());
            if (uri.isEmpty()) {
                uri = "/";
            }
        }
        if (uri.length() > 1 && uri.endsWith("/")) {
            uri = uri.substring(0, uri.length() - 1);
        }
        return uri;
    }

    private static String escapeJsonString(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\', '"' -> {
                    sb.append('\\');
                    sb.append(c);
                }
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                case '\b' -> sb.append("\\b");
                case '\f' -> sb.append("\\f");
                default -> {
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        return sb.toString();
    }
}
