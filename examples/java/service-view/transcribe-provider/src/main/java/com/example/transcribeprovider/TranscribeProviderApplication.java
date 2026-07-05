package com.example.transcribeprovider;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * TranscribeProvider - one leaf of the {@code @McpMeshService} service-view demo.
 *
 * <p>Publishes a single capability, {@code media_transcribe}. The
 * {@code media-gateway} consumer binds this capability through the OPTIONAL
 * {@code MediaService.transcribe(...)} view method — a third, independent agent
 * from the ones backing {@code caption(...)} and {@code thumbnail(...)}.
 */
@MeshAgent(
    name = "transcribe-provider",
    version = "1.0.0",
    description = "Generates a transcript for a media asset",
    port = 8112
)
@SpringBootApplication
public class TranscribeProviderApplication {

    private static final Logger log = LoggerFactory.getLogger(TranscribeProviderApplication.class);

    public static void main(String[] args) {
        log.info("Starting TranscribeProvider Agent...");
        SpringApplication.run(TranscribeProviderApplication.class, args);
    }

    /**
     * Produce a deterministic transcript from an asset id and source text.
     *
     * @param assetId the media asset identifier
     * @param text    source audio text
     * @return a transcript record, tagged with this provider's name
     */
    @MeshTool(
        capability = "media_transcribe",
        description = "Generates a transcript for a media asset",
        tags = {"media"}
    )
    public TranscriptResult transcribe(
        @Param(value = "assetId", description = "Media asset identifier") String assetId,
        @Param(value = "text", description = "Source audio text") String text
    ) {
        int words = text.trim().isEmpty() ? 0 : text.trim().split("\\s+").length;
        String transcript = "[" + assetId + "] " + text.trim().toUpperCase();
        return new TranscriptResult(assetId, transcript, words, "transcribe-provider");
    }

    /** Transcript result — {@code provider} makes the serving agent visible downstream. */
    public record TranscriptResult(String assetId, String transcript, int wordCount, String provider) {}
}
