package io.mcpmesh.types;

import io.mcpmesh.core.MeshObjectMappers;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Thrown by a provider tool to reject a call from a SUPERSEDED executor
 * (issue #1278).
 *
 * <p>A provider decides supersession itself — the framework does NOT
 * auto-detect it. The app compares the calling job's claim generation
 * (obtained via {@code MeshCallContext.callingJob()}, issue #1263) against its
 * own live epoch and throws this from the {@code @MeshTool} handler when the
 * caller is stale:
 *
 * <pre>{@code
 * var cj = MeshCallContext.callingJob();
 * if (cj != null && cj.claimEpoch() != null && cj.claimEpoch() < myLiveEpoch) {
 *     throw new MeshSupersededException("stale epoch " + cj.claimEpoch());
 * }
 * }</pre>
 *
 * <p>The signal crosses the wire as the reserved {@code isError} app envelope
 * {@code {"error":"claim_superseded"}} (plus an OPTIONAL {@code "detail"}
 * string — omitted, not null, when absent). The calling side's injected proxy
 * recognizes that envelope and re-throws {@code MeshSupersededException}, so a
 * superseded caller unwinds with a single {@code catch}
 * ({@code catch (MeshSupersededException e)}) instead of string-matching
 * {@code claim_superseded} after every mutating call. This is the exact
 * parallel of the {@code dependency_unavailable} refusal (issue #1273): the
 * contract (the reserved envelope), not the carrier, drives classification.
 *
 * <p>The marker string {@code "claim_superseded"} is the SAME canonical marker
 * the job path already uses on the wire (Go {@code ent_service_jobs.go} /
 * Rust {@code CLAIM_SUPERSEDED_REASON}), reused verbatim so a superseded signal
 * is one string end-to-end.
 */
public class MeshSupersededException extends RuntimeException {

    /**
     * Reserved marker for the supersession envelope — the canonical
     * {@code claim_superseded} string reused verbatim from the job path.
     */
    public static final String CLAIM_SUPERSEDED_MARKER = "claim_superseded";

    private static final ObjectMapper MAPPER = MeshObjectMappers.create();

    private final String detail;

    /**
     * Create the supersession signal with an optional human-readable detail.
     *
     * @param detail why the caller is superseded, or {@code null} when none —
     *               omitted entirely from the wire envelope when null
     */
    public MeshSupersededException(String detail) {
        super(detail == null ? "Caller superseded" : "Caller superseded: " + detail);
        this.detail = detail;
    }

    /**
     * The optional detail carried by the signal, or {@code null} when none.
     *
     * @return the detail string, or {@code null}
     */
    public String getDetail() {
        return detail;
    }

    /**
     * Return a {@code MeshSupersededException} if {@code errorText} is the
     * reserved supersession envelope, else {@code null}.
     *
     * <p>Defensive parse for the consumer recognize path: a non-JSON body, a
     * JSON body that is not an object, or one whose {@code error} field is not
     * exactly {@link #CLAIM_SUPERSEDED_MARKER} all return {@code null} so the
     * caller falls through to its existing generic error handling. Only the
     * exact reserved marker is classified — a {@code dependency_unavailable}
     * (or any other) envelope is left alone. A non-string {@code detail} is
     * treated as absent.
     *
     * @param errorText the {@code isError} tool-result text to classify
     * @return the typed signal, or {@code null} when not the reserved envelope
     */
    public static MeshSupersededException fromEnvelope(String errorText) {
        if (errorText == null) {
            return null;
        }
        JsonNode node;
        try {
            node = MAPPER.readTree(errorText);
        } catch (Exception e) {
            return null;
        }
        if (node == null || !node.isObject()) {
            return null;
        }
        JsonNode error = node.get("error");
        if (error == null || !error.isTextual()
                || !CLAIM_SUPERSEDED_MARKER.equals(error.asText())) {
            return null;
        }
        JsonNode detailNode = node.get("detail");
        String detail = (detailNode != null && detailNode.isTextual())
            ? detailNode.asText() : null;
        return new MeshSupersededException(detail);
    }
}
