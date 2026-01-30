package io.mcpmesh.types;

/**
 * Thrown when a call to a mesh tool fails.
 *
 * <p>This can happen due to:
 * <ul>
 *   <li>Network errors</li>
 *   <li>Remote agent errors</li>
 *   <li>Serialization/deserialization failures</li>
 *   <li>Tool execution errors</li>
 * </ul>
 */
public class MeshToolCallException extends RuntimeException {

    private final String capability;
    private final String functionName;

    public MeshToolCallException(String capability, String functionName, String message) {
        super(String.format("Tool call failed (%s.%s): %s", capability, functionName, message));
        this.capability = capability;
        this.functionName = functionName;
    }

    public MeshToolCallException(String capability, String functionName, Throwable cause) {
        super(String.format("Tool call failed (%s.%s): %s", capability, functionName, cause.getMessage()), cause);
        this.capability = capability;
        this.functionName = functionName;
    }

    /**
     * Get the capability name.
     *
     * @return The capability name
     */
    public String getCapability() {
        return capability;
    }

    /**
     * Get the function/tool name that was called.
     *
     * @return The function name
     */
    public String getFunctionName() {
        return functionName;
    }
}
