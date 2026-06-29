package io.mcpmesh.spring;

import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.types.MeshLlmAgent.GenerateBuilder;
import io.mcpmesh.types.MeshLlmAgent.GenerationMeta;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests that a {@code @MeshLlm} agentic loop emits LLM token-usage telemetry into
 * the per-thread sink that {@code ExecutionTracer.endSpan} stamps onto the CONSUMER
 * span (issue #1227 — parity with the Python runtime's {@code set_llm_metadata}).
 *
 * <p>The provider's {@code _mesh_usage} object — {@code {model, prompt_tokens,
 * completion_tokens}} — may arrive at the response top level OR inside the nested
 * {@code content[0].text} JSON envelope. Real mesh-delegated responses use the
 * envelope form, so both are exercised. We assert on
 * {@link TraceContext#getLlmMetadata()} (the contract handoff that the tracer reads,
 * analogous to asserting Python's contextvar) and on the builder's
 * {@link GenerationMeta}.
 *
 * <p>Wiring mirrors {@code MeshLlmAgentProxyModelParamsTest}: a real
 * {@link McpHttpClient} pointed at a {@link MockWebServer} returning the MCP
 * tools/call shape the LLM provider produces.
 */
@DisplayName("MeshLlmAgentProxy — LLM token-usage telemetry on the consumer span (issue #1227)")
class MeshLlmAgentProxyTokenTelemetryTest {

    private MockWebServer server;
    private McpHttpClient client;
    private ObjectMapper mapper;
    private MeshLlmAgentProxy proxy;

    @BeforeAll
    static void initTlsConfig() throws Exception {
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

        proxy = new MeshLlmAgentProxy("test.tokens");
        proxy.configure(client, null, null, null, "", "ctx", 1, false);
        proxy.updateProvider(
            server.url("/").toString().replaceAll("/$", ""),
            "process_chat",
            "anthropic"
        );

        // Clear any stale sink from a previous test on this thread.
        TraceContext.clearLlmMetadata();
    }

    @AfterEach
    void tearDown() throws Exception {
        TraceContext.clearLlmMetadata();
        if (client != null) client.close();
        server.shutdown();
    }

    // -------------------------------------------------------------------------
    // Mock helpers
    // -------------------------------------------------------------------------

    /** Build the MCP envelope wrapping a JSON-encoded inner provider payload. */
    private MockResponse envelope(Map<String, Object> innerPayload) {
        long id = System.currentTimeMillis();
        String innerJson;
        try {
            innerJson = mapper.writeValueAsString(innerPayload);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        Map<String, Object> envelope = Map.of(
            "jsonrpc", "2.0",
            "id", id,
            "result", Map.of(
                "content", List.of(Map.of("type", "text", "text", innerJson))
            )
        );
        String body;
        try {
            body = mapper.writeValueAsString(envelope);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        return new MockResponse()
            .setBody(body)
            .setHeader("Content-Type", "application/json");
    }

    /**
     * Content response carrying {@code _mesh_usage} in the inner provider payload — the
     * real mesh-delegated shape the proxy receives (the MCP client unwraps the JSON-RPC
     * envelope and parses the inner text into the response map).
     */
    private MockResponse stubContentWithUsage(String reply, String model, int prompt, int completion) {
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("role", "assistant");
        inner.put("content", reply);
        inner.put("_mesh_usage", Map.of(
            "model", model,
            "prompt_tokens", prompt,
            "completion_tokens", completion
        ));
        return envelope(inner);
    }

    /**
     * Content response where {@code _mesh_usage} sits at the TOP level of the response
     * map the proxy receives — i.e. a sibling of {@code role}/{@code content} in the
     * inner provider payload. (The MCP client unwraps the JSON-RPC envelope and returns
     * this inner object as the response map, so its top level IS the proxy's top level.)
     */
    private MockResponse stubContentWithTopLevelUsage(String reply, String model, int prompt, int completion) {
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("role", "assistant");
        inner.put("content", reply);
        inner.put("_mesh_usage", Map.of(
            "model", model,
            "prompt_tokens", prompt,
            "completion_tokens", completion
        ));
        return envelope(inner);
    }

    /** Tool-call response (no final content) that also carries usage in the inner payload. */
    private MockResponse stubToolCallWithUsage(String callId, String toolName, Map<String, Object> args,
                                               String model, int prompt, int completion) {
        Map<String, Object> toolCall = Map.of(
            "id", callId,
            "type", "function",
            "function", Map.of("name", toolName, "arguments", args)
        );
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("role", "assistant");
        inner.put("content", "");
        inner.put("tool_calls", List.of(toolCall));
        inner.put("_mesh_usage", Map.of(
            "model", model,
            "prompt_tokens", prompt,
            "completion_tokens", completion
        ));
        return envelope(inner);
    }

    // -------------------------------------------------------------------------
    // Tests
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("_mesh_usage in mesh-delegated response → consumer-span sink carries accumulated tokens + model")
    void meshDelegatedUsageStampsSink() {
        server.enqueue(stubContentWithUsage("done", "claude-sonnet-4-20250514", 120, 45));

        GenerateBuilder builder = proxy.request().user("hi");
        String result = builder.generate();
        assertEquals("done", result);

        TraceContext.LlmMetadata meta = TraceContext.getLlmMetadata();
        assertNotNull(meta, "LLM metadata sink must be populated for the consumer span to stamp");
        assertEquals(120, meta.inputTokens(), "llm_input_tokens");
        assertEquals(45, meta.outputTokens(), "llm_output_tokens");
        assertEquals(165, meta.inputTokens() + meta.outputTokens(), "llm_total_tokens");
        assertEquals("claude-sonnet-4-20250514", meta.model(), "llm_model");
        assertEquals("anthropic", meta.provider(), "llm_provider");

        // GenerationMeta exposes the same totals to API callers.
        GenerationMeta gm = builder.lastMeta();
        assertNotNull(gm);
        assertEquals(120, gm.inputTokens());
        assertEquals(45, gm.outputTokens());
        assertEquals(165, gm.totalTokens());
        assertEquals("claude-sonnet-4-20250514", gm.model());
    }

    @Test
    @DisplayName("top-level result._mesh_usage → also accumulated (both wire shapes supported)")
    void topLevelUsageStampsSink() {
        server.enqueue(stubContentWithTopLevelUsage("done", "gpt-4o", 200, 80));

        String result = proxy.request().user("hi").generate();
        assertEquals("done", result);

        TraceContext.LlmMetadata meta = TraceContext.getLlmMetadata();
        assertNotNull(meta);
        assertEquals(200, meta.inputTokens());
        assertEquals(80, meta.outputTokens());
        assertEquals("gpt-4o", meta.model());
    }

    @Test
    @DisplayName("multi-iteration agentic loop ACCUMULATES tokens across LLM calls (last model wins)")
    void multiIterationAccumulatesTokens() {
        proxy.configure(client, null, null, null, "", "ctx",
            io.mcpmesh.MeshLlmDefaults.MAX_ITERATIONS, false);

        // Iteration 1: tool_calls response with usage (prompt=100, completion=10).
        server.enqueue(stubToolCallWithUsage("call_1", "missing_tool", Map.of("q", "x"),
            "claude-sonnet-4-20250514", 100, 10));
        // Iteration 2: final content with usage (prompt=150, completion=30), newer model.
        server.enqueue(stubContentWithUsage("final", "claude-opus-4-20250514", 150, 30));

        String result = proxy.request().user("do it").generate();
        assertEquals("final", result);

        TraceContext.LlmMetadata meta = TraceContext.getLlmMetadata();
        assertNotNull(meta);
        assertEquals(250, meta.inputTokens(), "input tokens accumulate across iterations (100 + 150)");
        assertEquals(40, meta.outputTokens(), "output tokens accumulate across iterations (10 + 30)");
        assertEquals(290, meta.inputTokens() + meta.outputTokens(), "total accumulates");
        assertEquals("claude-opus-4-20250514", meta.model(),
            "effective model is the last iteration's reported model");
    }

    @Test
    @DisplayName("response with NO _mesh_usage → sink stays null (no zero-spam for non-reporting providers)")
    void noUsageLeavesSinkUntouched() {
        // Inner payload deliberately carries no _mesh_usage.
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("role", "assistant");
        inner.put("content", "ok");
        server.enqueue(envelope(inner));

        String result = proxy.request().user("hi").generate();
        assertEquals("ok", result);

        assertNull(TraceContext.getLlmMetadata(),
            "no _mesh_usage must leave the sink null so the span carries no zero token fields");
    }

    // -------------------------------------------------------------------------
    // extractUsage unwrap-path coverage (mirrors extractToolCalls' dual lookup):
    // top-level key AND nested content[0].text JSON envelope. Invoked reflectively
    // because the live MCP client collapses text responses before the proxy sees
    // them, so the nested-envelope branch is only reachable for raw/mixed shapes.
    // -------------------------------------------------------------------------

    @SuppressWarnings("unchecked")
    private Map<String, Object> invokeExtractUsage(Map<String, Object> response) throws Exception {
        java.lang.reflect.Method m = MeshLlmAgentProxy.class
            .getDeclaredMethod("extractUsage", Map.class);
        m.setAccessible(true);
        return (Map<String, Object>) m.invoke(proxy, response);
    }

    @Test
    @DisplayName("extractUsage reads _mesh_usage from a top-level response key")
    void extractUsageTopLevelKey() throws Exception {
        Map<String, Object> response = Map.of(
            "content", "hi",
            "_mesh_usage", Map.of("model", "gpt-4o", "prompt_tokens", 10, "completion_tokens", 5)
        );
        Map<String, Object> usage = invokeExtractUsage(response);
        assertNotNull(usage);
        assertEquals("gpt-4o", usage.get("model"));
        assertEquals(10, ((Number) usage.get("prompt_tokens")).intValue());
        assertEquals(5, ((Number) usage.get("completion_tokens")).intValue());
    }

    @Test
    @DisplayName("extractUsage reads _mesh_usage from the nested content[0].text JSON envelope")
    void extractUsageNestedEnvelope() throws Exception {
        String innerJson = mapper.writeValueAsString(Map.of(
            "content", "hi",
            "_mesh_usage", Map.of("model", "claude", "prompt_tokens", 7, "completion_tokens", 3)
        ));
        Map<String, Object> response = Map.of(
            "content", List.of(Map.of("type", "text", "text", innerJson))
        );
        Map<String, Object> usage = invokeExtractUsage(response);
        assertNotNull(usage, "nested content[0].text envelope must be unwrapped like extractToolCalls does");
        assertEquals("claude", usage.get("model"));
        assertEquals(7, ((Number) usage.get("prompt_tokens")).intValue());
        assertEquals(3, ((Number) usage.get("completion_tokens")).intValue());
    }

    @Test
    @DisplayName("extractUsage returns null when no _mesh_usage is present")
    void extractUsageMissingReturnsNull() throws Exception {
        assertNull(invokeExtractUsage(Map.of("content", "hi")));
    }
}
