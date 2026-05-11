package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link MeshA2ADispatcher#dispatch} on the {@code tasks/send}
 * verb when the user handler returns a {@link JobProxy} — the long-running
 * branch (spec §4.3).
 *
 * <p>Per spec §4.3 long-running branch:
 * <ul>
 *   <li>Response is a {@code Task} envelope with {@code status.state="working"}
 *       and an empty {@code artifacts[]} array.</li>
 *   <li>{@code sessionId} is echoed back (defaulting to the task_id when missing).</li>
 *   <li>The task is parked in the {@link MeshA2ATaskStore} with a non-null
 *       {@code jobProxy} slot — kept alive across {@code tasks/get} /
 *       {@code tasks/cancel} / {@code tasks/resubscribe} calls.</li>
 *   <li>{@code final} is NOT set on this envelope — {@code final} is only
 *       emitted on SSE frames (spec §5.2).</li>
 * </ul>
 */
@DisplayName("MeshA2ADispatcher.tasks/send long-running branch (spec §4.3)")
class MeshA2ADispatcherLongRunningSendTest {

    private MeshA2ARegistry registry;
    private MeshA2ATaskStore taskStore;
    private MeshA2ADispatcher dispatcher;
    private ObjectMapper mapper;

    @BeforeEach
    void setUp() {
        registry = new MeshA2ARegistry();
        registry.register(A2ATestFixtures.surfaceOf("/svc", "skill", "longRunningHandler"));
        taskStore = new MeshA2ATaskStore();
        mapper = A2ATestFixtures.objectMapper();
        dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper, A2ATestFixtures.emptyInjectorProvider());
    }

    @AfterEach
    void tearDown() {
        A2ATestFixtures.TestHandlerBean.PROXY_SLOT.remove();
    }

    /** Spec §4.3 long-running: handler returning JobProxy → state=working
     *  envelope, empty artifacts, task parked. */
    @Test
    @DisplayName("Handler returns JobProxy → state=working envelope with empty artifacts")
    void longRunningReturn_buildsWorkingEnvelope() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.jobId()).thenReturn("job-xyz");
        A2ATestFixtures.TestHandlerBean.PROXY_SLOT.set(proxy);

        String body = A2ATestFixtures.jsonRpcBody(42, "tasks/send",
            Map.of("id", "t-long", "sessionId", "s-long", "message",
                Map.of("role", "user", "parts",
                    java.util.List.of(Map.of("type", "text", "text", "go")))));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);

        assertEquals(200, resp.getStatusCode().value());
        JsonNode env = mapper.readTree(resp.getBody());

        // JSON-RPC envelope shape (spec §4.1).
        assertEquals("2.0", env.get("jsonrpc").asText());
        assertEquals(42, env.get("id").asInt(), "Request id echoed back (spec §4.1)");

        JsonNode result = env.get("result");
        assertEquals("t-long", result.get("id").asText());
        assertEquals("s-long", result.get("sessionId").asText(),
            "sessionId echoed back per spec §4.2");

        // Spec §4.3 long-running: state=working, empty artifacts.
        assertEquals("working", result.get("status").get("state").asText(),
            "Long-running branch returns state=working immediately");
        assertTrue(result.get("status").has("timestamp"),
            "Status timestamp present (spec §5.2 timestamp REQUIRED)");
        assertTrue(result.get("artifacts").isArray()
                && result.get("artifacts").isEmpty(),
            "artifacts MUST be empty array on long-running send (spec §4.3)");

        // Spec §5.2: final is for SSE frames only — NOT present on the
        // synchronous Task envelope.
        assertFalse(result.has("final"),
            "'final' field is for SSE frames only, MUST NOT appear on JSON-RPC envelope");
    }

    /** Spec §4.8: task parked in store with non-null jobProxy slot. */
    @Test
    @DisplayName("Long-running send parks task in store with jobProxy reference preserved")
    void longRunningReturn_parksTaskWithProxySlot() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.jobId()).thenReturn("job-park");
        A2ATestFixtures.TestHandlerBean.PROXY_SLOT.set(proxy);

        String body = A2ATestFixtures.jsonRpcBody("req-1", "tasks/send",
            Map.of("id", "t-parked", "message", Map.of()));
        dispatcher.dispatch("/svc", body);

        MeshA2ATaskStore.TaskRecord record = taskStore.get("t-parked");
        assertNotNull(record, "Task must be parked in the store");
        assertNull(record.terminalAt(),
            "Long-running record is NOT terminal — terminalAt must be null");
        assertNull(record.terminalEnvelope(),
            "Long-running record has no terminal envelope yet");
        assertSame(proxy, record.jobProxy(),
            "JobProxy slot must hold the EXACT proxy returned by the handler "
                + "(reference equality — needed for FFI handle stability)");
    }

    /** Spec §4.2: sessionId defaults to task_id when omitted. */
    @Test
    @DisplayName("sessionId defaults to task_id when omitted (spec §4.2)")
    void sessionIdDefaultsToTaskId() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.jobId()).thenReturn("job-default");
        A2ATestFixtures.TestHandlerBean.PROXY_SLOT.set(proxy);

        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t-no-session"));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        JsonNode env = mapper.readTree(resp.getBody());

        assertEquals("t-no-session", env.get("result").get("sessionId").asText(),
            "sessionId defaults to task_id per spec §4.2");
    }

    /** Spec §4.3: duplicate task_id → -32602 already in use. */
    @Test
    @DisplayName("Duplicate task_id on long-running send → -32602 'already in use'")
    void duplicateTaskId_returnsAlreadyInUse() throws Exception {
        // Park a first task.
        JobProxy proxy1 = mock(JobProxy.class);
        when(proxy1.jobId()).thenReturn("job-1");
        A2ATestFixtures.TestHandlerBean.PROXY_SLOT.set(proxy1);
        dispatcher.dispatch("/svc",
            A2ATestFixtures.jsonRpcBody(1, "tasks/send", Map.of("id", "t-dup")));

        // Attempt to park a second task with the same id.
        JobProxy proxy2 = mock(JobProxy.class);
        A2ATestFixtures.TestHandlerBean.PROXY_SLOT.set(proxy2);
        ResponseEntity<String> resp2 = dispatcher.dispatch("/svc",
            A2ATestFixtures.jsonRpcBody(2, "tasks/send", Map.of("id", "t-dup")));

        JsonNode env = mapper.readTree(resp2.getBody());
        assertEquals(MeshA2ADispatcher.JSONRPC_INVALID_PARAMS,
            env.get("error").get("code").asInt(),
            "Duplicate task_id MUST surface as -32602 per spec §4.3");
        assertTrue(env.get("error").get("message").asText().contains("already in use"),
            "Error message must explicitly call out 'already in use'");
    }

    /** Spec §4.3: history echoes the originating request message. */
    @Test
    @DisplayName("history[] echoes the originating request message (spec §4.3 / Appendix B item 6)")
    void historyEchoesRequestMessage() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.jobId()).thenReturn("job-hist");
        A2ATestFixtures.TestHandlerBean.PROXY_SLOT.set(proxy);

        Map<String, Object> message = Map.of(
            "role", "user",
            "parts", java.util.List.of(Map.of("type", "text", "text", "do the thing")));
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t-hist", "message", message));
        ResponseEntity<String> resp = dispatcher.dispatch("/svc", body);
        JsonNode env = mapper.readTree(resp.getBody());

        JsonNode history = env.get("result").get("history");
        assertTrue(history.isArray());
        assertEquals(1, history.size(),
            "v1 emits at most one entry in history[] (Appendix B item 6)");
        assertEquals("user", history.get(0).get("role").asText());
        assertEquals("do the thing", history.get(0).get("parts").get(0).get("text").asText());
    }
}
