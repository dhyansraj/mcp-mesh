package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;

/**
 * Unit tests for {@link MeshA2ADispatcher#buildResubscribeStream} —
 * the {@code tasks/resubscribe} entry point (spec §4.7).
 *
 * <p>Per spec §4.7:
 * <ul>
 *   <li>Missing {@code params.id} → {@code -32602} as a standard
 *       JSON-RPC response (NOT SSE — the connection has not been
 *       promoted to {@code text/event-stream} yet).</li>
 *   <li>Unknown {@code task_id} → {@code -32602}.</li>
 *   <li>Already-terminal task → ONE terminal status event + close
 *       (no replay per spec §4.7 / Appendix B item documented in spec).</li>
 *   <li>Active non-terminal task with {@code jobProxy} → switches to
 *       {@code LONG_RUNNING} plan (initial state=working frame, poll loop).</li>
 * </ul>
 */
@DisplayName("MeshA2ADispatcher.tasks/resubscribe (spec §4.7)")
class MeshA2ADispatcherResubscribeTest {

    private MeshA2ARegistry registry;
    private MeshA2ATaskStore taskStore;
    private MeshA2ADispatcher dispatcher;
    private ObjectMapper mapper;

    @BeforeEach
    void setUp() {
        registry = new MeshA2ARegistry();
        registry.register(A2ATestFixtures.surfaceOf("/svc", "skill", "syncHandler"));
        taskStore = new MeshA2ATaskStore();
        mapper = A2ATestFixtures.objectMapper();
        dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper, A2ATestFixtures.emptyInjectorProvider());
    }

    /** Spec §4.7: missing id → -32602 as a JSON-RPC response (NOT SSE). */
    @Test
    @DisplayName("Missing id → ERROR plan with JSON-RPC -32602 body (NOT SSE)")
    void missingId_returnsErrorPlanNotSse() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/resubscribe", Map.of());
        MeshA2ADispatcher.SseStreamPlan plan = dispatcher.buildResubscribeStream(body);

        assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.ERROR, plan.kind,
            "Spec §4.7: missing id MUST surface as a JSON-RPC error response, NOT SSE framing");
        assertNotNull(plan.errorBody);
        JsonNode env = mapper.readTree(plan.errorBody);
        assertEquals(MeshA2ADispatcher.JSONRPC_INVALID_PARAMS,
            env.get("error").get("code").asInt());
        assertTrue(env.get("error").get("message").asText().contains("id"),
            "Error message must reference the missing 'id' field");
    }

    /** Spec §4.7: unknown task_id → -32602. */
    @Test
    @DisplayName("Unknown task id → ERROR plan with -32602 'Unknown task id'")
    void unknownTaskId_returnsErrorPlan() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(2, "tasks/resubscribe",
            Map.of("id", "no-such"));
        MeshA2ADispatcher.SseStreamPlan plan = dispatcher.buildResubscribeStream(body);

        assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.ERROR, plan.kind);
        JsonNode env = mapper.readTree(plan.errorBody);
        assertEquals(MeshA2ADispatcher.JSONRPC_INVALID_PARAMS,
            env.get("error").get("code").asInt());
        assertTrue(env.get("error").get("message").asText().contains("Unknown task id"));
    }

    /** Spec §4.7: already-terminal task → ONE status event + close (no replay). */
    @Test
    @DisplayName("Already-terminal task → SINGLE_FRAME plan with terminal status event")
    void terminalTask_returnsSingleFrame() throws Exception {
        Map<String, Object> envelope = Map.of(
            "id", "t-done",
            "sessionId", "t-done",
            "status", Map.of(
                "state", "completed",
                "message", Map.of(
                    "role", "agent",
                    "parts", java.util.List.of(Map.of("type", "text", "text", "all done")))
            ),
            "artifacts", java.util.List.of(),
            "history", java.util.List.of()
        );
        taskStore.put("t-done", new MeshA2ATaskStore.TaskRecord(
            "t-done", null, envelope, System.currentTimeMillis(), null));

        String body = A2ATestFixtures.jsonRpcBody(3, "tasks/resubscribe",
            Map.of("id", "t-done"));
        MeshA2ADispatcher.SseStreamPlan plan = dispatcher.buildResubscribeStream(body);

        assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.SINGLE_FRAME, plan.kind,
            "Already-terminal task on resubscribe → SINGLE_FRAME (one terminal event, then close)");
        assertNotNull(plan.firstFrame);

        // Frame is a JSON-RPC envelope carrying the terminal status update.
        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) plan.firstFrame.get("result");
        @SuppressWarnings("unchecked")
        Map<String, Object> status = (Map<String, Object>) result.get("status");
        assertEquals("completed", status.get("state"));
        assertEquals(Boolean.TRUE, result.get("final"),
            "Terminal resubscribe frame MUST set final=true so the consumer closes");
    }

    /** Spec §4.7: active non-terminal task with JobProxy → LONG_RUNNING plan. */
    @Test
    @DisplayName("Active non-terminal task → LONG_RUNNING plan with proxy slot preserved")
    void activeTask_returnsLongRunningPlan() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        taskStore.put("t-live", new MeshA2ATaskStore.TaskRecord(
            "t-live", null, null, null, proxy));

        String body = A2ATestFixtures.jsonRpcBody(4, "tasks/resubscribe",
            Map.of("id", "t-live"));
        MeshA2ADispatcher.SseStreamPlan plan = dispatcher.buildResubscribeStream(body);

        assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.LONG_RUNNING, plan.kind,
            "Active non-terminal task on resubscribe → LONG_RUNNING (poll loop resumes)");
        assertEquals("t-live", plan.taskId);
        assertSame(proxy, plan.proxy,
            "LONG_RUNNING plan must carry the same JobProxy handle from the store "
                + "(reference identity required for FFI handle stability)");
    }

    /** Spec §4.7: non-terminal record without a JobProxy slot is an
     *  inconsistent state — dispatcher synthesizes a single failed frame
     *  rather than hanging. Defensive behaviour. */
    @Test
    @DisplayName("Non-terminal record without JobProxy → SINGLE_FRAME with state=failed (defensive)")
    void inconsistentRecord_returnsFailedSingleFrame() throws Exception {
        taskStore.put("t-inc", new MeshA2ATaskStore.TaskRecord(
            "t-inc", null, null, null, null));

        String body = A2ATestFixtures.jsonRpcBody(5, "tasks/resubscribe",
            Map.of("id", "t-inc"));
        MeshA2ADispatcher.SseStreamPlan plan = dispatcher.buildResubscribeStream(body);

        assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.SINGLE_FRAME, plan.kind);
        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) plan.firstFrame.get("result");
        @SuppressWarnings("unchecked")
        Map<String, Object> status = (Map<String, Object>) result.get("status");
        assertEquals("failed", status.get("state"),
            "Inconsistent record (non-terminal w/o proxy) MUST surface as state=failed "
                + "so the client doesn't hang waiting for a stream that won't make progress");
        assertEquals(Boolean.TRUE, result.get("final"));
    }

    /** Spec §4.1: parse-error response on malformed body — JSON-RPC -32700. */
    @Test
    @DisplayName("Malformed request body → ERROR plan with -32700 Parse error")
    void malformedBody_returnsParseError() throws Exception {
        MeshA2ADispatcher.SseStreamPlan plan = dispatcher.buildResubscribeStream("not json");
        assertEquals(MeshA2ADispatcher.SseStreamPlan.Kind.ERROR, plan.kind);
        JsonNode env = mapper.readTree(plan.errorBody);
        assertEquals(MeshA2ADispatcher.JSONRPC_PARSE_ERROR,
            env.get("error").get("code").asInt());
    }
}
