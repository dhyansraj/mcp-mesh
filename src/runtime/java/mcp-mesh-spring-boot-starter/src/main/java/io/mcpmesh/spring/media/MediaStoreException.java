package io.mcpmesh.spring.media;

/**
 * Exception thrown when a {@link MediaStore} operation fails.
 */
public class MediaStoreException extends RuntimeException {

    public MediaStoreException(String message) {
        super(message);
    }

    public MediaStoreException(String message, Throwable cause) {
        super(message, cause);
    }
}
