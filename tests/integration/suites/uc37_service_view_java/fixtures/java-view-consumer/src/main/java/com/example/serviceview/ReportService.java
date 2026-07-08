package com.example.serviceview;

import io.mcpmesh.MeshService;
import io.mcpmesh.Selector;

import java.util.Map;

/**
 * uc37 primary service view (RFC #1280): three methods, three capabilities,
 * three DIFFERENT provider agents. The group is a typed view — each method
 * delegates to its own per-capability proxy and rebinds independently.
 *
 * <p>{@code charlie()} carries {@code required = true}: its edge feeds the
 * issue #1249 availability derivation for the synthetic
 * {@code __mesh_service_deps} capability and the tool-boundary refusal
 * contract exercised by tc03.
 */
@MeshService
public interface ReportService {

    @Selector(capability = "view-cap-alpha")
    Map<String, Object> alpha();

    @Selector(capability = "view-cap-bravo")
    Map<String, Object> bravo();

    @Selector(capability = "view-cap-charlie", required = true)
    Map<String, Object> charlie();
}
