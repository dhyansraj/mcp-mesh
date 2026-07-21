package io.mcpmesh.spring;

import io.mcpmesh.MeshLlmDefaults;
import io.mcpmesh.core.MeshObjectMappers;
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
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1356: the consumer forwards {@code model_params.max_iterations} to the
 * provider ONLY when the cap was explicitly configured
 * ({@code @MeshLlm(maxIterations=...)} or {@code MESH_LLM_MAX_ITERATIONS}).
 *
 * <p>When unset ({@link MeshLlmDefaults#MAX_ITERATIONS_UNSET}) the key is
 * omitted so the provider keeps its own {@code MESH_LLM_MAX_ITERATIONS} /
 * default of 10 — matching the TypeScript reference and the Python SDK.
 *
 * <p>Wiring mirrors {@code MeshLlmAgentProxyModelParamsTest}.
 */
@DisplayName("MeshLlmAgentProxy — max_iterations forwarding (#1356)")
class MeshLlmAgentProxyMaxIterationsTest {

    private MockWebServer server;
    private McpHttpClient client;
    private ObjectMapper mapper;

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
    }

    @AfterEach
    void tearDown() throws Exception {
        if (client != null) client.close();
        server.shutdown();
    }

    private MeshLlmAgentProxy proxyWith(int maxIterations) {
        MeshLlmAgentProxy proxy = new MeshLlmAgentProxy("test.maxiterations");
        proxy.configure(client, null, null, null, "", "ctx", maxIterations, false);
        proxy.updateProvider(
            server.url("/").toString().replaceAll("/$", ""),
            "process_chat",
            "mesh-delegated"
        );
        return proxy;
    }

    private MockResponse stubLlmResponse(String reply) {
        Map<String, Object> innerPayload = Map.of("role", "assistant", "content", reply);
        String innerJson = mapper.writeValueAsString(innerPayload);
        Map<String, Object> envelope = Map.of(
            "jsonrpc", "2.0",
            "id", System.currentTimeMillis(),
            "result", Map.of("content", List.of(Map.of("type", "text", "text", innerJson)))
        );
        return new MockResponse()
            .setBody(mapper.writeValueAsString(envelope))
            .setHeader("Content-Type", "application/json");
    }

    private JsonNode readModelParams(RecordedRequest request) throws Exception {
        JsonNode root = mapper.readTree(request.getBody().readUtf8());
        JsonNode modelParams = root.get("params").get("arguments").get("request").get("model_params");
        assertNotNull(modelParams, "request.model_params must be present");
        return modelParams;
    }

    @Test
    @DisplayName("explicit cap is forwarded on the wire")
    void explicitCapForwarded() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        assertEquals("ok", proxyWith(4).request().user("hi").generate());

        JsonNode modelParams = readModelParams(server.takeRequest());
        assertEquals(4, modelParams.get("max_iterations").asInt());
    }

    @Test
    @DisplayName("unset cap is NOT forwarded — provider keeps its own resolution")
    void unsetCapOmitted() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        assertEquals("ok",
            proxyWith(MeshLlmDefaults.MAX_ITERATIONS_UNSET).request().user("hi").generate());

        JsonNode modelParams = readModelParams(server.takeRequest());
        assertFalse(modelParams.has("max_iterations"),
            "unset maxIterations must not put a cap on the wire");
    }

    @Test
    @DisplayName("unset cap still runs the local loop with the default of 10")
    void unsetCapStillDefaultsLocally() throws Exception {
        MeshLlmAgentProxy proxy = proxyWith(MeshLlmDefaults.MAX_ITERATIONS_UNSET);
        Object builder = proxy.request();
        Field f = builder.getClass().getDeclaredField("maxIterations");
        f.setAccessible(true);
        assertEquals(MeshLlmDefaults.MAX_ITERATIONS, f.getInt(builder));
    }

    @Test
    @DisplayName("modelParams escape hatch wins over the annotation cap")
    void escapeHatchWins() throws Exception {
        server.enqueue(stubLlmResponse("ok"));

        proxyWith(4).request()
            .user("hi")
            .modelParams(Map.of("max_iterations", 2))
            .generate();

        JsonNode modelParams = readModelParams(server.takeRequest());
        assertEquals(2, modelParams.get("max_iterations").asInt());
    }
}
