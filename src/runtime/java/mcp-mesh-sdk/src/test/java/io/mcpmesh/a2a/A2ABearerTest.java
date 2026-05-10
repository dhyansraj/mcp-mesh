package io.mcpmesh.a2a;

import org.junit.jupiter.api.Test;

import java.util.UUID;

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
    void of_whitespaceToken_throwsIllegalArgumentException() {
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.of("   "));
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.of("\t\n"));
    }

    @Test
    void fromEnv_rejectsBlankName() {
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.fromEnv(""));
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.fromEnv(null));
    }

    @Test
    void fromEnv_whitespaceName_throwsIllegalArgumentException() {
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.fromEnv("   "));
        assertThrows(IllegalArgumentException.class, () -> A2ABearer.fromEnv("\t\n"));
    }

    @Test
    void fromEnv_unsetEnvVar_throwsAuthException() {
        // Generate a unique env var name per invocation so the test is
        // immune to a stray export of the historical fixed name.
        String uniqueVar = "DEFINITELY_UNSET_A2A_BEARER_TEST_VAR_"
            + UUID.randomUUID().toString().replace("-", "");
        A2ABearer bearer = A2ABearer.fromEnv(uniqueVar);
        A2AAuthException thrown = assertThrows(A2AAuthException.class, bearer::authorizationHeader);
        assertTrue(thrown.getMessage().contains(uniqueVar),
            "exception message should name the missing env var: " + thrown.getMessage());
    }
}
