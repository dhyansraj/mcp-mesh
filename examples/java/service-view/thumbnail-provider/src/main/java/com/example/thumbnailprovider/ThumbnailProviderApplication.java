package com.example.thumbnailprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * ThumbnailProvider - one leaf of the {@code @McpMeshService} service-view demo.
 *
 * <p>Publishes a single capability, {@code media_thumbnail}. The
 * {@code media-gateway} consumer binds this capability through the OPTIONAL
 * {@code MediaService.thumbnail(...)} view method — stop this agent and the
 * gateway degrades gracefully while {@code caption(...)} and
 * {@code transcribe(...)} keep working.
 */
@MeshAgent(
    name = "thumbnail-provider",
    version = "1.0.0",
    description = "Generates a thumbnail descriptor for a media asset",
    port = 8111
)
@SpringBootApplication
public class ThumbnailProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(ThumbnailProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting ThumbnailProvider Agent...");
        SpringApplication.run(ThumbnailProviderApplication.class, args);
    }

    /**
     * Produce a deterministic thumbnail descriptor from an asset id and width.
     *
     * @param assetId the media asset identifier
     * @param width   requested thumbnail width in pixels
     * @return a thumbnail record, tagged with this provider's name
     */
    @MeshTool(
        capability = "media_thumbnail",
        description = "Generates a thumbnail descriptor for a media asset",
        tags = {"media"}
    )
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
