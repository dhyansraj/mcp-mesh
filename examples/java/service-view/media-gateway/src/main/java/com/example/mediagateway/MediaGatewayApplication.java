package com.example.mediagateway;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.types.MeshToolUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * MediaGateway - the consumer in the {@code @McpMeshService} service-view demo.
 *
 * <p>Autowires the {@link MediaService} facade and exposes a single
 * {@code process_media} tool that fans one request out across all three view
 * methods. Because each method binds its own capability, the returned
 * {@code servedBy} fields show THREE different provider agents answering through
 * ONE typed interface.
 *
 * <p>The optional {@code thumbnail}/{@code transcribe} methods are wrapped in a
 * {@link MeshToolUnavailableException} catch so the gateway keeps working (with
 * a degraded fallback) whenever those providers are down — while the REQUIRED
 * {@code caption} method is expected to always resolve.
 */
@MeshAgent(
    name = "media-gateway",
    version = "1.0.0",
    description = "Aggregates three media capabilities behind one typed service view",
    port = 8113
)
@SpringBootApplication
public class MediaGatewayApplication {

    private static final Logger log = LoggerFactory.getLogger(MediaGatewayApplication.class);

    private final MediaService media;

    public MediaGatewayApplication(MediaService media) {
        this.media = media;
    }

    public static void main(String[] args) {
        log.info("Starting MediaGateway Agent...");
        SpringApplication.run(MediaGatewayApplication.class, args);
    }

    /**
     * Process one media asset through all three view methods and combine the
     * results. Each capability may be served by a different provider agent.
     *
     * @param assetId the media asset identifier
     * @param text    source description / audio text
     * @return a combined map showing the value and serving provider per capability
     */
    @MeshTool(
        capability = "process_media",
        description = "Runs an asset through caption, thumbnail and transcribe via one service view",
        tags = {"media", "gateway"}
    )
    public Map<String, Object> processMedia(
        @Param(value = "assetId", description = "Media asset identifier") String assetId,
        @Param(value = "text", description = "Source description / audio text") String text
    ) {
        log.info("Processing media asset '{}' through the MediaService view", assetId);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("assetId", assetId);

        // REQUIRED edge — expected to resolve; a failure surfaces to the caller.
        MediaService.CaptionResult caption = media.caption(new MediaService.CaptionRequest(assetId, text));
        result.put("caption", entry(caption.caption(), caption.provider()));

        // OPTIONAL edge — degrade gracefully if no thumbnail provider is present.
        try {
            MediaService.ThumbnailResult thumb =
                media.thumbnail(new MediaService.ThumbnailRequest(assetId, 320));
            result.put("thumbnail", entry(thumb.uri() + " (" + thumb.size() + ")", thumb.provider()));
        } catch (MeshToolUnavailableException e) {
            log.warn("thumbnail capability unavailable — degrading: {}", e.getMessage());
            result.put("thumbnail", entry("(no thumbnail — provider offline)", "unavailable"));
        }

        // OPTIONAL edge — degrade gracefully if no transcribe provider is present.
        try {
            MediaService.TranscriptResult tx =
                media.transcribe(new MediaService.TranscribeRequest(assetId, text));
            result.put("transcript", entry(tx.transcript() + " [" + tx.wordCount() + " words]", tx.provider()));
        } catch (MeshToolUnavailableException e) {
            log.warn("transcribe capability unavailable — degrading: {}", e.getMessage());
            result.put("transcript", entry("(no transcript — provider offline)", "unavailable"));
        }

        return result;
    }

    /** One combined-result entry: the value plus the provider agent that served it. */
    private static Map<String, Object> entry(String value, String servedBy) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("value", value);
        m.put("servedBy", servedBy);
        return m;
    }
}
