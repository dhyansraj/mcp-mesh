package com.example.supersededprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.spring.MeshCallContext;
import io.mcpmesh.types.MeshSupersededException;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Typed supersession signal (issue #1278) — Java Provider: a write authority
 * that fences stale-executor writes.
 *
 * <p>This is the provider half of the calling-job fencing pattern. A state
 * authority (here an in-memory ledger) accepts mutating writes from job
 * executors. When a job is re-claimed after a crash/reclaim, a NEWER executor
 * runs under a HIGHER {@code claimEpoch}; the OLD executor may still be
 * mid-flight and try to write. Those stale writes must be rejected so the newer
 * executor owns the outcome.
 *
 * <p>Two mesh surfaces make this a few lines:
 * <pre>{@code
 * // 1. Read WHO called me (issue #1263 — the calling job's identity).
 * var cj = MeshCallContext.callingJob();     // fields nullable
 *
 * // 2. Reject a superseded caller with the TYPED signal (issue #1278).
 * throw new MeshSupersededException(detail);
 * }</pre>
 *
 * <p>The framework does NOT auto-detect supersession — the APP decides. The
 * mesh only propagates the calling job's identity and provides the typed
 * exception plus its emit/recognize plumbing. Here the "is superseded" rule is
 * deliberately simple and deterministic for teaching: the authority remembers
 * the highest {@code claimEpoch} it has seen per calling {@code jobId} and
 * rejects any call whose epoch is lower — i.e. "an older executor is trying to
 * write after a newer one already has".
 *
 * <p>{@link MeshSupersededException} crosses the wire as the reserved app
 * envelope {@code {"error":"claim_superseded"}} (plus an optional
 * {@code "detail"}). The calling side's injected proxy recognizes that envelope
 * and re-throws {@code MeshSupersededException} — so the CONSUMER unwinds with
 * ONE {@code catch (MeshSupersededException e)} (see
 * {@code ../superseded-consumer-java}) instead of string-matching a marker
 * after every call.
 *
 * <p>Run:
 * <pre>
 * MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "superseded-provider-java",
    version = "1.0.0",
    description = "Issue #1278 provider (Java) — write authority that fences "
        + "superseded executors via calling-job epoch + typed MeshSupersededException",
    port = 9124
)
@SpringBootApplication
public class SupersededProviderApplication {

    // Highest claimEpoch this authority has accepted a write under, per calling
    // jobId. This is the APP's supersession state — the framework does not keep
    // it. A ConcurrentHashMap because inbound tool calls may be served on
    // different request threads; a multi-replica authority would keep this in a
    // shared store (Redis, a DB version column, ...).
    private final Map<String, Long> latestEpochByJob = new ConcurrentHashMap<>();

    // The in-memory "ledger" we are protecting from stale writes.
    private final List<Map<String, Object>> ledger = new ArrayList<>();

    public static void main(String[] args) {
        SpringApplication.run(SupersededProviderApplication.class, args);
    }

    @MeshTool(
        capability = "apply_write",
        description = "Apply a mutating write to the ledger, fencing out writes "
            + "from a superseded (older-epoch) executor. Demonstrates "
            + "calling-job fencing with the typed MeshSupersededException."
    )
    public synchronized Map<String, Object> applyWrite(@Param("entry") String entry) {
        // The mutating payload (`entry`) is an ordinary tool argument. The
        // caller's IDENTITY is NOT in the payload — it rides the propagated
        // headers the mesh seeds on outbound calls made from within a job
        // execution context, and we read it back via MeshCallContext.
        MeshCallContext.CallingJob cj = MeshCallContext.callingJob();

        // No calling-job identity → a regular (non-job) call, or a caller on an
        // old SDK that does not propagate identity. Nothing to fence against;
        // apply the write. (Fencing is defense-in-depth — soft-fail-open when
        // identity is absent.)
        if (!cj.isPresent() || cj.claimEpoch() == null) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("entry", entry);
            row.put("byEpoch", null);
            ledger.add(row);
            return result(null);
        }

        long callerEpoch = cj.claimEpoch();
        long seen = latestEpochByJob.getOrDefault(cj.jobId(), -1L);

        if (callerEpoch < seen) {
            // APP DECISION: a newer executor (epoch `seen`) has already written
            // for this job, so this older executor's write is stale. Throw the
            // typed signal — it serializes to the reserved
            // {"error":"claim_superseded","detail":...} envelope, and the
            // caller's injected proxy re-throws MeshSupersededException.
            String detail = "job " + cj.jobId() + ": calling epoch " + callerEpoch
                + " < latest accepted epoch " + seen;
            throw new MeshSupersededException(detail);
        }

        // Caller is current (>= highest seen). Record its epoch and apply.
        latestEpochByJob.put(cj.jobId(), Math.max(seen, callerEpoch));
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("entry", entry);
        row.put("byEpoch", callerEpoch);
        ledger.add(row);
        return result(callerEpoch);
    }

    private Map<String, Object> result(Long acceptedEpoch) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("applied", true);
        out.put("ledger_size", ledger.size());
        if (acceptedEpoch != null) {
            out.put("accepted_epoch", acceptedEpoch);
        }
        return out;
    }
}
