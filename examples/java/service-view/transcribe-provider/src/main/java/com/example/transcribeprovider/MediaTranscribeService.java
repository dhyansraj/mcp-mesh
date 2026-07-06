package com.example.transcribeprovider;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;
import org.springframework.stereotype.Component;

/**
 * Producer-sugar bean (RFC #1280 phase 3): {@code @McpMeshService("media")}
 * publishes each public method as {@code media.<methodName>}. This bean's single
 * public method {@code transcribe} publishes the dotted capability
 * {@code media.transcribe} — the third slice of the same {@code media.*}
 * namespace served by a different agent.
 */
@Component
@McpMeshService("media")
public class MediaTranscribeService {

    /**
     * Produce a deterministic transcript from an asset id and source text.
     *
     * @param assetId the media asset identifier
     * @param text    source audio text
     * @return a transcript record, tagged with this provider's name
     */
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
