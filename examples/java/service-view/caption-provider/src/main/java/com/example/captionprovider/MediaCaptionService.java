package com.example.captionprovider;

import io.mcpmesh.McpMeshService;
import io.mcpmesh.Param;
import org.springframework.stereotype.Component;

/**
 * Producer-sugar bean (RFC #1280 phase 3): a class annotated
 * {@code @McpMeshService("media")} publishes each public method as a mesh tool
 * under the capability {@code media.<methodName>}. The {@code "media"} prefix is
 * entirely user-chosen — nothing about it is hard-coded in the mesh.
 *
 * <p>This bean exposes one public method, {@code caption}, so it publishes
 * exactly one capability: {@code media.caption}. Dotted capability names are
 * first-class across the stack; the input schema still comes from the
 * {@code @Param} annotations, exactly as a hand-written {@code @MeshTool} would.
 */
@Component
@McpMeshService("media")
public class MediaCaptionService {

    /**
     * Produce a deterministic caption from an asset id and source text.
     *
     * @param assetId the media asset identifier
     * @param text    source description text
     * @return a caption record, tagged with this provider's name
     */
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
