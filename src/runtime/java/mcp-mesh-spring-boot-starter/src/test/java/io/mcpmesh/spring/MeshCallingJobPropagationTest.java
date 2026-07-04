package io.mcpmesh.spring;

import io.mcpmesh.JobContext;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.spring.tracing.TraceContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Issue #1263 — calling-job identity propagation.
 *
 * <p>The calling job's identity rides a DEDICATED carrier
 * ({@code x-mesh-calling-job-id} / {@code x-mesh-calling-claim-epoch}), kept
 * strictly separate from the push-dispatch protocol pair
 * ({@code x-mesh-job-id} / {@code x-mesh-claim-epoch}).
 *
 * <p>Seams covered below the FFI boundary:
 * <ul>
 *   <li><b>Outbound</b>: {@link TraceContext#callingJobHeaders()} /
 *       {@link TraceContext#applyCallingJobIdentity(Map)} derive + overlay the
 *       carrier pair from the active {@link JobContext} — what
 *       {@code McpHttpClient} applies to every downstream tool call.</li>
 *   <li><b>Provider-side</b>: {@link MeshCallContext#callingJob()} reads the
 *       carrier pair back off inbound propagated headers.</li>
 *   <li><b>BLOCKER regression</b>: the carrier pair must NEVER trigger
 *       push-mode job dispatch (that gate keys on {@code x-mesh-job-id}).</li>
 * </ul>
 */
class MeshCallingJobPropagationTest {

    @AfterEach
    void clearContext() {
        TraceContext.clearPropagatedHeaders();
    }

    // ---- Outbound seam: callingJobHeaders ----------------------------------

    @Test
    void callingJobHeaders_empty_whenNoJobContext() {
        assertTrue(TraceContext.callingJobHeaders().isEmpty(),
            "no active job → no identity headers (purely additive outside a job)");
    }

    @Test
    void callingJobHeaders_seedsBoth_whenEpochPresent() throws Exception {
        Map<String, String> seen = JobContext.withJob(
            new JobContext.Snapshot("job-42", 30L, 7L),
            TraceContext::callingJobHeaders);
        assertEquals("job-42", seen.get("x-mesh-calling-job-id"));
        assertEquals("7", seen.get("x-mesh-calling-claim-epoch"),
            "claim epoch must serialize as the plain generation number");
        // Must NOT seed the push-dispatch protocol pair.
        assertFalse(seen.containsKey("x-mesh-job-id"),
            "outbound seeding must never write the push-dispatch discriminator");
        assertFalse(seen.containsKey("x-mesh-claim-epoch"));
    }

    @Test
    void callingJobHeaders_seedsOnlyJobId_whenEpochNull() throws Exception {
        Map<String, String> seen = JobContext.withJob(
            new JobContext.Snapshot("job-99", 30L, null),
            TraceContext::callingJobHeaders);
        assertEquals("job-99", seen.get("x-mesh-calling-job-id"));
        assertFalse(seen.containsKey("x-mesh-calling-claim-epoch"),
            "null claim epoch → seed only x-mesh-calling-job-id");
    }

    // ---- Outbound overlay: applyCallingJobIdentity (replace-pair) -----------

    @Test
    void applyCallingJobIdentity_noOp_whenNoJobContext() {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("x-mesh-calling-job-id", "inherited");
        headers.put("x-mesh-calling-claim-epoch", "1");
        TraceContext.applyCallingJobIdentity(headers);
        // Outside a job context, an inherited calling-* pair propagates
        // transitively unchanged.
        assertEquals("inherited", headers.get("x-mesh-calling-job-id"));
        assertEquals("1", headers.get("x-mesh-calling-claim-epoch"));
    }

    @Test
    void applyCallingJobIdentity_replacesInheritedPairEntirely() throws Exception {
        // A stale foreign epoch must NOT ride along with the fresh id — the
        // active job's identity replaces the pair atomically (both or none).
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("x-mesh-calling-job-id", "stale-job");
        headers.put("x-mesh-calling-claim-epoch", "999");
        JobContext.withJob(new JobContext.Snapshot("fresh-job", 30L, null), () -> {
            TraceContext.applyCallingJobIdentity(headers);
            return null;
        });
        assertEquals("fresh-job", headers.get("x-mesh-calling-job-id"));
        assertFalse(headers.containsKey("x-mesh-calling-claim-epoch"),
            "a null fresh epoch must evict the stale inherited epoch, not keep it");
    }

    // ---- Provider-side seam: MeshCallContext.callingJob ---------------------

    @Test
    void callingJob_returnsNulls_whenNoHeaders() {
        MeshCallContext.CallingJob cj = MeshCallContext.callingJob();
        assertNull(cj.jobId());
        assertNull(cj.claimEpoch());
        assertFalse(cj.isPresent());
    }

    @Test
    void callingJob_readsBothHeaders() {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("x-mesh-calling-job-id", "job-7");
        headers.put("x-mesh-calling-claim-epoch", "3");
        TraceContext.setPropagatedHeaders(headers);

        MeshCallContext.CallingJob cj = MeshCallContext.callingJob();
        assertEquals("job-7", cj.jobId());
        assertEquals(3L, cj.claimEpoch());
        assertTrue(cj.isPresent());
    }

    @Test
    void callingJob_ignoresPushProtocolPair() {
        // A push-mode inbound call carries x-mesh-job-id / x-mesh-claim-epoch
        // for its OWN dispatch — those must not be misread as a calling job.
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("x-mesh-job-id", "dispatch-job");
        headers.put("x-mesh-claim-epoch", "5");
        TraceContext.setPropagatedHeaders(headers);

        MeshCallContext.CallingJob cj = MeshCallContext.callingJob();
        assertNull(cj.jobId(), "the push-dispatch pair must not surface as calling-job identity");
        assertNull(cj.claimEpoch());
    }

    @Test
    void callingJob_jobIdWithoutEpoch_yieldsNullEpoch() {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("x-mesh-calling-job-id", "job-8");
        TraceContext.setPropagatedHeaders(headers);

        MeshCallContext.CallingJob cj = MeshCallContext.callingJob();
        assertEquals("job-8", cj.jobId());
        assertNull(cj.claimEpoch(), "absent epoch header → null (old SDK / push-mode caller)");
        assertTrue(cj.isPresent());
    }

    @Test
    void callingJob_malformedEpoch_yieldsNullEpoch() {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("x-mesh-calling-job-id", "job-9");
        headers.put("x-mesh-calling-claim-epoch", "not-a-number");
        TraceContext.setPropagatedHeaders(headers);

        MeshCallContext.CallingJob cj = MeshCallContext.callingJob();
        assertEquals("job-9", cj.jobId());
        assertNull(cj.claimEpoch(), "malformed epoch header must not throw — degrade to null");
    }

    // ---- Round-trip: outbound seed → inbound capture ------------------------

    @Test
    void roundTrip_outboundSeed_readBackByProvider() throws Exception {
        Map<String, String> outbound = JobContext.withJob(
            new JobContext.Snapshot("job-rt", 30L, 11L),
            TraceContext::callingJobHeaders);
        TraceContext.setPropagatedHeaders(outbound);

        MeshCallContext.CallingJob cj = MeshCallContext.callingJob();
        assertEquals("job-rt", cj.jobId());
        assertEquals(11L, cj.claimEpoch());
    }

    // ---- BLOCKER regression: carrier must not trigger push-mode dispatch ----

    /** task=true tool that records whether it ran inside a job dispatch scope. */
    @SuppressWarnings("unused")
    public static class TaskProbe {
        final AtomicReference<JobContext.Snapshot> jobScope = new AtomicReference<>();
        final AtomicReference<MeshCallContext.CallingJob> seenCaller = new AtomicReference<>();

        @MeshTool(capability = "probe", task = true)
        public String probe(@Param("input") String input) {
            // Non-null only when invokeInternal wrapped this call in
            // dispatchAsJob (JobContext.withJob). A plain (non-dispatch) call
            // leaves the job scope unset.
            jobScope.set(JobContext.current());
            seenCaller.set(MeshCallContext.callingJob());
            return "ok:" + input;
        }
    }

    private static MeshToolWrapper taskProbeWrapper(TaskProbe bean) throws Exception {
        Method m = TaskProbe.class.getMethod("probe", String.class);
        return new MeshToolWrapper(
            "TaskProbe.probe", "probe", "test", bean, m,
            List.of(), JsonMapper.builder().build(), true);
    }

    @Test
    void callingHeaders_doNotTriggerPushDispatch_forSameInstanceTaskTool() throws Exception {
        // Simulate a job handler calling a same-instance task=true tool: the
        // outbound call carries ONLY the calling-* carrier (no x-mesh-job-id).
        // The dispatch gate keys on x-mesh-job-id, so the callee MUST run as a
        // plain invocation — NOT dispatched as (and completing) the caller's job.
        TaskProbe bean = new TaskProbe();
        MeshToolWrapper wrapper = taskProbeWrapper(bean);

        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("x-mesh-calling-job-id", "caller-job");
        headers.put("x-mesh-calling-claim-epoch", "4");
        TraceContext.setPropagatedHeaders(headers);

        Object result = wrapper.invoke(Map.of("input", "x"));

        assertEquals("ok:x", result);
        assertNull(bean.jobScope.get(),
            "calling-* carrier must NOT trigger dispatchAsJob — the callee ran as a plain call, "
                + "so the caller's job is never auto-completed by this nested invocation");
        // The provider can still READ the caller's identity for write-fencing.
        assertNotNull(bean.seenCaller.get());
        assertEquals("caller-job", bean.seenCaller.get().jobId());
        assertEquals(4L, bean.seenCaller.get().claimEpoch());
    }
}
