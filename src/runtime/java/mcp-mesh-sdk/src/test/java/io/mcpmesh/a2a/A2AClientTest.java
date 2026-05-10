package io.mcpmesh.a2a;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link A2AClient}. Spins up a tiny in-process HTTP
 * server (JDK's {@code com.sun.net.httpserver.HttpServer}) so the
 * client tests don't pull in OkHttp / MockWebServer (the SDK module
 * cannot depend on them — that would create a cycle with
 * {@code mcp-mesh-spring-boot-starter}, see issue #916 design notes).
 */
class A2AClientTest {

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

    private static String readBody(HttpExchange ex) throws IOException {
        try (InputStream in = ex.getRequestBody()) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private static void respond(HttpExchange ex, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = ex.getResponseBody()) {
            out.write(bytes);
        }
    }

    @Test
    void send_terminalOnFirstResponse_returnsArtifactText() {
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{
              "status":{"state":"completed"},
              "artifacts":[{"parts":[{"type":"text","text":"hello"}]}]
            }}
            """));

        try (A2AClient client = new A2AClient(url(), "demo-skill")) {
            A2AResponse resp = client.send(Map.of(
                "role", "user",
                "parts", List.of(Map.of("type", "text", "text", "ping"))));
            assertEquals("hello", resp.artifactText());
            assertEquals("completed", resp.state());
            assertNotNull(resp.taskId());
            assertTrue(resp.taskId().startsWith("c-"));
            assertNotNull(resp.rawTask());
        }
    }

    @Test
    void send_pollsUntilTerminal() {
        AtomicInteger calls = new AtomicInteger(0);
        mount("/agents/test", ex -> {
            int n = calls.incrementAndGet();
            String body = readBody(ex);
            // First call should be tasks/send, subsequent are tasks/get.
            if (n == 1) {
                assertTrue(body.contains("tasks/send"), "first call must be tasks/send");
                respond(ex, 200, """
                    {"jsonrpc":"2.0","id":1,"result":{
                      "status":{"state":"working"},
                      "artifacts":[]
                    }}
                    """);
                return;
            }
            assertTrue(body.contains("tasks/get"), "follow-up calls must be tasks/get");
            if (n < 3) {
                respond(ex, 200, """
                    {"jsonrpc":"2.0","id":2,"result":{
                      "status":{"state":"working"},
                      "artifacts":[]
                    }}
                    """);
                return;
            }
            respond(ex, 200, """
                {"jsonrpc":"2.0","id":2,"result":{
                  "status":{"state":"completed"},
                  "artifacts":[{"parts":[{"type":"text","text":"done"}]}]
                }}
                """);
        });

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AResponse resp = client.send(Map.of("role", "user", "parts", List.of()));
            assertEquals("done", resp.artifactText());
            assertEquals("completed", resp.state());
            assertTrue(calls.get() >= 3, "expected at least 3 calls (1 send + >=2 polls), got " + calls.get());
        }
    }

    @Test
    void send_responseMissingResultAndError_throwsException() {
        // A producer that returns a JSON-RPC envelope with neither
        // 'result' nor 'error' is malformed. The client must surface
        // this as A2AException immediately rather than coercing the
        // missing 'result' to an empty object and spinning the polling
        // loop until the user-supplied deadline elapses.
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1}
            """));

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AException thrown = assertThrows(A2AException.class,
                () -> client.send(Map.of("role", "user", "parts", List.of())));
            assertTrue(thrown.getMessage().contains("malformed JSON-RPC envelope"),
                "exception should call out malformed envelope: " + thrown.getMessage());
        }
    }

    @Test
    void send_jsonRpcErrorEnvelope_throwsA2AException() {
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not implemented"}}
            """));

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AException thrown = assertThrows(A2AException.class,
                () -> client.send(Map.of("role", "user", "parts", List.of())));
            assertTrue(thrown.getMessage().contains("Method not implemented"),
                "exception should surface upstream error message: " + thrown.getMessage());
        }
    }

    @Test
    void send_httpErrorStatus_throwsA2AException() {
        mount("/agents/test", ex -> respond(ex, 500, "internal server error"));

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AException thrown = assertThrows(A2AException.class,
                () -> client.send(Map.of("role", "user", "parts", List.of())));
            assertTrue(thrown.getMessage().contains("HTTP 500"),
                "exception should mention HTTP 500: " + thrown.getMessage());
        }
    }

    @Test
    void send_neverReachesTerminal_throwsTimeout() {
        // Always reply with state=working so the client polls until the
        // user-supplied 1s deadline elapses, then surfaces TimeoutException.
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{
              "status":{"state":"working"},
              "artifacts":[]
            }}
            """));

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2ATimeoutException thrown = assertThrows(A2ATimeoutException.class,
                () -> client.send(Map.of("role", "user", "parts", List.of()), Duration.ofSeconds(1)));
            assertTrue(thrown.getMessage().contains("did not reach terminal"),
                thrown.getMessage());
        }
    }

    @Test
    void send_bearerHeader_isInjected() {
        AtomicReference<String> seenAuth = new AtomicReference<>();
        mount("/agents/test", ex -> {
            seenAuth.set(ex.getRequestHeaders().getFirst("Authorization"));
            respond(ex, 200, """
                {"jsonrpc":"2.0","id":1,"result":{
                  "status":{"state":"completed"},
                  "artifacts":[{"parts":[{"type":"text","text":"ok"}]}]
                }}
                """);
        });

        try (A2AClient client = new A2AClient(url(), "demo", A2ABearer.of("secret-token"))) {
            client.send(Map.of("role", "user", "parts", List.of()));
            assertEquals("Bearer secret-token", seenAuth.get(),
                "outbound request must carry Authorization: Bearer <token>");
        }
    }

    @Test
    void send_terminalCanceled_caseInsensitive_includesUkSpelling() {
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{
              "status":{"state":"Cancelled"},
              "artifacts":[]
            }}
            """));

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AResponse resp = client.send(Map.of("role", "user", "parts", List.of()));
            assertEquals("Cancelled", resp.state(),
                "client must short-circuit on the UK spelling 'cancelled' too");
        }
    }

    @Test
    void send_afterClose_throws() {
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"completed"},"artifacts":[]}}
            """));

        A2AClient client = new A2AClient(url(), "demo");
        client.close();
        A2AException ex = assertThrows(A2AException.class,
            () -> client.send(Map.of("role", "user", "parts", List.of())));
        assertTrue(ex.getMessage().contains("closed"));
    }

    @Test
    void constructor_rejectsBlankUrl() {
        assertThrows(IllegalArgumentException.class, () -> new A2AClient("", "demo"));
        assertThrows(IllegalArgumentException.class, () -> new A2AClient(null, "demo"));
    }

    @Test
    void send_rejectsNullMessage() {
        try (A2AClient client = new A2AClient(url(), "demo")) {
            assertThrows(IllegalArgumentException.class, () -> client.send(null));
        }
    }

    @Test
    void submit_returnsHandleWithoutPolling() {
        // submit() MUST issue exactly one tasks/send call regardless
        // of the upstream state — polling is the caller's job (via
        // job.bridge / job.waitUntilTerminal).
        AtomicInteger calls = new AtomicInteger(0);
        mount("/agents/test", ex -> {
            int n = calls.incrementAndGet();
            String body = readBody(ex);
            assertTrue(body.contains("tasks/send"),
                "submit() must issue tasks/send (call " + n + ")");
            respond(ex, 200, """
                {"jsonrpc":"2.0","id":1,"result":{
                  "status":{"state":"working"},
                  "artifacts":[]
                }}
                """);
        });

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            assertNotNull(job);
            assertEquals(1, calls.get(),
                "submit() MUST issue exactly one HTTP call (tasks/send), got " + calls.get());
            assertEquals("working", job.initialState());
            assertNotNull(job.taskId());
            assertTrue(job.taskId().startsWith("c-"));
        }
    }

    @Test
    void submit_afterClose_throws() {
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"working"},"artifacts":[]}}
            """));
        A2AClient client = new A2AClient(url(), "demo");
        client.close();
        A2AException ex = assertThrows(A2AException.class,
            () -> client.submit(Map.of("role", "user", "parts", List.of())));
        assertTrue(ex.getMessage().contains("closed"));
    }

    @Test
    void subscribe_returnsStreamOfEvents() {
        // subscribe() MUST POST tasks/sendSubscribe with
        // Accept: text/event-stream and return a stream that parses
        // the SSE body into A2AEvent.
        AtomicReference<String> seenAccept = new AtomicReference<>();
        mount("/agents/test", ex -> {
            seenAccept.set(ex.getRequestHeaders().getFirst("Accept"));
            String body = readBody(ex);
            assertTrue(body.contains("tasks/sendSubscribe"),
                "subscribe() must POST tasks/sendSubscribe");
            byte[] payload = """
                data: {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"completed"},"final":true}}

                """.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "text/event-stream");
            ex.sendResponseHeaders(200, payload.length);
            try (java.io.OutputStream out = ex.getResponseBody()) {
                out.write(payload);
            }
        });

        try (A2AClient client = new A2AClient(url(), "demo")) {
            try (A2AStream stream = client.subscribe(Map.of("role", "user", "parts", List.of()))) {
                assertEquals("text/event-stream", seenAccept.get(),
                    "subscribe() request must carry Accept: text/event-stream");
                int count = 0;
                for (A2AEvent event : stream) {
                    count++;
                    assertEquals(A2AEvent.Kind.STATUS, event.kind());
                    assertTrue(event.isFinal());
                }
                assertEquals(1, count);
            }
        }
    }

    @Test
    void subscribe_httpErrorStatus_throwsA2AException() {
        mount("/agents/test", ex -> {
            byte[] body = "internal error".getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json");
            ex.sendResponseHeaders(503, body.length);
            try (java.io.OutputStream out = ex.getResponseBody()) {
                out.write(body);
            }
        });
        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AException thrown = assertThrows(A2AException.class,
                () -> client.subscribe(Map.of("role", "user", "parts", List.of())));
            assertTrue(thrown.getMessage().contains("HTTP 503"),
                "exception should mention HTTP 503: " + thrown.getMessage());
        }
    }

    @Test
    void subscribe_rejectsNullMessage() {
        try (A2AClient client = new A2AClient(url(), "demo")) {
            assertThrows(IllegalArgumentException.class, () -> client.subscribe(null));
        }
    }
}
