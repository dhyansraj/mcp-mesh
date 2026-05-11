package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import io.mcpmesh.core.MeshException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.Mockito.*;

/**
 * Unit tests for {@link MeshA2ADispatcher#dispatch} on the {@code tasks/get}
 * verb when the task is parked with a live {@link JobProxy} (spec §4.4).
 *
 * <p>Per spec §4.4 the producer pulls the current mesh status from the
 * parked proxy, translates the mesh status to an A2A state, and includes
 * a result artifact ONLY when the state is {@code completed} AND the
 * producer can synchronously fetch the final value via
 * {@link JobProxy#await(double)}.
 *
 * <p>Transient status() failure (spec §4.4): MUST return a
 * {@code state=working} envelope with the error text in {@code status.message}
 * — NOT a JSON-RPC error. The registry's transient unreachability is not
 * authoritative evidence the job is dead.
 *
 * <p>UK 'cancelled' → US 'canceled' (spec §7.2 / Appendix B) is asserted
 * on the dispatcher boundary, not just on the translator unit.
 */
@DisplayName("MeshA2ADispatcher.tasks/get live-status pull (spec §4.4)")
class MeshA2ADispatcherTasksGetLiveStatusTest {

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

    private JsonNode dispatchGet(String taskId) throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/get", Map.of("id", taskId));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        return mapper.readTree(resp.getBody());
    }

    /** Spec §4.4: parked task + status() reports working → A2A state=working,
     *  no artifact, no proxy.await() call. */
    @Test
    @DisplayName("status=working → A2A state=working, no artifact, no await() call")
    void working_returnsWorkingNoArtifact() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.status()).thenReturn(Map.of("status", "working", "progress", 0.25));
        taskStore.put("t-w", new MeshA2ATaskStore.TaskRecord(
            "t-w", null, null, null, proxy));

        JsonNode env = dispatchGet("t-w");

        JsonNode result = env.get("result");
        assertEquals("working", result.get("status").get("state").asText());
        assertTrue(result.get("artifacts").isArray() && result.get("artifacts").isEmpty(),
            "No artifact must be emitted when state=working");
        verify(proxy, never()).await(anyDouble());
        // Spec §4.4: progress lifted to metadata.progress as a JSON number.
        assertTrue(result.has("metadata"));
        assertTrue(result.get("metadata").get("progress").isNumber(),
            "progress MUST be a JSON number, never stringified (Appendix A)");
    }

    /** Spec §4.4: status=completed → A2A state=completed, await(1.0)
     *  invoked, artifact populated from the await() return value. */
    @Test
    @DisplayName("status=completed → state=completed + artifact from await(1.0)")
    void completed_invokesAwaitAndPopulatesArtifact() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.status()).thenReturn(Map.of("status", "completed"));
        when(proxy.await(1.0)).thenReturn("the answer is 42");
        taskStore.put("t-c", new MeshA2ATaskStore.TaskRecord(
            "t-c", null, null, null, proxy));

        JsonNode env = dispatchGet("t-c");

        JsonNode result = env.get("result");
        assertEquals("completed", result.get("status").get("state").asText());
        verify(proxy, times(1)).await(1.0);
        assertEquals(1, result.get("artifacts").size(),
            "Single artifact emitted on completed task");
        JsonNode artifact = result.get("artifacts").get(0);
        assertEquals("result", artifact.get("name").asText(),
            "Canonical single-artifact name is 'result' per spec §5.2");
        assertEquals(0, artifact.get("index").asInt(),
            "Single-artifact index is 0 per spec §5.2");
        // Spec Appendix A: parts[0].type MUST be emitted as "text".
        assertEquals("text", artifact.get("parts").get(0).get("type").asText(),
            "parts[0].type MUST be 'text' for forward compatibility (Appendix A)");
        assertEquals("the answer is 42", artifact.get("parts").get(0).get("text").asText());
    }

    /** Spec §4.4: status=failed → A2A state=failed, NO await() call
     *  (don't block on a failed job's payload). */
    @Test
    @DisplayName("status=failed → state=failed, NO await() call")
    void failed_skipsAwait() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.status()).thenReturn(Map.of(
            "status", "failed",
            "error", "tool returned non-zero"));
        taskStore.put("t-f", new MeshA2ATaskStore.TaskRecord(
            "t-f", null, null, null, proxy));

        JsonNode env = dispatchGet("t-f");

        JsonNode result = env.get("result");
        assertEquals("failed", result.get("status").get("state").asText());
        verify(proxy, never()).await(anyDouble());
        // Spec §5.5: status.message carries the error text when available.
        assertEquals("tool returned non-zero",
            result.get("status").get("message").get("parts").get(0).get("text").asText());
        assertTrue(result.get("artifacts").isArray() && result.get("artifacts").isEmpty(),
            "No artifact must be emitted on failed jobs");
    }

    /** Spec §7.2 / Appendix B: mesh 'cancelled' (UK) → A2A 'canceled' (US). */
    @Test
    @DisplayName("status=cancelled (UK) → A2A state=canceled (US) — Appendix B")
    void cancelled_translatedToUsSpelling() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.status()).thenReturn(Map.of("status", "cancelled"));
        taskStore.put("t-x", new MeshA2ATaskStore.TaskRecord(
            "t-x", null, null, null, proxy));

        JsonNode env = dispatchGet("t-x");
        assertEquals("canceled", env.get("result").get("status").get("state").asText(),
            "Mesh UK 'cancelled' MUST surface as A2A US 'canceled' "
                + "at the producer boundary (spec Appendix B)");
        verify(proxy, never()).await(anyDouble());
    }

    /** Spec §4.4 transient unreachability: status() throws → A2A
     *  state=working envelope with error text in status.message, NOT a
     *  -32602 error. */
    @Test
    @DisplayName("status() throws → state=working + error in status.message (spec §4.4 transient)")
    void transientStatusFailure_returnsWorkingWithMessage() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.status())
            .thenThrow(new MeshException("registry connect timeout"));
        taskStore.put("t-tx", new MeshA2ATaskStore.TaskRecord(
            "t-tx", null, null, null, proxy));

        String body = A2ATestFixtures.jsonRpcBody(99, "tasks/get",
            Map.of("id", "t-tx"));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        assertEquals(200, resp.getStatusCode().value(),
            "Transient status() failure must NOT surface as HTTP error");
        JsonNode env = mapper.readTree(resp.getBody());

        // No JSON-RPC error code — this is a snapshot, not a protocol error.
        assertFalse(env.has("error"),
            "Transient status() failure MUST be a state=working snapshot, NOT a JSON-RPC error "
                + "(spec §4.4: registry transient unreachability not authoritative)");

        JsonNode result = env.get("result");
        assertEquals("working", result.get("status").get("state").asText());
        String msg = result.get("status").get("message").get("parts").get(0).get("text").asText();
        assertTrue(msg.contains("registry connect timeout"),
            "Error text must be present in status.message.parts[0].text — got: " + msg);
    }

    /** Spec §4.4: missing params.id → -32602. Sanity coverage on the
     *  error branch shared with cancel/resubscribe. */
    @Test
    @DisplayName("Missing id → -32602")
    void missingId_returnsInvalidParams() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/get", Map.of());
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        JsonNode env = mapper.readTree(resp.getBody());
        assertEquals(MeshA2ADispatcher.JSONRPC_INVALID_PARAMS,
            env.get("error").get("code").asInt());
    }

    /** Spec §4.4: unknown task_id → -32602. */
    @Test
    @DisplayName("Unknown task id → -32602 'Unknown task id: ...'")
    void unknownTaskId_returnsInvalidParams() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/get",
            Map.of("id", "no-such"));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        JsonNode env = mapper.readTree(resp.getBody());
        assertEquals(MeshA2ADispatcher.JSONRPC_INVALID_PARAMS,
            env.get("error").get("code").asInt());
        assertTrue(env.get("error").get("message").asText().contains("Unknown task id"));
    }

    /** Spec §4.4: cached terminal envelope is returned verbatim WITHOUT
     *  re-polling the JobProxy — even if the proxy is still attached. */
    @Test
    @DisplayName("Cached terminal envelope short-circuits the proxy poll")
    void cachedTerminalEnvelopeShortCircuitsPoll() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        Map<String, Object> cached = Map.of(
            "id", "t-cached",
            "sessionId", "t-cached",
            "status", Map.of("state", "completed"),
            "artifacts", java.util.List.of(),
            "__cached", "yes"
        );
        taskStore.put("t-cached", new MeshA2ATaskStore.TaskRecord(
            "t-cached", null, cached, System.currentTimeMillis(), proxy));

        JsonNode env = dispatchGet("t-cached");
        assertEquals("yes", env.get("result").get("__cached").asText(),
            "Cached envelope must be returned verbatim");
        verify(proxy, never()).status();
        verify(proxy, never()).await(anyDouble());
    }
}
