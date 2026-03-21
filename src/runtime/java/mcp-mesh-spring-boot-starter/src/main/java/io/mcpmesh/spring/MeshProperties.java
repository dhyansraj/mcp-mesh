package io.mcpmesh.spring;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Configuration properties for MCP Mesh.
 *
 * <p>These properties can be set in application.yml or application.properties:
 * <pre>
 * mesh:
 *   registry:
 *     url: http://localhost:8000
 *   agent:
 *     name: my-agent
 *     port: 9000
 * </pre>
 *
 * <p>Environment variables take precedence:
 * <ul>
 *   <li>{@code MCP_MESH_REGISTRY_URL}</li>
 *   <li>{@code MCP_MESH_AGENT_NAME}</li>
 *   <li>{@code MCP_MESH_HTTP_PORT}</li>
 * </ul>
 */
@ConfigurationProperties(prefix = "mesh")
public class MeshProperties {

    private final Registry registry = new Registry();
    private final Agent agent = new Agent();
    private Media media = new Media();

    public Registry getRegistry() {
        return registry;
    }

    public Agent getAgent() {
        return agent;
    }

    public Media getMedia() {
        return media;
    }

    public void setMedia(Media media) {
        this.media = media;
    }

    public static class Registry {
        private String url = "http://localhost:8000";

        public String getUrl() {
            return url;
        }

        public void setUrl(String url) {
            this.url = url;
        }
    }

    public static class Agent {
        private String name;
        private String version = "1.0.0";
        private int port = 0;
        private String host;  // null = auto-detect via Rust core
        private String namespace = "default";
        private int heartbeatInterval = 0;  // 0 = use Rust core default (5 seconds)

        public String getName() {
            return name;
        }

        public void setName(String name) {
            this.name = name;
        }

        public String getVersion() {
            return version;
        }

        public void setVersion(String version) {
            this.version = version;
        }

        public int getPort() {
            return port;
        }

        public void setPort(int port) {
            this.port = port;
        }

        public String getHost() {
            return host;
        }

        public void setHost(String host) {
            this.host = host;
        }

        public String getNamespace() {
            return namespace;
        }

        public void setNamespace(String namespace) {
            this.namespace = namespace;
        }

        public int getHeartbeatInterval() {
            return heartbeatInterval;
        }

        public void setHeartbeatInterval(int heartbeatInterval) {
            this.heartbeatInterval = heartbeatInterval;
        }
    }

    public static class Media {
        private String storage = "local";
        private String storagePath = "/tmp/mcp-mesh-media";
        private String storageBucket;
        private String storageEndpoint;
        private String storagePrefix = "media/";

        public String getStorage() {
            return storage;
        }

        public void setStorage(String storage) {
            this.storage = storage;
        }

        public String getStoragePath() {
            return storagePath;
        }

        public void setStoragePath(String storagePath) {
            this.storagePath = storagePath;
        }

        public String getStorageBucket() {
            return storageBucket;
        }

        public void setStorageBucket(String storageBucket) {
            this.storageBucket = storageBucket;
        }

        public String getStorageEndpoint() {
            return storageEndpoint;
        }

        public void setStorageEndpoint(String storageEndpoint) {
            this.storageEndpoint = storageEndpoint;
        }

        public String getStoragePrefix() {
            return storagePrefix;
        }

        public void setStoragePrefix(String storagePrefix) {
            this.storagePrefix = storagePrefix;
        }
    }
}
