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
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link A2AJob}, focused on {@link A2AJob#bridge}.
 * Spins up a tiny in-process HTTP server (JDK's
 * {@code com.sun.net.httpserver.HttpServer}) so the tests don't require
 * a real network endpoint or the full mesh runtime.
 *
 * <p>Uses a hand-rolled {@link RecordingController} that implements
 * the package-private {@link JobControllerAdapter} so we don't need
 * to instantiate a real native-handle-backed
 * {@link io.mcpmesh.JobController}.
 */
class A2AJobTest {

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
    void submit_returnsJobWithTaskIdAndInitialState() {
        mount("/agents/test", ex -> {
            String body = readBody(ex);
            assertTrue(body.contains("tasks/send"), "submit must POST tasks/send");
            respond(ex, 200, """
                {"jsonrpc":"2.0","id":1,"result":{
                  "status":{"state":"working"},
                  "artifacts":[]
                }}
                """);
        });

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            assertNotNull(job.taskId());
            assertTrue(job.taskId().startsWith("c-"));
            assertEquals("working", job.initialState());
        }
    }

    @Test
    void bridge_happyPath_mirrorsProgressAndReturnsArtifact() {
        AtomicInteger calls = new AtomicInteger(0);
        mount("/agents/test", ex -> {
            int n = calls.incrementAndGet();
            String body = readBody(ex);
            if (n == 1) {
                assertTrue(body.contains("tasks/send"));
                respond(ex, 200, """
                    {"jsonrpc":"2.0","id":1,"result":{
                      "status":{"state":"working","message":{"parts":[{"text":"starting"}]}},
                      "metadata":{"progress":0.0},
                      "artifacts":[]
                    }}
                    """);
                return;
            }
            assertTrue(body.contains("tasks/get"));
            if (n == 2) {
                respond(ex, 200, """
                    {"jsonrpc":"2.0","id":2,"result":{
                      "status":{"state":"working","message":{"parts":[{"text":"halfway"}]}},
                      "metadata":{"progress":0.5},
                      "artifacts":[]
                    }}
                    """);
                return;
            }
            respond(ex, 200, """
                {"jsonrpc":"2.0","id":2,"result":{
                  "status":{"state":"completed"},
                  "artifacts":[{"parts":[{"type":"text","text":"{\\"result\\":\\"ok\\"}"}]}]
                }}
                """);
        });

        RecordingController controller = new RecordingController();
        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            Object artifact = job.bridgeInternal(controller);
            // Producer JSON-stringified a dict as the artifact text →
            // bridge() should return the parsed Map.
            assertInstanceOf(Map.class, artifact, "artifact should be parsed back to a Map");
            @SuppressWarnings("unchecked")
            Map<String, Object> map = (Map<String, Object>) artifact;
            assertEquals("ok", map.get("result"));
            assertTrue(controller.progressUpdates.size() >= 2,
                "expected at least 2 progress updates (initial + halfway), got " + controller.progressUpdates);
            assertTrue(calls.get() >= 3,
                "expected at least 3 server calls (1 send + >=2 polls), got " + calls.get());
        }
    }

    @Test
    void bridge_terminalFailed_throwsA2AJobFailedException() {
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{
              "status":{"state":"failed","message":{"parts":[{"text":"boom"}]}},
              "artifacts":[]
            }}
            """));

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            A2AJobFailedException thrown = assertThrows(A2AJobFailedException.class,
                () -> job.bridgeInternal(new RecordingController()));
            assertTrue(thrown.getMessage().contains("boom"),
                "exception should surface the upstream message: " + thrown.getMessage());
        }
    }

    @Test
    void bridge_terminalCanceled_throwsA2AJobCanceledException() {
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{
              "status":{"state":"canceled","message":{"parts":[{"text":"upstream-cancel"}]}},
              "artifacts":[]
            }}
            """));

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            A2AJobCanceledException thrown = assertThrows(A2AJobCanceledException.class,
                () -> job.bridgeInternal(new RecordingController()));
            assertTrue(thrown.getMessage().contains("upstream-cancel"),
                "exception should surface the upstream message: " + thrown.getMessage());
        }
    }

    @Test
    void bridge_terminalCancelled_ukSpelling_throwsCanceledException() {
        // Mesh JobController uses UK "cancelled"; the bridge MUST treat
        // it as canceled per the same case-insensitive contract that
        // A2AClient.send already enforces.
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{
              "status":{"state":"Cancelled"},
              "artifacts":[]
            }}
            """));
        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            assertThrows(A2AJobCanceledException.class,
                () -> job.bridgeInternal(new RecordingController()));
        }
    }

    @Test
    void bridge_meshSideCancel_postsTasksCancelAndThrowsCanceled() {
        AtomicBoolean sawTasksCancel = new AtomicBoolean(false);
        AtomicInteger calls = new AtomicInteger(0);
        mount("/agents/test", ex -> {
            int n = calls.incrementAndGet();
            String body = readBody(ex);
            if (body.contains("tasks/cancel")) {
                sawTasksCancel.set(true);
                respond(ex, 200, """
                    {"jsonrpc":"2.0","id":3,"result":{
                      "status":{"state":"canceled"},
                      "artifacts":[]
                    }}
                    """);
                return;
            }
            if (n == 1) {
                respond(ex, 200, """
                    {"jsonrpc":"2.0","id":1,"result":{
                      "status":{"state":"working"},
                      "artifacts":[]
                    }}
                    """);
                return;
            }
            respond(ex, 200, """
                {"jsonrpc":"2.0","id":2,"result":{
                  "status":{"state":"working"},
                  "artifacts":[]
                }}
                """);
        });

        // Controller flips to cancelled on the SECOND isCancelled() call
        // — after the initial check passes and one tasks/get has run.
        AtomicInteger checks = new AtomicInteger(0);
        RecordingController controller = new RecordingController() {
            @Override
            public boolean isCancelled() {
                return checks.incrementAndGet() > 1;
            }
        };

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            A2AJobCanceledException thrown = assertThrows(A2AJobCanceledException.class,
                () -> job.bridgeInternal(controller));
            assertTrue(thrown.getMessage().contains("mesh-side"),
                "exception should mention mesh-side cancel: " + thrown.getMessage());
            assertTrue(sawTasksCancel.get(),
                "bridge MUST POST tasks/cancel upstream when controller flips to cancelled");
        }
    }

    @Test
    void bridge_pollFailure_postsTasksCancelAndThrowsFailed() {
        AtomicInteger calls = new AtomicInteger(0);
        AtomicBoolean sawTasksCancel = new AtomicBoolean(false);
        mount("/agents/test", ex -> {
            int n = calls.incrementAndGet();
            String body = readBody(ex);
            if (body.contains("tasks/cancel")) {
                sawTasksCancel.set(true);
                respond(ex, 200, """
                    {"jsonrpc":"2.0","id":3,"result":{
                      "status":{"state":"canceled"},
                      "artifacts":[]
                    }}
                    """);
                return;
            }
            if (n == 1) {
                respond(ex, 200, """
                    {"jsonrpc":"2.0","id":1,"result":{
                      "status":{"state":"working"},
                      "artifacts":[]
                    }}
                    """);
                return;
            }
            // Subsequent tasks/get returns 500 — bridge MUST surface
            // as A2AJobFailedException + best-effort tasks/cancel.
            respond(ex, 500, "internal server error");
        });

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            A2AJobFailedException thrown = assertThrows(A2AJobFailedException.class,
                () -> job.bridgeInternal(new RecordingController()));
            assertTrue(thrown.getMessage().contains("status poll failed"),
                "exception should mention poll failure: " + thrown.getMessage());
            assertTrue(sawTasksCancel.get(),
                "bridge MUST best-effort tasks/cancel upstream when poll fails");
        }
    }

    @Test
    void bridge_completeOnSubmit_shortCircuitsWithoutPolling() {
        // tasks/send returns terminal completed in the FIRST response —
        // bridge must skip the polling loop entirely and surface the
        // artifact from the initial result.
        AtomicInteger calls = new AtomicInteger(0);
        mount("/agents/test", ex -> {
            calls.incrementAndGet();
            respond(ex, 200, """
                {"jsonrpc":"2.0","id":1,"result":{
                  "status":{"state":"completed"},
                  "artifacts":[{"parts":[{"type":"text","text":"done-fast"}]}]
                }}
                """);
        });

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            Object result = job.bridgeInternal(new RecordingController());
            assertEquals("done-fast", result);
            assertEquals(1, calls.get(),
                "bridge MUST NOT POST tasks/get when initial submit was already terminal");
        }
    }

    @Test
    void bridge_isCancelledThrows_throwsJobFailedException() {
        // Simulates the native handle being invalidated mid-poll (FFI race
        // with PreDestroy, JNI library unload, etc.). controller.isCancelled()
        // throws an arbitrary RuntimeException — bridge() MUST translate it
        // to A2AJobFailedException so the documented exception contract
        // (A2AJobFailedException / A2AJobCanceledException only) holds.
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{
              "status":{"state":"working"},
              "artifacts":[]
            }}
            """));

        IllegalStateException nativeFailure =
            new IllegalStateException("native handle invalidated");
        JobControllerAdapter controller = new JobControllerAdapter() {
            @Override
            public void updateProgress(double progress, String message) {
                // unused
            }

            @Override
            public boolean isCancelled() {
                throw nativeFailure;
            }
        };

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            A2AJobFailedException thrown = assertThrows(A2AJobFailedException.class,
                () -> job.bridgeInternal(controller));
            assertSame(nativeFailure, thrown.getCause(),
                "bridge MUST preserve the original native failure as the cause");
            assertTrue(thrown.getMessage().contains("isCancelled"),
                "exception should mention isCancelled() failure: " + thrown.getMessage());
        }
    }

    @Test
    void bridge_sleepInterrupted_throwsJobCanceledException() throws Exception {
        // Producer always returns state=working so the bridge enters the
        // polling loop and stays there. Once the bridge thread is asleep
        // between polls we Thread.interrupt() it: bridge() MUST surface
        // an A2AJobCanceledException (with the original InterruptedException
        // as the cause) AND best-effort POST tasks/cancel upstream so the
        // producer stops billing for work whose result we'll never observe.
        AtomicBoolean cancelPosted = new AtomicBoolean(false);
        mount("/agents/test", ex -> {
            String body = readBody(ex);
            if (body.contains("tasks/cancel")) {
                cancelPosted.set(true);
                respond(ex, 200, """
                    {"jsonrpc":"2.0","id":3,"result":{
                      "status":{"state":"canceled"},
                      "artifacts":[]
                    }}
                    """);
                return;
            }
            respond(ex, 200, """
                {"jsonrpc":"2.0","id":2,"result":{
                  "status":{"state":"working"},
                  "artifacts":[]
                }}
                """);
        });

        JobControllerAdapter neverCancels = new JobControllerAdapter() {
            @Override
            public void updateProgress(double progress, String message) {
                // unused
            }

            @Override
            public boolean isCancelled() {
                return false;
            }
        };

        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            AtomicReference<Throwable> caught = new AtomicReference<>();
            Thread bridgeThread = new Thread(() -> {
                try {
                    job.bridgeInternal(neverCancels);
                    caught.set(new AssertionError("expected A2AJobCanceledException"));
                } catch (Throwable t) {
                    caught.set(t);
                }
            }, "bridge-interrupt-test");
            bridgeThread.start();
            // Give the bridge time to enter the sleep between polls (default
            // poll interval is 500ms).
            Thread.sleep(800);
            bridgeThread.interrupt();
            bridgeThread.join(5000);
            assertFalse(bridgeThread.isAlive(), "bridge thread should have terminated");
            Throwable thrown = caught.get();
            assertNotNull(thrown, "bridge thread should have produced an exception");
            assertInstanceOf(A2AJobCanceledException.class, thrown,
                "bridge MUST throw A2AJobCanceledException on local interrupt, got: " + thrown);
            assertNotNull(thrown.getCause(),
                "A2AJobCanceledException MUST preserve the original cause");
            assertInstanceOf(InterruptedException.class, thrown.getCause(),
                "cause MUST be the InterruptedException, got: " + thrown.getCause());
            assertTrue(cancelPosted.get(),
                "bridge MUST POST tasks/cancel upstream when interrupted locally");
        }
    }

    @Test
    void bridge_rejectsNullController() {
        mount("/agents/test", ex -> respond(ex, 200, """
            {"jsonrpc":"2.0","id":1,"result":{"status":{"state":"working"},"artifacts":[]}}
            """));
        try (A2AClient client = new A2AClient(url(), "demo")) {
            A2AJob job = client.submit(Map.of("role", "user", "parts", List.of()));
            assertThrows(IllegalArgumentException.class, () -> job.bridge(null));
        }
    }

    /**
     * In-memory {@link JobControllerAdapter} that records progress
     * updates and lets tests override {@link #isCancelled} as needed.
     */
    static class RecordingController implements JobControllerAdapter {
        final List<double[]> progressUpdates = new ArrayList<>();
        final List<String> messages = new ArrayList<>();

        @Override
        public void updateProgress(double progress, String message) {
            progressUpdates.add(new double[]{progress});
            messages.add(message);
        }

        @Override
        public boolean isCancelled() {
            return false;
        }
    }
}
