package io.mcpmesh.spring.media;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * Local filesystem implementation of {@link MediaStore}.
 *
 * <p>Stores media files under a configurable base path with an optional prefix.
 * URIs use the {@code file://} scheme.
 */
public class LocalMediaStore implements MediaStore {

    private static final Logger log = LoggerFactory.getLogger(LocalMediaStore.class);

    private final Path basePath;
    private final String prefix;

    /**
     * @param basePath Base directory for media storage (e.g., "/tmp/mcp-mesh-media")
     * @param prefix   Path prefix prepended to filenames (e.g., "media/")
     */
    public LocalMediaStore(String basePath, String prefix) {
        this.basePath = Paths.get(basePath);
        this.prefix = prefix != null ? prefix : "";
    }

    private void validatePath(Path filePath) {
        Path normalized = filePath.normalize();
        if (!normalized.startsWith(basePath.normalize())) {
            throw new MediaStoreException("Invalid filename (path traversal): " + filePath);
        }
    }

    @Override
    public String upload(byte[] data, String filename, String mimeType) {
        try {
            Path filePath = basePath.resolve(prefix + filename).normalize();
            validatePath(filePath);
            Files.createDirectories(filePath.getParent());
            Files.write(filePath, data);
            log.debug("Stored media: {} ({}, {} bytes)", filePath, mimeType, data.length);
            return "file://" + filePath.toAbsolutePath();
        } catch (MediaStoreException e) {
            throw e;
        } catch (IOException e) {
            throw new MediaStoreException("Failed to upload media: " + filename, e);
        }
    }

    @Override
    public MediaFetchResult fetch(String uri) {
        try {
            Path filePath = toPath(uri);
            validatePath(filePath);
            if (!Files.exists(filePath)) {
                throw new MediaStoreException("Media not found: " + uri);
            }
            byte[] data = Files.readAllBytes(filePath);
            String mimeType = Files.probeContentType(filePath);
            if (mimeType == null) {
                mimeType = "application/octet-stream";
            }
            return new MediaFetchResult(data, mimeType);
        } catch (MediaStoreException e) {
            throw e;
        } catch (IOException e) {
            throw new MediaStoreException("Failed to fetch media: " + uri, e);
        }
    }

    @Override
    public boolean exists(String uri) {
        try {
            Path filePath = toPath(uri);
            validatePath(filePath);
            return Files.exists(filePath);
        } catch (Exception e) {
            return false;
        }
    }

    private Path toPath(String uri) {
        if (uri.startsWith("file://")) {
            return Paths.get(uri.substring(7));
        }
        return Paths.get(uri);
    }
}
