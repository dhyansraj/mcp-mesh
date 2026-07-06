package com.example.serviceview;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

import java.util.Map;

/**
 * uc37 phase-2 service view (RFC #1280): consumed as a {@code @MeshTool}
 * METHOD PARAMETER by {@code view_tool_param}. Each method becomes an
 * ordinary dependency edge ON THAT TOOL (appended after explicit
 * {@code @Selector} deps, method-name order), with a per-consumer-slot proxy
 * — and, the headline, the REQUIRED {@code charlie()} edge participates in
 * the tool's pre-invoke guard: calling the tool while tp-cap-charlie is
 * unresolved returns the structured
 * {@code {"error":"dependency_unavailable","capability":"tp-cap-charlie"}}
 * refusal (issue #1273 envelope) BEFORE user code runs. Contrast with the
 * class-level {@link ReportService} bean path, which does NOT get the
 * envelope (see tc03 vs tc06).
 *
 * <p>DELIBERATELY a distinct capability namespace (tp-cap-*) from
 * {@link ReportService}'s view-cap-*: the agent-spec fold dedupes bean-path
 * view edges against every earlier source INCLUDING tool-declared deps, so
 * reusing view-cap-* here would dedupe the {@code __mesh_service_deps}
 * synthetic away entirely and break tc03/tc04's registry surface. Distinct
 * names keep BOTH dependency carriers observable: 3 edges on the
 * {@code view_tool_param} tool + 3 on the synthetic (tc07 asserts both).
 */
@McpMeshService
public interface ToolParamService {

    @Selector(capability = "tp-cap-alpha")
    Map<String, Object> alpha();

    @Selector(capability = "tp-cap-bravo")
    Map<String, Object> bravo();

    @Selector(capability = "tp-cap-charlie", required = true)
    Map<String, Object> charlie();
}
