package io.mcpmesh.spring.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Adds the SSE-buffering hints that Spring's
 * {@code ServerResponse.sse(...)} helper does not set on its own (spec
 * §4.6 / §5.1):
 * <ul>
 *   <li>{@code Cache-Control: no-cache} — stops intermediaries from
 *       caching mid-flight events;</li>
 *   <li>{@code X-Accel-Buffering: no} — defeats nginx response
 *       buffering;</li>
 *   <li>{@code Connection: keep-alive} — preserves the long-lived
 *       connection.</li>
 * </ul>
 *
 * <p>The filter peeks at the {@code Accept} header to decide whether to
 * stamp the headers — only requests that ask for {@code text/event-stream}
 * are affected. {@code POST {path}} requests for {@code tasks/send} (which
 * default to {@code application/json}) are untouched, so curl-style sync
 * clients see the regular JSON-RPC response shape.
 *
 * <p>Setting headers via a filter (rather than {@code ServerResponse}
 * post-processing) is the canonical Spring-MVC pattern when the response
 * body is delivered through an async/streaming mechanism — the body bypasses
 * the regular {@code BodyBuilder} chain so header customisations applied
 * after {@code sse()} return don't reach the wire.
 *
 * <p>Registered at {@code Ordered.HIGHEST_PRECEDENCE + 6} from
 * {@code MeshAutoConfiguration} so it sits BETWEEN the bearer-auth gate
 * (which rejects unauthenticated requests first) and the dispatcher.
 */
public class MeshA2ASseHeaderFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(MeshA2ASseHeaderFilter.class);

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String accept = request.getHeader("Accept");
        if (accept != null && accept.contains("text/event-stream")) {
            response.setHeader("Cache-Control", "no-cache");
            response.setHeader("X-Accel-Buffering", "no");
            response.setHeader("Connection", "keep-alive");
            log.debug("SSE buffering hints stamped on {} {}", request.getMethod(), request.getRequestURI());
        }
        chain.doFilter(request, response);
    }
}
