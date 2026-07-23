package io.mcpmesh.spring;

import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.types.MeshLlmStopReason;
import io.mcpmesh.types.MeshMaxIterationsException;
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
import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1355: the LLM {@code max_iterations} exhaustion signal (consumer side).
 *
 * <p>A provider-managed loop that hits its cap returns a terminal no-tool-calls
 * reply carrying the structural discriminant {@code _mesh_stop_reason:
 * "max_iterations"} — never the failure inside {@code content}. The delegating
 * consumer reads it and raises {@link MeshMaxIterationsException} instead of
 * silently returning prior assistant text. A normal completion (discriminant
 * absent) returns content as usual, and the {@code extractContent} bare-map
 * recovery guard treats {@code _mesh_stop_reason} as diagnostic metadata.
 *
 * <p>Mirrors the Python ({@code mesh_llm_agent.py}) and TypeScript
 * ({@code llm-agent.ts}) references. Wiring mirrors
 * {@code MeshLlmAgentProxyTokenTelemetryTest}: a real {@link McpHttpClient}
 * pointed at a {@link MockWebServer} returning the MCP tools/call shape.
 */
@DisplayName("MeshLlmAgentProxy — max_iterations exhaustion signal (#1355)")
class MeshLlmAgentProxyExhaustionTest {

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
        MeshLlmAgentProxy proxy = new MeshLlmAgentProxy("test.exhaustion");
        proxy.configure(client, null, null, null, "", "ctx", maxIterations, false);
        proxy.updateProvider(
            server.url("/").toString().replaceAll("/$", ""),
            "process_chat",
            "mesh-delegated"
        );
        return proxy;
    }

    /** Build the MCP envelope wrapping a JSON-encoded inner provider payload. */
    private MockResponse envelope(Map<String, Object> innerPayload) {
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

    /** Exhaustion reply: last assistant text (possibly "") + the discriminant sibling. */
    private MockResponse exhaustionReply(String lastText) {
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("role", "assistant");
        inner.put("content", lastText);
        inner.put("tool_calls", List.of());
        inner.put(MeshLlmStopReason.STOP_REASON_KEY, MeshLlmStopReason.STOP_REASON_MAX_ITERATIONS);
        return envelope(inner);
    }

    private MockResponse normalReply(String content) {
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("role", "assistant");
        inner.put("content", content);
        inner.put("tool_calls", List.of());
        return envelope(inner);
    }

    // ------------------------------------------------------------------- throws

    @Test
    @DisplayName("throws MeshMaxIterationsException on a provider exhaustion reply (empty content)")
    void throwsOnExhaustionReply() {
        server.enqueue(exhaustionReply(""));

        MeshMaxIterationsException ex = assertThrows(MeshMaxIterationsException.class,
            () -> proxyWith(5).request().user("hi").generate());

        assertEquals(5, ex.getMaxAllowed());
        assertEquals(5, ex.getIterationCount());
    }

    @Test
    @DisplayName("throws even when the exhaustion reply carries prior assistant text — content is never returned")
    void throwsAndDoesNotLeakPriorText() {
        server.enqueue(exhaustionReply("partial reasoning so far"));

        assertThrows(MeshMaxIterationsException.class,
            () -> proxyWith(3).request().user("hi").generate());
    }

    // ------------------------------------------------------------ does NOT throw

    @Test
    @DisplayName("normal completion (discriminant absent) returns content, does not throw")
    void doesNotThrowOnNormalCompletion() {
        server.enqueue(normalReply("all done"));

        assertEquals("all done", proxyWith(5).request().user("hi").generate());
    }

    // -------------------------------------------------------- reserved-key guard

    @Test
    @DisplayName("extractContent treats a bare _mesh_stop_reason map as diagnostic, not a bare answer")
    void reservedKeyGuardTreatsStopReasonAsDiagnostic() throws Exception {
        // A bare map with NO content/role, carrying only the discriminant, must not
        // be mis-recovered as the user's answer — the guard returns "" so the
        // exhaustion signal is never swallowed into content.
        Map<String, Object> bare = new LinkedHashMap<>();
        bare.put(MeshLlmStopReason.STOP_REASON_KEY, MeshLlmStopReason.STOP_REASON_MAX_ITERATIONS);

        MeshLlmAgentProxy proxy = proxyWith(5);
        Method extractContent = MeshLlmAgentProxy.class.getDeclaredMethod("extractContent", Map.class);
        extractContent.setAccessible(true);
        Object result = extractContent.invoke(proxy, bare);

        assertEquals("", result, "a bare _mesh_stop_reason map must not be recovered as content");
    }
}
