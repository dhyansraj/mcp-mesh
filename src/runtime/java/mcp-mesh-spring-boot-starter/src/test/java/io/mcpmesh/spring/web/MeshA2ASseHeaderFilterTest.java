package io.mcpmesh.spring.web;

import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.lang.reflect.Method;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link MeshA2ASseHeaderFilter} — the SSE buffering-hints
 * filter (spec §4.6 / §5.1).
 *
 * <p>The filter looks at the request's {@code Accept} header. When the
 * client asks for {@code text/event-stream}, the filter stamps the three
 * SSE-friendly headers per spec §4.6 / §5.1:
 * <ul>
 *   <li>{@code Cache-Control: no-cache}</li>
 *   <li>{@code X-Accel-Buffering: no}</li>
 *   <li>{@code Connection: keep-alive}</li>
 * </ul>
 *
 * <p>Non-SSE requests (e.g., {@code Accept: application/json} or no Accept
 * header at all) MUST NOT have these headers stamped — curl-style sync
 * clients see the regular JSON-RPC response.
 *
 * <p>Uses Spring's {@link MockHttpServletRequest} / {@link MockHttpServletResponse}
 * — same idiom Spring Boot's own tests use for filter-level coverage.
 */
@DisplayName("MeshA2ASseHeaderFilter — SSE buffering hints (spec §4.6 / §5.1)")
class MeshA2ASseHeaderFilterTest {

    private MeshA2ASseHeaderFilter filter;
    private FilterChain chain;
    private AtomicInteger chainInvocations;

    @BeforeEach
    void setUp() {
        filter = new MeshA2ASseHeaderFilter();
        chainInvocations = new AtomicInteger(0);
        chain = (req, resp) -> chainInvocations.incrementAndGet();
    }

    /** Spec §4.6 / §5.1: Accept: text/event-stream → three SSE headers stamped. */
    @Test
    @DisplayName("Accept: text/event-stream → stamps Cache-Control, X-Accel-Buffering, Connection")
    void sseAccept_stampsAllThreeHeaders() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
        req.addHeader("Accept", "text/event-stream");
        MockHttpServletResponse resp = new MockHttpServletResponse();

        invokeDoFilter(filter, req, resp, chain);

