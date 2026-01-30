package io.mcpmesh.spring;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpServerFeatures;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.spec.McpSchema;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.ServerCapabilities;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import io.modelcontextprotocol.spec.McpSchema.Tool;
import io.modelcontextprotocol.server.transport.HttpServletSseServerTransportProvider;
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
 * {@link MeshToolWrapper} instances as MCP tools. The server uses SSE
 * (Server-Sent Events) transport for HTTP communication.
 *
 * <p>The MCP endpoint is exposed at {@code /mcp} by default.
 *
 * @see MeshToolWrapperRegistry
 * @see MeshToolWrapper
 */
@Configuration
@ConditionalOnBean(MeshToolWrapperRegistry.class)
public class MeshMcpServerConfiguration {

    private static final Logger log = LoggerFactory.getLogger(MeshMcpServerConfiguration.class);

    private static final String MCP_ENDPOINT = "/mcp";

    private final ObjectMapper objectMapper;

    public MeshMcpServerConfiguration(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    /**
     * Create the SSE transport provider for MCP.
     */
    @Bean
    @ConditionalOnMissingBean
    public HttpServletSseServerTransportProvider mcpTransportProvider() {
        return new HttpServletSseServerTransportProvider(objectMapper, MCP_ENDPOINT);
    }

    /**
     * Create the MCP sync server with all registered tools.
     */
    @Bean
    @ConditionalOnMissingBean
    public McpSyncServer mcpSyncServer(
            HttpServletSseServerTransportProvider transportProvider,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshProperties properties) {

        String agentName = properties.getAgent().getName();
        String agentVersion = properties.getAgent().getVersion();

        McpSyncServer server = McpServer.sync(transportProvider)
            .serverInfo(agentName != null ? agentName : "mcp-mesh-agent",
                       agentVersion != null ? agentVersion : "1.0.0")
            .capabilities(ServerCapabilities.builder()
                .tools(true)
                .build())
            .build();

        // Register all tools from wrapper registry
        for (MeshToolWrapper wrapper : wrapperRegistry.getAllWrappers()) {
            registerTool(server, wrapper);
        }

        log.info("MCP server initialized with {} tools", wrapperRegistry.size());
        return server;
    }

    /**
     * Register a servlet for the MCP transport provider.
     */
    @Bean
    @ConditionalOnMissingBean(name = "mcpServletRegistration")
    public ServletRegistrationBean<HttpServlet> mcpServletRegistration(
            HttpServletSseServerTransportProvider transportProvider) {

        ServletRegistrationBean<HttpServlet> registration =
            new ServletRegistrationBean<>(transportProvider, MCP_ENDPOINT + "/*");
        registration.setName("mcpServlet");
        registration.setLoadOnStartup(1);

        log.info("Registered MCP servlet at {}", MCP_ENDPOINT);
        return registration;
    }

    /**
     * Register a MeshToolWrapper as an MCP tool specification.
     */
    private void registerTool(McpSyncServer server, MeshToolWrapper wrapper) {
        String capability = wrapper.getCapability();
        String description = wrapper.getDescription();
        Map<String, Object> inputSchema = wrapper.getInputSchema();

        // Convert input schema to JSON string for MCP
        String schemaJson;
        try {
            schemaJson = objectMapper.writeValueAsString(inputSchema);
        } catch (Exception e) {
            schemaJson = "{}";
        }

        // Create MCP Tool definition
        Tool tool = new Tool(capability, description, schemaJson);

        // Create tool specification with handler
        McpServerFeatures.SyncToolSpecification toolSpec =
            new McpServerFeatures.SyncToolSpecification(
                tool,
                (exchange, args) -> handleToolCall(wrapper, args)
            );

        server.addTool(toolSpec);
        log.debug("Registered MCP tool: {} (funcId: {})", capability, wrapper.getFuncId());
    }

    /**
     * Handle an MCP tool call by invoking the wrapper.
     */
    @SuppressWarnings("unchecked")
    private CallToolResult handleToolCall(MeshToolWrapper wrapper, Map<String, Object> args) {
        try {
            log.debug("MCP tool call: {} with args: {}", wrapper.getCapability(), args);

            // Invoke the wrapper
            Object result = wrapper.invoke(args);

            // Serialize result to JSON
            String resultJson;
            if (result == null) {
                resultJson = "null";
            } else if (result instanceof String) {
                resultJson = (String) result;
            } else {
                resultJson = objectMapper.writeValueAsString(result);
            }

            // Return as text content
            return new CallToolResult(
                List.of(new TextContent(resultJson)),
                false  // isError
            );

        } catch (Exception e) {
            log.error("Tool call failed for {}: {}", wrapper.getCapability(), e.getMessage(), e);

            // Return error result
            return new CallToolResult(
                List.of(new TextContent("Error: " + e.getMessage())),
                true  // isError
            );
        }
    }
}
