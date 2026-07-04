package io.mcpmesh.spring;

import io.mcpmesh.spring.tracing.TraceContext;

import java.util.Map;

/**
 * Provider-side accessor for the identity of the job that originated the
 * current inbound tool call (issue #1263).
 *
 * <p>When a job handler makes an outbound {@code McpMeshTool} call, the mesh
 * seeds the calling job's identity onto a DEDICATED carrier —
 * {@code x-mesh-calling-job-id} and (when known) {@code x-mesh-calling-claim-epoch}
 * (see {@link TraceContext#applyCallingJobIdentity(Map)}). A provider tool being
 * called can read that identity here — without the caller threading
 * {@code job_id} / {@code claim_epoch} through the tool payload — to fence
 * out-of-epoch writes (defense-in-depth on top of the cancellation-based fencing
 * exposed via {@code JobContext.claimEpoch}).
 *
 * <p>The carrier is deliberately separate from the push-dispatch protocol pair
 * ({@code x-mesh-job-id} / {@code x-mesh-claim-epoch}): reusing those would make
 * a nested same-instance {@code task=true} call self-dispatch as the caller's
 * job and auto-complete it with the wrong result.
 *
 * <p>Purely additive: returns nulls when the current call did not originate
 * from a job execution context, or when the caller is an older SDK that does
 * not seed the headers.
 *
 * <p>Cross-runtime consistent: reads exactly {@code x-mesh-calling-job-id} /
 * {@code x-mesh-calling-claim-epoch}, the same header names Python and
 * TypeScript seed.
 */
public final class MeshCallContext {

    private MeshCallContext() {}

    /**
     * Identity of the job that originated the current inbound call.
     *
     * @param jobId      the calling job's id, or {@code null} when the call did
     *                   not originate from a job (or the header was absent)
     * @param claimEpoch the calling job's claim generation, or {@code null}
     *                   when absent / a push-mode caller / an old SDK
     */
    public record CallingJob(String jobId, Long claimEpoch) {
        /** Whether an originating job id is present. */
        public boolean isPresent() {
            return jobId != null && !jobId.isEmpty();
        }
    }

    /**
     * Read the calling job's identity from the current thread's propagated
     * headers. Never null; its fields are null when the corresponding header is
     * absent.
     *
     * @return the calling job identity (fields nullable)
     */
    public static CallingJob callingJob() {
        Map<String, String> headers = TraceContext.getPropagatedHeaders();
        String jobId = headers != null ? headers.get(TraceContext.CALLING_JOB_ID_HEADER) : null;
        if (jobId != null && jobId.isEmpty()) {
            jobId = null;
        }
        Long claimEpoch = MeshToolWrapper.parseClaimEpochHeader(
            headers != null ? headers.get(TraceContext.CALLING_CLAIM_EPOCH_HEADER) : null);
        return new CallingJob(jobId, claimEpoch);
    }
}
