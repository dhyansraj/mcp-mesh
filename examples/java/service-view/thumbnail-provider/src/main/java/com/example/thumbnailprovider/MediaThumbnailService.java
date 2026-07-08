package com.example.thumbnailprovider;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.stereotype.Component;

/**
 * Publishes the dotted capability {@code media.thumbnail} — a second slice of
 * the shared {@code media.*} namespace, served by a different agent. The
 * capability name is declared EXPLICITLY on the {@code @MeshTool}.
 */
@Component
public class MediaThumbnailService {

    /**
     * Produce a deterministic thumbnail descriptor from an asset id and width.
     *
     * @param assetId the media asset identifier
     * @param width   requested thumbnail width in pixels
     * @return a thumbnail record, tagged with this provider's name
     */
    @MeshTool(capability = "media.thumbnail")
    public ThumbnailResult thumbnail(
        @Param(value = "assetId", description = "Media asset identifier") String assetId,
        @Param(value = "width", description = "Requested thumbnail width in pixels") int width
    ) {
        int w = width > 0 ? width : 128;
        int h = Math.max(1, w * 9 / 16);
        String uri = "thumb://" + assetId + "?w=" + w + "&h=" + h;
        return new ThumbnailResult(assetId, uri, w + "x" + h, "thumbnail-provider");
    }

    /** Thumbnail result — {@code provider} makes the serving agent visible downstream. */
    public record ThumbnailResult(String assetId, String uri, String size, String provider) {}
}
