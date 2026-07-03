package io.mcpmesh.ai;

import io.mcpmesh.ai.handlers.LlmProviderHandler.ToolExecutorCallback;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.spring.MeshTlsConfig;
import io.mcpmesh.spring.media.MediaStore;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.*;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Serialization contract for the MCP tool-executor callback that feeds tool
 * results back to the LLM ({@code MeshLlmProviderProcessor#createMcpToolExecutor}).
 *
 * <p>The untyped tool call now parses JSON tool outputs generically (arrays to
 * {@code List}, objects to {@code Map}, scalars to their boxed type). The
 * executor MUST re-serialize those as JSON so the LLM sees valid JSON — never
 * Java {@code toString()} rendering, which drops quotes/structure
 * ({@code ["a","b"] -> [a, b]}). Strings pass through verbatim.
 */
@DisplayName("MCP tool-executor result serialization")
class McpToolExecutorSerializationTest {

    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    private MockWebServer server;
    private ToolExecutorCallback executor;

    @BeforeAll
    static void initTlsConfig() throws Exception {
        // Pre-seed MeshTlsConfig.cached to avoid a native FFI call when the
        // executor constructs its McpHttpClient.
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

        MeshLlmProviderProcessor processor = new MeshLlmProviderProcessor();
        Method create = MeshLlmProviderProcessor.class.getDeclaredMethod(
            "createMcpToolExecutor", Map.class, String.class, MediaStore.class);
        create.setAccessible(true);
        executor = (ToolExecutorCallback) create.invoke(
            processor, Map.of("my_tool", server.url("/").toString()), "anthropic", null);
    }

    @AfterEach
    void tearDown() throws Exception {
        server.shutdown();
    }

    /** MCP JSON-RPC response whose single text-content item is {@code text}. */
    private void enqueueText(String text) {
        String escaped = MAPPER.writeValueAsString(text); // quoted + escaped
        server.enqueue(new MockResponse()
            .setBody("{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"content\":[{\"type\":\"text\",\"text\":"
                + escaped + "}]}}")
            .setHeader("Content-Type", "application/json"));
    }

    @Test
    @DisplayName("JSON-array tool result is re-serialized as JSON, not Java toString()")
    void jsonArrayResult() throws Exception {
        enqueueText("[\"a\",\"b\"]");

        String result = executor.execute("my_tool", "{}");

        assertEquals("[\"a\",\"b\"]", result);
    }

    @Test
    @DisplayName("JSON-object tool result is re-serialized as JSON")
    void jsonObjectResult() throws Exception {
        enqueueText("{\"k\":\"v\"}");

        String result = executor.execute("my_tool", "{}");

        assertEquals("{\"k\":\"v\"}", result);
    }

    @Test
    @DisplayName("text-only string result passes through verbatim")
    void plainStringResult() throws Exception {
        enqueueText("hello world");

        String result = executor.execute("my_tool", "{}");

        assertEquals("hello world", result);
    }
}
