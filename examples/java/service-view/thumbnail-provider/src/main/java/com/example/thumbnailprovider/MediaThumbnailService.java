package com.example.thumbnailprovider;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;
import org.springframework.stereotype.Component;

/**
 * Producer-sugar bean (RFC #1280 phase 3): {@code @McpMeshService("media")}
 * publishes each public method as {@code media.<methodName>}. This bean's single
 * public method {@code thumbnail} publishes the dotted capability
 * {@code media.thumbnail} — a second slice of the same {@code media.*} namespace
 * served by a different agent.
 */
@Component
@McpMeshService("media")
public class MediaThumbnailService {

    /**
     * Produce a deterministic thumbnail descriptor from an asset id and width.
     *
     * @param assetId the media asset identifier
     * @param width   requested thumbnail width in pixels
     * @return a thumbnail record, tagged with this provider's name
     */
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
