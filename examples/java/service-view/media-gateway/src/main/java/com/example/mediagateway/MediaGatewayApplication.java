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
 * <p>Demonstrates BOTH ways to consume a service view, side by side, over the
 * same {@link #combine} fan-out logic:
 *
 * <ul>
 *   <li>{@code process_media} — the view is a constructor-injected Spring bean
 *       (phase 1). App-wide facade; there is no tool-boundary refusal, so a
 *       missing REQUIRED capability surfaces as a
 *       {@link MeshToolUnavailableException} thrown from the call.</li>
 *   <li>{@code process_media_strict} — the view is a {@code @MeshTool} METHOD
 *       PARAMETER (phase 2). Each view method becomes a dependency edge ON THAT
 *       TOOL, so the REQUIRED {@code caption} edge gates the tool with the
 *       structured {@code dependency_unavailable} refusal BEFORE the handler
 *       runs, and the edges show up in the tool's dependency count.</li>
 * </ul>
 *
 * <p>Either way the optional {@code thumbnail}/{@code transcribe} methods are
 * wrapped in a {@link MeshToolUnavailableException} catch so the gateway keeps
 * working (with a degraded fallback) whenever those providers are down.
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
     * Phase-1 style: consume the view via the constructor-injected bean.
     *
     * <p>App-wide facade with no tool-boundary refusal — if {@code caption} has
     * no provider, the {@code media.caption(...)} call throws
     * {@link MeshToolUnavailableException}, which propagates out as a tool error.
     *
     * @param assetId the media asset identifier
     * @param text    source description / audio text
     * @return a combined map showing the value and serving provider per capability
     */
    @MeshTool(
        capability = "process_media",
        description = "Runs an asset through one service view injected as a bean",
        tags = {"media", "gateway"}
    )
    public Map<String, Object> processMedia(
        @Param(value = "assetId", description = "Media asset identifier") String assetId,
        @Param(value = "text", description = "Source description / audio text") String text
    ) {
        log.info("process_media: asset '{}' via constructor-injected view bean", assetId);
        return combine(this.media, assetId, text);
    }

    /**
     * Phase-2 style: consume the view via a {@code @MeshTool} METHOD PARAMETER.
     *
     * <p>The {@code MediaService} parameter (NOT {@code @Param}-annotated) expands
     * into three dependency edges on THIS tool. Because {@code caption} is
     * {@code required=true}, the mesh runtime returns the structured
     * {@code {"error":"dependency_unavailable","capability":"media.caption"}}
     * refusal BEFORE this method body runs whenever the caption edge is
     * unresolved — so here {@code caption} is guaranteed present, while the
     * optional edges still degrade gracefully.
     *
     * @param assetId the media asset identifier
     * @param text    source description / audio text
     * @param media   the service-view facade, injected as a tool dependency
     * @return a combined map showing the value and serving provider per capability
     */
    @MeshTool(
        capability = "process_media_strict",
        description = "Runs an asset through one service view injected as a tool parameter",
        tags = {"media", "gateway"}
    )
    public Map<String, Object> processStrict(
        @Param(value = "assetId", description = "Media asset identifier") String assetId,
        @Param(value = "text", description = "Source description / audio text") String text,
        MediaService media
    ) {
        log.info("process_media_strict: asset '{}' via tool-parameter view", assetId);
        return combine(media, assetId, text);
    }

    /**
     * Shared fan-out: run one asset through all three view methods and combine
     * the results. Each capability may be served by a different provider agent;
     * the two optional methods degrade gracefully when their provider is absent.
     */
    private static Map<String, Object> combine(MediaService media, String assetId, String text) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("assetId", assetId);

        // REQUIRED edge — in the tool-parameter path a missing provider is
        // refused before we get here; in the bean path it throws.
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
