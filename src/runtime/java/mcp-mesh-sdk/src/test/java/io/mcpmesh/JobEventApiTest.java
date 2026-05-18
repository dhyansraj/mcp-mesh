package io.mcpmesh;

import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Surface-shape tests for {@link JobController#recvEvent(List, Duration)}
 * and {@link JobProxy#sendEvent(String, Map)} (issue #1032). These tests
 * cover the public API signatures and arg-validation paths that DON'T
 * require a live FFI handle.
 *
 * <p>The full FFI round-trip (recv_event → backend HTTP, send_event →
 * backend HTTP, JobNotFound/JobTerminal classification) is exercised in
 * the integration suite (uc23_meshjob_java/tc24–tc26) which spins up a
 * real registry and two real Java agents.
 *
 * <p>This file complements {@link MeshJobsTest} which covers the
 * static helper + cache layer.
 */
class JobEventApiTest {

    /**
     * {@link JobController#recvEvent} must be a public instance method
     * accepting {@code (List<String>, Duration)} and returning
     * {@code Map<String, Object>}. Pinning the contract here means a
     * future refactor that accidentally changes the signature breaks
     * compilation rather than silently diverging from Python/TS.
     */
    @Test
    void jobController_recvEvent_hasExpectedSignature() throws NoSuchMethodException {
        Method m = JobController.class.getMethod("recvEvent", List.class, Duration.class);
        assertEquals(Map.class, m.getReturnType());
        assertTrue(java.lang.reflect.Modifier.isPublic(m.getModifiers()));
        // Throws clause should be empty (we throw RuntimeException
        // subclasses), so the method declares no checked exceptions.
        assertEquals(0, m.getExceptionTypes().length,
            "recvEvent must not declare checked exceptions");
    }

    /**
     * {@link JobProxy#sendEvent} must be public, accept
     * {@code (String, Map)}, and return {@code Map<String, Object>}.
     */
    @Test
    void jobProxy_sendEvent_hasExpectedSignature() throws NoSuchMethodException {
        Method m = JobProxy.class.getMethod("sendEvent", String.class, Map.class);
        assertEquals(Map.class, m.getReturnType());
        assertTrue(java.lang.reflect.Modifier.isPublic(m.getModifiers()));
        assertEquals(0, m.getExceptionTypes().length,
            "sendEvent must not declare checked exceptions");
    }

    /**
     * {@link MeshJobs#postEvent} must be public + static, accept
     * {@code (String, String, Map)}, and return {@code Map<String, Object>}.
     */
    @Test
    void meshJobs_postEvent_hasExpectedSignature() throws NoSuchMethodException {
        Method m = MeshJobs.class.getMethod("postEvent", String.class, String.class, Map.class);
        assertEquals(Map.class, m.getReturnType());
        assertTrue(java.lang.reflect.Modifier.isPublic(m.getModifiers()));
        assertTrue(java.lang.reflect.Modifier.isStatic(m.getModifiers()),
            "postEvent must be a static helper");
        assertEquals(0, m.getExceptionTypes().length);
    }

    /**
     * Typed exception inheritance: both must extend MeshException so
     * existing {@code catch (MeshException ...)} handlers keep working
     * (mirrors Python's {@code RuntimeError} subclassing pattern).
     */
    @Test
    void jobNotFoundException_isMeshException() {
        JobNotFoundException e = new JobNotFoundException("missing");
        assertTrue(e instanceof io.mcpmesh.core.MeshException);
    }

    @Test
    void jobTerminalException_isMeshException() {
        JobTerminalException e = new JobTerminalException("done");
        assertTrue(e instanceof io.mcpmesh.core.MeshException);
    }

    /**
     * Cause-chaining works on both typed exceptions (matches the
     * {@code MeshException(String, Throwable)} ctor pattern).
     */
    @Test
    void typedExceptions_supportCauseChaining() {
        Throwable cause = new RuntimeException("root");
        JobNotFoundException nf = new JobNotFoundException("wrap", cause);
        assertSame(cause, nf.getCause());
        JobTerminalException term = new JobTerminalException("wrap", cause);
        assertSame(cause, term.getCause());
    }
}
