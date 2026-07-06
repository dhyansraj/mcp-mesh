package com.example.supersededconsumer;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshSupersededException;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Typed supersession signal (issue #1278) — Java Consumer: a job executor whose
 * mutating writes unwind with ONE {@code catch (MeshSupersededException)}.
 *
 * <p>This is the consumer half of the fencing pattern. {@code runWriter} is a
 * {@code task = true} handler — it executes AS a job, so it runs under a
 * {@code claimEpoch}. Every outbound mesh call it makes (here to the provider's
 * {@code apply_write}) automatically carries this job's identity on the
 * propagated headers, so the provider can fence it via
 * {@code MeshCallContext.callingJob()} without the executor threading
 * {@code jobId} / {@code claimEpoch} through each payload.
 *
 * <p>The point of #1278 is the UNWIND. A job executor makes many mutating
 * downstream calls; if this executor has been superseded (a newer claim of the
 * same job is now authoritative) it must stop and bail — cleanly, from wherever
 * it is in the batch. Because a superseded write re-throws the TYPED
 * {@link MeshSupersededException}, the whole batch is wrapped in ONE
 * {@code catch}:
 * <pre>{@code
 * try {
 *     for (String entry : entries) {
 *         applyWrite.call(Map.of("entry", entry));   // any of these may be fenced
 *     }
 * } catch (MeshSupersededException e) {
 *     return Map.of("status", "superseded", "detail", e.getDetail());  // one unwind
 * }
 * }</pre>
 *
 * <p>Contrast the OLD pattern this REPLACES — inspecting every call's result and
 * string-matching the marker after each one:
 * <pre>{@code
 * for (String entry : entries) {
 *     Map<String, Object> r = applyWrite.call(Map.of("entry", entry));
 *     // brittle: re-check the shape/marker on EVERY call site
 *     if ("claim_superseded".equals(r.get("error"))) return supersededResult();
 * }
 * }</pre>
 *
 * <p>Note this is DISTINCT from {@code dependency_unavailable} (issue #1273):
 * that says "the capability isn't reachable"; supersession says "you personally
 * are stale, a newer you is authoritative". Both are typed so the CONTRACT (the
 * reserved envelope), not the error string, drives classification.
 *
 * <p>Run after the provider is up:
 * <pre>
 * MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "superseded-consumer-java",
    version = "1.0.0",
    description = "Issue #1278 consumer (Java) — a task=true writer job that "
        + "unwinds mutating writes with one catch (MeshSupersededException)",
    port = 9125
)
@SpringBootApplication
public class SupersededConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(SupersededConsumerApplication.class, args);
    }

    @MeshTool(
        capability = "run_writer",
        // task = true: this handler is dispatched AS a job (claimed from the
        // registry), so it runs under a claimEpoch that the mesh stamps onto
        // the calling-job headers of the applyWrite.call below.
        task = true,
        description = "Run a batch of ledger writes as a job. If this executor "
            + "is superseded mid-batch, unwind cleanly with one "
            + "catch (MeshSupersededException).",
        // Regular McpMeshTool dependency on the provider's mutating capability.
        // (A dependency, NOT a MeshJobSubmitter — apply_write is a plain tool.)
        dependencies = @Selector(capability = "apply_write")
    )
    public Map<String, Object> runWriter(
            @Param(value = "count", required = false) Integer count,
            // Injected by type: the apply_write McpMeshTool proxy.
            McpMeshTool<Map<String, Object>> applyWrite,
            // Injected by type: the controller for THIS job (its own identity /
            // claimEpoch live here; the provider sees it via callingJob()).
            MeshJob job) {

        if (applyWrite == null) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "apply_write not injected — check that the "
                + "superseded-provider-java is registered");
            return err;
        }

        int n = (count == null) ? 3 : count;
        List<String> written = new ArrayList<>();
        try {
            for (int i = 0; i < n; i++) {
                String entry = "line-" + i;
                // Any of these calls may be fenced by the provider. If this
                // executor has been superseded, the provider throws
                // MeshSupersededException; the injected proxy recognizes the
                // reserved envelope and re-throws MeshSupersededException here
                // — so we do NOT inspect each result for a marker.
                applyWrite.call(Map.of("entry", entry));
                written.add(entry);
            }
        } catch (MeshSupersededException e) {
            // ONE unwind for the whole batch. A newer claim of this job is
            // authoritative — stop writing and hand back what we managed before
            // being fenced. No rollback needed: the provider already rejected
            // the stale write, so the ledger reflects only the authoritative
            // executor.
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("status", "superseded");
            out.put("written_before_fence", written);
            out.put("detail", e.getDetail());
            return out;
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("status", "completed");
        out.put("written", written);
        return out;
    }
}
