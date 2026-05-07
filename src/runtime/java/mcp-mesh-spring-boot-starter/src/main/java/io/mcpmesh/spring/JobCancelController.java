package io.mcpmesh.spring;

import io.mcpmesh.core.MeshCore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Spring MVC controller exposing {@code POST /jobs/{jobId}/cancel} on every
 * mesh agent (Phase B — MeshJob substrate). The registry forwards cancel
 * requests for an active job to its owner replica via this route; the
 * handler fires the in-process cancel token via
 * {@link MeshCore#mesh_cancel_active_job}, which signals any
 * {@code mesh_run_as_job}-bound futures to abort.
 *
 * <p>Mirror of:
 * <ul>
 *   <li>Python {@code _mcp_mesh.engine.cancel_route} (FastAPI handler)</li>
 *   <li>TypeScript {@code @mcp-mesh/runtime registerCancelRoute} in agent.ts</li>
 * </ul>
 *
 * <p>Returns {@code {"cancelled": <bool>, "jobId": <id>}} per
 * {@code MESHJOB_DESIGN.org} → "Cancel route response". The boolean is
 * true iff a token was found and fired (i.e. this replica owned an
 * active job for the id), false otherwise — the registry treats the
 * 200/false response as "owner replica is alive but the job has already
 * gone terminal" and proceeds to mark the row cancelled.
 */
@RestController
public class JobCancelController {

    private static final Logger log = LoggerFactory.getLogger(JobCancelController.class);

    @PostMapping("/jobs/{jobId}/cancel")
    public Map<String, Object> cancelJob(@PathVariable String jobId) {
        MeshCore core = MeshCore.load();
        int rc = core.mesh_cancel_active_job(jobId);
        boolean cancelled = rc == 1;
        if (rc < 0) {
            log.warn("mesh_cancel_active_job returned {} for jobId={}", rc, jobId);
        } else if (cancelled) {
            log.info("Cancelled active job {}", jobId);
        } else {
            log.debug("No active job for {} (registry will still mark cancelled)", jobId);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("cancelled", cancelled);
        body.put("jobId", jobId);
        return body;
    }
}
