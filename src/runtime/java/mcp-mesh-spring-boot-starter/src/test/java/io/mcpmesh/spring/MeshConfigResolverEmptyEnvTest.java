package io.mcpmesh.spring;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

@DisplayName("MeshConfigResolver log level / debug: blank env means unset (issue #1619)")
class MeshConfigResolverEmptyEnvTest {

    @Test
    @DisplayName("log level: blank env falls back to the system property, then 'info'")
    void logLevelBlankEnvFallsThrough() {
        assertEquals("debug", MeshConfigResolver.logLevel("", "debug"));
        assertEquals("debug", MeshConfigResolver.logLevel("   ", "debug"));
        assertEquals("info", MeshConfigResolver.logLevel("", null));
        assertEquals("info", MeshConfigResolver.logLevel("", "  "));
        assertEquals("info", MeshConfigResolver.logLevel(null, null));
    }

    @Test
    @DisplayName("log level: a set env value wins")
    void logLevelEnvWins() {
        assertEquals("warn", MeshConfigResolver.logLevel("warn", "debug"));
        assertEquals("warn", MeshConfigResolver.logLevel(" warn ", null));
    }

    @Test
    @DisplayName("debug: blank env falls back to the system property, then off")
    void debugBlankEnvFallsThrough() {
        assertTrue(MeshConfigResolver.isDebugEnabled("", "true"));
        assertTrue(MeshConfigResolver.isDebugEnabled("  ", "TRUE"));
        assertFalse(MeshConfigResolver.isDebugEnabled("", null));
        assertFalse(MeshConfigResolver.isDebugEnabled(null, null));
    }

    @Test
    @DisplayName("debug: a set env value wins")
    void debugEnvWins() {
        assertFalse(MeshConfigResolver.isDebugEnabled("false", "true"));
        assertTrue(MeshConfigResolver.isDebugEnabled("true", "false"));
    }

    @Test
    @DisplayName("firstNonBlank skips null and blank values and trims the winner")
    void firstNonBlank() {
        assertEquals("x", MeshConfigResolver.firstNonBlank(null, "", "  ", " x "));
        assertNull(MeshConfigResolver.firstNonBlank(null, "", "  "));
    }
}
