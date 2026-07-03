package io.mcpmesh.spring;

import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshToolCallException;
import tools.jackson.core.type.TypeReference;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Type;
import java.util.List;
import java.util.Map;

/**
 * Empty-content handling (#1250).
 *
 * <p>A provider returning None or an empty collection serializes to an MCP
 * result with an EMPTY content array. Typed returns carry the value in
 * {@code structuredContent} (FastMCP wraps non-object values as
 * {@code {"result": X}} and tags the wrapping with a {@code fastmcp.wrap_result}
 * meta marker); None returns carry no {@code structuredContent}.
 *
 * <p>Before the fix, an empty content array left {@code textContent} null and the
 * whole MCP envelope was fed to {@code treeToValue} — typed collection returns
 * threw, dynamic returns leaked the raw envelope map. Now the value is recovered
 * from {@code structuredContent} (unwrapping only when the marker is set), or
 * resolved to {@code null} when there is nothing to recover.
 */
@DisplayName("McpHttpClient empty-content handling (#1250)")
class McpHttpClientEmptyContentTest {

    private MockWebServer server;
    private McpHttpClient client;

    @BeforeAll
    static void initTlsConfig() throws Exception {
        // Pre-seed MeshTlsConfig.cached to avoid native FFI call during tests.
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

    private void enqueue(String jsonResponse) {
        server.enqueue(new MockResponse()
            .setBody(jsonResponse)
            .setHeader("Content-Type", "application/json"));
    }

    @Nested
    @DisplayName("empty content + structuredContent")
    class WithStructuredContent {

        @Test
        @DisplayName("wrapped {\"result\": []} deserializes to a typed empty list")
        void wrappedEmptyListTyped() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [],
                        "structuredContent": {"result": []},
                        "_meta": {"fastmcp": {"wrap_result": true}},
                        "isError": false
                    }
                }
                """);

            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<String>>() {}.getType();
            List<String> result = client.callTool(endpoint, "test_tool", Map.of(), listType);

            assertNotNull(result);
            assertTrue(result.isEmpty());
        }

        @Test
        @DisplayName("wrapped {\"result\": []} resolves to an empty list for dynamic returns")
        void wrappedEmptyListDynamic() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [],
                        "structuredContent": {"result": []},
                        "_meta": {"fastmcp": {"wrap_result": true}}
                    }
                }
                """);

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertInstanceOf(List.class, result);
            assertTrue(((List<?>) result).isEmpty());
        }

        @Test
        @DisplayName("no wrap marker → structuredContent is used as-is (not unwrapped)")
        @SuppressWarnings("unchecked")
        void noMarkerUsedAsIs() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [],
                        "structuredContent": {"result": []}
                    }
                }
                """);

            String endpoint = server.url("/").toString();
            Type mapType = new TypeReference<Map<String, Object>>() {}.getType();
            Map<String, Object> result = client.callTool(endpoint, "test_tool", Map.of(), mapType);

            // Single-key {"result": []} must NOT be blindly unwrapped without the marker.
            assertNotNull(result);
            assertTrue(result.containsKey("result"));
            assertInstanceOf(List.class, result.get("result"));
            assertTrue(((List<Object>) result.get("result")).isEmpty());
        }

        @Test
        @DisplayName("marker + sibling key alongside \"result\" is NOT unwrapped (exact-keys rule)")
        @SuppressWarnings("unchecked")
        void markerWithSiblingKeyNotUnwrapped() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [],
                        "structuredContent": {"result": 1, "extra": 2},
                        "_meta": {"fastmcp": {"wrap_result": true}}
                    }
                }
                """);

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            // Keys must be exactly {"result"} to unwrap; sibling keys are kept.
            assertInstanceOf(Map.class, result);
            Map<String, Object> map = (Map<String, Object>) result;
            assertEquals(1, map.get("result"));
            assertEquals(2, map.get("extra"));
        }

        @Test
        @DisplayName("_meta present-but-null falls back to meta for the marker")
        void metaFallbackWhenUnderscoreMetaNull() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [],
                        "structuredContent": {"result": []},
                        "_meta": null,
                        "meta": {"fastmcp": {"wrap_result": true}}
                    }
                }
                """);

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertInstanceOf(List.class, result);
            assertTrue(((List<?>) result).isEmpty());
        }

        @Test
        @DisplayName("non-result structuredContent object is used as-is")
        void nonResultStructuredContent() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [],
                        "structuredContent": {"count": 3, "name": "x"},
                        "_meta": {"fastmcp": {"wrap_result": true}}
                    }
                }
                """);

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertInstanceOf(Map.class, result);
            Map<?, ?> map = (Map<?, ?>) result;
            assertEquals(3, map.get("count"));
            assertEquals("x", map.get("name"));
        }
    }

    @Nested
    @DisplayName("empty content + no structuredContent")
    class WithoutStructuredContent {

        @Test
        @DisplayName("typed return resolves to null (never mangles the envelope)")
        void typedReturnsNull() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"content": []}
                }
                """);

            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<String>>() {}.getType();
            List<String> result = client.callTool(endpoint, "test_tool", Map.of(), listType);

            assertNull(result);
        }

        @Test
        @DisplayName("dynamic return resolves to null")
        void dynamicReturnsNull() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"content": []}
                }
                """);

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertNull(result);
        }
    }

    @Nested
    @DisplayName("regression: non-empty content is unchanged")
    class NonEmptyContentUnchanged {

        @Test
        @DisplayName("single text block \"[]\" deserializes to a typed empty list")
        void textBlockEmptyListTyped() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [{"type": "text", "text": "[]"}]
                    }
                }
                """);

            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<String>>() {}.getType();
            List<String> result = client.callTool(endpoint, "test_tool", Map.of(), listType);

            assertNotNull(result);
            assertTrue(result.isEmpty());
        }

        @Test
        @DisplayName("single text block \"null\" deserializes to null")
        void textBlockNull() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [{"type": "text", "text": "null"}]
                    }
                }
                """);

            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<String>>() {}.getType();
            List<String> result = client.callTool(endpoint, "test_tool", Map.of(), listType);

            assertNull(result);
        }

        @Test
        @DisplayName("normal text payload is returned verbatim")
        void normalTextPayload() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [{"type": "text", "text": "hello world"}]
                    }
                }
                """);

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of());

            assertEquals("hello world", result);
        }
    }

    @Nested
    @DisplayName("text content deserialization by declared return type (uc32)")
    class TextContentByReturnType {

        private void enqueueText(String text) {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [{"type": "text", "text": "%s"}]
                    }
                }
                """.formatted(text));
        }

        @Test
        @DisplayName("Object target + empty text round-trips to \"\" (uc32 bug fix)")
        void objectTargetEmptyText() {
            enqueueText("");

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of(), Object.class);

            assertEquals("", result);
        }

        @Test
        @DisplayName("Object target + non-JSON text returns the raw string")
        void objectTargetNonJsonText() {
            enqueueText("hello");

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of(), Object.class);

            assertEquals("hello", result);
        }

        @Test
        @DisplayName("Object target + JSON object text parses to a map")
        void objectTargetJsonText() {
            // Escaped quotes so the embedded JSON survives the outer envelope.
            enqueueText("{\\\"a\\\": 1}");

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of(), Object.class);

            assertInstanceOf(Map.class, result);
            assertEquals(1, ((Map<?, ?>) result).get("a"));
        }

        @Test
        @DisplayName("Object target + JSON array text parses to a List (uc32 array fix)")
        @SuppressWarnings("unchecked")
        void objectTargetEmptyArray() {
            enqueueText("[]");

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of(), Object.class);

            assertInstanceOf(List.class, result);
            assertTrue(((List<Object>) result).isEmpty());
        }

        @Test
        @DisplayName("Object target + non-empty JSON array text parses to a List")
        @SuppressWarnings("unchecked")
        void objectTargetNonEmptyArray() {
            enqueueText("[1, 2, 3]");

            String endpoint = server.url("/").toString();
            Object result = client.callTool(endpoint, "test_tool", Map.of(), Object.class);

            assertInstanceOf(List.class, result);
            assertEquals(List.of(1, 2, 3), result);
        }

        @Test
        @DisplayName("Object target + JSON scalar text parses to the scalar")
        void objectTargetScalars() {
            String endpoint = server.url("/").toString();

            enqueueText("42");
            Object intResult = client.callTool(endpoint, "test_tool", Map.of(), Object.class);
            assertEquals(Integer.valueOf(42), intResult);

            enqueueText("true");
            Object boolResult = client.callTool(endpoint, "test_tool", Map.of(), Object.class);
            assertEquals(Boolean.TRUE, boolResult);
        }

        @Test
        @DisplayName("Object target results equal untyped (returnType==null) results for the same inputs")
        void objectTargetEqualsUntyped() {
            String endpoint = server.url("/").toString();
            for (String text : new String[] {"", "hello", "[]", "[1, 2, 3]", "42", "true"}) {
                enqueueText(text);
                Object typed = client.callTool(endpoint, "test_tool", Map.of(), Object.class);
                enqueueText(text);
                Object untyped = client.callTool(endpoint, "test_tool", Map.of());
                assertEquals(untyped, typed, "mismatch for text: " + text);
            }
        }

        @Test
        @DisplayName("String target + empty text returns \"\" (raw text is a valid String)")
        void stringTargetEmptyText() {
            enqueueText("");

            String endpoint = server.url("/").toString();
            String result = client.callTool(endpoint, "test_tool", Map.of(), String.class);

            assertEquals("", result);
        }

        @Test
        @DisplayName("List<Object> target + empty array parses to an empty List (typed-probe fix)")
        @SuppressWarnings("unchecked")
        void listTargetEmptyArray() {
            enqueueText("[]");

            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<Object>>() {}.getType();
            List<Object> result = client.callTool(endpoint, "test_tool", Map.of(), listType);

            assertNotNull(result);
            assertTrue(result.isEmpty());
        }

        @Test
        @DisplayName("List<Object> target + non-empty array parses to a List")
        void listTargetNonEmptyArray() {
            enqueueText("[1, 2, 3]");

            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<Object>>() {}.getType();
            List<Object> result = client.callTool(endpoint, "test_tool", Map.of(), listType);

            assertEquals(List.of(1, 2, 3), result);
        }

        @Test
        @DisplayName("erased target (getRawType→Object but not literally Object) uses the STRICT path")
        void erasedTypeVariableTargetIsStrict() {
            enqueueText("");

            String endpoint = server.url("/").toString();
            // A TypeVariable resolves via getRawType() to Object.class, but is NOT
            // literally Object.class. The lenient "" -> "" fallback must NOT fire
            // for it; the strict path must throw — proving the gate is exact
            // Object.class only, so List/Map/POJO/erased targets never leak.
            Type erased = List.class.getTypeParameters()[0]; // TypeVariable "E"

            assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint, "test_tool", Map.of(), erased));
        }

        @Test
        @DisplayName("List target + empty text still fails loudly (regression pin)")
        void listTargetEmptyTextThrows() {
            enqueueText("");

            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<Object>>() {}.getType();

            assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint, "test_tool", Map.of(), listType));
        }
    }

    @Nested
    @DisplayName("proxy cache isolates return types per injection site (parallel-run nondeterminism)")
    class ProxyCacheTypeIsolation {

        private void enqueueEmptyObject() {
            enqueue("""
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [{"type": "text", "text": "{}"}]
                    }
                }
                """);
        }

        // The Object consumer deserializes "{}" to a Map; the List<Object>
        // consumer strictly FAILS on the same payload — proving each proxy uses
        // its OWN declared type regardless of which injection site resolved
        // first (before the fix they shared one proxy and one returnType, so
        // whichever resolved first silently governed both).
        private void assertEachDeserializesByOwnType(McpMeshTool<Object> objProxy,
                                                     McpMeshTool<List<Object>> listProxy) {
            enqueueEmptyObject();
            Object objResult = objProxy.call();
            assertInstanceOf(Map.class, objResult);
            assertTrue(((Map<?, ?>) objResult).isEmpty());

            enqueueEmptyObject();
            assertThrows(MeshToolCallException.class, listProxy::call);
        }

        @Test
        @DisplayName("Object and List<Object> consumers get distinct proxies — Object resolves first")
        void distinctProxiesObjectFirst() {
            McpMeshToolProxyFactory factory = new McpMeshToolProxyFactory(client);
            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<Object>>() {}.getType();

            McpMeshTool<Object> objProxy = factory.getOrCreateProxy(endpoint, "test_tool", Object.class);
            McpMeshTool<List<Object>> listProxy = factory.getOrCreateProxy(endpoint, "test_tool", listType);

            assertNotSame(objProxy, listProxy);
            assertEachDeserializesByOwnType(objProxy, listProxy);
        }

        @Test
        @DisplayName("Object and List<Object> consumers get distinct proxies — List resolves first")
        void distinctProxiesListFirst() {
            McpMeshToolProxyFactory factory = new McpMeshToolProxyFactory(client);
            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<Object>>() {}.getType();

            McpMeshTool<List<Object>> listProxy = factory.getOrCreateProxy(endpoint, "test_tool", listType);
            McpMeshTool<Object> objProxy = factory.getOrCreateProxy(endpoint, "test_tool", Object.class);

            assertNotSame(objProxy, listProxy);
            assertEachDeserializesByOwnType(objProxy, listProxy);
        }

        @Test
        @DisplayName("same declared type reuses one cached proxy")
        void sameTypeSharesProxy() {
            McpMeshToolProxyFactory factory = new McpMeshToolProxyFactory(client);
            String endpoint = server.url("/").toString();

            McpMeshTool<Object> a = factory.getOrCreateProxy(endpoint, "test_tool", Object.class);
            McpMeshTool<Object> b = factory.getOrCreateProxy(endpoint, "test_tool", Object.class);

            assertSame(a, b);
        }

        @Test
        @DisplayName("null (untyped) and Object.class share one dynamic proxy")
        void untypedAndObjectShareProxy() {
            McpMeshToolProxyFactory factory = new McpMeshToolProxyFactory(client);
            String endpoint = server.url("/").toString();

            // Both deserialize dynamically and identically → one proxy, no
            // duplicate for the common untyped case.
            McpMeshTool<?> untyped = factory.getOrCreateProxy(endpoint, "test_tool");
            McpMeshTool<Object> objectTyped = factory.getOrCreateProxy(endpoint, "test_tool", Object.class);

            assertSame(untyped, objectTyped);
        }

        @Test
        @DisplayName("updateOrCreateProxy prefers the dynamic variant, deterministically")
        void updateOrCreatePrefersDynamic() {
            McpMeshToolProxyFactory factory = new McpMeshToolProxyFactory(client);
            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<Object>>() {}.getType();

            McpMeshTool<Object> dyn = factory.getOrCreateProxy(endpoint, "test_tool", Object.class);
            factory.getOrCreateProxy(endpoint, "test_tool", listType);

            McpMeshTool<?> rep1 = factory.updateOrCreateProxy(endpoint, "test_tool");
            McpMeshTool<?> rep2 = factory.updateOrCreateProxy(endpoint, "test_tool");

            assertSame(dyn, rep1);
            assertSame(rep1, rep2);
        }

        @Test
        @DisplayName("updateOrCreateProxy is deterministic with no dynamic variant (stable order)")
        void updateOrCreateStableWhenNoDynamic() {
            McpMeshToolProxyFactory factory = new McpMeshToolProxyFactory(client);
            String endpoint = server.url("/").toString();
            Type listType = new TypeReference<List<Object>>() {}.getType();

            McpMeshTool<String> strProxy = factory.getOrCreateProxy(endpoint, "test_tool", String.class);
            factory.getOrCreateProxy(endpoint, "test_tool", listType);

            // "java.lang.String" sorts before "java.util.List<java.lang.Object>",
            // so the String proxy is the stable representative on every call.
            McpMeshTool<?> rep1 = factory.updateOrCreateProxy(endpoint, "test_tool");
            McpMeshTool<?> rep2 = factory.updateOrCreateProxy(endpoint, "test_tool");

            assertSame(strProxy, rep1);
            assertSame(rep1, rep2);
        }
    }
}
