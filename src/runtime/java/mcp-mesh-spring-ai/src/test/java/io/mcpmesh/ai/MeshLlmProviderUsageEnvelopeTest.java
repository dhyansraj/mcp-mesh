package io.mcpmesh.ai;

import io.mcpmesh.MeshLlmProvider;
import io.mcpmesh.ai.handlers.LlmProviderHandler;
import io.mcpmesh.ai.handlers.LlmProviderHandlerRegistry;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.spring.McpHttpClient;
import io.mcpmesh.spring.MeshLlmAgentProxy;
import io.mcpmesh.spring.MeshTlsConfig;
import io.mcpmesh.spring.tracing.ExecutionTracer;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.spring.tracing.TracePublisher;
import io.mcpmesh.types.MeshLlmAgent.GenerateBuilder;
import io.mcpmesh.types.MeshLlmAgent.GenerationMeta;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.context.ApplicationContext;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * Issue #1592: a Java provider reports token usage as {@code _mesh_usage}
 * with {@code prompt_tokens} / {@code completion_tokens} / {@code model} — the
 * key, field names and top-level placement Python's {@code _build_mesh_usage}
 * and TypeScript emit, and the one every consumer reads. It used to emit
 * {@code _usage} with {@code input_tokens} / {@code output_tokens}, so token
 * accounting behind a Java provider was silently zero, and {@code _usage}
 * leaked onto the wire whenever tracing was off.
 */
@DisplayName("MeshLlmProviderProcessor — _mesh_usage envelope (issue #1592)")
class MeshLlmProviderUsageEnvelopeTest {

    private static final String VENDOR = "usagetest";

    @MeshLlmProvider(model = VENDOR + "/model-a")
    static class UsageProvider {
    }

    /** A vendor handler that reports fixed token usage and makes no network call. */
    public static class UsageReportingHandler implements LlmProviderHandler {
        static volatile List<Map<String, Object>> lastMessages;
        /** When set, generateWithTools answers from this script in order. */
        static final java.util.Deque<LlmResponse> script = new java.util.concurrent.ConcurrentLinkedDeque<>();

        @Override
        public String getVendor() {
            return VENDOR;
        }

        @Override
        public String generateWithMessages(
                ChatModel model, List<Map<String, Object>> messages, Map<String, Object> options) {
            return generateWithMessagesFull(model, messages, options).content();
        }

        @Override
        public LlmResponse generateWithMessagesFull(
                ChatModel model, List<Map<String, Object>> messages, Map<String, Object> options) {
            lastMessages = messages;
            return new LlmResponse("plain answer", List.of(), new UsageMeta(4, 2, "plain-vendor-id"));
        }

        @Override
        public LlmResponse generateWithTools(
                ChatModel model, List<Map<String, Object>> messages, List<ToolDefinition> tools,
                ToolExecutorCallback toolExecutor, OutputSchema outputSchema,
                Map<String, Object> options) {
            lastMessages = messages;
            LlmResponse scripted = script.poll();
            if (scripted != null) {
                return scripted;
            }
            return new LlmResponse("the answer", List.of(),
                new UsageMeta(12, 7, "vendor-reported-model-id"));
        }
    }

    private MeshLlmProviderProcessor processor;
    private static Object savedTlsConfig;

    private static Field tlsCacheField() throws Exception {
        Field cachedField = MeshTlsConfig.class.getDeclaredField("cached");
        cachedField.setAccessible(true);
        return cachedField;
    }

    @BeforeAll
    static void registerHandler() throws Exception {
        LlmProviderHandlerRegistry.register(VENDOR, UsageReportingHandler.class);

        // McpHttpClient reads the TLS posture at construction; pin it off for
        // this class and restore whatever was there afterwards.
        Constructor<MeshTlsConfig> ctor = MeshTlsConfig.class.getDeclaredConstructor(
            boolean.class, String.class, String.class, String.class, String.class);
        ctor.setAccessible(true);
        savedTlsConfig = tlsCacheField().get(null);
        tlsCacheField().set(null, ctor.newInstance(false, "off", null, null, null));
    }

