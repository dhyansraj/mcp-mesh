package io.mcpmesh.spring;

import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the cancel HTTP route handler. Covers:
 * <ul>
 *   <li>Returns the {@code {"cancelled": ..., "jobId": ...}} envelope</li>
 *   <li>Returns {@code cancelled=false} for an unknown jobId (no token in
 *       the cancel registry — the registry sweep is the backstop).</li>
 * </ul>
 *
 * <p>End-to-end behavior (cancel signal → in-flight handler abort) is
 * exercised in the integration suite which spawns a real producer.
 */
class JobCancelControllerTest {

    @Test
    void cancel_returnsFalseForUnknownJobId() {
        JobCancelController controller = new JobCancelController();
        // Random UUID — no JobController has bound a token for this id.
        String jobId = UUID.randomUUID().toString();
        Map<String, Object> body = controller.cancelJob(jobId);

        assertEquals(jobId, body.get("jobId"));
        assertEquals(Boolean.FALSE, body.get("cancelled"),
            "no active job → cancelled=false (registry will still mark cancelled)");
    }

    @Test
    void cancel_responseShape_includesBothKeys() {
        JobCancelController controller = new JobCancelController();
        Map<String, Object> body = controller.cancelJob("some-id");
        assertTrue(body.containsKey("cancelled"));
        assertTrue(body.containsKey("jobId"));
        assertEquals(2, body.size(), "response envelope is exactly {cancelled, jobId}");
    }
}
