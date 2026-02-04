package io.mcpmesh.spring;

import io.modelcontextprotocol.common.McpTransportContext;
import io.modelcontextprotocol.json.jackson.JacksonMcpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpStatelessServerFeatures;
import io.modelcontextprotocol.server.McpStatelessSyncServer;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.ServerCapabilities;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import io.modelcontextprotocol.spec.McpSchema.Tool;
import io.modelcontextprotocol.spec.McpSchema.JsonSchema;
import io.modelcontextprotocol.server.transport.HttpServletStatelessServerTransport;
import jakarta.servlet.http.HttpServlet;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.web.servlet.ServletRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.List;
import java.util.Map;

/**
 * MCP Server configuration for MCP Mesh agents.
 *
 * <p>This configuration creates an MCP server that exposes registered
 * {@link MeshToolWrapper} instances as MCP tools. The server uses stateless
 * HTTP transport for direct JSON-RPC communication (no session required).
 *
 * <p>The MCP endpoint is exposed at {@code /mcp} by default.
 *
 * <p>Stateless transport enables:
 * <ul>
 *   <li>Direct POST requests without session establishment</li>
 *   <li>Compatibility with meshctl call command</li>
 *   <li>Consistent behavior with Python/TypeScript SDKs</li>
 *   <li>Simpler load balancing (no sticky sessions)</li>
 * </ul>
 *
 * @see MeshToolWrapperRegistry
 * @see MeshToolWrapper
 */
@Configuration
@ConditionalOnBean(MeshToolWrapperRegistry.class)
public class MeshMcpServerConfiguration {

    private static final Logger log = LoggerFactory.getLogger(MeshMcpServerConfiguration.class);

    private static final String MCP_ENDPOINT = "/mcp";

    // MCP SDK uses Jackson 2 (com.fasterxml.jackson), not Jackson 3 (tools.jackson)
    private final com.fasterxml.jackson.databind.ObjectMapper mcpObjectMapper;

    public MeshMcpServerConfiguration() {
        // Create Jackson 2 ObjectMapper for MCP SDK compatibility
        this.mcpObjectMapper = new com.fasterxml.jackson.databind.ObjectMapper();
    }

    /**
     * Create the stateless HTTP transport for MCP.
     *
     * <p>Stateless transport allows direct JSON-RPC POST requests without
     * session establishment, matching the behavior of Python FastMCP.
     */
    @Bean
    @ConditionalOnMissingBean
    public HttpServletStatelessServerTransport mcpStatelessTransport() {
        JacksonMcpJsonMapper jsonMapper = new JacksonMcpJsonMapper(mcpObjectMapper);
        return HttpServletStatelessServerTransport.builder()
            .jsonMapper(jsonMapper)
            .messageEndpoint(MCP_ENDPOINT)
            .build();
    }

    /**
     * Create the stateless MCP server with all registered tools.
     */
    @Bean
    @ConditionalOnMissingBean
    public McpStatelessSyncServer mcpStatelessServer(
            HttpServletStatelessServerTransport transport,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshProperties properties) {

        String agentName = properties.getAgent().getName();
        String agentVersion = properties.getAgent().getVersion();

        McpStatelessSyncServer server = McpServer.sync(transport)
            .serverInfo(agentName != null ? agentName : "mcp-mesh-agent",
                       agentVersion != null ? agentVersion : "1.0.0")
            .capabilities(ServerCapabilities.builder()
                .tools(true)
                .build())
            .build();

        // Register all tools from wrapper registry (includes both @MeshTool and @MeshLlmProvider)
        for (McpToolHandler handler : wrapperRegistry.getAllHandlers()) {
            registerTool(server, handler);
        }

        log.info("Stateless MCP server initialized with {} tools for agent '{}'",
            wrapperRegistry.getAllHandlers().size(), agentName);
        return server;
    }

    /**
     * Register a servlet for the MCP stateless transport.
     */
    @Bean
    @ConditionalOnMissingBean(name = "mcpServletRegistration")
    public ServletRegistrationBean<HttpServlet> mcpServletRegistration(
            HttpServletStatelessServerTransport transport) {

        ServletRegistrationBean<HttpServlet> registration =
            new ServletRegistrationBean<>(transport, MCP_ENDPOINT);
        registration.setName("mcpServlet");
        registration.setLoadOnStartup(1);

        log.info("Registered stateless MCP servlet at {}", MCP_ENDPOINT);
        return registration;
    }

    /**
     * Register a McpToolHandler as an MCP tool specification.
     */
    private void registerTool(McpStatelessSyncServer server, McpToolHandler handler) {
        // Use method name as tool name to match what registry advertises
        String toolName = handler.getMethodName();
        String description = handler.getDescription();
        Map<String, Object> inputSchema = handler.getInputSchema();

        // Create JsonSchema from input schema map
        JsonSchema jsonSchema = createJsonSchema(inputSchema);

        // Create MCP Tool definition using builder
        Tool tool = Tool.builder()
            .name(toolName)
            .description(description)
            .inputSchema(jsonSchema)
            .build();

        // Create tool specification with handler
        McpStatelessServerFeatures.SyncToolSpecification toolSpec =
            new McpStatelessServerFeatures.SyncToolSpecification(
                tool,
                (context, request) -> handleToolCall(handler, request.arguments())
            );

        server.addTool(toolSpec);
        log.debug("Registered MCP tool: {} (capability: {}, funcId: {})",
            toolName, handler.getCapability(), handler.getFuncId());
    }

    /**
     * Create a JsonSchema from a schema map.
     */
    @SuppressWarnings("unchecked")
    private JsonSchema createJsonSchema(Map<String, Object> schemaMap) {
        String type = (String) schemaMap.getOrDefault("type", "object");
        Map<String, Object> properties = (Map<String, Object>) schemaMap.get("properties");
        List<String> required = (List<String>) schemaMap.get("required");

        return new JsonSchema(
            type,
            properties,
            required,
            null,  // additionalProperties
            null,  // defs
            null   // definitions
        );
    }

    /**
     * Handle an MCP tool call by invoking the handler.
     */
    private CallToolResult handleToolCall(McpToolHandler handler, Map<String, Object> args) {
        try {
            log.debug("MCP tool call: {} with args: {}", handler.getCapability(), args);

            // Invoke the handler
            Object result = handler.invoke(args);

            // Serialize result to JSON
            String resultJson;
            if (result == null) {
                resultJson = "null";
            } else if (result instanceof String) {
                resultJson = (String) result;
            } else {
                resultJson = mcpObjectMapper.writeValueAsString(result);
            }

            // Return as text content
            return new CallToolResult(
                List.of(new TextContent(resultJson)),
                false  // isError
            );

        } catch (Exception e) {
            log.error("Tool call failed for {}: {}", handler.getCapability(), e.getMessage(), e);

            // Return error result
            return new CallToolResult(
                List.of(new TextContent("Error: " + e.getMessage())),
                true  // isError
            );
        }
    }
}
