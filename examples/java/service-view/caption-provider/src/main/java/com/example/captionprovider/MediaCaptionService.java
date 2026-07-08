package com.example.captionprovider;

import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.stereotype.Component;

/**
 * Publishes one tool into the shared {@code media.*} capability namespace. The
 * dotted capability name {@code media.caption} is declared EXPLICITLY on the
 * {@code @MeshTool}, so the wire contract is owned by the annotation rather than
 * derived from the Java method name. Dotted capability names are first-class
 * across the stack; the input schema comes from the {@code @Param} annotations.
 */
@Component
public class MediaCaptionService {

    /**
     * Produce a deterministic caption from an asset id and source text.
     *
     * @param assetId the media asset identifier
     * @param text    source description text
     * @return a caption record, tagged with this provider's name
     */
    @MeshTool(capability = "media.caption")
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
