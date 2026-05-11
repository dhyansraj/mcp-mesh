package io.mcpmesh.spring.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

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
        if (acceptsEventStream(request.getHeader("Accept"))) {
            response.setHeader("Cache-Control", "no-cache");
            response.setHeader("X-Accel-Buffering", "no");
            response.setHeader("Connection", "keep-alive");
            log.debug("SSE buffering hints stamped on {} {}", request.getMethod(), request.getRequestURI());
        }
        chain.doFilter(request, response);
    }

    /**
     * Returns true when the {@code Accept} header asks for
     * {@code text/event-stream}. Uses Spring's {@link MediaType#parseMediaTypes}
     * so case ("TEXT/EVENT-STREAM"), parameter suffixes ("text/event-stream;
     * charset=UTF-8"), and compound values ("application/json,
     * text/event-stream;q=0.9") are all handled correctly — a raw
     * {@code String.contains("text/event-stream")} check is brittle on all
     * three counts.
     */
    static boolean acceptsEventStream(String acceptHeader) {
        if (acceptHeader == null || acceptHeader.isBlank()) {
            return false;
        }
        try {
            List<MediaType> media = MediaType.parseMediaTypes(acceptHeader);
            for (MediaType m : media) {
                if (m.isCompatibleWith(MediaType.TEXT_EVENT_STREAM)) {
                    return true;
                }
            }
        } catch (org.springframework.http.InvalidMediaTypeException
            | org.springframework.util.InvalidMimeTypeException e) {
            // Malformed Accept header: fall back to a defensive substring
            // check so we don't drop legitimate SSE clients on a header parse
            // failure that's outside our control. Both Spring exception types
            // are caught — different Spring versions raise different subclasses.
            return acceptHeader.toLowerCase().contains("text/event-stream");
        }
        return false;
    }
}
