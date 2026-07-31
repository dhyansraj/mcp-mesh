package io.mcpmesh.spring;

import io.modelcontextprotocol.common.McpTransportContext;
import io.modelcontextprotocol.json.jackson3.JacksonMcpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpStatelessServerFeatures;
import io.modelcontextprotocol.server.McpStatelessSyncServer;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.Content;
import io.modelcontextprotocol.spec.McpSchema.ResourceLink;
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

import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

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

    /**
     * FastMCP's {@code wrap_result} marker (issue #1250/#1251), carried in the
     * CallToolResult {@code meta} field — which the MCP SDK serializes on the
     * wire as {@code _meta}. Signals that {@code structuredContent} is a
     * {@code {"result": <value>}} envelope wrapping a non-object return, so a
     * consumer unwraps the single {@code "result"} key. Byte-identical to the
     * Python provider's {@code {"fastmcp": {"wrap_result": True}}}.
     */
    private static final Map<String, Object> WRAP_RESULT_META =
        Map.of("fastmcp", Map.of("wrap_result", true));

    /** funcId prefix {@code LlmProviderToolWrapper} builds ({@code llm_provider:<capability>}). */
    private static final String LLM_PROVIDER_FUNC_ID_PREFIX = "llm_provider:";

    // MCP SDK 2.0.0 uses Jackson 3 (tools.jackson)
    private final tools.jackson.databind.json.JsonMapper mcpJsonMapper;

    public MeshMcpServerConfiguration() {
        // Create Jackson 3 JsonMapper for MCP SDK 2.0.0
        // Jackson 3 has built-in java.time support and writes dates as ISO-8601 by default
        this.mcpJsonMapper = tools.jackson.databind.json.JsonMapper.builder().build();
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
        JacksonMcpJsonMapper jsonMapper = new JacksonMcpJsonMapper(mcpJsonMapper);
        return HttpServletStatelessServerTransport.builder()
            .jsonMapper(jsonMapper)
            .messageEndpoint(MCP_ENDPOINT)
            .build();
    }

    /**
     * Create the stateless MCP server with all registered tools.
     *
     * <p>Resolves the agent name/version from {@link MeshRuntime#getAgentSpec()}
     * (which has already merged {@code @MeshAgent} annotation values,
     * {@link MeshProperties} defaults, and environment-variable overrides) so
     * the boot log and MCP {@code serverInfo} both reflect the actual agent
     * identity. Reading from {@link MeshProperties} alone would surface
     * {@code null} whenever the user configured their agent only via the
     * {@code @MeshAgent} annotation.
     */
    @Bean
    @ConditionalOnMissingBean
    public McpStatelessSyncServer mcpStatelessServer(
            HttpServletStatelessServerTransport transport,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshRuntime meshRuntime) {

        String agentName = meshRuntime.getAgentSpec().getName();
        String agentVersion = meshRuntime.getAgentSpec().getVersion();

        McpStatelessSyncServer server = McpServer.sync(transport)
            .serverInfo(agentName != null ? agentName : "mcp-mesh-agent",
                       agentVersion != null ? agentVersion : "1.0.0")
            .capabilities(ServerCapabilities.builder()
                .tools(true)
                .build())
            .immediateExecution(true)
            // Preserve mesh's lenient cross-runtime coercion + soft-fail semantics; strictness stays opt-in. Adopting SDK-native input validation is tracked in #1303.
            .validateToolInputs(false)
            .build();

        // Issue #1442: refuse to boot when two declarations would advertise the
        // same MCP tool name. Runs BEFORE any addTool so the agent never comes up
        // half-registered.
        assertUniqueAdvertisedToolNames(wrapperRegistry.getAllHandlers());

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
     * Refuse to boot when two DIFFERENT tool declarations would be advertised
     * under the same MCP tool name (issue #1442).
     *
     * <p>The advertised name is the wire name: a client's {@code tools/call}
     * carries {@code params.name = <the registry's function_name>}, which is
     * exactly {@link McpToolHandler#getMethodName()}. It is a bare method name
     * with no class qualifier, so two {@code @MeshTool} methods named
     * {@code analyze} in different classes claim the same slot — and the MCP SDK
     * (2.0.0) resolves that by silently keeping one, leaving the other tool
     * permanently unreachable even though the registry advertises it.
     *
     * <p>This is the MCP-layer analogue of the duplicate-capability guard in
     * {@link MeshToolRegistry#registerTool}, and it borrows that guard's
     * tolerance: the discriminator is the <b>funcId</b>
     * ({@code FQCN.methodName}), not handler identity. Re-registering the SAME
     * declaration — a prototype-scoped bean instantiated twice, a Spring context
     * refresh, a repeated bean post-processing pass — produces a fresh handler
     * instance for an unchanged funcId, which every other index in
     * {@link MeshToolWrapperRegistry} already replaces without complaint. Only a
     * second, genuinely different declaration throws.
     *
     * <p>The framework's own fixed names are each claimed exactly once per
     * agent, so a normal agent never trips this:
     * <ul>
     *   <li>{@code llm_generate} — one {@code @MeshLlmProvider} class produces
     *       one handler with funcId {@code llm_provider:<capability>}. TWO
     *       provider classes on one agent DO throw, correctly: they would both
     *       advertise {@code llm_generate} and one would be dead on the wire.</li>
     *   <li>{@code __mesh_job_status} / {@code __mesh_job_result} /
     *       {@code __mesh_job_cancel} — {@link JobsHelperToolsRegistrar}
     *       registers one handler per op under the synthetic funcId
     *       {@code __mesh_jobs_helper.<op>}, and the registry is keyed by funcId,
     *       so a repeated registrar pass replaces rather than accumulates.</li>
     * </ul>
     *
     * <p><b>Overloads in ONE class never reach this guard — they are rejected
     * earlier</b> (issue #1448). This scans
     * {@link MeshToolWrapperRegistry#getAllHandlers()}, which is keyed by funcId,
     * and a funcId is {@code FQCN.methodName} with no parameter types, so two
     * overloaded {@code @MeshTool} methods in the same class share one and the
     * second would evict the first from that map before this guard ever sees it.
     * {@link MeshToolWrapperRegistry#registerWrapper} now refuses that at the
     * store site. Widening the funcId would not have helped: both overloads
     * still collapse onto ONE wire name — the bare method name, which keys the
     * MCP tool table, the registry's {@code dependencies_resolved} map and
     * {@code wrappersByMethodName} — and {@code @MeshTool} has no name attribute
     * to separate them.
     *
     * @param handlers every handler about to be registered with the MCP server
     * @throws IllegalStateException naming both colliding declarations
     */
    static void assertUniqueAdvertisedToolNames(Collection<McpToolHandler> handlers) {
        Map<String, String> claimedBy = new LinkedHashMap<>();
        for (McpToolHandler handler : handlers) {
            String toolName = handler.getMethodName();
            if (toolName == null) {
                continue;
            }
            String funcId = handler.getFuncId();
            // containsKey, NOT putIfAbsent: the map permits null values, and
            // putIfAbsent REPLACES a null-valued mapping and returns null — so a
            // name first claimed by a handler with a null funcId would read as
            // unclaimed for every later claimant, and the collision this guard
            // exists to catch would walk straight through. Nothing enforces a
            // non-null funcId: McpToolHandler is a public interface and
            // getFuncId() has no default.
            if (!claimedBy.containsKey(toolName)) {
                claimedBy.put(toolName, funcId);
                continue;
            }
            String previousFuncId = claimedBy.get(toolName);
            if (Objects.equals(previousFuncId, funcId)) {
                // The same declaration re-registered — fine.
                continue;
            }
            throw new IllegalStateException(String.format(
                "Duplicate MCP tool name '%s': advertised by both %s and %s. "
                    + "The MCP tool name is the wire name a client calls "
                    + "(tools/call params.name), so registering it twice leaves one of "
                    + "these tools permanently unreachable. %s",
                toolName, previousFuncId, funcId, remedyFor(previousFuncId, funcId)));
        }
    }

    /**
     * The actionable half of the duplicate-tool-name error. "Rename one of the
     * methods" is wrong advice for an {@code @MeshLlmProvider} collision: there
     * is no method to rename — {@code llm_generate} is a framework constant that
     * every provider wrapper returns from {@code getMethodName()}, so the only
     * fix is to stop hosting two providers on one agent.
     */
    private static String remedyFor(String previousFuncId, String funcId) {
        boolean previousIsProvider = previousFuncId != null
            && previousFuncId.startsWith(LLM_PROVIDER_FUNC_ID_PREFIX);
        boolean incomingIsProvider = funcId != null
            && funcId.startsWith(LLM_PROVIDER_FUNC_ID_PREFIX);
        if (previousIsProvider && incomingIsProvider) {
            return "Both are @MeshLlmProvider classes, and every provider advertises the "
                + "framework's fixed 'llm_generate' tool name — there is no method name to "
                + "change. One agent hosts at most one @MeshLlmProvider: keep one and move "
                + "the other to its own agent.";
        }
        if (previousIsProvider || incomingIsProvider) {
            return "One of them is a @MeshLlmProvider class, which always advertises the "
                + "framework's fixed 'llm_generate' tool name. Rename the @MeshTool method, "
                + "or move the provider to its own agent.";
        }
        return "Rename one of the methods, or move one of the tools to a separate agent.";
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
     * Build the {@code structuredContent} for a serialized tool return,
     * mirroring FastMCP / the Python provider (issue #1282, honoring the
     * #1250/#1251 empty-return contract):
     * <ul>
     *   <li>object-shaped return (a {@code Map} or POJO serializing to a JSON
     *       object) → the object itself, as a {@code Map}, with NO wrap marker;</li>
     *   <li>every non-object return (list/array, scalar number/boolean, string,
     *       {@code null}) → wrapped as {@code {"result": <value>}}, paired with
     *       the {@link #WRAP_RESULT_META} marker (set by the caller).</li>
     * </ul>
     *
     * <p>This produces exactly the emission the Python provider's
     * empty-collection test asserts: {@code []} → {@code {"result": []}} +
     * marker, {@code {}} → {@code {}} (no marker), {@code ""} →
     * {@code {"result": ""}} + marker, {@code null} → {@code {"result": null}}
     * + marker. Shared so any future structured-output path emits identically
     * rather than forking.
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> buildStructuredContent(Object result) {
        if (isObjectShaped(result)) {
            return mcpJsonMapper.convertValue(result, Map.class);
        }
        Map<String, Object> wrapped = new LinkedHashMap<>();
        wrapped.put("result", result);
        return wrapped;
    }

    /**
     * Whether a tool return is object-shaped — i.e. serializes to a JSON object
     * ({@code {...}}) rather than an array, scalar, string, or null. Object
     * returns become {@code structuredContent} directly; everything else is
     * wrapped in a {@code {"result": X}} envelope with the wrap marker, matching
     * FastMCP.
     */
    private boolean isObjectShaped(Object result) {
        if (result == null) {
            return false;
        }
        if (result instanceof Map) {
            return true;
        }
        if (result instanceof Iterable
                || result instanceof CharSequence
                || result instanceof Number
                || result instanceof Boolean
                || result.getClass().isArray()) {
            return false;
        }
        // POJO / other: let Jackson decide by the serialized JSON shape.
        tools.jackson.databind.JsonNode node = mcpJsonMapper.valueToTree(result);
        return node != null && node.isObject();
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
     *
     * <p>Supports three return types from tool handlers:
     * <ul>
     *   <li>{@link CallToolResult} — passed through directly</li>
     *   <li>{@link Content} (e.g., ResourceLink, TextContent) — wrapped in a single-item CallToolResult</li>
     *   <li>Any other object — serialized to JSON and wrapped in TextContent</li>
     * </ul>
     */
    private CallToolResult handleToolCall(McpToolHandler handler, Map<String, Object> args) {
        try {
            log.debug("MCP tool call: {} with args: {}", handler.getCapability(), args);

            // Invoke the handler
            Object result = handler.invoke(args);

            // Pass through CallToolResult directly
            if (result instanceof CallToolResult callToolResult) {
                return callToolResult;
            }

            // Wrap Content subtypes (ResourceLink, TextContent, ImageContent, etc.)
            if (result instanceof Content contentItem) {
                return new CallToolResult(
                    List.of(contentItem),
                    false,  // isError
                    null,   // structuredContent
                    null    // meta
                );
            }

            // Serialize result to JSON
            String resultJson;
            if (result == null) {
                resultJson = "null";
            } else if (result instanceof String) {
                resultJson = (String) result;
            } else {
                resultJson = mcpJsonMapper.writeValueAsString(result);
            }

            // Return as text content, ADDITIONALLY populating structuredContent
            // (issue #1282) so spec-compliant MCP clients — and future
            // structured-first consumers — see the same structured value the
            // Python provider emits via FastMCP. The text block
            // (content[0].text = resultJson) is UNCHANGED: mesh consumers
            // recover text-first (#1250/#1251), so the cross-runtime round-trip
            // stays byte-identical regardless of this additive field.
            Object structuredContent = buildStructuredContent(result);
            Map<String, Object> meta = isObjectShaped(result) ? null : WRAP_RESULT_META;
            return new CallToolResult(
                List.of(new TextContent(resultJson)),
                false,  // isError
                structuredContent,
                meta
            );

        } catch (Exception e) {
            log.error("Tool call failed for {}: {}", handler.getCapability(), e.getMessage(), e);

            // Return error result
            return new CallToolResult(
                List.of(new TextContent("Error: " + e.getMessage())),
                true,   // isError
                null,    // structuredContent
                null     // meta
            );
        }
    }
}
