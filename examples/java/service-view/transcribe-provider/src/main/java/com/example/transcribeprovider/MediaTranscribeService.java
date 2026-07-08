package com.example.transcribeprovider;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.stereotype.Component;

/**
 * Publishes the dotted capability {@code media.transcribe} — the third slice of
 * the shared {@code media.*} namespace, served by a different agent. The
 * capability name is declared EXPLICITLY on the {@code @MeshTool}.
 */
@Component
public class MediaTranscribeService {

    /**
     * Produce a deterministic transcript from an asset id and source text.
     *
     * @param assetId the media asset identifier
     * @param text    source audio text
     * @return a transcript record, tagged with this provider's name
     */
    @MeshTool(capability = "media.transcribe")
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
