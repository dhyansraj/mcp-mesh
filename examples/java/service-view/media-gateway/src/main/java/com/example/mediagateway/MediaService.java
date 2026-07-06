package com.example.mediagateway;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Selector;

/**
 * A consumer-owned <b>service view</b> (RFC #1280): one typed interface that
 * aggregates three independent capabilities. Each abstract method binds exactly
 * one capability via its own {@link Selector}, so the three methods resolve to
 * three DIFFERENT provider agents and rebind independently as the mesh topology
 * changes.
 *
 * <ul>
 *   <li>{@link #caption} → {@code media.caption} (caption-provider), REQUIRED</li>
 *   <li>{@link #thumbnail} → {@code media.thumbnail} (thumbnail-provider), optional</li>
 *   <li>{@link #transcribe} → {@code media.transcribe} (transcribe-provider), optional</li>
 * </ul>
 *
 * <p>The capabilities use dotted names ({@code media.*}) — first-class across
 * the stack — matching the shared namespace the three producer-sugar agents
 * publish into.
 *
 * <p>Spring auto-discovers this interface on the classpath and registers a
 * facade bean named {@code mediaService}; the {@code media-gateway} agent
 * {@code @Autowired}s it and calls the methods directly. Each optional method
 * throws {@link io.mcpmesh.types.MeshToolUnavailableException} when its provider
 * is absent, which the gateway catches for graceful degradation.
 */
@McpMeshService
public interface MediaService {

    @Selector(capability = "media.caption", required = true)
    CaptionResult caption(CaptionRequest req);

    @Selector(capability = "media.thumbnail")
    ThumbnailResult thumbnail(ThumbnailRequest req);

    @Selector(capability = "media.transcribe")
    TranscriptResult transcribe(TranscribeRequest req);

    // ---- Single-POJO request records (one unannotated param per method) -------

    record CaptionRequest(String assetId, String text) {}

    record ThumbnailRequest(String assetId, int width) {}

    record TranscribeRequest(String assetId, String text) {}

    // ---- Result records (field names mirror each provider's response) --------

    record CaptionResult(String assetId, String caption, String provider) {}

    record ThumbnailResult(String assetId, String uri, String size, String provider) {}

    record TranscriptResult(String assetId, String transcript, int wordCount, String provider) {}
}
