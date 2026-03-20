package io.mcpmesh.spring.media;

/**
 * Abstraction for storing and retrieving media content (images, files, etc.)
 * produced by MCP tool calls.
 *
 * <p>Implementations provide pluggable backends (local filesystem, S3, etc.)
 * configured via {@code mcp.mesh.media.storage} property.
 */
public interface MediaStore {

    /**
     * Upload media data and return a URI that can be used to retrieve it.
     *
     * @param data     Raw bytes of the media content
     * @param filename Name for the stored file (may include path separators)
     * @param mimeType MIME type of the content (e.g., "image/png")
     * @return URI identifying the stored media (scheme depends on implementation)
     */
    String upload(byte[] data, String filename, String mimeType);

    /**
     * Fetch previously stored media by URI.
     *
     * @param uri URI returned from a previous {@link #upload} call
     * @return The media data and its MIME type
     * @throws MediaStoreException if the URI is not found or cannot be read
     */
    MediaFetchResult fetch(String uri);

    /**
     * Check whether media exists at the given URI.
     *
     * @param uri URI to check
     * @return {@code true} if the media exists and is accessible
     */
    boolean exists(String uri);
}
