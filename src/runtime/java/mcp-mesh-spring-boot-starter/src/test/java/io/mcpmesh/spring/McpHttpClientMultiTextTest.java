package io.mcpmesh.spring;

import io.mcpmesh.types.MeshToolCallException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
import java.util.ArrayList;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Several text blocks in one tool result (#1630).
 *
 * <p>Before the fix, a result whose {@code content} held more than one text
 * block returned only the first block's text and silently dropped the rest.
 * Now every block comes back, in order, in the same {@code List<Map>} raw-item
 * form as mixed content, to every target that can hold them, even when
 * {@code structuredContent} is present. A typed target that cannot hold several
 * blocks is deserialized from {@code structuredContent} when present, and
 * otherwise fails loudly instead of receiving a partial value.
 */
@DisplayName("McpHttpClient multi-text-block results (#1630)")
class McpHttpClientMultiTextTest {

    record Point(int x, int y) {}

    record Employee(String name, String dept) {}

    /** Source of TypeVariables: U is unbounded, B is bounded by Point. */
    @SuppressWarnings("unused")
    static class Holder<U, B extends Point> {
        List<?> unboundedWildcard;
        List<? extends Point> boundedWildcard;
    }

    private static Type typeVar(int index) {
        return Holder.class.getTypeParameters()[index];
    }

    private static Type wildcardOf(String field) throws Exception {
        ParameterizedType pt = (ParameterizedType) Holder.class.getDeclaredField(field).getGenericType();
        return pt.getActualTypeArguments()[0];
    }

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

    private void enqueueResult(String resultJson) {
        server.enqueue(new MockResponse()
            .setBody("{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":" + resultJson + "}")
            .setHeader("Content-Type", "application/json"));
    }

    private String endpoint() {
        return server.url("/").toString();
    }

    private static final String THREE_TEXTS = """
        {"content": [
            {"type": "text", "text": "alpha"},
            {"type": "text", "text": "{\\"k\\": 1}"},
            {"type": "text", "text": "gamma"}
        ]}
        """;

    @SuppressWarnings("unchecked")
    private static void assertTexts(Object result, String... expected) {
        assertInstanceOf(List.class, result);
        List<Map<String, Object>> items = (List<Map<String, Object>>) result;
        assertEquals(expected.length, items.size());
        for (int i = 0; i < expected.length; i++) {
            assertEquals("text", items.get(i).get("type"));
            assertEquals(expected[i], items.get(i).get("text"));
        }
    }

    @Nested
    @DisplayName("several text blocks, no structuredContent")
    class MultiText {

        @Test
        @DisplayName("two blocks: both returned, in order (untyped)")
        void twoBlocksUntyped() {
            enqueueResult("""
                {"content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"}
                ]}
                """);

            Object result = client.callTool(endpoint(), "t", Map.of());

            assertTexts(result, "first", "second");
        }

        @Test
        @DisplayName("three blocks: all returned, in order, JSON text left unparsed")
        void threeBlocksUntyped() {
            enqueueResult(THREE_TEXTS);

            Object result = client.callTool(endpoint(), "t", Map.of());

            assertTexts(result, "alpha", "{\"k\": 1}", "gamma");
        }

        @Test
        @DisplayName("McpMeshTool<Object> target gets the same list")
        void objectTarget() {
            enqueueResult(THREE_TEXTS);

            Object result = client.callTool(endpoint(), "t", Map.of(), Object.class);

            assertTexts(result, "alpha", "{\"k\": 1}", "gamma");
        }

        @Test
        @DisplayName("List<Map<String, Object>> target gets the items")
        void listOfMapTarget() {
            enqueueResult(THREE_TEXTS);

            Type listType = new TypeReference<List<Map<String, Object>>>() {}.getType();
            List<Map<String, Object>> result = client.callTool(endpoint(), "t", Map.of(), listType);

            assertTexts(result, "alpha", "{\"k\": 1}", "gamma");
        }

        @Test
        @DisplayName("String target fails loudly instead of returning the first block")
        void stringTargetFails() {
            enqueueResult(THREE_TEXTS);

            MeshToolCallException e = assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint(), "t", Map.of(), String.class));
            assertTrue(e.getMessage().contains("3 text content blocks"), e.getMessage());
            assertTrue(e.getMessage().contains("java.lang.String"), e.getMessage());
        }

        @Test
        @DisplayName("record target fails loudly")
        void recordTargetFails() {
            enqueueResult("""
                {"content": [
                    {"type": "text", "text": "{\\"x\\": 1, \\"y\\": 2}"},
                    {"type": "text", "text": "{\\"x\\": 3, \\"y\\": 4}"}
                ]}
                """);

            MeshToolCallException e = assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint(), "t", Map.of(), Point.class));
            assertTrue(e.getMessage().contains("2 text content blocks"), e.getMessage());
        }

        @Test
        @DisplayName("List<String> target cannot hold content items and fails loudly")
        void listOfStringTargetFails() {
            enqueueResult(THREE_TEXTS);

            Type listType = new TypeReference<List<String>>() {}.getType();
            MeshToolCallException e = assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint(), "t", Map.of(), listType));
            assertTrue(e.getMessage().contains("3 text content blocks"), e.getMessage());
        }

        @Test
        @DisplayName("isError still reports the first block's text")
        void isErrorUsesFirstText() {
            enqueueResult("""
                {"isError": true, "content": [
                    {"type": "text", "text": "boom"},
                    {"type": "text", "text": "detail"}
                ]}
                """);

            MeshToolCallException e = assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint(), "t", Map.of()));
            assertTrue(e.getMessage().contains("boom"), e.getMessage());
        }
    }

    @Nested
    @DisplayName("single text block (unchanged)")
    class SingleText {

        @Test
        @DisplayName("plain text returns the string")
        void plainText() {
            enqueueResult("{\"content\": [{\"type\": \"text\", \"text\": \"hello\"}]}");

            Object result = client.callTool(endpoint(), "t", Map.of());

            assertEquals("hello", result);
        }

        @Test
        @DisplayName("String target returns the text")
        void stringTarget() {
            enqueueResult("{\"content\": [{\"type\": \"text\", \"text\": \"hello\"}]}");

            String result = client.callTool(endpoint(), "t", Map.of(), String.class);

            assertEquals("hello", result);
        }

        @Test
        @DisplayName("JSON text deserializes into a typed record")
        void jsonIntoRecord() {
            enqueueResult("{\"content\": [{\"type\": \"text\", \"text\": \"{\\\"x\\\": 1, \\\"y\\\": 2}\"}]}");

            Point result = client.callTool(endpoint(), "t", Map.of(), Point.class);

            assertEquals(new Point(1, 2), result);
        }

        @Test
        @DisplayName("JSON text parses dynamically when untyped")
        void jsonUntyped() {
            enqueueResult("{\"content\": [{\"type\": \"text\", \"text\": \"{\\\"x\\\": 1}\"}]}");

            Object result = client.callTool(endpoint(), "t", Map.of());

            assertEquals(Map.of("x", 1), result);
        }
    }

    @Nested
    @DisplayName("collection, JsonNode, type-variable and void targets")
    class TargetShapes {

        @Test
        @DisplayName("ArrayList<Map<String, Object>> target gets the items")
        void arrayListTarget() {
            enqueueResult(THREE_TEXTS);

            Type t = new TypeReference<ArrayList<Map<String, Object>>>() {}.getType();
            Object result = client.callTool(endpoint(), "t", Map.of(), t);

            assertInstanceOf(ArrayList.class, result);
            assertTexts(result, "alpha", "{\"k\": 1}", "gamma");
        }

        @Test
        @DisplayName("raw LinkedList target gets the items")
        void linkedListTarget() {
            enqueueResult(THREE_TEXTS);

            Object result = client.callTool(endpoint(), "t", Map.of(), LinkedList.class);

            assertInstanceOf(LinkedList.class, result);
            assertTexts(result, "alpha", "{\"k\": 1}", "gamma");
        }

        @Test
        @DisplayName("List<JsonNode> target gets the items")
        void listOfJsonNodeTarget() {
            enqueueResult(THREE_TEXTS);

            Type t = new TypeReference<List<JsonNode>>() {}.getType();
            List<JsonNode> result = client.callTool(endpoint(), "t", Map.of(), t);

            assertEquals(3, result.size());
            assertEquals("gamma", result.get(2).get("text").asString());
        }

        @Test
        @DisplayName("JsonNode target gets a JSON array of the items")
        void jsonNodeTarget() {
            enqueueResult(THREE_TEXTS);

            JsonNode result = client.callTool(endpoint(), "t", Map.of(), JsonNode.class);

            assertTrue(result.isArray());
            assertEquals(3, result.size());
            assertEquals("alpha", result.get(0).get("text").asString());
        }

        @Test
        @DisplayName("Set target fails loudly (a set could collapse equal blocks)")
        void setTargetFails() {
            enqueueResult(THREE_TEXTS);

            Type t = new TypeReference<Set<Map<String, Object>>>() {}.getType();
            assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint(), "t", Map.of(), t));
        }

        @Test
        @DisplayName("unbounded type variable resolves to Object and gets the list")
        void unboundedTypeVariable() {
            enqueueResult(THREE_TEXTS);

            Object result = client.callTool(endpoint(), "t", Map.of(), typeVar(0));

            assertTexts(result, "alpha", "{\"k\": 1}", "gamma");
        }

        @Test
        @DisplayName("bounded type variable resolves to its bound and fails loudly")
        void boundedTypeVariableFails() {
            enqueueResult(THREE_TEXTS);

            MeshToolCallException e = assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint(), "t", Map.of(), typeVar(1)));
            assertTrue(e.getMessage().contains("3 text content blocks"), e.getMessage());
        }

        @Test
        @DisplayName("List<?> target gets the items")
        void unboundedWildcardList() throws Exception {
            enqueueResult(THREE_TEXTS);

            Type t = Holder.class.getDeclaredField("unboundedWildcard").getGenericType();
            Object result = client.callTool(endpoint(), "t", Map.of(), t);

            assertTexts(result, "alpha", "{\"k\": 1}", "gamma");
        }

        @Test
        @DisplayName("List<? extends Point> target fails loudly")
        void boundedWildcardListFails() throws Exception {
            enqueueResult(THREE_TEXTS);

            Type t = Holder.class.getDeclaredField("boundedWildcard").getGenericType();
            assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint(), "t", Map.of(), t));
        }

        @Test
        @DisplayName("bare wildcard resolves like its bound")
        void bareWildcard() throws Exception {
            enqueueResult(THREE_TEXTS);
            Object result = client.callTool(endpoint(), "t", Map.of(), wildcardOf("unboundedWildcard"));
            assertTexts(result, "alpha", "{\"k\": 1}", "gamma");

            enqueueResult(THREE_TEXTS);
            assertThrows(MeshToolCallException.class,
                () -> client.callTool(endpoint(), "t", Map.of(), wildcardOf("boundedWildcard")));
        }

        @Test
        @DisplayName("void and Void targets return null")
        void voidTargets() {
            enqueueResult(THREE_TEXTS);
            assertNull(client.callTool(endpoint(), "t", Map.of(), void.class));

            enqueueResult(THREE_TEXTS);
            assertNull(client.callTool(endpoint(), "t", Map.of(), Void.class));
        }

        @Test
        @DisplayName("items with no type field are returned raw, all of them")
        @SuppressWarnings("unchecked")
        void itemsWithoutType() {
            enqueueResult("""
                {"content": [
                    {"text": "one"},
                    {"text": "two"}
                ]}
                """);

            Object result = client.callTool(endpoint(), "t", Map.of());

            assertInstanceOf(List.class, result);
            List<Map<String, Object>> items = (List<Map<String, Object>>) result;
            assertEquals(List.of(Map.of("text", "one"), Map.of("text", "two")), items);
        }
    }

    @Nested
    @DisplayName("lenient (production-like) mapper")
    class LenientMapper {

        private McpHttpClient lenient;

        @BeforeEach
        void setUpLenient() {
            // Spring Boot's ObjectMapper ignores unknown properties; without the
            // element-type check each content item would become a null-filled
            // Employee(null, null) without any error.
            lenient = new McpHttpClient(JsonMapper.builder()
                .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .build());
        }

        @AfterEach
        void tearDownLenient() {
            lenient.close();
        }

        @Test
        @DisplayName("List<Record> target fails loudly instead of null-filled records")
        void listOfRecordFails() {
            enqueueResult(THREE_TEXTS);

            Type t = new TypeReference<List<Employee>>() {}.getType();
            MeshToolCallException e = assertThrows(MeshToolCallException.class,
                () -> lenient.callTool(endpoint(), "t", Map.of(), t));
            assertTrue(e.getMessage().contains("3 text content blocks"), e.getMessage());
        }

        @Test
        @DisplayName("record target fails loudly")
        void recordFails() {
            enqueueResult(THREE_TEXTS);

            assertThrows(MeshToolCallException.class,
                () -> lenient.callTool(endpoint(), "t", Map.of(), Employee.class));
        }
    }

    @Nested
    @DisplayName("structuredContent + several text blocks")
    class WithStructuredContent {

        private static final String WRAPPED = """
            {
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "text", "text": "b"}
                ],
                "structuredContent": {"result": ["a", "b"]},
                "_meta": {"fastmcp": {"wrap_result": true}}
            }
            """;

        private static final String UNWRAPPED_OBJECT = """
            {
                "content": [
                    {"type": "text", "text": "x is 5"},
                    {"type": "text", "text": "y is 6"}
                ],
                "structuredContent": {"x": 5, "y": 6}
            }
            """;

        @Test
        @DisplayName("untyped target gets every block (content wins)")
        void untypedGetsBlocks() {
            enqueueResult(WRAPPED);

            Object result = client.callTool(endpoint(), "t", Map.of());

            assertTexts(result, "a", "b");
        }

        @Test
        @DisplayName("Object target gets every block, no wrap marker")
        void objectGetsBlocksNoMarker() {
            enqueueResult(UNWRAPPED_OBJECT);

            Object result = client.callTool(endpoint(), "t", Map.of(), Object.class);

            assertTexts(result, "x is 5", "y is 6");
        }

        @Test
        @DisplayName("List<Map> target gets every block")
        void listOfMapGetsBlocks() {
            enqueueResult(WRAPPED);

            Type t = new TypeReference<List<Map<String, Object>>>() {}.getType();
            Object result = client.callTool(endpoint(), "t", Map.of(), t);

            assertTexts(result, "a", "b");
        }

        @Test
        @DisplayName("List<String> target deserializes from wrapped structuredContent")
        void listOfStringFromStructuredContent() {
            enqueueResult(WRAPPED);

            Type t = new TypeReference<List<String>>() {}.getType();
            List<String> result = client.callTool(endpoint(), "t", Map.of(), t);

            assertEquals(List.of("a", "b"), result);
        }

        @Test
        @DisplayName("record target deserializes from structuredContent without a wrap marker")
        void recordFromStructuredContentNoMarker() {
            enqueueResult(UNWRAPPED_OBJECT);

            Point result = client.callTool(endpoint(), "t", Map.of(), Point.class);

            assertEquals(new Point(5, 6), result);
        }

        @Test
        @DisplayName("Map target deserializes from structuredContent without a wrap marker")
        void mapFromStructuredContentNoMarker() {
            enqueueResult(UNWRAPPED_OBJECT);

            Type t = new TypeReference<Map<String, Object>>() {}.getType();
            Map<String, Object> result = client.callTool(endpoint(), "t", Map.of(), t);

            assertEquals(Map.of("x", 5, "y", 6), result);
        }

        @Test
        @DisplayName("String target deserializes from wrapped structuredContent")
        void stringFromStructuredContent() {
            enqueueResult("""
                {
                    "content": [
                        {"type": "text", "text": "a"},
                        {"type": "text", "text": "b"}
                    ],
                    "structuredContent": {"result": "a and b"},
                    "_meta": {"fastmcp": {"wrap_result": true}}
                }
                """);

            String result = client.callTool(endpoint(), "t", Map.of(), String.class);

            assertEquals("a and b", result);
        }
    }

    @Nested
    @DisplayName("mixed content (unchanged)")
    class Mixed {

        @Test
        @DisplayName("text + image returns the raw item list")
        @SuppressWarnings("unchecked")
        void textAndImage() {
            enqueueResult("""
                {"content": [
                    {"type": "text", "text": "caption"},
                    {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"}
                ]}
                """);

            Object result = client.callTool(endpoint(), "t", Map.of());

            assertInstanceOf(List.class, result);
            List<Map<String, Object>> items = (List<Map<String, Object>>) result;
            assertEquals(2, items.size());
            assertEquals("caption", items.get(0).get("text"));
            assertEquals("image", items.get(1).get("type"));
            assertEquals("iVBORw0KGgo=", items.get(1).get("data"));
        }

        @Test
        @DisplayName("text + image ignores structuredContent (pins current behaviour)")
        @SuppressWarnings("unchecked")
        void textAndImageIgnoresStructuredContent() {
            enqueueResult("""
                {
                    "content": [
                        {"type": "text", "text": "caption"},
                        {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"}
                    ],
                    "structuredContent": {"x": 1, "y": 2}
                }
                """);

            Object result = client.callTool(endpoint(), "t", Map.of(), Point.class);

            assertInstanceOf(List.class, result);
            assertEquals(2, ((List<Map<String, Object>>) result).size());
        }
    }
}