    @org.junit.jupiter.api.AfterAll
    @SuppressWarnings("unchecked")
    static void restoreGlobals() throws Exception {
        tlsCacheField().set(null, savedTlsConfig);
        Field handlers = LlmProviderHandlerRegistry.class.getDeclaredField("handlers");
        handlers.setAccessible(true);
        ((Map<String, ?>) handlers.get(null)).remove(VENDOR);
        LlmProviderHandlerRegistry.clearCache();
    }

    @BeforeEach
    void setUp() {
        ApplicationContext ctx = mock(ApplicationContext.class);
        SpringAiLlmProvider llmProvider = mock(SpringAiLlmProvider.class);
        when(llmProvider.getModelForProvider(VENDOR)).thenReturn(mock(ChatModel.class));
        when(ctx.getBean(SpringAiLlmProvider.class)).thenReturn(llmProvider);

        processor = new MeshLlmProviderProcessor();
        processor.setApplicationContext(ctx);
        processor.postProcessAfterInitialization(new UsageProvider(), "usageProvider");
    }

    @AfterEach
    void tearDown() {
        UsageReportingHandler.script.clear();
        System.clearProperty("mcp.mesh.distributed-tracing-enabled");
        TraceContext.clear();
        TraceContext.clearLlmMetadata();
    }

    /** A delegated request with one tool and no endpoint (the tool_calls-returning path). */
    private static Map<String, Object> request(Map<String, Object> modelParams) {
        Map<String, Object> message = new LinkedHashMap<>();
        message.put("role", "user");
        message.put("content", "hi");
        // Mutable: the processor strips per-tool routing keys in place.
        Map<String, Object> function = new LinkedHashMap<>();
        function.put("name", "lookup");
        function.put("description", "look something up");
        function.put("parameters", new LinkedHashMap<>(Map.of("type", "object")));
        Map<String, Object> tool = new LinkedHashMap<>();
        tool.put("type", "function");
        tool.put("function", function);
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("messages", new java.util.ArrayList<>(List.of(message)));
        request.put("tools", new java.util.ArrayList<>(List.of(tool)));
        request.put("model_params", modelParams);
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("request", request);
        return args;
    }

    private LlmProviderToolWrapper wrapper() {
        return new LlmProviderToolWrapper("llm", "test", "1.0.0", List.of(), processor);
    }

    @Test
    @DisplayName("emits _mesh_usage {prompt_tokens, completion_tokens, model} at the top level")
    void emitsPythonShapedUsage() {
        Map<String, Object> response = processor.handleGenerateRequest("llm", request(new LinkedHashMap<>()));

        assertEquals(
            Map.of("prompt_tokens", 12L, "completion_tokens", 7L, "model", VENDOR + "/model-a"),
            response.get("_mesh_usage"));
        assertFalse(response.containsKey("_usage"), "the old key must be gone");
        assertEquals(VENDOR + "/model-a", response.get("model"),
            "the top-level model agrees with _mesh_usage.model");
    }

    @Test
    @DisplayName("plain-text path (no tools, no schema) reports _mesh_usage too")
    void plainTextPathReportsUsage() {
        Map<String, Object> args = request(new LinkedHashMap<>());
        @SuppressWarnings("unchecked")
        Map<String, Object> req = (Map<String, Object>) args.get("request");
        req.remove("tools");

        Map<String, Object> response = processor.handleGenerateRequest("llm", args);

        assertEquals("plain answer", response.get("content"));
        assertEquals(
            Map.of("prompt_tokens", 4L, "completion_tokens", 2L, "model", VENDOR + "/model-a"),
            response.get("_mesh_usage"));
    }

