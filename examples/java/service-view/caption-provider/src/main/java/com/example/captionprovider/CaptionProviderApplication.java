package com.example.captionprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * CaptionProvider - one leaf of the {@code @McpMeshService} service-view demo.
 *
 * <p>Publishes a single capability, {@code media_caption}. The
 * {@code media-gateway} consumer binds this capability through the
 * {@code MediaService.caption(...)} view method — a different agent than the
 * ones backing {@code thumbnail(...)} and {@code transcribe(...)}.
 */
@MeshAgent(
    name = "caption-provider",
    version = "1.0.0",
    description = "Generates a human caption for a media asset",
    port = 8110
)
@SpringBootApplication
public class CaptionProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(CaptionProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting CaptionProvider Agent...");
        SpringApplication.run(CaptionProviderApplication.class, args);
    }

    /**
     * Produce a deterministic caption from an asset id and source text.
     *
     * @param assetId the media asset identifier
     * @param text    source description text
     * @return a caption record, tagged with this provider's name
     */
    @MeshTool(
        capability = "media_caption",
        description = "Generates a human caption for a media asset",
        tags = {"media"}
    )
    public CaptionResult caption(
        @Param(value = "assetId", description = "Media asset identifier") String assetId,
        @Param(value = "text", description = "Source description text") String text
    ) {
        String caption = "A scene showing " + text.trim().toLowerCase() + ".";
        return new CaptionResult(assetId, caption, "caption-provider");
    }

    /** Caption result — {@code provider} makes the serving agent visible downstream. */
    public record CaptionResult(String assetId, String caption, String provider) {}
}
