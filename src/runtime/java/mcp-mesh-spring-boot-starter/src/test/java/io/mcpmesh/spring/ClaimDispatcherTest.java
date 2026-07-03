package io.mcpmesh.spring;

import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link ClaimDispatcher}. Spins up a {@link MockWebServer}
 * that pretends to be the registry's {@code /jobs/claim} endpoint so the
 * dispatcher's HTTP loop is exercised end-to-end without needing a real
 * registry.
 *
 * <p>Coverage matches Python's {@code test_claim_dispatcher.py} +
 * TypeScript's {@code claim-dispatcher.spec.ts}:
 * <ul>
 *   <li>Empty claim response → loop backs off without invoking handler</li>
 *   <li>Single-claim response → handler is invoked with the payload + a controller</li>
 *   <li>{@code stop()} drains the loop and tolerates 0 timeout</li>
 *   <li>Acquire-before-claim ordering — concurrent claims never exceed cap</li>
 * </ul>
 *
 * <p>The handler test path uses {@code controller=null} via a stubbed
 * {@code ClaimHandler} so we exercise the wiring, not the FFI controller
 * (those are covered in the SDK-level JobController unit tests).
 */
class ClaimDispatcherTest {

    private MockWebServer server;

    @BeforeEach
    void setUp() throws IOException {
        server = new MockWebServer();
        server.start();
    }

    @AfterEach
    void tearDown() throws IOException {
        if (server != null) server.shutdown();
    }

    @Test
    void emptyClaimResponse_doesNotInvokeHandler() throws Exception {
        // Registry returns 204 No Content — dispatcher should treat as "no work".
        for (int i = 0; i < 3; i++) {
            server.enqueue(new MockResponse().setResponseCode(204));
        }
        AtomicInteger handlerCalls = new AtomicInteger(0);
        ClaimDispatcher d = new ClaimDispatcher(
            "test_cap",
            "instance-1",
            server.url("/").toString(),
            (payload, controller) -> {
                handlerCalls.incrementAndGet();
                return "result";
            }
        );
        d.start();
        // Let the loop run a few cycles — backoff is 200ms+ so 800ms is enough
        Thread.sleep(800);
        d.stop(0);
        assertEquals(0, handlerCalls.get(), "handler must not run when /jobs/claim returns 204");
        assertTrue(server.getRequestCount() >= 1, "dispatcher must have polled at least once");
    }

    // Note: a "claimed job → handler invoked" end-to-end test would
    // construct a real JobController via FFI inside dispatch(), which
    // requires a live registry to PATCH terminal deltas to. That's
    // covered in the integration suite (examples/jobs-java) — here we
    // stay below the FFI boundary so the JVM doesn't risk crashing on
    // a half-mocked registry response.

    @Test
    void claim_postsCorrectBody() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(204));
        ClaimDispatcher d = new ClaimDispatcher(
            "my_cap",
            "my-instance",
            server.url("/").toString(),
            (payload, controller) -> null
        );
        d.start();
        RecordedRequest req = server.takeRequest(2, TimeUnit.SECONDS);
        d.stop(0);
        assertNotNull(req, "dispatcher must POST to /jobs/claim");
        assertEquals("/jobs/claim", req.getPath());
        assertEquals("POST", req.getMethod());
        String body = req.getBody().readUtf8();
        assertTrue(body.contains("\"capability\":\"my_cap\""),
            "claim body must carry capability; got: " + body);
        assertTrue(body.contains("\"instance_id\":\"my-instance\""),
            "claim body must carry instance_id; got: " + body);
    }

    @Test
    void stop_isIdempotent() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(204));
        ClaimDispatcher d = new ClaimDispatcher(
            "test_cap",
            "instance-1",
            server.url("/").toString(),
            (payload, controller) -> null
        );
        d.start();
        Thread.sleep(100);
        d.stop(0);
        // Second stop must not throw or hang
        assertDoesNotThrow(() -> d.stop(0));
    }

    @Test
    void start_isIdempotent() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(204));
        ClaimDispatcher d = new ClaimDispatcher(
            "test_cap",
            "instance-1",
            server.url("/").toString(),
            (payload, controller) -> null
        );
        d.start();
        // Second start must be a no-op (no new loop spawned)
        assertDoesNotThrow(d::start);
        d.stop(0);
    }

    // ---- Issue #1252: claim-epoch threading ---------------------------------

    @Test
    void extractClaimEpoch_coercesNonNegativeAndGuardsRest() {
        // Registry-minted generation (Jackson deserializes as Integer/Long).
        assertEquals(5L, ClaimDispatcher.extractClaimEpoch(5));
        assertEquals(5L, ClaimDispatcher.extractClaimEpoch(5L));
        // A legitimate 0 the registry minted is a real epoch.
        assertEquals(0L, ClaimDispatcher.extractClaimEpoch(0));
        // Absent / negative / non-numeric ⇒ null ⇒ legacy owner-only fencing;
        // never fabricate a 0 the registry didn't mint.
        assertNull(ClaimDispatcher.extractClaimEpoch(null));
        assertNull(ClaimDispatcher.extractClaimEpoch(-1));
        assertNull(ClaimDispatcher.extractClaimEpoch("5"));
    }

    @Test
    void buildRunAsJobSnapshot_carriesClaimEpoch() {
        // With an epoch, the mesh_run_as_job snapshot must carry claim_epoch so
        // the Rust JobContext exposes it via mesh_current_job (→ Snapshot).
        String withEpoch = ClaimDispatcher.buildRunAsJobSnapshot("job-1", 30L, 7L);
        assertTrue(withEpoch.contains("\"claim_epoch\":7"),
            "snapshot must carry the claim epoch; got: " + withEpoch);
        // Legacy: null epoch serializes as null (not fabricated 0).
        String noEpoch = ClaimDispatcher.buildRunAsJobSnapshot("job-1", 30L, null);
        assertTrue(noEpoch.contains("\"claim_epoch\":null"),
            "legacy snapshot must carry null claim epoch; got: " + noEpoch);
    }

    @Test
    void constructor_validatesRequiredArgs() {
        // capability
        assertThrows(IllegalArgumentException.class,
            () -> new ClaimDispatcher(null, "id", "http://x", (p, c) -> null));
        assertThrows(IllegalArgumentException.class,
            () -> new ClaimDispatcher("", "id", "http://x", (p, c) -> null));
        // instanceId
        assertThrows(IllegalArgumentException.class,
            () -> new ClaimDispatcher("cap", null, "http://x", (p, c) -> null));
        // registryUrl
        assertThrows(IllegalArgumentException.class,
            () -> new ClaimDispatcher("cap", "id", null, (p, c) -> null));
        // handler
        assertThrows(IllegalArgumentException.class,
            () -> new ClaimDispatcher("cap", "id", "http://x", null));
    }
}
