package io.mcpmesh.core;

/**
 * Exception thrown by MCP Mesh operations.
 */
public class MeshException extends RuntimeException {

    public MeshException(String message) {
        super(message);
    }

    public MeshException(String message, Throwable cause) {
        super(message, cause);
    }
}
