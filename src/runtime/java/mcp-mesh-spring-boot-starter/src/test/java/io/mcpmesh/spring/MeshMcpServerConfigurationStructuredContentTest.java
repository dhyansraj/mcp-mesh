package io.mcpmesh.spring;

import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Provider-side unit tests for {@code tools/call} {@code structuredContent}
 * emission parity (issue #1282), mirroring the Python provider's #1250/#1251
 * empty-return contract.
 *
 * <p>The Java provider now populates {@code structuredContent} (and the
 * {@code fastmcp.wrap_result} marker in {@code _meta}) for object-shaped and
 * non-object returns using the SAME rules FastMCP applies:
 * <ul>
 *   <li>object-shaped (Map/POJO) → {@code structuredContent} = the object, no
 *       marker;</li>
 *   <li>non-object (list, scalar, string, null) → {@code {"result": X}} + the
 *       wrap marker.</li>
 * </ul>
 *
 * <p>Critically, {@code content[0].text} is UNCHANGED in every case — mesh
 * consumers recover text-first, so the cross-runtime round-trip is preserved
 * and {@code structuredContent} is purely additive.
 */
@DisplayName("MeshMcpServerConfiguration structuredContent emission (#1282)")
class MeshMcpServerConfigurationStructuredContentTest {

    private static final Map<String, Object> WRAP_MARKER =
        Map.of("fastmcp", Map.of("wrap_result", true));

    /** Minimal handler that returns a fixed value from {@code invoke}. */
    private static final class FixedHandler implements McpToolHandler {
        private final Object value;

        FixedHandler(Object value) {
            this.value = value;
        }

        @Override public String getFuncId() { return "test.fixed"; }
        @Override public String getCapability() { return "fixed"; }
        @Override public String getMethodName() { return "fixed"; }
        @Override public String getDescription() { return "fixed"; }
        @Override public Map<String, Object> getInputSchema() { return Map.of("type", "object"); }
        @Override public Object invoke(Map<String, Object> mcpArgs) { return value; }
        @Override public int getDependencyCount() { return 0; }
        @Override public int getLlmAgentCount() { return 0; }
    }

    private CallToolResult call(Object returnValue) throws Exception {
        MeshMcpServerConfiguration config = new MeshMcpServerConfiguration();
        Method m = MeshMcpServerConfiguration.class.getDeclaredMethod(
            "handleToolCall", McpToolHandler.class, Map.class);
        m.setAccessible(true);
        return (CallToolResult) m.invoke(config, new FixedHandler(returnValue), Map.of());
    }

    private String text(CallToolResult r) {
        assertEquals(1, r.content().size(), "expected exactly one content block");
        return ((TextContent) r.content().get(0)).text();
    }

    // ----- object-shaped returns: structuredContent = object, no marker -----

    @Test
    @DisplayName("Map return → structuredContent is the object, no wrap marker")
    void mapReturn() throws Exception {
        Map<String, Object> obj = new LinkedHashMap<>();
        obj.put("a", 1);
        obj.put("b", "two");
        CallToolResult r = call(obj);

        assertEquals("{\"a\":1,\"b\":\"two\"}", text(r));
        assertEquals(obj, r.structuredContent());
        assertNull(r.meta(), "object-shaped return must not carry the wrap marker");
        assertFalse(r.isError());
    }

    @Test
    @DisplayName("Empty map {} → structuredContent {}, no marker (#1251)")
    void emptyMapReturn() throws Exception {
        CallToolResult r = call(new LinkedHashMap<String, Object>());

        assertEquals("{}", text(r));
        assertEquals(Map.of(), r.structuredContent());
        assertNull(r.meta());
    }

    // ----- non-object returns: {"result": X} + wrap marker -----

    @Test
    @DisplayName("Empty list [] → structuredContent {\"result\": []} + marker (#1250)")
    void emptyListReturn() throws Exception {
        CallToolResult r = call(new ArrayList<Integer>());

        assertEquals("[]", text(r));
        Map<String, Object> expected = new LinkedHashMap<>();
        expected.put("result", List.of());
        assertEquals(expected, r.structuredContent());
        assertEquals(WRAP_MARKER, r.meta());
    }

    @Test
    @DisplayName("Non-empty list → structuredContent {\"result\": [...]} + marker")
    void nonEmptyListReturn() throws Exception {
        CallToolResult r = call(Arrays.asList(1, 2, 3));

        assertEquals("[1,2,3]", text(r));
        Map<String, Object> expected = new LinkedHashMap<>();
        expected.put("result", Arrays.asList(1, 2, 3));
        assertEquals(expected, r.structuredContent());
        assertEquals(WRAP_MARKER, r.meta());
    }

    @Test
    @DisplayName("Empty string \"\" → structuredContent {\"result\": \"\"} + marker (#1251)")
    void emptyStringReturn() throws Exception {
        CallToolResult r = call("");

        assertEquals("", text(r));
        Map<String, Object> expected = new LinkedHashMap<>();
        expected.put("result", "");
        assertEquals(expected, r.structuredContent());
        assertEquals(WRAP_MARKER, r.meta());
    }

    @Test
    @DisplayName("Plain string → text is the raw string, structuredContent wraps it")
    void plainStringReturn() throws Exception {
        CallToolResult r = call("hello");

        assertEquals("hello", text(r));
        Map<String, Object> expected = new LinkedHashMap<>();
        expected.put("result", "hello");
        assertEquals(expected, r.structuredContent());
        assertEquals(WRAP_MARKER, r.meta());
    }

    @Test
    @DisplayName("Scalar number → structuredContent {\"result\": 42} + marker")
    void scalarNumberReturn() throws Exception {
        CallToolResult r = call(42);

        assertEquals("42", text(r));
        Map<String, Object> expected = new LinkedHashMap<>();
        expected.put("result", 42);
        assertEquals(expected, r.structuredContent());
        assertEquals(WRAP_MARKER, r.meta());
    }

    @Test
    @DisplayName("Boolean → structuredContent {\"result\": true} + marker")
    void scalarBooleanReturn() throws Exception {
        CallToolResult r = call(true);

        assertEquals("true", text(r));
        Map<String, Object> expected = new LinkedHashMap<>();
        expected.put("result", true);
        assertEquals(expected, r.structuredContent());
        assertEquals(WRAP_MARKER, r.meta());
    }

    @Test
    @DisplayName("null → text is \"null\", structuredContent {\"result\": null} + marker")
    void nullReturn() throws Exception {
        CallToolResult r = call(null);

        assertEquals("null", text(r));
        Map<String, Object> expected = new LinkedHashMap<>();
        expected.put("result", null);
        assertEquals(expected, r.structuredContent());
        assertEquals(WRAP_MARKER, r.meta());
    }

    // ----- POJO is object-shaped -----

    public static final class Point {
        public int x;
        public int y;
        public Point(int x, int y) { this.x = x; this.y = y; }
    }

    @Test
    @DisplayName("POJO return → structuredContent is the object map, no marker")
    void pojoReturn() throws Exception {
        CallToolResult r = call(new Point(3, 4));

        assertEquals("{\"x\":3,\"y\":4}", text(r));
        Map<String, Object> expected = new LinkedHashMap<>();
        expected.put("x", 3);
        expected.put("y", 4);
        assertEquals(expected, r.structuredContent());
        assertNull(r.meta());
    }

    // ----- text block is never mutated: the #1250/#1251 round-trip anchor -----

    @Test
    @DisplayName("content[0].text is unchanged across every return shape")
    void textBlockUnchanged() throws Exception {
        assertEquals("[]", text(call(new ArrayList<>())));
        assertEquals("{}", text(call(new LinkedHashMap<>())));
        assertEquals("", text(call("")));
        assertEquals("null", text(call(null)));
        assertEquals("{\"a\":1}", text(call(Map.of("a", 1))));
    }
}
