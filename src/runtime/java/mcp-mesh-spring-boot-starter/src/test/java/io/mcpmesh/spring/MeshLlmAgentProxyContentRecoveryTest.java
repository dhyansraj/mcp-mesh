package io.mcpmesh.spring;

import io.mcpmesh.core.MeshObjectMappers;
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
 * Consumer-side recovery + honest diagnostics for the {@code {role, content}}
 * reply envelope in {@link MeshLlmAgentProxy}.
 *
 * <p>Providers should send the answer as a string. Two malformed-but-recoverable
 * shapes occur in the field:
 * <ul>
 *   <li>{@code content} is a raw Map — the structured answer leaked unserialized.
 *       {@link MeshLlmAgentProxy#extractContent} serializes it to a JSON string.</li>
 *   <li>the map carries neither {@code content} nor {@code role} — a bare
 *       structured answer without the envelope. The whole map is serialized.</li>
 * </ul>
 *
 * <p>When content resolves to empty, {@code generate(Class)} must blame the empty
 * reply and surface the raw payload — not a misleading "Failed to parse as &lt;Model&gt;".
 *
 * <p>{@code extractContent} is reflected out (private instance method) so the exact
 * proxy logic is exercised; the empty-content diagnostic runs end-to-end through a
 * {@link MockWebServer} mirroring {@code MeshLlmAgentProxyTokenTelemetryTest}.
 */
@DisplayName("MeshLlmAgentProxy — content recovery + empty-content diagnostics")
class MeshLlmAgentProxyContentRecoveryTest {

    private MockWebServer server;
    private McpHttpClient client;
    private ObjectMapper mapper;
    private MeshLlmAgentProxy proxy;

    record Reply(String answer) {}

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

        proxy = new MeshLlmAgentProxy("test.recovery");
        proxy.configure(client, null, null, null, "", "ctx", 1, false);
        proxy.updateProvider(
            server.url("/").toString().replaceAll("/$", ""),
            "process_chat",
            "anthropic"
        );
    }

    @AfterEach
    void tearDown() throws Exception {
        if (client != null) client.close();
        server.shutdown();
    }

    // -------------------------------------------------------------------------
    // extractContent (reflected private instance method)
    // -------------------------------------------------------------------------

    private String invokeExtractContent(Map<String, Object> response) throws Exception {
        Method m = MeshLlmAgentProxy.class.getDeclaredMethod("extractContent", Map.class);
        m.setAccessible(true);
        return (String) m.invoke(proxy, response);
    }

    @Test
    @DisplayName("string content passes through unchanged (regression)")
    void stringContentUnchanged() throws Exception {
        assertEquals("hello", invokeExtractContent(Map.of("role", "assistant", "content", "hello")));
    }

    @Test
    @DisplayName("list-of-blocks content reads the first block's text (regression)")
    void listOfBlocksUnchanged() throws Exception {
        Map<String, Object> response = Map.of(
            "role", "assistant",
            "content", List.of(Map.of("type", "text", "text", "hi from block"))
        );
        assertEquals("hi from block", invokeExtractContent(response));
    }

    @Test
    @DisplayName("Map content is serialized to a JSON string")
    void mapContentSerialized() throws Exception {
        Map<String, Object> answer = new LinkedHashMap<>();
        answer.put("answer", "42");
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("role", "assistant");
        response.put("content", answer);

        String result = invokeExtractContent(response);

        // Round-trips into the response model rather than degrading to "".
        Reply parsed = mapper.readValue(result, Reply.class);
        assertEquals("42", parsed.answer());
    }

    @Test
    @DisplayName("bare map without content/role keys is serialized whole")
    void bareMapSerializedWhole() throws Exception {
        Map<String, Object> bare = new LinkedHashMap<>();
        bare.put("answer", "bare");

        String result = invokeExtractContent(bare);

        Reply parsed = mapper.readValue(result, Reply.class);
        assertEquals("bare", parsed.answer());
    }

    @Test
    @DisplayName("error map (truthy) is NOT treated as a bare answer (degrades to empty)")
    void errorMapNotBareAnswer() throws Exception {
        assertEquals("", invokeExtractContent(Map.of("error", "rate limited by vendor")));
    }

    @Test
    @DisplayName("bare answer with a null error field is still recovered")
    void bareAnswerWithNullErrorFieldRecovered() throws Exception {
        // LinkedHashMap tolerates the null value that Map.of() rejects.
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("answer", "ok");
        payload.put("error", null);

        String result = invokeExtractContent(payload);

        assertFalse(result.isEmpty(),
            "bare answer with a falsy error field must be recovered, not degraded to empty");
        Map<?, ?> back = mapper.readValue(result, Map.class);
        assertEquals("ok", back.get("answer"));
        assertTrue(back.containsKey("error"), "the whole map (incl. error:null) is serialized");
    }

    @Test
    @DisplayName("tool_calls-only map is NOT treated as a bare answer (degrades to empty)")
    void toolCallsMapNotBareAnswer() throws Exception {
        Map<String, Object> response = Map.of(
            "tool_calls", List.of(Map.of(
                "id", "call_1",
                "type", "function",
                "function", Map.of("name", "f", "arguments", "{}")
            ))
        );
        assertEquals("", invokeExtractContent(response));
    }

    @Test
    @DisplayName("_mesh_usage-only map is NOT treated as a bare answer (degrades to empty)")
    void meshUsageMapNotBareAnswer() throws Exception {
        assertEquals("", invokeExtractContent(
            Map.of("_mesh_usage", Map.of("prompt_tokens", 1, "completion_tokens", 2))));
    }

    @Test
    @DisplayName("envelope with empty content still degrades to empty string")
    void emptyEnvelopeStillEmpty() throws Exception {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("role", "assistant");
        response.put("content", "");
        assertEquals("", invokeExtractContent(response));
    }

    // -------------------------------------------------------------------------
    // Nested provider-wrapper recovery: a String / content[0].text carrying a
    // serialized {role, content} envelope (parseNestedContent path) mirrors the
    // top-level guards instead of returning the wrapper JSON verbatim.
    // -------------------------------------------------------------------------

    /** Wraps a serialized envelope as the (string) content of an outer response. */
    private String extractFromNestedWrapper(Object innerEnvelope) throws Exception {
        String wrapper = mapper.writeValueAsString(innerEnvelope);
        return invokeExtractContent(Map.of("role", "assistant", "content", wrapper));
    }

    @Test
    @DisplayName("nested wrapper with string content → inner string returned (regression)")
    void nestedWrapperStringContentUnchanged() throws Exception {
        assertEquals("hello world", extractFromNestedWrapper(
            Map.of("role", "assistant", "content", "hello world")));
    }

    @Test
    @DisplayName("nested wrapper with dict content → inner map serialized")
    void nestedWrapperMapContentSerialized() throws Exception {
        String result = extractFromNestedWrapper(
            Map.of("role", "assistant", "content", Map.of("answer", "42")));
        Reply parsed = mapper.readValue(result, Reply.class);
        assertEquals("42", parsed.answer());
    }

    @Test
    @DisplayName("nested bare error payload → empty (diagnostics), not the wrapper JSON")
    void nestedTruthyErrorDegradesToEmpty() throws Exception {
        assertEquals("", extractFromNestedWrapper(
            Map.of("error", "rate limited by vendor")));
    }

    @Test
    @DisplayName("nested envelope with role but no usable content → empty (diagnostics)")
    void nestedEnvelopeNoContentDegradesToEmpty() throws Exception {
        assertEquals("", extractFromNestedWrapper(
            Map.of("role", "assistant", "error", "rate limited")));
    }

    @Test
    @DisplayName("nested bare _mesh_stop_reason payload → empty (diagnostics), not the wrapper JSON")
    void nestedStopReasonOnlyDegradesToEmpty() throws Exception {
        assertEquals("", extractFromNestedWrapper(
            Map.of("_mesh_stop_reason", "tool_use")));
    }

    @Test
    @DisplayName("genuine nested JSON answer (no wrapper markers) passes through unchanged")
    void nestedGenuineJsonAnswerUnchanged() throws Exception {
        String result = extractFromNestedWrapper(Map.of("answer", "42"));
        Reply parsed = mapper.readValue(result, Reply.class);
        assertEquals("42", parsed.answer());
    }

    // -------------------------------------------------------------------------
    // generate(Class) empty-content diagnostic (end-to-end via MockWebServer)
    // -------------------------------------------------------------------------

    /** Build the MCP JSON-RPC envelope wrapping a JSON-encoded inner provider payload. */
    private MockResponse envelope(Map<String, Object> innerPayload) {
        try {
            String innerJson = mapper.writeValueAsString(innerPayload);
            Map<String, Object> envelope = Map.of(
                "jsonrpc", "2.0",
                "id", System.currentTimeMillis(),
                "result", Map.of(
                    "content", List.of(Map.of("type", "text", "text", innerJson))
                )
            );
            return new MockResponse()
                .setBody(mapper.writeValueAsString(envelope))
                .setHeader("Content-Type", "application/json");
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    @Test
    @DisplayName("empty content under a response model → error blames empty content + shows raw payload")
    void emptyContentDiagnostic() {
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("role", "assistant");
        inner.put("content", "");
        server.enqueue(envelope(inner));

        RuntimeException ex = assertThrows(RuntimeException.class,
            () -> proxy.request().user("hi").generate(Reply.class));

        assertTrue(ex.getMessage().contains("empty content"),
            "error must blame the empty reply, got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("Raw response payload:"),
            "error must include the raw payload, got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("assistant"),
            "raw payload snippet must carry the envelope, got: " + ex.getMessage());
    }

    @Test
    @DisplayName("Map content under a response model → deserializes instead of failing")
    void mapContentDeserializesEndToEnd() {
        Map<String, Object> inner = new LinkedHashMap<>();
        inner.put("role", "assistant");
        inner.put("content", Map.of("answer", "structured"));
        server.enqueue(envelope(inner));

        Reply result = proxy.request().user("hi").generate(Reply.class);
        assertEquals("structured", result.answer());
    }

    @Test
    @DisplayName("error map under a response model → diagnostic surfaces the error, not a schema failure")
    void errorMapSurfacedInDiagnostic() {
        server.enqueue(envelope(Map.of("error", "rate limited by vendor")));

        RuntimeException ex = assertThrows(RuntimeException.class,
            () -> proxy.request().user("hi").generate(Reply.class));

        assertTrue(ex.getMessage().contains("empty content"),
            "error must blame the empty reply, got: " + ex.getMessage());
        assertTrue(ex.getMessage().contains("rate limited by vendor"),
            "raw payload snippet must surface the error, got: " + ex.getMessage());
    }

    @Test
    @DisplayName("genuine bare answer under a response model → recovered (not an error)")
    void genuineBareAnswerEndToEnd() {
        server.enqueue(envelope(Map.of("answer", "bare")));

        Reply result = proxy.request().user("hi").generate(Reply.class);
        assertEquals("bare", result.answer());
    }
}
