package io.mcpmesh.spring;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

import java.lang.reflect.Field;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests that the response-model deserialization path in {@link MeshLlmAgentProxy}
 * tolerates the loosely-shaped JSON that {@code output_mode=hint} can produce —
 * specifically the documented single-value-as-array drift where the LLM returns a
 * scalar for a schema field declared as a list (issue #1142).
 *
 * <p>Under hint mode the provider embeds the schema in the prompt but does not
 * enforce it natively, so a {@code List<String>} field can come back as a bare
 * string ({@code "insights": "x"} instead of {@code ["x"]}). Before the fix this
 * threw Jackson {@code MismatchedInputException}. The fix enables
 * {@code ACCEPT_SINGLE_VALUE_AS_ARRAY} on a dedicated lenient mapper scoped to the
 * {@code generate(Class)} response-model path only.
 *
 * <p>The test reflects out the private static {@code responseModelMapper} so it
 * exercises the EXACT mapper the proxy uses, not a hand-rolled copy.
 */
class MeshLlmAgentProxyResponseModelLenientTest {

    /** Mirrors a typical @MeshLlm response model with a list field. */
    record Analysis(String summary, List<String> insights) {}

    private static ObjectMapper responseModelMapper() throws Exception {
        Field f = MeshLlmAgentProxy.class.getDeclaredField("responseModelMapper");
        f.setAccessible(true);
        return (ObjectMapper) f.get(null);
    }

    @Test
    @DisplayName("scalar string for a List<String> field deserializes to a single-element list (hint-mode drift)")
    void scalarCoercedToSingleElementList() throws Exception {
        ObjectMapper mapper = responseModelMapper();
        String json = "{\"summary\":\"ok\",\"insights\":\"only-one\"}";

        Analysis result = mapper.readValue(json, Analysis.class);

        assertEquals("ok", result.summary());
        assertEquals(List.of("only-one"), result.insights());
    }

    @Test
    @DisplayName("well-shaped array still deserializes correctly (no-op for strict output)")
    void normalArrayStillWorks() throws Exception {
        ObjectMapper mapper = responseModelMapper();
        String json = "{\"summary\":\"ok\",\"insights\":[\"a\",\"b\"]}";

        Analysis result = mapper.readValue(json, Analysis.class);

        assertEquals("ok", result.summary());
        assertEquals(List.of("a", "b"), result.insights());
    }
}
