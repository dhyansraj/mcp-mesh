package io.mcpmesh.core;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Event received from the MCP Mesh Rust core runtime.
 *
 * <p>Events are pushed from the Rust runtime to notify the SDK of state changes
 * such as dependency availability, LLM tools updates, and shutdown.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public class MeshEvent {

    @JsonProperty("event_type")
    private EventType eventType;

    @JsonProperty("agent_id")
    private String agentId;

    private String capability;
    private String endpoint;

    @JsonProperty("function_name")
    private String functionName;

    @JsonProperty("function_id")
    private String functionId;

    @JsonProperty("requesting_function")
    private String requestingFunction;

    @JsonProperty("dep_index")
    private Integer depIndex;

    private String error;
    private String reason;
    private String status;

    private List<LlmToolInfo> tools;

    @JsonProperty("provider_info")
    private LlmProviderInfo providerInfo;

    // Getters

    public EventType getEventType() {
        return eventType;
    }

    public String getAgentId() {
        return agentId;
    }

    public String getCapability() {
        return capability;
    }

    public String getEndpoint() {
        return endpoint;
    }

    public String getFunctionName() {
        return functionName;
    }

    public String getFunctionId() {
        return functionId;
    }

    public String getRequestingFunction() {
        return requestingFunction;
    }

    public Integer getDepIndex() {
        return depIndex;
    }

    public String getError() {
        return error;
    }

    public String getReason() {
        return reason;
    }

    public String getStatus() {
        return status;
    }

    public List<LlmToolInfo> getTools() {
        return tools;
    }

    public LlmProviderInfo getProviderInfo() {
        return providerInfo;
    }

    @Override
    public String toString() {
        return "MeshEvent{" +
                "eventType=" + eventType +
                ", agentId='" + agentId + '\'' +
                ", capability='" + capability + '\'' +
                '}';
    }

    /**
     * Type of mesh event.
     */
    public enum EventType {
        @JsonProperty("agent_registered")
        AGENT_REGISTERED,

        @JsonProperty("registration_failed")
        REGISTRATION_FAILED,

        @JsonProperty("dependency_available")
        DEPENDENCY_AVAILABLE,

        @JsonProperty("dependency_unavailable")
        DEPENDENCY_UNAVAILABLE,

        @JsonProperty("dependency_changed")
        DEPENDENCY_CHANGED,

        @JsonProperty("llm_tools_updated")
        LLM_TOOLS_UPDATED,

        @JsonProperty("llm_provider_available")
        LLM_PROVIDER_AVAILABLE,

        @JsonProperty("health_check_due")
        HEALTH_CHECK_DUE,

        @JsonProperty("health_status_changed")
        HEALTH_STATUS_CHANGED,

        @JsonProperty("registry_connected")
        REGISTRY_CONNECTED,

        @JsonProperty("registry_disconnected")
        REGISTRY_DISCONNECTED,

        @JsonProperty("shutdown")
        SHUTDOWN
    }

    /**
     * LLM tool information from LlmToolsUpdated event.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class LlmToolInfo {
        @JsonProperty("function_name")
        private String functionName;

        private String capability;
        private String description;
        private String endpoint;

        @JsonProperty("agent_id")
        private String agentId;

        @JsonProperty("input_schema")
        private Map<String, Object> inputSchema;

        public String getFunctionName() {
            return functionName;
        }

        public String getCapability() {
            return capability;
        }

        public String getDescription() {
            return description;
        }

        public String getEndpoint() {
            return endpoint;
        }

        public String getAgentId() {
            return agentId;
        }

        public Map<String, Object> getInputSchema() {
            return inputSchema;
        }
    }

    /**
     * LLM provider information from LlmProviderAvailable event.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class LlmProviderInfo {
        @JsonProperty("function_id")
        private String functionId;

        @JsonProperty("agent_id")
        private String agentId;

        private String endpoint;

        @JsonProperty("function_name")
        private String functionName;

        private String model;

        public String getFunctionId() {
            return functionId;
        }

        public String getAgentId() {
            return agentId;
        }

        public String getEndpoint() {
            return endpoint;
        }

        public String getFunctionName() {
            return functionName;
        }

        public String getModel() {
            return model;
        }
    }
}
