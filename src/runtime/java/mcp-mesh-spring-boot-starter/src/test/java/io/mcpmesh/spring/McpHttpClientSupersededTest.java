package io.mcpmesh.spring;

import io.mcpmesh.types.MeshSupersededException;
import io.mcpmesh.types.MeshToolCallException;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.*;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1278 — consumer recognize + swallow point ({@link McpHttpClient}).
 *
 * <p>The injected remote proxy classifies an {@code isError} tool result: the
 * reserved {@code {"error":"claim_superseded"}} envelope is re-thrown as the
 * typed {@link MeshSupersededException} (carrying detail), while a generic
 * isError — or the sibling {@code dependency_unavailable} envelope (#1273) —
 * still throws {@link MeshToolCallException}. Critically, the thrown typed
 * signal must reach the caller UNTOUCHED: the method's outer
 * {@code catch (Exception)} must not re-wrap it back into MeshToolCallException.
 */
@DisplayName("McpHttpClient supersession recognize (#1278)")
class McpHttpClientSupersededTest {

    private MockWebServer server;
    private McpHttpClient client;

    @BeforeAll
    static void initTlsConfig() throws Exception {
        // Pre-seed MeshTlsConfig.cached to avoid a native FFI call during tests.
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
        client = new McpHttpClient();
    }

    @AfterEach
    void tearDown() throws Exception {
        if (client != null) {
            client.close();
        }
        server.shutdown();
    }

    /** Enqueue a JSON-RPC isError result whose single text block is {@code envelope}. */
    private void enqueueError(String envelope) {
        String escaped = envelope.replace("\"", "\\\"");
        String body = "{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"content\":[{\"type\":\"text\","
            + "\"text\":\"" + escaped + "\"}],\"isError\":true}}";
        server.enqueue(new MockResponse()
            .setBody(body)
            .setHeader("Content-Type", "application/json"));
    }

    @Test
    void reservedEnvelopeWithDetail_throwsTypedSignal_untouched() {
        enqueueError("{\"error\":\"claim_superseded\",\"detail\":\"stale\"}");
        String endpoint = server.url("/").toString();

        // The swallow-point assertion: the CAUGHT exception is the typed signal
        // itself — NOT a MeshToolCallException wrapping it.
        MeshSupersededException e = assertThrows(MeshSupersededException.class,
            () -> client.callTool(endpoint, "mutate", Map.of()),
            "the reserved envelope must surface as the typed signal, not re-wrapped");
        assertEquals("stale", e.getDetail(), "the detail must be carried to the caller");
    }

    @Test
    void reservedEnvelopeNoDetail_throwsTypedSignal_detailNull() {
        enqueueError("{\"error\":\"claim_superseded\"}");
        String endpoint = server.url("/").toString();

        MeshSupersededException e = assertThrows(MeshSupersededException.class,
            () -> client.callTool(endpoint, "mutate", Map.of()));
        assertNull(e.getDetail());
    }

    @Test
    void dependencyUnavailableEnvelope_stillThrowsMeshToolCallException() {
        // #1273 sibling envelope must NOT be misclassified as supersession.
        enqueueError("{\"error\":\"dependency_unavailable\",\"capability\":\"lookup\"}");
        String endpoint = server.url("/").toString();

        assertThrows(MeshToolCallException.class,
            () -> client.callTool(endpoint, "mutate", Map.of()),
            "dependency_unavailable must remain a MeshToolCallException");
    }

    @Test
    void genericErrorText_stillThrowsMeshToolCallException() {
        enqueueError("boom: something went wrong");
        String endpoint = server.url("/").toString();

        assertThrows(MeshToolCallException.class,
            () -> client.callTool(endpoint, "mutate", Map.of()),
            "a generic isError must remain a MeshToolCallException");
    }
}
