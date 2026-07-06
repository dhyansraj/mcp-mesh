package com.example.serviceview;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

import java.util.Map;

/**
 * uc37 phase-3 consumer view (RFC #1280): binds the DOT-SEPARATED
 * {@code svc.*} capabilities published by the java-view-producer agent's
 * {@code @McpMeshService("svc")} producer sugar. Both edges are OPTIONAL —
 * this view exists to prove dotted capability names traverse the whole
 * pipeline (widened registry validator -> registration -> dependency
 * resolution -> facade call), not to exercise required semantics (tc03/tc06
 * own those).
 *
 * <p>Consumed as a constructor-injected bean by the {@code view_dotted}
 * observation tool (tc08). Adds two svc.* edges to the
 * {@code __mesh_service_deps} synthetic (5 bean-path edges total — see
 * tc04/tc07's dependency arithmetic).
 */
@McpMeshService
public interface DottedService {

    @Selector(capability = "svc.alpha")
    Map<String, Object> alpha();

    @Selector(capability = "svc.bravo")
    Map<String, Object> bravo();
}
