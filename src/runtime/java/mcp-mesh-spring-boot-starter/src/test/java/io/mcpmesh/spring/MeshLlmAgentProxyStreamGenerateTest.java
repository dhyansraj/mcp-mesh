package io.mcpmesh.spring;

import io.mcpmesh.core.MeshObjectMappers;
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
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.Flow;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for {@link MeshLlmAgent.GenerateBuilder#streamGenerate()} — issue #1023.
 *
 * <p>The builder's {@code streamGenerate()} is a terminal method that mirrors
 * the buffered {@code generate()} path's model_params merge semantics
 * (issue #1019 / PR #1024) while routing the call through the streaming
 * {@code process_chat_stream} MCP transport. This file asserts:
 * <ul>
 *   <li>{@code modelParams} keys (e.g., {@code thinking_config}) flow into the
 *       wire request's {@code model_params}</li>
 *   <li>Typed setters ({@code .temperature}) win over {@code modelParams}
 *       on collision</li>
 *   <li>Annotation defaults DON'T clobber values supplied solely via
 *       {@code .modelParams(Map.of("max_tokens", ...))}</li>
 *   <li>The legacy {@code stream(List)} shortcut delegates to the builder so
 *       its wire shape matches {@code request().messages(...).streamGenerate()}</li>
 * </ul>
 *
 * <p>Mirrors {@link MeshLlmAgentProxyStreamTest}'s {@link MockWebServer} wiring.
 */
@DisplayName("GenerateBuilder.streamGenerate() — issue #1023")
class MeshLlmAgentProxyStreamGenerateTest {

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

        proxy = new MeshLlmAgentProxy("test.streamGenerate");
        // Defaults: maxTokens=4096, temperature=0.7, parallelToolCalls=false.
        proxy.configure(client, null, null, null, "", "ctx", 1, false);
        proxy.updateProvider(
            server.url("/").toString().replaceAll("/$", ""),
            "process_chat_stream",
            "mesh-delegated"
        );
    }

    @AfterEach
    void tearDown() throws Exception {
        if (client != null) client.close();
        server.shutdown();
    }

    // -------------------------------------------------------------------------
    // SSE helpers — same shape as MeshLlmAgentProxyStreamTest.
    // -------------------------------------------------------------------------

    private String sseEvent(String json) {
        return "event: message\ndata: " + json + "\n\n";
    }

    private String finalEmptyResultEvent(long requestId) {
        return sseEvent("{\"jsonrpc\":\"2.0\",\"id\":" + requestId + ",\"result\":{}}");
    }

    /**
     * Dispatcher that captures the outbound request body and returns an SSE
     * stream with only a final-result event (no progress chunks needed —
     * we're only inspecting the request, not the response chunks).
     */
    private String[] enqueueCapturingDispatcher() {
        final String[] bodyHolder = new String[1];
        server.setDispatcher(new okhttp3.mockwebserver.Dispatcher() {
            @Override
            public MockResponse dispatch(RecordedRequest request) {
                bodyHolder[0] = request.getBody().readUtf8();
                try {
                    long id = mapper.readTree(bodyHolder[0]).get("id").asLong();
                    return new MockResponse()
                        .setBody(finalEmptyResultEvent(id))
                        .setHeader("Content-Type", "text/event-stream");
                } catch (Exception e) {
                    return new MockResponse().setResponseCode(500);
                }
            }
        });
        return bodyHolder;
    }

    /** Collect Flow.Publisher chunks blocking, throwing on onError. */
    private static List<String> collect(Flow.Publisher<String> publisher) throws Exception {
        ConcurrentLinkedQueue<String> chunks = new ConcurrentLinkedQueue<>();
        CompletableFuture<Throwable> done = new CompletableFuture<>();
        publisher.subscribe(new Flow.Subscriber<>() {
            @Override public void onSubscribe(Flow.Subscription s) { s.request(Long.MAX_VALUE); }
            @Override public void onNext(String item) { chunks.add(item); }
            @Override public void onError(Throwable t) { done.complete(t); }
            @Override public void onComplete() { done.complete(null); }
        });
        Throwable err = done.get(10, TimeUnit.SECONDS);
        if (err != null) {
            if (err instanceof RuntimeException re) throw re;
            throw new RuntimeException(err);
        }
        return new ArrayList<>(chunks);
    }

    /** Read the captured outbound body and pull out the model_params node. */
    private JsonNode readModelParams(String body) throws Exception {
        JsonNode root = mapper.readTree(body);
        JsonNode args = root.get("params").get("arguments");
        JsonNode req = args.get("request");
        JsonNode modelParams = req.get("model_params");
        assertNotNull(modelParams, "request.model_params must be present");
        return modelParams;
    }

    // -------------------------------------------------------------------------
    // Tests
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("streamGenerate merges modelParams into wire request")
    void streamGenerateMergesModelParamsIntoWire() throws Exception {
        String[] bodyHolder = enqueueCapturingDispatcher();

        Flow.Publisher<String> pub = proxy.request()
            .user("hi")
            .modelParams(Map.of(
                "thinking_config", Map.of("thinking_budget", 0)
            ))
            .streamGenerate();
        collect(pub);

        JsonNode modelParams = readModelParams(bodyHolder[0]);
        JsonNode thinking = modelParams.get("thinking_config");
        assertNotNull(thinking, "thinking_config must be present in wire model_params");
        assertEquals(0, thinking.get("thinking_budget").asInt());

        // Annotation defaults still present
        assertTrue(modelParams.has("max_tokens"));
        assertTrue(modelParams.has("temperature"));
    }

    @Test
    @DisplayName("streamGenerate: typed setter (.temperature) wins on collision with modelParams")
    void streamGenerateTypedSetterWinsOnCollision() throws Exception {
        String[] bodyHolder = enqueueCapturingDispatcher();

        Flow.Publisher<String> pub = proxy.request()
            .user("hi")
            .temperature(0.5)
            .modelParams(Map.of("temperature", 0.9))
            .streamGenerate();
        collect(pub);

        JsonNode modelParams = readModelParams(bodyHolder[0]);
        assertEquals(0.5, modelParams.get("temperature").asDouble(), 1e-9,
            "typed .temperature(0.5) must win over modelParams temperature=0.9");
    }

    @Test
    @DisplayName("streamGenerate: annotation default does NOT clobber modelParams when no typed setter is used")
    void streamGenerateAnnotationDefaultOnlyAppliesWhenUnset() throws Exception {
        String[] bodyHolder = enqueueCapturingDispatcher();

        Flow.Publisher<String> pub = proxy.request()
            .user("hi")
            // NO .maxTokens() typed setter — escape-hatch only.
            .modelParams(Map.of("max_tokens", 999))
            .streamGenerate();
        collect(pub);

        JsonNode modelParams = readModelParams(bodyHolder[0]);
        assertEquals(999, modelParams.get("max_tokens").asInt(),
            "modelParams.max_tokens=999 must reach the wire when no typed .maxTokens() is set;"
            + " annotation default (4096) must NOT clobber it");
    }

    @Test
    @DisplayName("streamGenerate clears ThreadLocal invocationContext on return (issue #1026)")
    @SuppressWarnings("unchecked")
    void streamGenerateClearsInvocationContextOnReturn() throws Exception {
        // Issue #1026: buffered generate() wraps in try/finally{clearInvocationContext()},
        // but streamGenerate() did not — leaking the per-invocation ThreadLocal
        // context onto the originating thread. In Spring/Tomcat pooled-thread
        // environments the next request reusing the thread can observe the
        // stale context until MeshToolWrapper re-populates it. Fix wraps the
        // streamGenerate body in try/finally so the ThreadLocal is cleared
        // synchronously after Publisher construction.
        enqueueCapturingDispatcher();

        // Seed the ThreadLocal as MeshToolWrapper.setInvocationContext() would.
        proxy.setInvocationContext(Map.of("user_name", "alice"));

        // Sanity: the ThreadLocal is populated BEFORE the call.
        Field ctxField = MeshLlmAgentProxy.class.getDeclaredField("invocationContext");
        ctxField.setAccessible(true);
        ThreadLocal<Map<String, Object>> tl = (ThreadLocal<Map<String, Object>>) ctxField.get(proxy);
        assertNotNull(tl.get(), "ThreadLocal must be seeded before streamGenerate()");
        assertEquals("alice", tl.get().get("user_name"));

        Flow.Publisher<String> pub = proxy.request().user("hi").streamGenerate();
        assertNotNull(pub, "streamGenerate() must return a non-null Publisher");

        // IMMEDIATELY after return (no subscriber yet) the ThreadLocal must be cleared.
        assertNull(tl.get(),
            "streamGenerate() must clear the ThreadLocal invocationContext on return "
            + "to prevent leak across pooled-thread reuse (issue #1026)");

        // Drain the publisher so the mock server doesn't hang.
        collect(pub);
    }

    @Test
    @DisplayName("legacy stream(messages) shortcut delegates to builder — same wire shape as streamGenerate")
    void streamLegacyShortFormDelegatesToBuilder() throws Exception {
        // Path A: legacy stream(messages)
        String[] legacyBody = enqueueCapturingDispatcher();
        collect(proxy.stream(List.of(MeshLlmAgent.Message.user("hello"))));
        String legacyWire = legacyBody[0];
        assertNotNull(legacyWire, "legacy stream() must have hit the mock server");

        // Path B: builder request().messages(...).streamGenerate()
        String[] builderBody = enqueueCapturingDispatcher();
        collect(proxy.request()
            .messages(List.of(MeshLlmAgent.Message.user("hello")))
            .streamGenerate());
        String builderWire = builderBody[0];
        assertNotNull(builderWire, "builder streamGenerate() must have hit the mock server");

        // Compare the inner `request` payloads — they should be identical
        // structurally (the only thing that differs between calls is the
        // JSON-RPC id and progressToken, both of which are outside `arguments.request`).
        JsonNode legacyReq = mapper.readTree(legacyWire)
            .get("params").get("arguments").get("request");
        JsonNode builderReq = mapper.readTree(builderWire)
            .get("params").get("arguments").get("request");

        assertEquals(legacyReq.get("messages").toString(), builderReq.get("messages").toString(),
            "legacy stream() and builder streamGenerate() must produce identical messages");
        assertEquals(legacyReq.get("model_params").toString(), builderReq.get("model_params").toString(),
            "legacy stream() and builder streamGenerate() must produce identical model_params");

        // Full-shape contract: the entire `request` payload must be byte-for-byte
        // structurally identical between the two paths. Per-key assertions above
        // remain for nicer diagnostic-on-failure messages.
        assertEquals(legacyReq, builderReq,
            "Legacy stream(messages) must produce identical wire shape to request().messages(messages).streamGenerate()");
    }
}
