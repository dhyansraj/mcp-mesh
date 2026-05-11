package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import io.mcpmesh.core.MeshException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * Unit tests for {@link MeshA2ADispatcher#dispatch} on the {@code tasks/cancel}
 * verb (spec §4.5).
 *
 * <p>Per spec §4.5: cancel is idempotent and best-effort. Underlying
 * {@code JobProxy.cancel()} exceptions are swallowed (the job may already
 * be terminal). Already-terminal tasks echo the cached envelope rather
 * than re-poking the proxy.
 *
 * <p>Error cases (spec §4.5):
 * <ul>
 *   <li>Missing {@code params.id} → {@code -32602 Invalid params}.</li>
 *   <li>Unknown {@code task_id} → {@code -32602 Unknown task id}.</li>
 * </ul>
 */
@DisplayName("MeshA2ADispatcher.tasks/cancel (spec §4.5)")
class MeshA2ADispatcherCancelTest {

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

    /** Spec §4.5: missing params.id → -32602 Invalid params. */
    @Test
    @DisplayName("Missing id → -32602 with message naming 'id'")
    void missingId_returnsInvalidParams() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(7, "tasks/cancel", Map.of());
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        assertEquals(200, resp.getStatusCode().value(),
            "JSON-RPC errors return HTTP 200 with the error in the body");
        JsonNode env = mapper.readTree(resp.getBody());
        assertEquals(MeshA2ADispatcher.JSONRPC_INVALID_PARAMS,
            env.get("error").get("code").asInt());
        String msg = env.get("error").get("message").asText();
        assertTrue(msg.contains("id"), "Error message must mention the missing 'id' field, got: " + msg);
        assertEquals(7, env.get("id").asInt(), "Request id MUST be echoed in error responses");
    }

    /** Spec §4.5: unknown task_id → -32602 Unknown task id. */
    @Test
    @DisplayName("Unknown task id → -32602 'Unknown task id: ...'")
    void unknownTaskId_returnsInvalidParams() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(8, "tasks/cancel", Map.of("id", "no-such"));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        JsonNode env = mapper.readTree(resp.getBody());
        assertEquals(MeshA2ADispatcher.JSONRPC_INVALID_PARAMS,
            env.get("error").get("code").asInt());
        assertTrue(env.get("error").get("message").asText().contains("Unknown task id"),
            "Error message must contain 'Unknown task id' per spec §4.5");
    }

    /** Spec §4.5: already-terminal task → echoes the cached terminal envelope
     *  (idempotent ack, no proxy interaction). */
    @Test
    @DisplayName("Already-terminal task → echo cached envelope (idempotent ack)")
    void terminalTask_echoesCachedEnvelope() throws Exception {
        // Seed the store with a terminal record carrying a recognisable
        // sentinel field so we can assert the response is the cached one.
        Map<String, Object> cached = new LinkedHashMap<>();
        cached.put("id", "t-done");
        cached.put("sessionId", "t-done");
        cached.put("status", Map.of("state", "completed"));
        cached.put("artifacts", java.util.List.of());
        cached.put("history", java.util.List.of());
        cached.put("__cached_marker", "FROM_CACHE");

        JobProxy proxy = mock(JobProxy.class);
        taskStore.put("t-done", new MeshA2ATaskStore.TaskRecord(
            "t-done", null, cached, System.currentTimeMillis(), proxy));

        String body = A2ATestFixtures.jsonRpcBody(11, "tasks/cancel",
            Map.of("id", "t-done", "reason", "user pressed stop"));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        JsonNode env = mapper.readTree(resp.getBody());

        // Cached envelope echoed verbatim (idempotent ack).
        assertEquals("FROM_CACHE", env.get("result").get("__cached_marker").asText(),
            "Already-terminal cancel must echo cached envelope (spec §4.5 idempotent)");
        // Proxy must NOT have been called — idempotent ack short-circuits.
        verify(proxy, never()).cancel(any());
        verify(proxy, never()).status();
    }

    /** Spec §4.5: non-terminal task + JobProxy.cancel() succeeds → post-cancel
     *  status reads as terminal and we return the canceled envelope. */
    @Test
    @DisplayName("Non-terminal task + cancel() succeeds → state=canceled returned")
    void nonTerminal_cancelSucceeds_returnsCanceledEnvelope() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        // proxy.cancel() does NOT throw; proxy.status() reports cancelled (UK).
        when(proxy.status()).thenReturn(Map.of("status", "cancelled"));

        taskStore.put("t-alive", new MeshA2ATaskStore.TaskRecord(
            "t-alive", null, null, null, proxy));

        String body = A2ATestFixtures.jsonRpcBody(12, "tasks/cancel",
            Map.of("id", "t-alive", "reason", "user pressed stop"));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        JsonNode env = mapper.readTree(resp.getBody());

        verify(proxy, times(1)).cancel("user pressed stop");
        assertEquals("canceled", env.get("result").get("status").get("state").asText(),
            "UK 'cancelled' from mesh substrate must surface as US 'canceled' on A2A wire");
        // Record must now be terminal (markTerminal called by dispatcher).
        MeshA2ATaskStore.TaskRecord post = taskStore.get("t-alive");
        assertNotNull(post.terminalAt(),
            "Successful cancel must flip the record to terminal so subsequent "
                + "tasks/get is short-circuited from the cache");
    }

    /** Spec §4.5: cancel exceptions on the underlying job are logged and
     *  SWALLOWED. The producer falls back to synthesizing a state=canceled
     *  envelope so the A2A client sees a clean terminal response. */
    @Test
    @DisplayName("Non-terminal task + cancel() throws → exception swallowed, canceled envelope synthesized")
    void nonTerminal_cancelThrows_swallowsAndSynthesizesCanceled() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        doThrow(new MeshException("registry unreachable"))
            .when(proxy).cancel(any());
        // Post-cancel status() ALSO fails — exercises the
        // "transient unreachability" fallback path.
        when(proxy.status()).thenThrow(new MeshException("registry still unreachable"));

        taskStore.put("t-flaky", new MeshA2ATaskStore.TaskRecord(
            "t-flaky", null, null, null, proxy));

        String body = A2ATestFixtures.jsonRpcBody(13, "tasks/cancel",
            Map.of("id", "t-flaky", "reason", "user pressed stop"));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);

        // Did NOT propagate the proxy exception to the A2A caller.
        assertEquals(200, resp.getStatusCode().value(),
            "JobProxy.cancel() exceptions must NOT surface as HTTP errors — spec §4.5");
        JsonNode env = mapper.readTree(resp.getBody());
        assertEquals("canceled", env.get("result").get("status").get("state").asText(),
            "Cancel exceptions must be swallowed and the response must synthesize "
                + "a state=canceled terminal envelope (spec §4.5 fallback)");
    }

    /** Spec §4.5: cancel without a JobProxy slot (defensive — shouldn't
     *  happen in practice but the dispatcher must not crash). The cancel
     *  request still returns a terminal envelope. */
    @Test
    @DisplayName("Cancel on non-terminal record without JobProxy slot does not crash")
    void noProxy_returnsCanceled() throws Exception {
        // Non-terminal record with proxy=null — exotic but the dispatcher
        // must remain robust.
        taskStore.put("t-no-proxy", new MeshA2ATaskStore.TaskRecord(
            "t-no-proxy", null, null, null, null));

        String body = A2ATestFixtures.jsonRpcBody(14, "tasks/cancel",
            Map.of("id", "t-no-proxy"));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        JsonNode env = mapper.readTree(resp.getBody());

        // No proxy → no cancel attempt; buildTaskFromLiveStatus returns
        // a state=working envelope, which is non-terminal, so we synthesize
        // a canceled envelope per the dispatcher fallback path.
        String state = env.get("result").get("status").get("state").asText();
        assertEquals("canceled", state,
            "Missing JobProxy must still produce a clean canceled terminal");
    }
}