    @Test
    @DisplayName("parallel tool loop sums usage across every LLM call, not just the last")
    void parallelLoopAccumulatesUsage() {
        UsageReportingHandler.script.add(new LlmProviderHandler.LlmResponse("", List.of(
            new LlmProviderHandler.ToolCall("c1", "lookup", "{}")),
            new LlmProviderHandler.UsageMeta(12, 7, "vendor-id")));
        UsageReportingHandler.script.add(new LlmProviderHandler.LlmResponse("final", List.of(),
            new LlmProviderHandler.UsageMeta(5, 3, "vendor-id")));
        Map<String, Object> modelParams = new LinkedHashMap<>();
        modelParams.put("parallel_tool_calls", true);
        Map<String, Object> args = request(modelParams);
        @SuppressWarnings("unchecked")
        Map<String, Object> req = (Map<String, Object>) args.get("request");
        @SuppressWarnings("unchecked")
        Map<String, Object> fn = (Map<String, Object>) ((Map<String, Object>)
            ((List<?>) req.get("tools")).get(0)).get("function");
        // An unreachable endpoint: the tool call fails into an error string,
        // which is all the loop needs to take a second turn.
        fn.put("_mesh_endpoint", "http://127.0.0.1:1");

        Map<String, Object> response = processor.handleGenerateRequest("llm", args);

        assertEquals("final", response.get("content"));
        assertEquals(
            Map.of("prompt_tokens", 17L, "completion_tokens", 10L, "model", VENDOR + "/model-a"),
            response.get("_mesh_usage"));
    }

    @Test
    @DisplayName("a vendor-qualified override is reported as given (vertex_ai/ on a Gemini provider)")
    void vertexOverrideReportedAsGiven() {
        MeshLlmProviderProcessor.LlmProviderConfig config = new MeshLlmProviderProcessor.LlmProviderConfig(
            "llm", "gemini", "gemini-2.0-flash", List.of(), "1.0.0");
        Map<String, Object> options = new LinkedHashMap<>();
        options.put(LlmProviderHandler.OPTION_DECLARED_MODEL, "gemini-2.0-flash");
        options.put(LlmProviderHandler.OPTION_MODEL, "vertex_ai/gemini-2.5-pro");

        assertEquals("vertex_ai/gemini-2.5-pro", MeshLlmProviderProcessor.effectiveModel(
            config, new io.mcpmesh.ai.handlers.GeminiHandler(), options));

        options.remove(LlmProviderHandler.OPTION_MODEL);
        assertEquals("gemini/gemini-2.0-flash", MeshLlmProviderProcessor.effectiveModel(
            config, new io.mcpmesh.ai.handlers.GeminiHandler(), options));
    }

    @Test
    @DisplayName("_mesh_usage.model is the vendor-matched per-call override, like Python's effective_model")
    void modelReflectsPerCallOverride() {
        Map<String, Object> modelParams = new LinkedHashMap<>();
        modelParams.put("model", VENDOR + "/model-b");

        Map<String, Object> response = processor.handleGenerateRequest("llm", request(modelParams));

        @SuppressWarnings("unchecked")
        Map<String, Object> usage = (Map<String, Object>) response.get("_mesh_usage");
        assertEquals(VENDOR + "/model-b", usage.get("model"));
        assertEquals(VENDOR + "/model-b", response.get("model"));
    }

    @Test
    @DisplayName("tracing off: _mesh_usage stays on the response and _usage never appears")
    void tracingOffKeepsMeshUsage() throws Exception {
        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) wrapper().invoke(request(new LinkedHashMap<>()));

