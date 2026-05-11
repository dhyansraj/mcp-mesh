package io.mcpmesh.spring.web;

import io.mcpmesh.JobProxy;
import io.mcpmesh.spring.MeshProperties;
import jakarta.servlet.ServletContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.converter.StringHttpMessageConverter;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockServletContext;
import org.springframework.web.servlet.function.HandlerFunction;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.ServerRequest;
import org.springframework.web.servlet.function.ServerResponse;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * End-to-end producer pipeline test (spec §4 / §5).
 *
 * <p>Wires {@link MeshA2ADispatcherController#buildRouterFunction()}
 * directly and drives it via Spring's {@link ServerRequest#create} factory.
 * This is one level below MockMvc — we skip the DispatcherServlet because
 * its standalone setup has Spring-version-dependent quirks around message
 * converter wiring for functional routers, and the actual servlet
 * round-trip isn't what this test asserts on. We're asserting that the
 * <em>router + controller + dispatcher + state translator</em> pipeline
 * produces wire-shape envelopes per spec §4.
 *
 * <p>End-to-end coverage:
 * <ul>
 *   <li>{@code tasks/send} sync handler → JSON-RPC envelope with
 *       {@code state=completed} + artifact</li>
 *   <li>{@code tasks/send} handler raises → state=failed envelope (NOT a
 *       JSON-RPC error, per spec §4.3)</li>
 *   <li>{@code tasks/cancel} on a parked long-running task → state=canceled</li>
 *   <li>Unknown method → -32601</li>
 *   <li>Malformed body → 400 + -32700</li>
 *   <li>sessionId echoed back, non-string returns JSON-stringified</li>
 * </ul>
 */
@DisplayName("MeshA2A producer — end-to-end router pipeline (spec §4 / §5)")
class MeshA2AControllerSliceTest {

    private static final List<org.springframework.http.converter.HttpMessageConverter<?>> CONVERTERS =
        List.of(new StringHttpMessageConverter(StandardCharsets.UTF_8));

    private MeshA2ARegistry registry;
    private MeshA2ATaskStore taskStore;
    private MeshA2ADispatcher dispatcher;
    private RouterFunction<ServerResponse> routerFunction;
    private ObjectMapper mapper;
    private ServletContext servletContext;

    @BeforeEach
    void setUp() {
        registry = new MeshA2ARegistry();
        registry.register(A2ATestFixtures.surfaceOf("/svc/sync", "sync-skill", "syncHandler"));
        registry.register(A2ATestFixtures.surfaceOf("/svc/long", "long-skill", "longRunningHandler"));
        taskStore = new MeshA2ATaskStore();
        mapper = A2ATestFixtures.objectMapper();
        dispatcher = new MeshA2ADispatcher(
            registry, taskStore, mapper, A2ATestFixtures.emptyInjectorProvider());
        MeshA2ASseDispatcher sseDispatcher = new MeshA2ASseDispatcher(dispatcher);
        MeshA2ACardBuilder cardBuilder = new MeshA2ACardBuilder(null, mapper);

        MeshA2ADispatcherController controller = new MeshA2ADispatcherController(
            registry, dispatcher, sseDispatcher, cardBuilder,
            emptyProvider(MeshProperties.class),
            emptyProvider(MeshA2APublicUrlCache.class));
        routerFunction = controller.buildRouterFunction();
        servletContext = new MockServletContext();
    }

    @AfterEach
    void tearDown() {
        A2ATestFixtures.TestHandlerBean.PROXY_SLOT.remove();
    }

    /** Wire a JSON-RPC request through the full router → dispatcher
     *  pipeline. Returns the parsed JSON-RPC response envelope. */
    private RouteResult dispatch(String path, String body) throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest(servletContext, "POST", path);
        req.setContent(body == null ? new byte[0] : body.getBytes(StandardCharsets.UTF_8));
        req.setContentType(MediaType.APPLICATION_JSON_VALUE);
        req.addHeader(HttpHeaders.ACCEPT, MediaType.APPLICATION_JSON_VALUE);
        MockHttpServletResponse resp = new MockHttpServletResponse();

        ServerRequest serverRequest = ServerRequest.create(req, CONVERTERS);
        HandlerFunction<?> handler = routerFunction.route(serverRequest).orElseThrow(
            () -> new AssertionError("No route matched: POST " + path));
        ServerResponse response = (ServerResponse) handler.handle(serverRequest);
        // Materialise the response onto our MockHttpServletResponse.
        response.writeTo(req, resp, new ServerResponse.Context() {
            @Override
            public java.util.List<org.springframework.http.converter.HttpMessageConverter<?>> messageConverters() {
                return CONVERTERS;
            }
        });
        return new RouteResult(resp.getStatus(), resp.getContentAsString());
    }

    private record RouteResult(int status, String body) {}

    /** Spec §4.3 sync: tasks/send returning a string → state=completed,
     *  artifact carries the return as a text part. */
    @Test
    @DisplayName("tasks/send (sync return) → 200 with state=completed + artifact")
    void tasksSend_syncReturn_completes() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t-sync",
                "message", Map.of("role", "user",
                    "parts", List.of(Map.of("type", "text", "text", "hello")))));

        RouteResult res = dispatch("/svc/sync", body);

        assertEquals(200, res.status, "Body: " + res.body);
        JsonNode env = mapper.readTree(res.body);
        assertEquals("2.0", env.get("jsonrpc").asText());
        assertEquals(1, env.get("id").asInt(), "Body: " + res.body);
        JsonNode result = env.get("result");
        assertNotNull(result, "Expected success envelope, got: " + res.body);
        assertEquals("t-sync", result.get("id").asText());
        assertEquals("completed", result.get("status").get("state").asText());
        assertEquals(1, result.get("artifacts").size());
        // Spec Appendix A: parts[0].type MUST be 'text'.
        assertEquals("text",
            result.get("artifacts").get(0).get("parts").get(0).get("type").asText());
        assertEquals("ok",
            result.get("artifacts").get(0).get("parts").get(0).get("text").asText());
    }

    /** Spec §4.3: handler raises → state=failed envelope, NOT a JSON-RPC error. */
    @Test
    @DisplayName("tasks/send (handler raises) → state=failed envelope (NOT JSON-RPC error)")
    void tasksSend_handlerRaises_returnsFailedTask() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(2, "tasks/send",
            Map.of("id", "t-raise",
                "message", Map.of("op", "raise", "text", "topic required")));

        RouteResult res = dispatch("/svc/sync", body);

        assertEquals(200, res.status,
            "Handler exceptions MUST surface as 200 + state=failed (spec §4.3), NOT HTTP 5xx");
        JsonNode env = mapper.readTree(res.body);
        assertFalse(env.has("error"),
            "Spec §4.3: handler exception is a state=failed Task, not a JSON-RPC error. "
                + "Body: " + res.body);
        JsonNode result = env.get("result");
        assertEquals("failed", result.get("status").get("state").asText());
        assertEquals("topic required",
            result.get("status").get("message").get("parts").get(0).get("text").asText(),
            "Exception message must surface in status.message.parts[0].text");
    }

    /** Spec §4.5: tasks/cancel on a parked task. */
    @Test
    @DisplayName("tasks/cancel on parked long-running task → state=canceled")
    void tasksCancel_parkedTask_returnsCanceled() throws Exception {
        JobProxy proxy = mock(JobProxy.class);
        when(proxy.jobId()).thenReturn("job-cancel");
        when(proxy.status()).thenReturn(Map.of("status", "cancelled"));
        A2ATestFixtures.TestHandlerBean.PROXY_SLOT.set(proxy);

        // Park.
        String sendBody = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t-cancel", "message", Map.of()));
        RouteResult send = dispatch("/svc/long", sendBody);
        JsonNode sendEnv = mapper.readTree(send.body);
        assertEquals("working", sendEnv.get("result").get("status").get("state").asText(),
            "Sanity: long-running send returns state=working");

        // Cancel.
        String cancelBody = A2ATestFixtures.jsonRpcBody(2, "tasks/cancel",
            Map.of("id", "t-cancel", "reason", "user pressed stop"));
        RouteResult cancel = dispatch("/svc/long", cancelBody);
        assertEquals(200, cancel.status);
        JsonNode env = mapper.readTree(cancel.body);
        assertEquals("canceled", env.get("result").get("status").get("state").asText(),
            "Spec §7.2: UK 'cancelled' from mesh substrate MUST surface as US 'canceled'");
    }

    /** Spec §4.1: unknown method → -32601 Method not implemented. */
    @Test
    @DisplayName("Unknown JSON-RPC method → -32601 'Method not implemented'")
    void unknownMethod_returnsMethodNotFound() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(99, "tasks/explode", Map.of());
        RouteResult res = dispatch("/svc/sync", body);
        JsonNode env = mapper.readTree(res.body);
        assertEquals(MeshA2ADispatcher.JSONRPC_METHOD_NOT_FOUND,
            env.get("error").get("code").asInt());
        assertTrue(env.get("error").get("message").asText().contains("Method not implemented"));
    }

    /** Spec §4.1: malformed JSON body → HTTP 400 + -32700 Parse error. */
    @Test
    @DisplayName("Malformed body → 400 + -32700 Parse error")
    void malformedBody_returns400ParseError() throws Exception {
        RouteResult res = dispatch("/svc/sync", "not-json");
        assertEquals(400, res.status,
            "Spec §4.1: malformed body MUST return HTTP 400");
        JsonNode env = mapper.readTree(res.body);
        assertEquals(MeshA2ADispatcher.JSONRPC_PARSE_ERROR,
            env.get("error").get("code").asInt());
    }

    /** Spec §4.3: sessionId echoed back when the client provides one. */
    @Test
    @DisplayName("sessionId echoed back from request to response (spec §4.3 / §4.2)")
    void sessionIdEchoed() throws Exception {
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t-x", "sessionId", "session-xyz",
                "message", Map.of()));
        RouteResult res = dispatch("/svc/sync", body);
        JsonNode env = mapper.readTree(res.body);
        assertEquals("session-xyz", env.get("result").get("sessionId").asText(),
            "sessionId from request MUST be echoed back per spec §4.3");
    }

    /** Spec §4.3: non-string handler return is JSON-stringified into the
     *  artifact text. */
    @Test
    @DisplayName("Non-string handler return is JSON-stringified into artifacts[0].parts[0].text")
    void nonStringReturn_jsonStringifiedIntoArtifact() throws Exception {
        Map<String, Object> message = Map.of("op", "echo", "k", "v");
        String body = A2ATestFixtures.jsonRpcBody(1, "tasks/send",
            Map.of("id", "t-echo", "message", message));
        RouteResult res = dispatch("/svc/sync", body);
        JsonNode env = mapper.readTree(res.body);
        String text = env.get("result").get("artifacts").get(0)
            .get("parts").get(0).get("text").asText();
        JsonNode reparsed = mapper.readTree(text);
        assertEquals("v", reparsed.get("k").asText(),
            "Non-string returns MUST be JSON-stringified into the artifact text "
                + "(spec §4.3 Implementation note)");
    }

    private static <T> ObjectProvider<T> emptyProvider(Class<T> ignored) {
        return new ObjectProvider<>() {
            @Override public T getObject() { return null; }
            @Override public T getObject(Object... args) { return null; }
            @Override public T getIfAvailable() { return null; }
            @Override public T getIfUnique() { return null; }
        };
    }
}
