package io.mcpmesh.spring;

import io.mcpmesh.core.MeshEvent;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.spring.tracing.TraceInfo;
import io.mcpmesh.types.MeshLlmAgent;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1164 MED-3 + MED-4 coverage for {@link MeshLlmAgentProxy}.
 *
 * <ul>
 *   <li>MED-3: buffered {@code generate()} must not NPE on a null-content
 *       message (tool-call-only assistant turns from persisted history).</li>
 *   <li>MED-4: {@code generateAsync()} and the parallel tool-call branch run
 *       on pool threads — caller-thread ThreadLocals (trace context,
 *       propagated headers, invocation context for {@code ${ctx.*}} template
 *       vars) must be captured and restored, otherwise outbound calls lose
 *       trace + propagated headers and template vars vanish.</li>
 * </ul>
 *
 * <p>Wiring mirrors {@link MeshLlmAgentProxyModelParamsTest}: a real
 * {@link McpHttpClient} pointed at a {@link MockWebServer}.
 */
@DisplayName("MeshLlmAgentProxy — async context propagation + null-content history (issue #1164)")
class MeshLlmAgentProxyAsyncContextTest {

    private MockWebServer server;
    private McpHttpClient client;
    private ObjectMapper mapper;
    private MeshLlmAgentProxy proxy;

    @BeforeAll
    static void initTlsConfig() throws Exception {
        // Pre-seed MeshTlsConfig.cached so tests don't hit native FFI
        Constructor<MeshTlsConfig> ctor = MeshTlsConfig.class.getDeclaredConstructor(
            boolean.class, String.class, String.class, String.class, String.class);
        ctor.setAccessible(true);
        MeshTlsConfig disabled = ctor.newInstance(false, "off", null, null, null);

        Field cachedField = MeshTlsConfig.class.getDeclaredField("cached");
        cachedField.setAccessible(true);
        cachedField.set(null, disabled);
    }

    @BeforeEach
    void setUp() throws Exception {
        server = new MockWebServer();
        server.start();
        mapper = MeshObjectMappers.create();
        client = new McpHttpClient(mapper);

        proxy = new MeshLlmAgentProxy("test.asynccontext");
        proxy.configure(client, null, null, null, "", "ctx", 1, false);
        proxy.updateProvider(
            server.url("/").toString().replaceAll("/$", ""),
            "process_chat",
            "mesh-delegated"
        );
    }

    @AfterEach
    void tearDown() throws Exception {
        TraceContext.clear();
        TraceContext.clearPropagatedHeaders();
        if (client != null) client.close();
        server.shutdown();
    }

    // ── Mock helpers (same MCP tools/call shape as ModelParamsTest) ────────

    private MockResponse stubLlmResponse(String reply) {
        Map<String, Object> innerPayload = Map.of("role", "assistant", "content", reply);
        return envelope(innerPayload);
    }

    private MockResponse stubToolCallsResponse(List<Map<String, Object>> toolCalls) {
        Map<String, Object> innerPayload = Map.of(
            "role", "assistant",
            "content", "",
            "tool_calls", toolCalls
        );
        return envelope(innerPayload);
    }

