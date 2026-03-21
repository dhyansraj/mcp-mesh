package io.mcpmesh.spring.media;

/**
 * Result of saving an upload to MediaStore.
 *
 * @param uri      URI identifying the stored media
 * @param name     Filename or display name
 * @param mimeType MIME type of the content
 * @param size     Size in bytes
 */
public record MediaUploadResult(String uri, String name, String mimeType, long size) {}
