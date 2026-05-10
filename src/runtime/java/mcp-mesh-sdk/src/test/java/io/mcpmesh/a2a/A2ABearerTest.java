package io.mcpmesh.a2a;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link A2ABearer} covering both literal and env-var
 * resolution paths and the no-credential failure mode.
 */
class A2ABearerTest {

    @Test
    void of_buildsHeaderFromLiteralToken() {
        A2ABearer bearer = A2ABearer.of("abc123");
        assertEquals("Bearer abc123", bearer.authorizationHeader());
    }

    @Test
    void of_rejectsBlankLiteral() {
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.of(""));
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.of(null));
    }

    @Test
    void fromEnv_rejectsBlankName() {
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.fromEnv(""));
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.fromEnv(null));
    }

    @Test
    void fromEnv_unsetEnvVar_throwsAuthException() {
        // System.getenv("DEFINITELY_UNSET_A2A_BEARER_TEST_VAR") is null
        // in any sane test environment.
        A2ABearer bearer = A2ABearer.fromEnv("DEFINITELY_UNSET_A2A_BEARER_TEST_VAR");
        A2AAuthException thrown = assertThrows(A2AAuthException.class, bearer::authorizationHeader);
        assertTrue(thrown.getMessage().contains("DEFINITELY_UNSET_A2A_BEARER_TEST_VAR"),
            "exception message should name the missing env var: " + thrown.getMessage());
    }
}
