package io.mcpmesh.spring.media;

/**
 * Result of fetching media from a {@link MediaStore}.
 *
 * @param data     Raw bytes of the media content
 * @param mimeType MIME type of the content (e.g., "image/png")
 */
public record MediaFetchResult(byte[] data, String mimeType) {
}
