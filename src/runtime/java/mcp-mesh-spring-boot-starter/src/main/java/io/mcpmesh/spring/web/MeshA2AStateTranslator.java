package io.mcpmesh.spring.web;

import java.util.Map;

/**
 * Mesh job lifecycle ↔ A2A v1.0 state translation (spec §7.2).
 *
 * <p>The mesh job substrate uses these internal statuses:
 * <ul>
 *   <li>{@code working}, {@code completed}, {@code failed}, {@code cancelled} (UK)</li>
 * </ul>
 * A2A v1.0 uses:
 * <ul>
 *   <li>{@code working}, {@code completed}, {@code failed}, {@code canceled} (US)</li>
 * </ul>
 *
 * <p>The UK ↔ US spelling boundary is the most error-prone part of the
 * translation (Appendix B item flagged in spec). Consumers accept both
 * spellings; producers MUST emit the US form.
 *
 * <p>Unknown / unset mesh statuses fall back to {@code working} — preserves
 * the invariant that we never emit an A2A state outside the spec's
 * enumerated set, even when the registry reports a status we haven't mapped.
 * Mirrors Python's {@code _map_mesh_state} (a2a.py:112-122).
 */
public final class MeshA2AStateTranslator {

    /** A2A v1.0 state: long-running task in flight. */
    public static final String A2A_WORKING = "working";
    /** A2A v1.0 terminal state: task finished successfully. */
    public static final String A2A_COMPLETED = "completed";
    /** A2A v1.0 terminal state: handler raised or job failed. */
    public static final String A2A_FAILED = "failed";
    /** A2A v1.0 terminal state: task canceled (US spelling). */
    public static final String A2A_CANCELED = "canceled";

    private MeshA2AStateTranslator() {
        // Utility class
    }

    /**
     * Translate a mesh job status string to its A2A v1.0 equivalent.
     *
     * <p>Mapping table:
     * <table border="1">
     *   <tr><th>Mesh status</th><th>A2A state</th></tr>
     *   <tr><td>{@code working}</td><td>{@code working}</td></tr>
     *   <tr><td>{@code completed}</td><td>{@code completed}</td></tr>
     *   <tr><td>{@code failed}</td><td>{@code failed}</td></tr>
     *   <tr><td>{@code cancelled} (UK)</td><td>{@code canceled} (US)</td></tr>
     *   <tr><td>anything else / null</td><td>{@code working} (fallback)</td></tr>
     * </table>
     *
     * @param meshStatus the mesh-side status string (may be {@code null})
     * @return one of the four A2A v1.0 enumerated states; never {@code null}
     */
    public static String fromMesh(String meshStatus) {
        if (meshStatus == null || meshStatus.isEmpty()) {
            return A2A_WORKING;
        }
        return switch (meshStatus) {
            case "working" -> A2A_WORKING;
            case "completed" -> A2A_COMPLETED;
            case "failed" -> A2A_FAILED;
            case "cancelled", "canceled" -> A2A_CANCELED;
            default -> A2A_WORKING;
        };
    }

    /**
     * @return {@code true} when the A2A state is one of the three terminal
     *     values ({@code completed} / {@code failed} / {@code canceled}).
     */
    public static boolean isTerminal(String a2aState) {
        return A2A_COMPLETED.equals(a2aState)
            || A2A_FAILED.equals(a2aState)
            || A2A_CANCELED.equals(a2aState);
    }

    /**
     * @return {@code true} when the mesh status string represents a terminal
     *     state. Accepts both UK and US "canceled" spellings (the mesh
     *     substrate emits {@code cancelled} but a normalizer upstream may
     *     have already translated).
     */
    public static boolean isMeshTerminal(String meshStatus) {
        if (meshStatus == null) {
            return false;
        }
        return "completed".equals(meshStatus)
            || "failed".equals(meshStatus)
            || "cancelled".equals(meshStatus)
            || "canceled".equals(meshStatus);
    }

    /**
     * Extract the mesh-side status string from a {@code proxy.status()}
     * payload. Returns {@code null} when the payload lacks a recognisable
     * status field — callers default to {@code working} via {@link #fromMesh}.
     */
    public static String meshStatusOf(Map<String, Object> statusPayload) {
        if (statusPayload == null) {
            return null;
        }
        Object s = statusPayload.get("status");
        return s == null ? null : s.toString();
    }
}