    private MockResponse envelope(Map<String, Object> innerPayload) {
        try {
            String innerJson = mapper.writeValueAsString(innerPayload);
            Map<String, Object> env = Map.of(
                "jsonrpc", "2.0",
                "id", System.currentTimeMillis(),
                "result", Map.of(
                    "content", List.of(Map.of("type", "text", "text", innerJson))
                )
            );
            return new MockResponse()
                .setBody(mapper.writeValueAsString(env))
                .setHeader("Content-Type", "application/json");
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private Map<String, Object> toolCall(String id, String name) {
        return Map.of(
            "id", id,
            "type", "function",
            "function", Map.of("name", name, "arguments", Map.of())
        );
    }

    private MeshEvent.LlmToolInfo llmToolInfo(String name, String endpoint) throws Exception {
        Map<String, Object> json = new LinkedHashMap<>();
        json.put("function_name", name);
        json.put("capability", name);
        json.put("description", "test tool " + name);
        json.put("endpoint", endpoint);
        json.put("agent_id", "agent-1");
        json.put("input_schema", "{\"type\":\"object\",\"properties\":{}}");
        return mapper.readValue(mapper.writeValueAsString(json), MeshEvent.LlmToolInfo.class);
    }

    private JsonNode requestMessages(RecordedRequest req) throws Exception {
        JsonNode root = mapper.readTree(req.getBody().readUtf8());
        return root.get("params").get("arguments").get("request").get("messages");
    }

    // ── MED-3: null-content history ────────────────────────────────────────

    @Test
    @DisplayName("MED-3: history with a null-content assistant turn does not NPE")
    void nullContentAssistantTurnDoesNotNpe() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        // Tool-call-only assistant turns persisted from history carry content=null.
        String result = proxy.request()
            .user("question")
            .message(new MeshLlmAgent.Message("assistant", null))
            .generate();

        assertEquals("ok", result);

        RecordedRequest req = server.takeRequest(2, TimeUnit.SECONDS);
        assertNotNull(req);
        JsonNode messages = requestMessages(req);
        boolean sawNullContentAssistant = false;
        for (JsonNode m : messages) {
            if ("assistant".equals(m.path("role").asText()) && m.get("content").isNull()) {
                sawNullContentAssistant = true;
            }
        }
        assertTrue(sawNullContentAssistant,
            "null-content assistant turn must reach the wire as content:null. Got: " + messages);
    }

    // ── MED-4: generateAsync context propagation ───────────────────────────

    @Test
    @DisplayName("MED-4: generateAsync propagates trace, propagated headers, and ${ctx} template vars")
    void generateAsyncPropagatesCallerContext() throws Exception {
        // System prompt template reads an invocation-context variable.
        proxy.configure(client, null, null, null, "Hello ${name}!", "ctx", 1, false);

        TraceContext.set(TraceInfo.forPropagation("aaaabbbbccccdddd", "span00001111"));
        TraceContext.setPropagatedHeaders(Map.of("x-mesh-timeout", "42"));
        proxy.setInvocationContext(Map.of("name", "Bob"));

        server.enqueue(stubLlmResponse("ok"));

        String result = proxy.request().user("hi").generateAsync().get(10, TimeUnit.SECONDS);
        assertEquals("ok", result);

        RecordedRequest req = server.takeRequest(2, TimeUnit.SECONDS);
        assertNotNull(req);

        // Trace headers must survive the pool-thread hop.
        assertEquals("aaaabbbbccccdddd", req.getHeader("X-Trace-ID"),
            "trace header must be present on the outbound LLM call made from the async pool thread");
        // Propagated header (x-mesh-timeout is always allowlisted).
        assertEquals("42", req.getHeader("x-mesh-timeout"),
            "propagated headers must be forwarded from the async pool thread");

        // ${ctx} template var must render (invocation context restored on pool thread).
        JsonNode messages = requestMessages(req);
        assertEquals("system", messages.get(0).path("role").asText());
        assertTrue(messages.get(0).path("content").asText().contains("Hello Bob!"),
            "invocation-context template var must render in the async path. Got: " + messages);
    }

    @Test
    @DisplayName("MED-4: pool thread is not polluted — invocation context cleared after async task")
    void asyncTaskClearsPoolThreadContext() throws Exception {
        proxy.configure(client, null, null, null, "Hi ${name}!", "ctx", 1, false);
        proxy.setInvocationContext(Map.of("name", "Eve"));

        server.enqueue(stubLlmResponse("first"));
        assertEquals("first", proxy.request().user("a").generateAsync().get(10, TimeUnit.SECONDS));
        server.takeRequest(2, TimeUnit.SECONDS);

        // Clear the CALLER thread's context, then issue a second async call:
        // the template must fail to resolve ${name} (renderer falls back to
        // the raw template) rather than reusing 'Eve' leaked into a pool
        // thread by the first call.
        proxy.setInvocationContext(null);
        server.enqueue(stubLlmResponse("second"));
        assertEquals("second", proxy.request().user("b").generateAsync().get(10, TimeUnit.SECONDS));
        RecordedRequest req2 = server.takeRequest(2, TimeUnit.SECONDS);
        assertNotNull(req2);
        JsonNode messages = requestMessages(req2);
        String systemContent = messages.get(0).path("content").asText();
        assertFalse(systemContent.contains("Eve"),
            "pool thread must not leak a previous call's invocation context. Got: " + systemContent);
    }

    // ── MED-4: parallel tool-call branch ───────────────────────────────────

    @Test
    @DisplayName("MED-4: parallel tool calls carry trace + propagated headers on outbound requests")
    void parallelToolCallsPropagateContext() throws Exception {
        String endpoint = server.url("/").toString().replaceAll("/$", "");
        // parallelToolCalls=true, two iterations, real proxy factory so tool
        // calls go over HTTP to the mock server.
        proxy.configure(client, new McpMeshToolProxyFactory(client), null, null, "", "ctx", 2, true);
        proxy.updateTools(List.of(
            llmToolInfo("tool_a", endpoint),
            llmToolInfo("tool_b", endpoint)
        ));

        TraceContext.set(TraceInfo.forPropagation("ffff0000ffff0000", null));
        TraceContext.setPropagatedHeaders(Map.of("x-mesh-timeout", "55"));

        // Iteration 1: LLM requests two tool calls → executed in parallel.
        server.enqueue(stubToolCallsResponse(List.of(
            toolCall("c1", "tool_a"),
            toolCall("c2", "tool_b")
        )));
        // The two parallel tool invocations (order nondeterministic).
        server.enqueue(stubLlmResponse("a-result"));
        server.enqueue(stubLlmResponse("b-result"));
        // Iteration 2: final content.
        server.enqueue(stubLlmResponse("done"));

        String result = proxy.request().user("go").generate();
        assertEquals("done", result);

        List<RecordedRequest> toolRequests = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            RecordedRequest req = server.takeRequest(5, TimeUnit.SECONDS);
            assertNotNull(req, "expected 4 outbound requests, missing #" + (i + 1));
            JsonNode body = mapper.readTree(req.getBody().readUtf8());
            String name = body.get("params").get("name").asText();
            if ("tool_a".equals(name) || "tool_b".equals(name)) {
                toolRequests.add(req);
            }
        }
        assertEquals(2, toolRequests.size(), "both parallel tool calls must reach the wire");

        for (RecordedRequest toolReq : toolRequests) {
            assertEquals("ffff0000ffff0000", toolReq.getHeader("X-Trace-ID"),
                "parallel tool execution must carry trace headers (pool thread context)");
            assertEquals("55", toolReq.getHeader("x-mesh-timeout"),
                "parallel tool execution must forward propagated headers");
        }
    }

    // ── LOW: buildErrorResponse must emit valid JSON for control chars ─────

    @Test
    @DisplayName("LOW: error response with newlines/control chars is valid JSON")
    void buildErrorResponseControlCharsValidJson() throws Exception {
        String message = "line1\nline2\ttabbed \"quoted\" back\\slash bell\u0001 end";
        String json = MeshLlmAgentProxy.buildErrorResponse("tool_call_failed", "my_tool", message);

        JsonNode node = mapper.readTree(json); // must parse — previously invalid
        assertEquals("tool_call_failed", node.get("error").get("type").asText());
        assertEquals("my_tool", node.get("error").get("tool").asText());
        assertEquals(message, node.get("error").get("message").asText(),
            "message must round-trip exactly through serialization");
    }

    @Test
    @DisplayName("LOW: null message falls back to 'Unknown error'")
    void buildErrorResponseNullMessage() throws Exception {
        String json = MeshLlmAgentProxy.buildErrorResponse("unexpected_error", "t", null);
        JsonNode node = mapper.readTree(json);
        assertEquals("Unknown error", node.get("error").get("message").asText());
    }
}
