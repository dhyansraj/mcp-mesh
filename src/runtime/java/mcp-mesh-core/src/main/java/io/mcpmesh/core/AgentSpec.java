package io.mcpmesh.core;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.List;

/**
 * Specification for an MCP Mesh agent.
 *
 * <p>This is the primary configuration passed to start the agent runtime.
 * It contains agent metadata, tools, dependencies, and LLM configurations.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AgentSpec {

    /** Base agent name (shared across replicas, e.g., "fortuna"). */
    private String name;

    /**
     * Unique per-replica agent ID (e.g., "fortuna-abc12345").
     * Serialized to the Rust core as the `agent_id` field; defaults to `name`
     * when left null for backward compatibility.
     */
    @JsonProperty("agent_id")
    private String agentId;

    private String version = "1.0.0";
    private String description = "";

    @JsonProperty("registry_url")
    private String registryUrl;

    @JsonProperty("http_port")
    private int httpPort = 0;

    @JsonProperty("http_host")
    private String httpHost = "localhost";

    private String namespace = "default";

    @JsonProperty("agent_type")
    private String agentType = "mcp_agent";

    private String runtime = "java";

    private List<ToolSpec> tools = new ArrayList<>();

    @JsonProperty("llm_agents")
    private List<LlmAgentSpec> llmAgents = new ArrayList<>();

    @JsonProperty("heartbeat_interval")
    private long heartbeatInterval = 5;

    public AgentSpec() {
    }

    public AgentSpec(String name, String registryUrl) {
        this.name = name;
        this.registryUrl = registryUrl;
    }

    // Builder-style setters

    public AgentSpec name(String name) {
        this.name = name;
        return this;
    }

    public AgentSpec agentId(String agentId) {
        this.agentId = agentId;
        return this;
    }

    public AgentSpec version(String version) {
        this.version = version;
        return this;
    }

    public AgentSpec description(String description) {
        this.description = description;
        return this;
    }

    public AgentSpec registryUrl(String registryUrl) {
        this.registryUrl = registryUrl;
        return this;
    }

    public AgentSpec httpPort(int httpPort) {
        this.httpPort = httpPort;
        return this;
    }

    public AgentSpec httpHost(String httpHost) {
        this.httpHost = httpHost;
        return this;
    }

    public AgentSpec namespace(String namespace) {
        this.namespace = namespace;
        return this;
    }

    public AgentSpec agentType(String agentType) {
        this.agentType = agentType;
        return this;
    }

    public AgentSpec addTool(ToolSpec tool) {
        this.tools.add(tool);
        return this;
    }

    public AgentSpec addLlmAgent(LlmAgentSpec llmAgent) {
        this.llmAgents.add(llmAgent);
        return this;
    }

    public AgentSpec heartbeatInterval(long heartbeatInterval) {
        this.heartbeatInterval = heartbeatInterval;
        return this;
    }

    // Standard getters

    public String getName() {
        return name;
    }

    /**
     * Returns the unique per-replica agent ID (e.g., "fortuna-abc12345").
     * Falls back to {@link #getName()} when {@code agentId} is unset, which
     * preserves behavior for callers that haven't been migrated yet.
     *
     * <p>The fallback is intentional for Jackson serialization: the
     * {@code @JsonProperty("agent_id")} annotation sits on the field, but
     * Jackson uses this getter when emitting JSON, so unset {@code agentId}
     * serializes as {@code agent_id == name}. This matches the fallback
     * behavior of {@code AgentSpec::agent_id()} in the Rust core.
     */
    public String getAgentId() {
        return (agentId != null && !agentId.isEmpty()) ? agentId : name;
    }

    public String getVersion() {
        return version;
    }

    public String getDescription() {
        return description;
    }

    public String getRegistryUrl() {
        return registryUrl;
    }

    public int getHttpPort() {
        return httpPort;
    }

    public String getHttpHost() {
        return httpHost;
    }

    public String getNamespace() {
        return namespace;
    }

    public String getAgentType() {
        return agentType;
    }

    public String getRuntime() {
        return runtime;
    }

    public List<ToolSpec> getTools() {
        return tools;
    }

    public List<LlmAgentSpec> getLlmAgents() {
        return llmAgents;
    }

    public long getHeartbeatInterval() {
        return heartbeatInterval;
    }

    // Standard setters

    public void setName(String name) {
        this.name = name;
    }

    public void setAgentId(String agentId) {
        this.agentId = agentId;
    }

    public void setVersion(String version) {
        this.version = version;
    }

    public void setDescription(String description) {
        this.description = description;
    }

    public void setRegistryUrl(String registryUrl) {
        this.registryUrl = registryUrl;
    }

    public void setHttpPort(int httpPort) {
        this.httpPort = httpPort;
    }

    public void setHttpHost(String httpHost) {
        this.httpHost = httpHost;
    }

    public void setNamespace(String namespace) {
        this.namespace = namespace;
    }

    public void setAgentType(String agentType) {
        this.agentType = agentType;
    }

    public void setRuntime(String runtime) {
        this.runtime = runtime;
    }

    public void setTools(List<ToolSpec> tools) {
        this.tools = tools;
    }

    public void setLlmAgents(List<LlmAgentSpec> llmAgents) {
        this.llmAgents = llmAgents;
    }

    public void setHeartbeatInterval(long heartbeatInterval) {
        this.heartbeatInterval = heartbeatInterval;
    }

    /**
     * Specification for a tool/capability provided by the agent.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class ToolSpec {
        @JsonProperty("function_name")
        private String functionName;

        private String capability;
        private String version = "1.0.0";
        private String description = "";
        private List<String> tags = new ArrayList<>();
        private List<DependencySpec> dependencies = new ArrayList<>();

        @JsonProperty("input_schema")
        private String inputSchema;

        /** Raw JSON Schema for output (return type) - serialized JSON string. Issue #547. */
        @JsonProperty("output_schema")
        private String outputSchema;

        /** Canonical normalized input schema (post-DI-strip, post-normalize) - serialized JSON string. Issue #547. */
        @JsonProperty("input_schema_canonical")
        private String inputSchemaCanonical;

        /** SHA256 hash (sha256:&lt;hex&gt;) of inputSchemaCanonical. Issue #547. */
        @JsonProperty("input_schema_hash")
        private String inputSchemaHash;

        /** Canonical normalized output schema - serialized JSON string. Issue #547. */
        @JsonProperty("output_schema_canonical")
        private String outputSchemaCanonical;

        /** SHA256 hash (sha256:&lt;hex&gt;) of outputSchemaCanonical. Issue #547. */
        @JsonProperty("output_schema_hash")
        private String outputSchemaHash;

        /** Normalizer warnings (list of strings). Issue #547. */
        @JsonProperty("schema_warnings")
        private List<String> schemaWarnings;

        @JsonProperty("llm_filter")
        private String llmFilter;

        @JsonProperty("llm_provider")
        private String llmProvider;

        private String kwargs;

        public ToolSpec() {
        }

        public ToolSpec(String functionName, String capability) {
            this.functionName = functionName;
            this.capability = capability;
        }

        // Builder-style setters

        public ToolSpec functionName(String functionName) {
            this.functionName = functionName;
            return this;
        }

        public ToolSpec capability(String capability) {
            this.capability = capability;
            return this;
        }

        public ToolSpec version(String version) {
            this.version = version;
            return this;
        }

        public ToolSpec description(String description) {
            this.description = description;
            return this;
        }

        public ToolSpec tags(List<String> tags) {
            this.tags = tags;
            return this;
        }

        public ToolSpec addTag(String tag) {
            this.tags.add(tag);
            return this;
        }

        public ToolSpec dependencies(List<DependencySpec> dependencies) {
            this.dependencies = dependencies;
            return this;
        }

        public ToolSpec addDependency(DependencySpec dependency) {
            this.dependencies.add(dependency);
            return this;
        }

        public ToolSpec inputSchema(String inputSchema) {
            this.inputSchema = inputSchema;
            return this;
        }

        public ToolSpec outputSchema(String outputSchema) {
            this.outputSchema = outputSchema;
            return this;
        }

        public ToolSpec inputSchemaCanonical(String inputSchemaCanonical) {
            this.inputSchemaCanonical = inputSchemaCanonical;
            return this;
        }

        public ToolSpec inputSchemaHash(String inputSchemaHash) {
            this.inputSchemaHash = inputSchemaHash;
            return this;
        }

        public ToolSpec outputSchemaCanonical(String outputSchemaCanonical) {
            this.outputSchemaCanonical = outputSchemaCanonical;
            return this;
        }

        public ToolSpec outputSchemaHash(String outputSchemaHash) {
            this.outputSchemaHash = outputSchemaHash;
            return this;
        }

        public ToolSpec schemaWarnings(List<String> schemaWarnings) {
            this.schemaWarnings = schemaWarnings;
            return this;
        }

        // Standard getters and setters

        public String getFunctionName() {
            return functionName;
        }

        public void setFunctionName(String functionName) {
            this.functionName = functionName;
        }

        public String getCapability() {
            return capability;
        }

        public void setCapability(String capability) {
            this.capability = capability;
        }

        public String getVersion() {
            return version;
        }

        public void setVersion(String version) {
            this.version = version;
        }

        public String getDescription() {
            return description;
        }

        public void setDescription(String description) {
            this.description = description;
        }

        public List<String> getTags() {
            return tags;
        }

        public void setTags(List<String> tags) {
            this.tags = tags;
        }

        public List<DependencySpec> getDependencies() {
            return dependencies;
        }

        public void setDependencies(List<DependencySpec> dependencies) {
            this.dependencies = dependencies;
        }

        public String getInputSchema() {
            return inputSchema;
        }

        public void setInputSchema(String inputSchema) {
            this.inputSchema = inputSchema;
        }

        public String getOutputSchema() {
            return outputSchema;
        }

        public void setOutputSchema(String outputSchema) {
            this.outputSchema = outputSchema;
        }

        public String getInputSchemaCanonical() {
            return inputSchemaCanonical;
        }

        public void setInputSchemaCanonical(String inputSchemaCanonical) {
            this.inputSchemaCanonical = inputSchemaCanonical;
        }

        public String getInputSchemaHash() {
            return inputSchemaHash;
        }

        public void setInputSchemaHash(String inputSchemaHash) {
            this.inputSchemaHash = inputSchemaHash;
        }

        public String getOutputSchemaCanonical() {
            return outputSchemaCanonical;
        }

        public void setOutputSchemaCanonical(String outputSchemaCanonical) {
            this.outputSchemaCanonical = outputSchemaCanonical;
        }

        public String getOutputSchemaHash() {
            return outputSchemaHash;
        }

        public void setOutputSchemaHash(String outputSchemaHash) {
            this.outputSchemaHash = outputSchemaHash;
        }

        public List<String> getSchemaWarnings() {
            return schemaWarnings;
        }

        public void setSchemaWarnings(List<String> schemaWarnings) {
            this.schemaWarnings = schemaWarnings;
        }

        public String getLlmFilter() {
            return llmFilter;
        }

        public void setLlmFilter(String llmFilter) {
            this.llmFilter = llmFilter;
        }

        public String getLlmProvider() {
            return llmProvider;
        }

        public void setLlmProvider(String llmProvider) {
            this.llmProvider = llmProvider;
        }

        public String getKwargs() {
            return kwargs;
        }

        public void setKwargs(String kwargs) {
            this.kwargs = kwargs;
        }
    }

    /**
     * Specification for a dependency required by a tool.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class DependencySpec {
        private String capability;
        private String tags = "[]";
        private String version;

        /** Canonical normalized expected-response schema (consumer side). Issue #547. */
        @JsonProperty("expected_schema_canonical")
        private String expectedSchemaCanonical;

        /** SHA256 hash of expectedSchemaCanonical. Issue #547. */
        @JsonProperty("expected_schema_hash")
        private String expectedSchemaHash;

        /** Schema match mode: "subset", "strict", or null for no schema check. Issue #547. */
        @JsonProperty("match_mode")
        private String matchMode;

        public DependencySpec() {
        }

        public DependencySpec(String capability) {
            this.capability = capability;
        }

        public DependencySpec(String capability, String tags) {
            this.capability = capability;
            this.tags = tags;
        }

        // Builder-style setters

        public DependencySpec capability(String capability) {
            this.capability = capability;
            return this;
        }

        public DependencySpec tags(String tags) {
            this.tags = tags;
            return this;
        }

        public DependencySpec version(String version) {
            this.version = version;
            return this;
        }

        public DependencySpec expectedSchemaCanonical(String expectedSchemaCanonical) {
            this.expectedSchemaCanonical = expectedSchemaCanonical;
            return this;
        }

        public DependencySpec expectedSchemaHash(String expectedSchemaHash) {
            this.expectedSchemaHash = expectedSchemaHash;
            return this;
        }

        public DependencySpec matchMode(String matchMode) {
            this.matchMode = matchMode;
            return this;
        }

        // Standard getters and setters

        public String getCapability() {
            return capability;
        }

        public void setCapability(String capability) {
            this.capability = capability;
        }

        public String getTags() {
            return tags;
        }

        public void setTags(String tags) {
            this.tags = tags;
        }

        public String getVersion() {
            return version;
        }

        public void setVersion(String version) {
            this.version = version;
        }

        public String getExpectedSchemaCanonical() {
            return expectedSchemaCanonical;
        }

        public void setExpectedSchemaCanonical(String expectedSchemaCanonical) {
            this.expectedSchemaCanonical = expectedSchemaCanonical;
        }

        public String getExpectedSchemaHash() {
            return expectedSchemaHash;
        }

        public void setExpectedSchemaHash(String expectedSchemaHash) {
            this.expectedSchemaHash = expectedSchemaHash;
        }

        public String getMatchMode() {
            return matchMode;
        }

        public void setMatchMode(String matchMode) {
            this.matchMode = matchMode;
        }
    }

    /**
     * Specification for an LLM agent function.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class LlmAgentSpec {
        @JsonProperty("function_id")
        private String functionId;

        private String provider;
        private String filter;

        @JsonProperty("filter_mode")
        private String filterMode = "all";

        @JsonProperty("max_iterations")
        private int maxIterations = 1;

        public LlmAgentSpec() {
        }

        public LlmAgentSpec(String functionId, String provider) {
            this.functionId = functionId;
            this.provider = provider;
        }

        // Builder-style setters

        public LlmAgentSpec functionId(String functionId) {
            this.functionId = functionId;
            return this;
        }

        public LlmAgentSpec provider(String provider) {
            this.provider = provider;
            return this;
        }

        public LlmAgentSpec filter(String filter) {
            this.filter = filter;
            return this;
        }

        public LlmAgentSpec filterMode(String filterMode) {
            this.filterMode = filterMode;
            return this;
        }

        public LlmAgentSpec maxIterations(int maxIterations) {
            this.maxIterations = maxIterations;
            return this;
        }

        // Standard getters and setters

        public String getFunctionId() {
            return functionId;
        }

        public void setFunctionId(String functionId) {
            this.functionId = functionId;
        }

        public String getProvider() {
            return provider;
        }

        public void setProvider(String provider) {
            this.provider = provider;
        }

        public String getFilter() {
            return filter;
        }

        public void setFilter(String filter) {
            this.filter = filter;
        }

        public String getFilterMode() {
            return filterMode;
        }

        public void setFilterMode(String filterMode) {
            this.filterMode = filterMode;
        }

        public int getMaxIterations() {
            return maxIterations;
        }

        public void setMaxIterations(int maxIterations) {
            this.maxIterations = maxIterations;
        }
    }
}
