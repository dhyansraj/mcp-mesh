package io.mcpmesh.spring.media;

import io.modelcontextprotocol.spec.McpSchema.ResourceLink;

/**
 * Public helpers for building MCP media content items.
 *
 * <p>Provides convenience methods matching the Python {@code mesh.media_result()}
 * and TypeScript {@code mediaResult()} helpers. A {@code @MeshTool} method can
 * return the result directly and the framework will wrap it in a proper
 * {@code resource_link} MCP content type.
 *
 * <p>Example usage:
 * <pre>{@code
 * @MeshTool(description = "Generate a chart image")
 * public ResourceLink generateChart(String query) {
 *     byte[] png = renderChart(query);
 *     String uri = mediaStore.upload(png, "chart.png", "image/png");
 *     return MeshMedia.mediaResult(uri, "chart.png", "image/png");
 * }
 * }</pre>
 */
public final class MeshMedia {

    private MeshMedia() {}

    /**
     * Create a {@code resource_link} content item for tool results.
     *
     * @param uri      URI of the media resource (e.g., {@code file://...} or {@code s3://...})
     * @param name     Human-readable name for the resource
     * @param mimeType MIME type (e.g., {@code "image/png"})
     * @return A {@link ResourceLink} that the MCP server serializes as {@code resource_link}
     */
    public static ResourceLink mediaResult(String uri, String name, String mimeType) {
        return ResourceLink.builder()
            .uri(uri)
            .name(name)
            .mimeType(mimeType)
            .build();
    }

    /**
     * Create a {@code resource_link} content item with optional metadata.
     *
     * @param uri         URI of the media resource
     * @param name        Human-readable name for the resource
     * @param mimeType    MIME type (e.g., {@code "image/png"})
     * @param description Optional description (may be {@code null})
     * @param size        Optional size in bytes (may be {@code null})
     * @return A {@link ResourceLink} that the MCP server serializes as {@code resource_link}
     */
    public static ResourceLink mediaResult(
            String uri, String name, String mimeType,
            String description, Long size) {
        ResourceLink.Builder builder = ResourceLink.builder()
            .uri(uri)
            .name(name)
            .mimeType(mimeType);
        if (description != null) {
            builder.description(description);
        }
        if (size != null) {
            builder.size(size);
        }
        return builder.build();
    }
}
