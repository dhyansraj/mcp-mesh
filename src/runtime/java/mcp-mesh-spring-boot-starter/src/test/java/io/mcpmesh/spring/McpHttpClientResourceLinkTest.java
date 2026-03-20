package io.mcpmesh.spring;

import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.util.List;
import java.util.Map;

@DisplayName("McpHttpClient resource_link handling")
class McpHttpClientResourceLinkTest {

    private MockWebServer server;
    private McpHttpClient client;

    @BeforeAll
    static void initTlsConfig() throws Exception {
        // Pre-seed MeshTlsConfig.cached to avoid native FFI call during tests
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

    @Nested
    @DisplayName("text-only content")
    class TextOnlyTests {

        @Test
        @DisplayName("single text content returns string")
        void singleTextContentReturnsString() {
            String jsonResponse = """
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [
                            {"type": "text", "text": "hello world"}
                        ]
                    }
                }
                """;
            server.enqueue(new MockResponse()
                .setBody(jsonResponse)
                .setHeader("Content-Type", "application/json"));

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertInstanceOf(String.class, result);
            assertEquals("hello world", result);
        }

        @Test
        @DisplayName("multiple text items returns first as string")
        void multipleTextItemsReturnsFirstAsString() {
            String jsonResponse = """
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [
                            {"type": "text", "text": "first"},
                            {"type": "text", "text": "second"}
                        ]
                    }
                }
                """;
            server.enqueue(new MockResponse()
                .setBody(jsonResponse)
                .setHeader("Content-Type", "application/json"));

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertInstanceOf(String.class, result);
            assertEquals("first", result);
        }
    }

    @Nested
    @DisplayName("mixed content (resource_link)")
    class MixedContentTests {

        @Test
        @DisplayName("text + resource_link preserved as list")
        @SuppressWarnings("unchecked")
        void textAndResourceLinkPreservedAsList() {
            String jsonResponse = """
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [
                            {"type": "text", "text": "Here is the file:"},
                            {"type": "resource_link", "uri": "file:///tmp/output.png", "name": "output.png", "mimeType": "image/png"}
                        ]
                    }
                }
                """;
            server.enqueue(new MockResponse()
                .setBody(jsonResponse)
                .setHeader("Content-Type", "application/json"));

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertInstanceOf(List.class, result);
            List<Map<String, Object>> content = (List<Map<String, Object>>) result;
            assertEquals(2, content.size());

            // First item: text
            assertEquals("text", content.get(0).get("type"));
            assertEquals("Here is the file:", content.get(0).get("text"));

            // Second item: resource_link with preserved fields
            Map<String, Object> resourceLink = content.get(1);
            assertEquals("resource_link", resourceLink.get("type"));
            assertEquals("file:///tmp/output.png", resourceLink.get("uri"));
            assertEquals("output.png", resourceLink.get("name"));
            assertEquals("image/png", resourceLink.get("mimeType"));
        }

        @Test
        @DisplayName("resource_link only preserved as list")
        @SuppressWarnings("unchecked")
        void resourceLinkOnlyPreservedAsList() {
            String jsonResponse = """
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [
                            {"type": "resource_link", "uri": "s3://bucket/key.pdf", "name": "report.pdf", "mimeType": "application/pdf"}
                        ]
                    }
                }
                """;
            server.enqueue(new MockResponse()
                .setBody(jsonResponse)
                .setHeader("Content-Type", "application/json"));

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertInstanceOf(List.class, result);
            List<Map<String, Object>> content = (List<Map<String, Object>>) result;
            assertEquals(1, content.size());
            assertEquals("resource_link", content.get(0).get("type"));
            assertEquals("s3://bucket/key.pdf", content.get(0).get("uri"));
        }

        @Test
        @DisplayName("image content preserved as list")
        @SuppressWarnings("unchecked")
        void imageContentPreservedAsList() {
            String jsonResponse = """
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [
                            {"type": "text", "text": "Generated image:"},
                            {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"}
                        ]
                    }
                }
                """;
            server.enqueue(new MockResponse()
                .setBody(jsonResponse)
                .setHeader("Content-Type", "application/json"));

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertInstanceOf(List.class, result);
            List<Map<String, Object>> content = (List<Map<String, Object>>) result;
            assertEquals(2, content.size());
            assertEquals("image", content.get(1).get("type"));
            assertEquals("iVBORw0KGgo=", content.get(1).get("data"));
            assertEquals("image/png", content.get(1).get("mimeType"));
        }
    }

    @Nested
    @DisplayName("content without type field")
    class NoTypeFieldTests {

        @Test
        @DisplayName("content items without type default to text")
        void noTypeFieldDefaultsToText() {
            String jsonResponse = """
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [
                            {"text": "implicit text"}
                        ]
                    }
                }
                """;
            server.enqueue(new MockResponse()
                .setBody(jsonResponse)
                .setHeader("Content-Type", "application/json"));

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertInstanceOf(String.class, result);
            assertEquals("implicit text", result);
        }
    }
}