        assertEquals("no-cache", resp.getHeader("Cache-Control"),
            "Spec §4.6: SSE responses MUST set Cache-Control: no-cache");
        assertEquals("no", resp.getHeader("X-Accel-Buffering"),
            "Spec §4.6: X-Accel-Buffering: no defeats nginx response buffering");
        assertEquals("keep-alive", resp.getHeader("Connection"),
            "Spec §4.6: Connection: keep-alive preserves the long-lived stream");
        assertEquals(1, chainInvocations.get(),
            "Filter MUST always invoke the chain — not a short-circuit");
    }

    /** Spec §4.6: Accept: application/json → NO SSE headers stamped. */
    @Test
    @DisplayName("Accept: application/json → does NOT stamp SSE headers")
    void jsonAccept_doesNotStampHeaders() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
        req.addHeader("Accept", "application/json");
        MockHttpServletResponse resp = new MockHttpServletResponse();

        invokeDoFilter(filter, req, resp, chain);

        assertNull(resp.getHeader("Cache-Control"));
        assertNull(resp.getHeader("X-Accel-Buffering"));
        assertNull(resp.getHeader("Connection"));
        assertEquals(1, chainInvocations.get());
    }

    /** Spec §4.6: Missing Accept header → NO SSE headers (filter only
     *  stamps when client explicitly opted into SSE). */
    @Test
    @DisplayName("Missing Accept header → does NOT stamp SSE headers")
    void missingAccept_doesNotStampHeaders() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
        MockHttpServletResponse resp = new MockHttpServletResponse();

        invokeDoFilter(filter, req, resp, chain);

        assertNull(resp.getHeader("Cache-Control"));
        assertNull(resp.getHeader("X-Accel-Buffering"));
        assertNull(resp.getHeader("Connection"));
        assertEquals(1, chainInvocations.get());
    }

    /** Defensive: Accept header that CONTAINS text/event-stream (with
     *  qualifier or multi-type list) still triggers stamping — the filter
     *  uses {@code String.contains} semantics. */
    @Test
    @DisplayName("Accept header containing text/event-stream (with q-value) still stamps headers")
    void sseAcceptWithQValue_stampsHeaders() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
        req.addHeader("Accept", "text/event-stream;q=1.0, application/json;q=0.5");
        MockHttpServletResponse resp = new MockHttpServletResponse();

        invokeDoFilter(filter, req, resp, chain);

        assertEquals("no-cache", resp.getHeader("Cache-Control"),
            "Multi-type Accept that includes text/event-stream MUST trigger SSE header stamping");
    }

    /** Wrong media type — does NOT stamp. Guards against false positives. */
    @Test
    @DisplayName("Accept: text/plain → does NOT stamp SSE headers (only event-stream triggers)")
    void plainTextAccept_doesNotStampHeaders() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
        req.addHeader("Accept", "text/plain");
        MockHttpServletResponse resp = new MockHttpServletResponse();

        invokeDoFilter(filter, req, resp, chain);

        assertNull(resp.getHeader("Cache-Control"),
            "Only Accept containing 'text/event-stream' triggers the SSE-headers branch");
    }

    /** Filter always invokes the chain — never short-circuits, even when
     *  it doesn't stamp headers. */
    @Test
    @DisplayName("Filter always invokes the chain, regardless of Accept value")
    void chainAlwaysInvoked() throws Exception {
        for (String accept : new String[]{
                "text/event-stream", "application/json", "*/*", "weird-thing"}) {
            chainInvocations.set(0);
            MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
            if (accept != null) req.addHeader("Accept", accept);
            invokeDoFilter(filter, req, new MockHttpServletResponse(), chain);
            assertEquals(1, chainInvocations.get(),
                "Filter MUST invoke chain for Accept='" + accept + "'");
        }
    }

    /** Case-insensitive Accept value still triggers the SSE branch. The
     *  HTTP spec says media types are case-insensitive; a raw
     *  {@code String.contains("text/event-stream")} would miss
     *  {@code TEXT/EVENT-STREAM}, but {@code MediaType.parseMediaTypes}
     *  normalises case. */
    @Test
    @DisplayName("Accept: TEXT/EVENT-STREAM (uppercase) → stamps SSE headers")
    void uppercaseAccept_stampsHeaders() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
        req.addHeader("Accept", "TEXT/EVENT-STREAM");
        MockHttpServletResponse resp = new MockHttpServletResponse();

        invokeDoFilter(filter, req, resp, chain);

        assertEquals("no-cache", resp.getHeader("Cache-Control"),
            "Media types are case-insensitive per HTTP spec");
        assertEquals(1, chainInvocations.get());
    }

    /** Accept with charset parameter → still stamps. The MediaType parser
     *  knows {@code text/event-stream;charset=UTF-8} is compatible with
     *  bare {@code text/event-stream}. */
    @Test
    @DisplayName("Accept: text/event-stream;charset=UTF-8 → stamps SSE headers")
    void acceptWithCharsetParam_stampsHeaders() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
        req.addHeader("Accept", "text/event-stream;charset=UTF-8");
        MockHttpServletResponse resp = new MockHttpServletResponse();

        invokeDoFilter(filter, req, resp, chain);

        assertEquals("no-cache", resp.getHeader("Cache-Control"));
    }

    /** Compound Accept value listing JSON first then SSE → still stamps. The
     *  order of media types in Accept does NOT affect compatibility; the
     *  filter only checks "does any listed type accept SSE". */
    @Test
    @DisplayName("Accept: application/json, text/event-stream → stamps SSE headers")
    void compoundAcceptWithJsonFirst_stampsHeaders() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
        req.addHeader("Accept", "application/json, text/event-stream");
        MockHttpServletResponse resp = new MockHttpServletResponse();

        invokeDoFilter(filter, req, resp, chain);

        assertEquals("no-cache", resp.getHeader("Cache-Control"),
            "Compound Accept that includes SSE among its entries MUST trigger stamping");
    }

    /** Malformed Accept header → defensive substring fallback still works for
     *  the common case. We never want a stray invalid header to drop a
     *  legitimate SSE client. */
    @Test
    @DisplayName("Malformed Accept header containing 'text/event-stream' still stamps via fallback")
    void malformedAcceptWithSubstring_stillStamps() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("POST", "/agents/x");
        // Intentionally malformed (unbalanced quote) — MediaType.parseMediaTypes
        // throws InvalidMimeTypeException, we fall back to a lowercase substring
        // check.
        req.addHeader("Accept", "\"text/event-stream");
        MockHttpServletResponse resp = new MockHttpServletResponse();

        invokeDoFilter(filter, req, resp, chain);

        assertEquals("no-cache", resp.getHeader("Cache-Control"),
            "Malformed Accept should not drop legitimate SSE clients");
    }

    /** Direct unit tests of {@code acceptsEventStream} — pure helper, no
     *  filter chain machinery. */
    @Test
    @DisplayName("acceptsEventStream() helper — case + compound + null + blank coverage")
    void acceptsEventStreamHelperCoverage() {
        assertTrue(MeshA2ASseHeaderFilter.acceptsEventStream("text/event-stream"));
        assertTrue(MeshA2ASseHeaderFilter.acceptsEventStream("TEXT/EVENT-STREAM"));
        assertTrue(MeshA2ASseHeaderFilter.acceptsEventStream(
            "text/event-stream;charset=UTF-8"));
        assertTrue(MeshA2ASseHeaderFilter.acceptsEventStream(
            "application/json, text/event-stream"));
        assertTrue(MeshA2ASseHeaderFilter.acceptsEventStream(
            "text/event-stream;q=1.0, application/json;q=0.5"));
        assertFalse(MeshA2ASseHeaderFilter.acceptsEventStream("application/json"));
        assertFalse(MeshA2ASseHeaderFilter.acceptsEventStream("text/plain"));
        assertFalse(MeshA2ASseHeaderFilter.acceptsEventStream(""));
        assertFalse(MeshA2ASseHeaderFilter.acceptsEventStream("   "));
        assertFalse(MeshA2ASseHeaderFilter.acceptsEventStream(null));
    }

    /** {@link MeshA2ASseHeaderFilter#doFilterInternal} is protected (inherited
     *  from {@code OncePerRequestFilter}). Use reflection to invoke it directly
     *  so we don't need to register the filter into a real chain. */
    private static void invokeDoFilter(
            MeshA2ASseHeaderFilter filter,
            MockHttpServletRequest req,
            MockHttpServletResponse resp,
            FilterChain chain) throws Exception {
        Method m = MeshA2ASseHeaderFilter.class.getDeclaredMethod(
            "doFilterInternal",
            jakarta.servlet.http.HttpServletRequest.class,
            jakarta.servlet.http.HttpServletResponse.class,
            FilterChain.class);
        m.setAccessible(true);
        m.invoke(filter, req, resp, chain);
    }
}