        assertTrue(result.containsKey("_mesh_usage"));
        assertFalse(result.containsKey("_usage"));
    }

    @Test
    @DisplayName("tracing on: the provider span is enriched AND _mesh_usage still reaches the wire")
    void tracingOnEnrichesSpanAndKeepsMeshUsage() throws Exception {
        System.setProperty("mcp.mesh.distributed-tracing-enabled", "true");
        TracePublisher publisher = mock(TracePublisher.class);
        ExecutionTracer tracer = new ExecutionTracer(publisher, null);
        assumeTracingEnabled(tracer);
        LlmProviderToolWrapper wrapper = wrapper();
        wrapper.setTracer(tracer);

        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) wrapper.invoke(request(new LinkedHashMap<>()));

        assertTrue(result.containsKey("_mesh_usage"),
            "_mesh_usage is the wire contract — the consumer reads it; tracing must not strip it");
        assertFalse(result.containsKey("_usage"));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> span = ArgumentCaptor.forClass(Map.class);
        verify(publisher).publish(span.capture());
        assertEquals(12L, ((Number) span.getValue().get("llm_input_tokens")).longValue());
        assertEquals(7L, ((Number) span.getValue().get("llm_output_tokens")).longValue());
        // The span records the model the vendor reported running, falling back
        // to the requested one — what Python's provider span records.
        assertEquals("vendor-reported-model-id", span.getValue().get("llm_model"));
    }

    private static void assumeTracingEnabled(ExecutionTracer tracer) {
        org.junit.jupiter.api.Assumptions.assumeTrue(tracer.isEnabled(),
            "tracing could not be enabled in this environment");
    }

    @Test
    @DisplayName("round trip: a Java provider's usage reaches a Java consumer's GenerationMeta")
    void roundTripToConsumer() throws Exception {
        @SuppressWarnings("unchecked")
        Map<String, Object> providerResult =
            (Map<String, Object>) wrapper().invoke(request(new LinkedHashMap<>()));

        ObjectMapper mapper = MeshObjectMappers.create();
        // The provider's return value travels as the JSON text of one MCP
        // content block — exactly what the MCP server layer serializes.
        String innerJson = mapper.writeValueAsString(providerResult);
        String body = mapper.writeValueAsString(Map.of(
            "jsonrpc", "2.0",
            "id", 1,
            "result", Map.of("content", List.of(Map.of("type", "text", "text", innerJson)))));

        MockWebServer server = new MockWebServer();
        server.start();
        McpHttpClient client = new McpHttpClient(mapper);
        try {
            server.enqueue(new MockResponse().setBody(body).setHeader("Content-Type", "application/json"));
            MeshLlmAgentProxy consumer = new MeshLlmAgentProxy("test.roundtrip");
            consumer.configure(client, null, null, null, "", "ctx", 1, false);
            consumer.updateProvider(server.url("/").toString().replaceAll("/$", ""),
                "llm_generate", VENDOR);

            GenerateBuilder builder = consumer.request().user("hi");
            assertEquals("the answer", builder.generate());

            GenerationMeta meta = builder.lastMeta();
            assertEquals(12, meta.inputTokens());
            assertEquals(7, meta.outputTokens());
            assertEquals(VENDOR + "/model-a", meta.model());
        } finally {
            client.close();
            server.shutdown();
        }
    }

    @Test
    @DisplayName("provider-side tool calls reuse the runtime's shared McpHttpClient bean")
    @SuppressWarnings("unchecked")
    void reusesTheSharedMcpHttpClient() {
        McpHttpClient shared = new McpHttpClient(MeshObjectMappers.create());
        ApplicationContext ctx = mock(ApplicationContext.class);
        org.springframework.beans.factory.ObjectProvider<McpHttpClient> provider =
            mock(org.springframework.beans.factory.ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(shared);
        when(ctx.getBeanProvider(McpHttpClient.class)).thenReturn(provider);
        MeshLlmProviderProcessor p = new MeshLlmProviderProcessor();
        p.setApplicationContext(ctx);

        assertSame(shared, p.getMcpHttpClient());
        assertSame(shared, p.getMcpHttpClient(), "one client per process, not per request");
    }

    @Test
    @DisplayName("without a bean, one provider-local client is built once and reused")
    void buildsOneClientWhenNoBean() {
        MeshLlmProviderProcessor p = new MeshLlmProviderProcessor();
        McpHttpClient first = p.getMcpHttpClient();
        assertNotNull(first);
        assertSame(first, p.getMcpHttpClient());
    }

    @Test
    @DisplayName("missing messages is rejected; an empty list is sent as-is (no invented prompt)")
    void emptyMessagesAreNotReplacedWithAPrompt() {
        Map<String, Object> args = request(new LinkedHashMap<>());
        @SuppressWarnings("unchecked")
        Map<String, Object> req = (Map<String, Object>) args.get("request");
        req.put("messages", new java.util.ArrayList<>());

        // The fake vendor answers whatever it is sent; the point is that the
        // request reached it with no fabricated "Hello" user turn.
        Map<String, Object> response = processor.handleGenerateRequest("llm", args);
        assertEquals("the answer", response.get("content"));
        assertEquals(List.of(), UsageReportingHandler.lastMessages,
            "the vendor must see the empty conversation, not a synthesized prompt");

        req.remove("messages");
        assertThrows(IllegalArgumentException.class,
            () -> processor.handleGenerateRequest("llm", args));
    }
}
