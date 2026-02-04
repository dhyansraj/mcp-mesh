package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a class as an MCP Mesh agent.
 *
 * <p>Apply this annotation to your Spring Boot application class to configure
 * the agent's registration with the mesh registry.
 *
 * <h2>Example</h2>
 * <pre>{@code
 * @MeshAgent(
 *     name = "greeter",
 *     version = "1.0.0",
 *     port = 9000,
 *     description = "Simple greeting service"
 * )
 * @SpringBootApplication
 * public class GreeterAgent {
 *     public static void main(String[] args) {
 *         SpringApplication.run(GreeterAgent.class, args);
 *     }
 * }
 * }</pre>
 *
 * <h2>Configuration Resolution</h2>
 * <p>Values can be overridden via environment variables (highest priority):
 * <ul>
 *   <li>{@code MCP_MESH_AGENT_NAME} → {@link #name()}</li>
 *   <li>{@code MCP_MESH_HTTP_PORT} → {@link #port()}</li>
 *   <li>{@code MCP_MESH_HTTP_HOST} → {@link #host()}</li>
 *   <li>{@code MCP_MESH_NAMESPACE} → {@link #namespace()}</li>
 * </ul>
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
public @interface MeshAgent {

    /**
     * Unique agent name/identifier.
     *
     * <p>Override with {@code MCP_MESH_AGENT_NAME} environment variable.
     */
    String name();

    /**
     * Agent version (semver format).
     *
     * <p>Override with {@code MCP_MESH_AGENT_VERSION} environment variable.
     */
    String version() default "1.0.0";

    /**
     * Human-readable description of the agent.
     */
    String description() default "";

    /**
     * HTTP port for this agent.
     *
     * <p>Use 0 for auto-assignment.
     * Override with {@code MCP_MESH_HTTP_PORT} environment variable.
     */
    int port() default 0;

    /**
     * HTTP host announced to registry.
     *
     * <p>If empty, the SDK will auto-detect the external IP address.
     * Override with {@code MCP_MESH_HTTP_HOST} environment variable.
     */
    String host() default "";

    /**
     * Namespace for agent isolation.
     *
     * <p>Override with {@code MCP_MESH_NAMESPACE} environment variable.
     */
    String namespace() default "default";

    /**
     * Heartbeat interval in seconds.
     *
     * <p>Override with {@code MCP_MESH_HEARTBEAT_INTERVAL} environment variable.
     */
    int heartbeatInterval() default 0;  // 0 = use Rust core default (5 seconds)
}
