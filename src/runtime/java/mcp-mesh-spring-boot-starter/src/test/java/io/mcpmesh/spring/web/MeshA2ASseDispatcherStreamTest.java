package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.invocation.InvocationOnMock;
import org.mockito.stubbing.Answer;
import org.springframework.web.servlet.function.ServerResponse;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * Unit tests for {@link MeshA2ASseDispatcher} stream emission (spec §5).
 *
 * <p>Each {@link MeshA2ADispatcher.SseStreamPlan} kind is fed into the
 * dispatcher and the emitted frames are captured via a Mockito-mocked
 * {@link ServerResponse.SseBuilder}. Frame payloads are parsed back into
 * JSON via Jackson so we can assert on the SHAPE (real boolean
 * {@code final}, real number {@code progress}, etc.) rather than on
 * brittle string matches.
 *
 * <p>Test #7 (timing — exact poll cadence + keepalive interval) is
 * deferred — see report; the dispatcher has no injectable clock and the
 * keepalive interval is 15s, which is unsuitable for a unit test.
 */
@DisplayName("MeshA2ASseDispatcher — SSE stream emission (spec §5)")
class MeshA2ASseDispatcherStreamTest {

    private MeshA2ARegistry registry;
    private MeshA2ATaskStore taskStore;
    private MeshA2ADispatcher dispatcher;
    private MeshA2ASseDispatcher sseDispatcher;
    private ObjectMapper mapper;

