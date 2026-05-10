package io.mcpmesh.a2a;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link A2AStream}. Spins up an in-process
 * {@link HttpServer} that streams a hand-crafted SSE body to validate
 * line buffering, frame parsing, and the bridge convenience.
 */
class A2AStreamTest {

    private HttpServer server;
    private int port;

    @BeforeEach
    void startServer() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        port = server.getAddress().getPort();
        server.start();
    }

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    private String url() {
        return "http://127.0.0.1:" + port + "/agents/test";
    }

    private void mount(String path, HttpHandler handler) {
        server.createContext(path, handler);
    }

    /** Stream the supplied SSE body using chunked transfer encoding. */
    private static void streamSse(HttpExchange ex, String body) throws IOException {
        ex.getResponseHeaders().add("Content-Type", "text/event-stream");
        ex.sendResponseHeaders(200, 0);
        try (OutputStream out = ex.getResponseBody()) {
            out.write(body.getBytes(StandardCharsets.UTF_8));
            out.flush();
        }
    }

    @Test
    void subscribe_iteratesStatusAndArtifactFrames() {
        mount("/agents/test", ex -> streamSse(ex, """
            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"working"},"metadata":{"progress":0.0}}}

            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"working","message":{"parts":[{"text":"halfway"}]}},"metadata":{"progress":0.5}}}

            data: {"jsonrpc":"2.0","id":1,"result":{"artifact":{"parts":[{"type":"text","text":"final-payload"}]}}}

            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"completed"},"final":true}}

            """));

        try (A2AClient client = new A2AClient(url(), "demo")) {
            try (A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()))) {
                List<A2AEvent> events = new ArrayList<>();
                for (A2AEvent event : stream) {
                    events.add(event);
                }
                assertEquals(4, events.size(), "expected 4 parsed events: 2 status + 1 artifact + 1 terminal status");
                assertEquals(A2AEvent.Kind.STATUS, events.get(0).kind());
                assertEquals(0.0, events.get(0).progress());
                assertEquals(A2AEvent.Kind.STATUS, events.get(1).kind());
                assertEquals("halfway", events.get(1).message());
                assertEquals(A2AEvent.Kind.ARTIFACT, events.get(2).kind());
                assertEquals("final-payload", events.get(2).artifactText());
                assertEquals(A2AEvent.Kind.STATUS, events.get(3).kind());
                assertTrue(events.get(3).isFinal(), "last event must be marked isFinal");
            }
        }
    }

    @Test
    void iterator_skipsCommentLinesAndKeepalives() {
        mount("/agents/test", ex -> streamSse(ex, """
            : keep-alive comment line

            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"working"}}}

            : another comment
            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"completed"},"final":true}}

            """));
        try (A2AClient client = new A2AClient(url(), "demo")) {
            try (A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()))) {
                List<A2AEvent> events = new ArrayList<>();
                for (A2AEvent event : stream) {
                    events.add(event);
                }
                assertEquals(2, events.size(), "comments must be skipped, not surface as events");
                assertTrue(events.get(1).isFinal());
            }
        }
    }

    @Test
    void iterator_terminatesAfterFinalFrame() {
        // After the isFinal=true frame the iterator MUST report
        // hasNext()=false even if more bytes were on the wire.
        mount("/agents/test", ex -> streamSse(ex, """
            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"completed"},"final":true}}

            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"working"}}}

            """));
        try (A2AClient client = new A2AClient(url(), "demo")) {
            try (A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()))) {
                Iterator<A2AEvent> it = stream.iterator();
                assertTrue(it.hasNext());
                A2AEvent first = it.next();
                assertTrue(first.isFinal());
                assertFalse(it.hasNext(),
                    "iterator must terminate after the isFinal=true frame, ignoring any trailing bytes");
            }
        }
    }

    @Test
    void bridge_mirrorsProgressAndReturnsParsedArtifact() {
        mount("/agents/test", ex -> streamSse(ex, """
            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"working","message":{"parts":[{"text":"start"}]}},"metadata":{"progress":0.0}}}

            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"working","message":{"parts":[{"text":"mid"}]}},"metadata":{"progress":0.5}}}

            data: {"jsonrpc":"2.0","id":1,"result":{"artifact":{"parts":[{"type":"text","text":"{\\"x\\":42}"}]}}}

            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"completed"},"final":true}}

            """));

        A2AJobTest.RecordingController controller = new A2AJobTest.RecordingController();
        try (A2AClient client = new A2AClient(url(), "demo")) {
            try (A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()))) {
                Object artifact = stream.bridgeInternal(controller);
                assertInstanceOf(Map.class, artifact, "artifact JSON should parse to Map");
                @SuppressWarnings("unchecked")
                Map<String, Object> map = (Map<String, Object>) artifact;
                assertEquals(42, ((Number) map.get("x")).intValue());
                assertTrue(controller.progressUpdates.size() >= 2,
                    "expected at least 2 progress updates, got " + controller.progressUpdates);
                assertTrue(controller.messages.contains("start"), "should mirror 'start' message");
                assertTrue(controller.messages.contains("mid"), "should mirror 'mid' message");
            }
        }
    }

    @Test
    void bridge_terminalFailed_throwsA2AJobFailedException() {
        mount("/agents/test", ex -> streamSse(ex, """
            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"failed","message":{"parts":[{"text":"upstream-boom"}]}},"final":true}}

            """));
        try (A2AClient client = new A2AClient(url(), "demo")) {
            try (A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()))) {
                A2AJobFailedException thrown = assertThrows(A2AJobFailedException.class,
                    () -> stream.bridgeInternal(new A2AJobTest.RecordingController()));
                assertTrue(thrown.getMessage().contains("upstream-boom"),
                    "exception should surface upstream message: " + thrown.getMessage());
            }
        }
    }

    @Test
    void bridge_terminalCanceled_throwsA2AJobCanceledException() {
        mount("/agents/test", ex -> streamSse(ex, """
            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"canceled","message":{"parts":[{"text":"upstream-cancel"}]}},"final":true}}

            """));
        try (A2AClient client = new A2AClient(url(), "demo")) {
            try (A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()))) {
                A2AJobCanceledException thrown = assertThrows(A2AJobCanceledException.class,
                    () -> stream.bridgeInternal(new A2AJobTest.RecordingController()));
                assertTrue(thrown.getMessage().contains("upstream-cancel"));
            }
        }
    }

    @Test
    void bridge_streamEndsWithoutArtifact_throwsA2AJobFailedException() {
        // Producer closes the stream cleanly but never emitted an
        // artifact AND no terminal failure — surface as failed so the
        // user function raises rather than silently returning null.
        mount("/agents/test", ex -> streamSse(ex, """
            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"working"}}}

            """));
        try (A2AClient client = new A2AClient(url(), "demo")) {
            try (A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()))) {
                A2AJobFailedException thrown = assertThrows(A2AJobFailedException.class,
                    () -> stream.bridgeInternal(new A2AJobTest.RecordingController()));
                assertTrue(thrown.getMessage().contains("ended without artifact"),
                    "exception should call out missing artifact: " + thrown.getMessage());
            }
        }
    }

    @Test
    void close_isIdempotent() {
        mount("/agents/test", ex -> streamSse(ex, """
            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"completed"},"final":true}}

            """));
        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()));
            stream.close();
            // Second close must be a no-op.
            stream.close();
        }
    }

    @Test
    void bridge_rejectsNullController() {
        mount("/agents/test", ex -> streamSse(ex, """
            data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"completed"},"final":true}}

            """));
        try (A2AClient client = new A2AClient(url(), "demo")) {
            try (A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()))) {
                assertThrows(IllegalArgumentException.class, () -> stream.bridge(null));
            }
        }
    }
}
