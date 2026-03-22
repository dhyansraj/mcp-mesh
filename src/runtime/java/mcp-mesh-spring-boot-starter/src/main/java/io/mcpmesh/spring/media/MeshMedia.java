package io.mcpmesh.spring.media;

import io.modelcontextprotocol.spec.McpSchema.ResourceLink;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;

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
 *
 * <p>Or use the bytes-based overload for a single-step upload + link:
 * <pre>{@code
 * @MeshTool(description = "Generate a chart image")
 * public ResourceLink generateChart(String query) {
 *     byte[] png = renderChart(query);
 *     return MeshMedia.mediaResult(png, "chart.png", "image/png", mediaStore);
 * }
 * }</pre>
 */
public final class MeshMedia {

    private MeshMedia() {}

    // ── URI-based mediaResult (existing) ────────────────────────────────

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

    // ── Bytes-based mediaResult (upload + ResourceLink in one step) ─────

    /**
     * Upload bytes to a {@link MediaStore} and return a {@code resource_link} in one step.
     *
     * @param data     Raw bytes of the media content
     * @param filename Name for the stored file (also used as the resource name)
     * @param mimeType MIME type of the content
     * @param store    MediaStore to upload to
     * @return A {@link ResourceLink} pointing to the uploaded content
     */
    public static ResourceLink mediaResult(
            byte[] data, String filename, String mimeType, MediaStore store) {
        String uri = store.upload(data, filename, mimeType);
        return mediaResult(uri, filename, mimeType, null, (long) data.length);
    }

    /**
     * Upload bytes to a {@link MediaStore} with full metadata and return a {@code resource_link}.
     *
     * @param data        Raw bytes of the media content
     * @param filename    Name for the stored file
     * @param mimeType    MIME type of the content
     * @param name        Human-readable name (falls back to {@code filename} if {@code null})
     * @param description Optional description (may be {@code null})
     * @param store       MediaStore to upload to
     * @return A {@link ResourceLink} pointing to the uploaded content
     */
    public static ResourceLink mediaResult(
            byte[] data, String filename, String mimeType,
            String name, String description, MediaStore store) {
        String uri = store.upload(data, filename, mimeType);
        return mediaResult(uri, name != null ? name : filename, mimeType, description, (long) data.length);
    }

    // ── MultipartFile helpers ───────────────────────────────────────────

    /**
     * Save a Spring {@link MultipartFile} to a {@link MediaStore} and return the URI.
     *
     * @param file  The uploaded file
     * @param store MediaStore to save to
     * @return URI identifying the stored media
     * @throws IOException if reading the file bytes fails
     */
    public static String saveUpload(MultipartFile file, MediaStore store) throws IOException {
        byte[] data = file.getBytes();
        String filename = file.getOriginalFilename() != null ? file.getOriginalFilename() : "upload";
        String mimeType = file.getContentType() != null ? file.getContentType() : "application/octet-stream";
        return store.upload(data, filename, mimeType);
    }

    /**
     * Save a Spring {@link MultipartFile} to a {@link MediaStore} with filename/mimeType overrides.
     *
     * @param file     The uploaded file
     * @param store    MediaStore to save to
     * @param filename Override filename (falls back to original if {@code null})
     * @param mimeType Override MIME type (falls back to content type if {@code null})
     * @return URI identifying the stored media
     * @throws IOException if reading the file bytes fails
     */
    public static String saveUpload(
            MultipartFile file, MediaStore store,
            String filename, String mimeType) throws IOException {
        byte[] data = file.getBytes();
        String fname = filename != null ? filename :
            (file.getOriginalFilename() != null ? file.getOriginalFilename() : "upload");
        String mtype = mimeType != null ? mimeType :
            (file.getContentType() != null ? file.getContentType() : "application/octet-stream");
        return store.upload(data, fname, mtype);
    }

    /**
     * Save a Spring {@link MultipartFile} to a {@link MediaStore} and return a
     * {@link MediaUploadResult} with all metadata.
     *
     * @param file  The uploaded file
     * @param store MediaStore to save to
     * @return Result containing the URI, filename, MIME type, and size
     * @throws IOException if reading the file bytes fails
     */
    public static MediaUploadResult saveUploadResult(
            MultipartFile file, MediaStore store) throws IOException {
        byte[] data = file.getBytes();
        String filename = file.getOriginalFilename() != null ? file.getOriginalFilename() : "upload";
        String mimeType = file.getContentType() != null ? file.getContentType() : "application/octet-stream";
        String uri = store.upload(data, filename, mimeType);
        return new MediaUploadResult(uri, filename, mimeType, data.length);
    }
}