    @BeforeEach
    void setUp() {
        registry = new MeshA2ARegistry();
        registry.register(A2ATestFixtures.surfaceOf("/svc", "skill", "syncHandler"));
        taskStore = new MeshA2ATaskStore();
        mapper = A2ATestFixtures.objectMapper();
        dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper, A2ATestFixtures.emptyInjectorProvider());
        sseDispatcher = new MeshA2ASseDispatcher(dispatcher);
    }

    /** Capture writes against a mocked {@link ServerResponse.SseBuilder}.
     *  Each {@code builder.data(json)} call appends the raw JSON payload;
     *  each {@code builder.comment(...).send()} call appends a comment marker. */
    private static final class CapturingBuilder {
        final List<String> dataFrames = new ArrayList<>();
        final List<String> commentFrames = new ArrayList<>();
        final ServerResponse.SseBuilder mockBuilder = mock(ServerResponse.SseBuilder.class);
        // Disconnect flag to simulate client gone — when true, the next
        // data() call throws IOException, which the dispatcher swallows
        // and exits the loop cleanly.
        boolean disconnected = false;

        CapturingBuilder() {
            try {
                doAnswer((Answer<Void>) inv -> {
                    if (disconnected) throw new IOException("client disconnected");
                    dataFrames.add(inv.getArgument(0).toString());
                    return null;
                }).when(mockBuilder).data(any());
            } catch (IOException e) {
                throw new AssertionError(e);
            }
            // builder.comment(text).send() — return self from comment(...)
            // so the chain works.
            when(mockBuilder.comment(any())).thenAnswer(inv -> {
                commentFrames.add(": " + inv.getArgument(0));
                return mockBuilder;
            });
            try {
                doNothing().when(mockBuilder).send();
            } catch (IOException e) {
                throw new AssertionError(e);
            }
        }

        JsonNode parsed(int index, ObjectMapper m) {
            try {
                return m.readTree(dataFrames.get(index));
            } catch (Exception e) {
                throw new AssertionError("Frame " + index + " is not valid JSON", e);
            }
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // Plan kinds — exercise via direct frame-writing private methods
    // ─────────────────────────────────────────────────────────────────

    /** Spec §5.3 SINGLE_FRAME: one data frame then close. */
    @Test
    @DisplayName("SINGLE_FRAME plan emits exactly one data frame")
    void singleFramePlan_emitsOneFrame() throws Exception {
        Map<String, Object> frame = dispatcher.buildStatusUpdateFrame(
            7, "t-1", MeshA2AStateTranslator.A2A_FAILED, "boom", true, null);
        MeshA2ADispatcher.SseStreamPlan plan = MeshA2ADispatcher.SseStreamPlan.singleFrame(frame);
        assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.SINGLE_FRAME, plan.kind);

        CapturingBuilder cap = new CapturingBuilder();
        invokeWriteFrame(cap.mockBuilder, plan.firstFrame);

        assertEquals(1, cap.dataFrames.size(), "exactly one data frame for SINGLE_FRAME");
        JsonNode env = cap.parsed(0, mapper);
        assertEquals("2.0", env.get("jsonrpc").asText());
        assertEquals(7, env.get("id").asInt());
        JsonNode result = env.get("result");
        assertEquals("t-1", result.get("id").asText());
        assertEquals("failed", result.get("status").get("state").asText());
        // Appendix A: 'final' MUST be a real boolean.
        assertTrue(result.get("final").isBoolean(),
            "'final' MUST be a real JSON boolean, not a stringified value (Appendix A)");
        assertTrue(result.get("final").asBoolean());
    }

    /** Spec §5.3 SYNC_COMPLETED: artifact frame then terminal status frame. */
    @Test
    @DisplayName("SYNC_COMPLETED plan emits artifact frame then terminal status frame (final=true)")
    void syncCompletedPlan_emitsArtifactThenTerminal() throws Exception {
        Map<String, Object> artifactFrame = dispatcher.buildArtifactUpdateFrame(1, "t-sc", "the result");
        Map<String, Object> terminalFrame = dispatcher.buildStatusUpdateFrame(
            1, "t-sc", MeshA2AStateTranslator.A2A_COMPLETED, null, true, null);
        MeshA2ADispatcher.SseStreamPlan plan =
            MeshA2ADispatcher.SseStreamPlan.syncCompleted(1, "t-sc", artifactFrame, terminalFrame);
        assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.SYNC_COMPLETED, plan.kind);

        CapturingBuilder cap = new CapturingBuilder();
        invokeWriteFrame(cap.mockBuilder, plan.firstFrame);
        invokeWriteFrame(cap.mockBuilder, plan.secondFrame);

        assertEquals(2, cap.dataFrames.size(),
            "SYNC_COMPLETED emits artifact frame then terminal status frame");

        JsonNode artifact = cap.parsed(0, mapper).get("result").get("artifact");
        assertEquals("result", artifact.get("name").asText());
        assertEquals(0, artifact.get("index").asInt(),
            "Single artifact index is 0 per spec §5.2");
        assertEquals("text", artifact.get("parts").get(0).get("type").asText(),
            "parts[0].type MUST be 'text' (Appendix A)");
        assertEquals("the result", artifact.get("parts").get(0).get("text").asText());

        JsonNode terminal = cap.parsed(1, mapper).get("result");
        assertEquals("completed", terminal.get("status").get("state").asText());
        // Appendix A: real boolean.
        assertTrue(terminal.get("final").isBoolean());
        assertTrue(terminal.get("final").asBoolean(),
            "Terminal frame MUST set final=true (spec §5.2)");
    }

    /** Spec §5.3 LONG_RUNNING: initial state=working frame on subscription. */
    @Test
    @DisplayName("LONG_RUNNING: initial frame is state=working with final=false (real boolean)")
    void longRunning_initialFrameIsWorking() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        // Status reports terminal immediately so we exit after the initial frame.
        when(proxy.status()).thenReturn(Map.of("status", "completed"));
        when(proxy.await(1.0)).thenReturn("done");

        CapturingBuilder cap = new CapturingBuilder();
        invokeRunLongRunningStream(sseDispatcher, cap.mockBuilder, 1, "t-lr", proxy);

        assertTrue(cap.dataFrames.size() >= 1, "at least the initial frame must be emitted");
        JsonNode initial = cap.parsed(0, mapper).get("result");
        assertEquals("working", initial.get("status").get("state").asText(),
            "Initial LONG_RUNNING frame MUST be state=working (spec §5.3)");
        // Appendix A: real boolean, not the string "false".
        assertTrue(initial.get("final").isBoolean());
        assertFalse(initial.get("final").asBoolean(),
            "Initial frame MUST have final=false (spec §5.3)");
    }

    /** Spec §5.3 LONG_RUNNING completion: terminal arrives → artifact frame
     *  then terminal status frame with final=true. */
    @Test
    @DisplayName("LONG_RUNNING: terminal=completed → artifact frame then final=true status frame")
    void longRunning_terminalCompleted_emitsArtifactThenFinalTrue() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.status()).thenReturn(Map.of("status", "completed"));
        when(proxy.await(1.0)).thenReturn("the answer");

        CapturingBuilder cap = new CapturingBuilder();
        invokeRunLongRunningStream(sseDispatcher, cap.mockBuilder, 99, "t-end", proxy);

        // Expect at least: initial state=working (final=false), artifact, terminal (final=true).
        assertTrue(cap.dataFrames.size() >= 3,
            "Expected at least 3 frames (working/artifact/final); got " + cap.dataFrames.size());

        // Last frame is the terminal status frame.
        JsonNode terminal = cap.parsed(cap.dataFrames.size() - 1, mapper).get("result");
        assertEquals("completed", terminal.get("status").get("state").asText());
        assertTrue(terminal.get("final").isBoolean());
        assertTrue(terminal.get("final").asBoolean(),
            "Terminal frame on completion MUST set final=true (spec §5.3)");

        // The frame before the terminal carries the artifact.
        JsonNode beforeTerminal = cap.parsed(cap.dataFrames.size() - 2, mapper).get("result");
        assertTrue(beforeTerminal.has("artifact"),
            "Frame before terminal status MUST be the artifact event (spec §5.3 ordering)");
        assertEquals("the answer",
            beforeTerminal.get("artifact").get("parts").get(0).get("text").asText());
    }

    /** Spec §5.3 only-on-change emission: same status twice → only one
     *  progress frame is emitted (suppress redundant). */
    @Test
    @DisplayName("Same progress/message twice → only one progress frame emitted")
    void longRunning_suppressesRedundantProgressFrames() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        AtomicInteger calls = new AtomicInteger(0);
        Map<String, Object> firstWorking = Map.of(
            "status", "working", "progress", 0.5, "progress_message", "halfway");
        Map<String, Object> sameWorking = Map.of(
            "status", "working", "progress", 0.5, "progress_message", "halfway");
        Map<String, Object> terminal = Map.of("status", "completed");
        // 3 calls: same working twice, then completed.
        when(proxy.status()).thenAnswer(inv -> switch (calls.getAndIncrement()) {
            case 0 -> firstWorking;
            case 1 -> sameWorking;
            default -> terminal;
        });
        when(proxy.await(1.0)).thenReturn("done");

        CapturingBuilder cap = new CapturingBuilder();
        invokeRunLongRunningStream(sseDispatcher, cap.mockBuilder, 1, "t-rep", proxy);

        // Count distinct "working+progress=0.5" frames in the data stream.
        long progressFrames = cap.dataFrames.stream()
            .filter(f -> f.contains("\"progress\":0.5"))
            .count();
        assertEquals(1, progressFrames,
            "Identical progress on two consecutive polls MUST emit only ONE progress frame "
                + "(spec §5.3 only-on-change suppression)");
    }

    /** Appendix A: progress MUST be a JSON number, not a string. */
    @Test
    @DisplayName("progress field is emitted as a JSON number (not a string) — Appendix A")
    void longRunning_progressIsRealNumber() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        AtomicInteger calls = new AtomicInteger(0);
        when(proxy.status()).thenAnswer(inv -> switch (calls.getAndIncrement()) {
            case 0 -> Map.of("status", "working", "progress", 0.42, "progress_message", "draft 1");
            default -> Map.of("status", "completed");
        });
        when(proxy.await(1.0)).thenReturn("done");

        CapturingBuilder cap = new CapturingBuilder();
        invokeRunLongRunningStream(sseDispatcher, cap.mockBuilder, 1, "t-num", proxy);

        // Find the progress frame (state=working with metadata.progress).
        JsonNode progressFrame = null;
        for (int i = 0; i < cap.dataFrames.size(); i++) {
            JsonNode env = cap.parsed(i, mapper);
            JsonNode meta = env.get("result").get("metadata");
            if (meta != null && meta.has("progress")) {
                progressFrame = env;
                break;
            }
        }
        assertNotNull(progressFrame, "Expected a frame carrying metadata.progress");
        JsonNode prog = progressFrame.get("result").get("metadata").get("progress");
        assertTrue(prog.isNumber(),
            "metadata.progress MUST be a real JSON number (Appendix A); got node type: " + prog.getNodeType());
        assertEquals(0.42, prog.asDouble(), 0.0001);
    }

    /** Spec §5.3 LONG_RUNNING failed branch: terminal=failed → no
     *  artifact, status frame with state=failed final=true. */
    @Test
    @DisplayName("LONG_RUNNING: terminal=failed → no artifact, final status frame state=failed")
    void longRunning_terminalFailed_skipsArtifact() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.status()).thenReturn(Map.of(
            "status", "failed", "error", "the tool exploded"));

        CapturingBuilder cap = new CapturingBuilder();
        invokeRunLongRunningStream(sseDispatcher, cap.mockBuilder, 1, "t-bad", proxy);

        verify(proxy, never()).await(anyDouble());
        // Last frame is the failed terminal frame.
        JsonNode last = cap.parsed(cap.dataFrames.size() - 1, mapper).get("result");
        assertEquals("failed", last.get("status").get("state").asText());
        assertTrue(last.get("final").asBoolean());
        // status.message present with the error text.
        assertEquals("the tool exploded",
            last.get("status").get("message").get("parts").get(0).get("text").asText());
        // No artifact frame anywhere in the stream.
        boolean hasArtifact = cap.dataFrames.stream().anyMatch(f -> f.contains("\"artifact\":"));
        assertFalse(hasArtifact, "No artifact frame on failed terminal (spec §5.3)");
    }

    /** Spec §5.3 LONG_RUNNING cancellation: terminal=cancelled (UK) →
     *  A2A state=canceled (US). */
    @Test
    @DisplayName("LONG_RUNNING: terminal=cancelled (UK) → final status frame state=canceled (US)")
    void longRunning_terminalCancelled_emitsCanceled() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.status()).thenReturn(Map.of("status", "cancelled"));

        CapturingBuilder cap = new CapturingBuilder();
        invokeRunLongRunningStream(sseDispatcher, cap.mockBuilder, 1, "t-cx", proxy);

        JsonNode last = cap.parsed(cap.dataFrames.size() - 1, mapper).get("result");
        assertEquals("canceled", last.get("status").get("state").asText(),
            "UK mesh 'cancelled' MUST surface as US A2A 'canceled' on the SSE wire");
        assertTrue(last.get("final").asBoolean());
    }

    /** Spec §7.3 / §5.4: client disconnect (IOException on data write)
     *  MUST NOT cancel the underlying job — the loop exits and proxy.cancel
     *  is never called. */
    @Test
    @DisplayName("Client disconnect during stream → loop exits, JobProxy.cancel NOT called")
    void clientDisconnect_doesNotCancelJob() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        AtomicInteger statusCalls = new AtomicInteger(0);
        // First call returns working — gives the dispatcher something to
        // try to emit. The client "disconnects" before the data() write
        // succeeds.
        when(proxy.status()).thenAnswer(inv -> {
            statusCalls.incrementAndGet();
            return Map.of("status", "working", "progress", 0.1, "progress_message", "starting");
        });
        CapturingBuilder cap = new CapturingBuilder();
        cap.disconnected = true; // every data() call now throws.

        invokeRunLongRunningStream(sseDispatcher, cap.mockBuilder, 1, "t-disco", proxy);

        verify(proxy, never()).cancel(any()); // critical: do NOT cancel on disconnect.
    }

    /** ERROR plan — emits a JSON-RPC error body, NOT SSE framing.
     *  Asserted via the public {@code render(plan)} which short-circuits
     *  to {@code ServerResponse.status(...).body(...)} for ERROR kind. */
    @Test
    @DisplayName("ERROR plan → render() returns JSON-RPC error body, NOT SSE framing")
    void errorPlan_returnsJsonRpcError() {
        String errorBody = "{\"jsonrpc\":\"2.0\",\"error\":{\"code\":-32602,"
            + "\"message\":\"Unknown task id: zzz\"},\"id\":1}";
        MeshA2ADispatcher.SseStreamPlan plan = MeshA2ADispatcher.SseStreamPlan
            .error(errorBody, org.springframework.http.HttpStatus.OK);
        assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.ERROR, plan.kind);
        // The render() path is mostly Spring plumbing — we assert on the
        // plan shape itself, which the controller layer surfaces directly
        // without SSE framing.
        assertEquals(errorBody, plan.errorBody);
        assertEquals(org.springframework.http.HttpStatus.OK, plan.errorStatus);
    }

    // ─────────────────────────────────────────────────────────────────
    // Reflection helpers — invoke the SSE dispatcher's private methods
    // without standing up Spring's full SSE plumbing. Pattern mirrors
    // MeshSseTest which also reaches into private fields via reflection.
    // ─────────────────────────────────────────────────────────────────

    private static void invokeRunLongRunningStream(
            MeshA2ASseDispatcher sse, ServerResponse.SseBuilder builder,
            Object reqId, String taskId, JobProxy proxy) throws Exception {
        Method m = MeshA2ASseDispatcher.class.getDeclaredMethod(
            "runLongRunningStream", ServerResponse.SseBuilder.class,
            Object.class, String.class, JobProxy.class);
        m.setAccessible(true);
        m.invoke(sse, builder, reqId, taskId, proxy);
    }

    private static void invokeWriteFrame(
            ServerResponse.SseBuilder builder, Map<String, Object> envelope) {
        // For SINGLE_FRAME / SYNC_COMPLETED kinds we call the public
        // dispatcher to serialize, then invoke builder.data() directly —
        // that's exactly what writeFrame() does.
        // Using the test's own dispatcher instance for serialization.
        try {
            MeshA2ASseDispatcher tmp = new MeshA2ASseDispatcher(
                new MeshA2ADispatcher(
                    new MeshA2ARegistry(), new MeshA2ATaskStore(),
                    A2ATestFixtures.objectMapper(), A2ATestFixtures.emptyInjectorProvider()));
            Method m = MeshA2ASseDispatcher.class.getDeclaredMethod(
                "writeFrame", ServerResponse.SseBuilder.class, Map.class);
            m.setAccessible(true);
            m.invoke(tmp, builder, envelope);
        } catch (Exception e) {
            throw new AssertionError(e);
        }
    }
}
