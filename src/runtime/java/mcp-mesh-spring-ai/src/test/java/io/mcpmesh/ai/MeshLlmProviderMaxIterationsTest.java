package io.mcpmesh.ai;

import io.mcpmesh.MeshLlmDefaults;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1356: the provider-managed agentic loop must honour the consumer's
 * forwarded {@code model_params.max_iterations} instead of a hardcoded 10.
 *
 * <p>Contract mirrors the TypeScript reference ({@code sanitizeMaxIterations} /
 * {@code resolveMaxIterations} in {@code llm-provider.ts}) and the Python
 * helpers in {@code mesh/helpers.py}. The helpers are pure w.r.t. the
 * environment (env value is a parameter), same style as
 * {@code MeshLlmRegistry.resolveMaxIterations}.
 */
@DisplayName("MeshLlmProviderProcessor — max_iterations resolution (#1356)")
class MeshLlmProviderMaxIterationsTest {

    // ---------------------------------------------------------------- sanitize

    @Test
    @DisplayName("sanitize: positive integers pass through (Number and String)")
    void sanitizeValid() {
        assertEquals(3, MeshLlmProviderProcessor.sanitizeMaxIterations(3));
        assertEquals(7, MeshLlmProviderProcessor.sanitizeMaxIterations("7"));
        assertEquals(1, MeshLlmProviderProcessor.sanitizeMaxIterations(1L));
        assertEquals(42, MeshLlmProviderProcessor.sanitizeMaxIterations(" 42 "));
    }

    @Test
    @DisplayName("sanitize: fractional values are floored BEFORE the >0 check")
    void sanitizeFractional() {
        assertEquals(2, MeshLlmProviderProcessor.sanitizeMaxIterations(2.9));
        assertEquals(2, MeshLlmProviderProcessor.sanitizeMaxIterations("2.9"));
        // 0.5 floors to 0 → rejected, NOT a zero cap
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations(0.5));
    }

    @Test
    @DisplayName("sanitize: zero, negative, NaN, infinite, non-numeric and null are invalid")
    void sanitizeInvalid() {
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations(0));
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations(-1));
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations("0"));
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations("-4"));
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations(Double.NaN));
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations(Double.POSITIVE_INFINITY));
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations("abc"));
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations(""));
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations(null));
        assertNull(MeshLlmProviderProcessor.sanitizeMaxIterations(Map.of()));
    }

    // ----------------------------------------------------------------- resolve

    @Test
    @DisplayName("resolve: a forwarded value wins over the provider env")
    void forwardedValueWins() {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("max_iterations", 3);
        assertEquals(3, MeshLlmProviderProcessor.extractMaxIterations(params, "8"));
    }

    @Test
    @DisplayName("resolve: a PRESENT but invalid value falls back to 10, NOT to env")
    void invalidExplicitFallsBackToDefaultNotEnv() {
        for (Object bad : new Object[] {0, -3, "abc", null, Double.NaN}) {
            Map<String, Object> params = new HashMap<>();
            params.put("max_iterations", bad);
            assertEquals(MeshLlmDefaults.MAX_ITERATIONS,
                MeshLlmProviderProcessor.extractMaxIterations(params, "8"),
                "invalid explicit value " + bad + " must resolve to the default");
        }
    }

    @Test
    @DisplayName("resolve: absent key consults MESH_LLM_MAX_ITERATIONS")
    void absentUsesEnv() {
        assertEquals(8, MeshLlmProviderProcessor.extractMaxIterations(new LinkedHashMap<>(), "8"));
        assertEquals(8, MeshLlmProviderProcessor.extractMaxIterations(null, "8"));
    }

    @Test
    @DisplayName("resolve: absent key + missing/invalid env → default 10")
    void absentWithoutEnvUsesDefault() {
        assertEquals(MeshLlmDefaults.MAX_ITERATIONS,
            MeshLlmProviderProcessor.extractMaxIterations(new LinkedHashMap<>(), null));
        assertEquals(MeshLlmDefaults.MAX_ITERATIONS,
            MeshLlmProviderProcessor.extractMaxIterations(new LinkedHashMap<>(), "not-a-number"));
        assertEquals(MeshLlmDefaults.MAX_ITERATIONS,
            MeshLlmProviderProcessor.extractMaxIterations(new LinkedHashMap<>(), "0"));
    }

    // ------------------------------------------------------------------ strip

    @Test
    @DisplayName("the key is stripped from model_params so it never reaches the vendor API")
    void keyIsStripped() {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("max_iterations", 4);
        params.put("temperature", 0.1);

        MeshLlmProviderProcessor.extractMaxIterations(params, null);

        assertFalse(params.containsKey("max_iterations"));
        assertEquals(0.1, params.get("temperature"));
    }

    @Test
    @DisplayName("an invalid forwarded value is stripped too")
    void invalidKeyIsStripped() {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("max_iterations", "abc");

        assertEquals(MeshLlmDefaults.MAX_ITERATIONS,
            MeshLlmProviderProcessor.extractMaxIterations(params, null));
        assertFalse(params.containsKey("max_iterations"));
    }
}
