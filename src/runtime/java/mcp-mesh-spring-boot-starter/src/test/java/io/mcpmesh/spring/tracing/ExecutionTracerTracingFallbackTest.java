package io.mcpmesh.spring.tracing;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

@DisplayName("ExecutionTracer tracing-enabled fallback: blank env means unset (issue #1619)")
class ExecutionTracerTracingFallbackTest {

    @Test
    @DisplayName("blank env falls back to the system property")
    void blankEnvFallsBackToProperty() {
        assertTrue(ExecutionTracer.tracingEnabledFallback("", "true"));
        assertTrue(ExecutionTracer.tracingEnabledFallback("   ", "1"));
        assertFalse(ExecutionTracer.tracingEnabledFallback("", "false"));
    }

    @Test
    @DisplayName("neither set means disabled")
    void neitherSetIsDisabled() {
        assertFalse(ExecutionTracer.tracingEnabledFallback(null, null));
        assertFalse(ExecutionTracer.tracingEnabledFallback("", null));
    }

    @Test
    @DisplayName("a set env value wins over the system property")
    void envWins() {
        assertTrue(ExecutionTracer.tracingEnabledFallback("true", "false"));
        assertTrue(ExecutionTracer.tracingEnabledFallback(" TRUE ", null));
        assertFalse(ExecutionTracer.tracingEnabledFallback("false", "true"));
        assertFalse(ExecutionTracer.tracingEnabledFallback("off", "true"));
    }
}
