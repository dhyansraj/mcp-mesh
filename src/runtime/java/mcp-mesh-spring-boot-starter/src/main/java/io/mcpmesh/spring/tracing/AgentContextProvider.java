package io.mcpmesh.spring.tracing;

import java.net.InetAddress;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Provides agent metadata for trace spans.
 *
 * <p>Collects static context at startup that is included in every trace span:
 * <ul>
 *   <li>Agent identity: id, name, namespace</li>
 *   <li>Network info: hostname, IP, port, endpoint</li>
 *   <li>Runtime info: Java version</li>
 *   <li>Kubernetes info: pod name, pod IP (if available)</li>
 * </ul>
 */
public class AgentContextProvider {

    private final Map<String, Object> staticContext;

    /**
     * Create an AgentContextProvider with agent metadata.
     *
     * @param agentId Unique agent identifier
     * @param agentName Agent name
     * @param hostname Agent hostname
     * @param port Agent HTTP port
     * @param namespace Agent namespace
     */
    public AgentContextProvider(String agentId, String agentName,
                                 String hostname, int port, String namespace) {
        Map<String, Object> context = new LinkedHashMap<>();

        // Agent identity
        context.put("agent_id", agentId);
        context.put("agent_name", agentName);
        context.put("agent_namespace", namespace != null ? namespace : "default");

        // Network info
        context.put("agent_hostname", hostname != null ? hostname : getLocalHostname());
        context.put("agent_port", port);
        context.put("agent_endpoint", buildEndpoint(hostname, port));

        // Get local IP
        String localIp = getLocalIp();
        context.put("agent_ip", localIp);

        // Runtime info
        context.put("agent_runtime", "java");
        context.put("java_version", System.getProperty("java.version"));

        // Kubernetes info (if running in K8s)
        String podName = System.getenv("HOSTNAME");
        if (podName != null) {
            context.put("pod_name", podName);
        }
        String podIp = System.getenv("POD_IP");
        if (podIp != null) {
            context.put("pod_ip", podIp);
        }
        String podNamespace = System.getenv("POD_NAMESPACE");
        if (podNamespace != null) {
            context.put("pod_namespace", podNamespace);
        }

        this.staticContext = Collections.unmodifiableMap(context);
    }

    /**
     * Get the static agent context.
     *
     * @return Unmodifiable map of agent context
     */
    public Map<String, Object> getContext() {
        return staticContext;
    }

    /**
     * Get a subset of context optimized for trace storage.
     *
     * @return Map with essential trace metadata
     */
    public Map<String, Object> getTraceMetadata() {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("agent_id", staticContext.get("agent_id"));
        metadata.put("agent_name", staticContext.get("agent_name"));
        metadata.put("agent_namespace", staticContext.get("agent_namespace"));
        metadata.put("agent_hostname", staticContext.get("agent_hostname"));
        metadata.put("agent_ip", staticContext.get("agent_ip"));
        metadata.put("agent_port", staticContext.get("agent_port"));
        metadata.put("agent_endpoint", staticContext.get("agent_endpoint"));
        return metadata;
    }

    private String getLocalHostname() {
        try {
            return InetAddress.getLocalHost().getHostName();
        } catch (Exception e) {
            return "unknown";
        }
    }

    private String getLocalIp() {
        try {
            return InetAddress.getLocalHost().getHostAddress();
        } catch (Exception e) {
            return "127.0.0.1";
        }
    }

    private String buildEndpoint(String hostname, int port) {
        String host = hostname != null ? hostname : getLocalHostname();
        return "http://" + host + ":" + port;
    }
}
