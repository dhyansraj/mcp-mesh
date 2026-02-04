package io.mcpmesh.types;

/**
 * Thrown when attempting to call a mesh tool that is not available.
 *
 * <p>This can happen when:
 * <ul>
 *   <li>The dependency was never resolved</li>
 *   <li>The remote agent went offline</li>
 *   <li>The tool was unregistered from the mesh</li>
 * </ul>
 *
 * <p>To handle gracefully, check {@link McpMeshTool#isAvailable()} before calling.
 */
public class MeshToolUnavailableException extends RuntimeException {

    private final String capability;

    public MeshToolUnavailableException(String capability) {
        super("Mesh tool unavailable: " + capability);
        this.capability = capability;
    }

    public MeshToolUnavailableException(String capability, String message) {
        super("Mesh tool unavailable (" + capability + "): " + message);
        this.capability = capability;
    }

    /**
     * Get the capability name that was unavailable.
     *
     * @return The capability name
     */
    public String getCapability() {
        return capability;
    }
}
