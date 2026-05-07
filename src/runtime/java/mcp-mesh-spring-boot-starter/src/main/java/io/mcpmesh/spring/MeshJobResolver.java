package io.mcpmesh.spring;

import io.mcpmesh.MeshJob;
import io.mcpmesh.types.McpMeshTool;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;

/**
 * Reflective DDDI resolver implementing the contract in
 * {@code MESHJOB_DDDI_CONTRACT.md}. Sister implementation of:
 * <ul>
 *   <li>Python {@code _mcp_mesh.engine.signature_analyzer.analyze_mesh_job_signature}</li>
 *   <li>TypeScript {@code @mcp-mesh/runtime ... analyzeMeshJobSignature}</li>
 * </ul>
 *
 * <p>For each parameter in declaration order:
 * <ul>
 *   <li>Type assignable to {@link McpMeshTool} → mesh dependency, assigned
 *       the next positional slot ({@code mesh_tool_position_counter}++).</li>
 *   <li>Type assignable to {@link MeshJob} → mesh job param, recorded by
 *       <i>signature</i> position in {@link Resolved#meshJobParamIndex}.
 *       Does NOT touch the positional counter.</li>
 *   <li>Anything else → user argument (caller-supplied at signature index).</li>
 * </ul>
 *
 * <p><b>Validation</b> (per the contract):
 * <ul>
 *   <li>At most one {@link MeshJob} parameter — multiple is rejected at
 *       resolve time with {@link IllegalStateException}.</li>
 *   <li>{@link MeshJob} may appear at any position (including in the middle
 *       of {@link McpMeshTool} params) — no trailing-only rule.</li>
 * </ul>
 *
 * <p>This class is intentionally a free-standing static helper rather than
 * folded into {@link MeshToolWrapper#analyzeParameters} so the contract has
 * a clean test seam ({@code MeshJobResolverTest}) without spinning up the
 * full Spring + native bridge.
 */
public final class MeshJobResolver {

    private MeshJobResolver() {}

    /**
     * Resolved view of a method signature.
     *
     * @param meshToolPositions   Signature positions of {@code McpMeshTool}
     *                            parameters in declaration order. Index in
     *                            this list is the dependency's positional
     *                            slot (the {@code mesh_tool_position_counter}
     *                            value at assignment).
     * @param meshJobParamIndex   Signature position of the (single) MeshJob
     *                            parameter, or empty if none.
     * @param totalParameterCount Convenience: total parameter count of the
     *                            analyzed method.
     */
    public record Resolved(
        List<Integer> meshToolPositions,
        Optional<Integer> meshJobParamIndex,
        int totalParameterCount
    ) {
        public Resolved {
            // Defensive copy so the returned list can't be mutated.
            meshToolPositions = List.copyOf(meshToolPositions);
        }

        /** Number of {@link McpMeshTool} dependencies declared on this method. */
        public int meshToolCount() {
            return meshToolPositions.size();
        }

        /** True iff the method declares a {@link MeshJob} parameter. */
        public boolean hasMeshJob() {
            return meshJobParamIndex.isPresent();
        }
    }

    /**
     * Resolve the signature of {@code method}.
     *
     * @param method The method to analyze
     * @return The resolved signature view
     * @throws IllegalArgumentException if {@code method} is null
     * @throws IllegalStateException if more than one {@link MeshJob} parameter
     *         is declared (per {@code MESHJOB_DDDI_CONTRACT.md})
     */
    public static Resolved resolve(Method method) {
        if (method == null) {
            throw new IllegalArgumentException("method is required");
        }
        Parameter[] params = method.getParameters();
        List<Integer> meshToolPositions = new ArrayList<>();
        Integer meshJobIndex = null;

        for (int i = 0; i < params.length; i++) {
            Class<?> type = params[i].getType();
            // Order matters: MeshJob check first so a class implementing
            // BOTH (theoretically possible if a user creates a custom
            // MeshJob marker that also implements McpMeshTool — odd but
            // valid Java) classifies as MeshJob, matching the Python
            // resolver which checks the MeshJob Protocol before the
            // MeshTool Protocol. In practice the SDK's first-party types
            // (JobController, JobProxy, MeshJobSubmitter) implement only
            // MeshJob.
            if (MeshJob.class.isAssignableFrom(type)) {
                if (meshJobIndex != null) {
                    throw new IllegalStateException(
                        "Method " + method.getDeclaringClass().getName() + "."
                            + method.getName()
                            + " declares multiple MeshJob parameters (positions "
                            + meshJobIndex + " and " + i
                            + "); a tool function may declare at most one MeshJob "
                            + "parameter — see MESHJOB_DDDI_CONTRACT.md."
                    );
                }
                meshJobIndex = i;
            } else if (McpMeshTool.class.isAssignableFrom(type)) {
                meshToolPositions.add(i);
            }
            // Everything else: user arg. Not tracked here — handled by
            // the caller (MeshToolWrapper) which already classifies them
            // via @Param.
        }

        return new Resolved(
            Collections.unmodifiableList(meshToolPositions),
            Optional.ofNullable(meshJobIndex),
            params.length
        );
    }
}
