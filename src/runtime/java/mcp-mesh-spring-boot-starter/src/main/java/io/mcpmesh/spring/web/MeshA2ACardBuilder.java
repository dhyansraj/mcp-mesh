package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshToolRegistry;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.core.type.TypeReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Builds A2A v1.0 AgentCard JSON for {@code GET {path}/.well-known/agent.json}
 * (spec §3).
 *
 * <p>One card is rendered per {@code @MeshA2A} surface — multi-skill grouping
 * under a single card is v2 scope (spec Appendix B item 1). Auto-populates
 * from:
 *
 * <ul>
 *   <li>the surface's {@link MeshA2A} metadata directly (skill id, name,
 *       description, tags);</li>
 *   <li>the {@code @MeshTool} input-schema of the declared dependencies, when
 *       one of them happens to be a local tool whose schema is in
 *       {@link MeshToolRegistry} — surfaced under
 *       {@code skills[0].metadata.input_schema} (optional in spec; useful
 *       for downstream tooling like LangGraph).</li>
 * </ul>
 *
 * <p>Mirrors Python's {@code _mcp_mesh.engine.a2a_card.build_agent_card}.
 */
public class MeshA2ACardBuilder {

    private static final Logger log = LoggerFactory.getLogger(MeshA2ACardBuilder.class);

    /**
     * A2A v1.0 default input modes. Materialised at card-render time (not at
     * heartbeat-emit time per spec §2.1).
     */
    public static final List<String> DEFAULT_INPUT_MODES = List.of("application/json");

    /**
     * A2A v1.0 default output modes. Materialised at card-render time.
     */
    public static final List<String> DEFAULT_OUTPUT_MODES = List.of("application/json");

    private final MeshToolRegistry toolRegistry;
    private final ObjectMapper objectMapper;

    public MeshA2ACardBuilder(MeshToolRegistry toolRegistry, ObjectMapper objectMapper) {
        this.toolRegistry = toolRegistry;
        this.objectMapper = objectMapper;
    }

    /**
     * Build the agent card JSON for {@code surface}.
     *
     * @param surface        the registered surface metadata
     * @param agentName      the mesh agent display name (defaults to
     *                       {@code "agent"} when blank; mirrors Python's
     *                       fallback in {@code a2a.py:340-344})
     * @param agentVersion   the agent version string ({@code "1.0.0"} by
     *                       convention)
     * @param agentDescription free-form agent description; falls back to
     *                         {@code agentName} on the card (spec §3.2)
     * @param publicUrl      the registry-stamped public FQDN for
     *                       {@code POST {path}}, or {@code null} when the
     *                       registry has not stamped one yet — the
     *                       {@code url} field is OMITTED rather than emitted
     *                       as an empty string (spec §3.2 + conformance
     *                       checklist)
     * @return a {@link LinkedHashMap} ready for JSON serialization with
     *     deterministic key order
     */
    public Map<String, Object> build(
            MeshA2ARegistry.SurfaceMetadata surface,
            String agentName,
            String agentVersion,
            String agentDescription,
            String publicUrl) {

        String name = (agentName != null && !agentName.isBlank()) ? agentName : "agent";
        String version = (agentVersion != null && !agentVersion.isBlank()) ? agentVersion : "1.0.0";
        String description = (agentDescription != null && !agentDescription.isBlank())
            ? agentDescription : name;

        Map<String, Object> skill = new LinkedHashMap<>();
        skill.put("id", surface.skillId());
        skill.put("name", surface.skillName());
        skill.put("description",
            surface.description().isEmpty() ? surface.skillName() : surface.description());
        skill.put("tags", new ArrayList<>(surface.tags()));
        skill.put("inputModes", new ArrayList<>(DEFAULT_INPUT_MODES));
        skill.put("outputModes", new ArrayList<>(DEFAULT_OUTPUT_MODES));

        Map<String, Object> underlyingInputSchema = locateUnderlyingInputSchema(surface);
        if (underlyingInputSchema != null) {
            skill.put("metadata", Map.of("input_schema", underlyingInputSchema));
        }

        Map<String, Object> capabilities = new LinkedHashMap<>();
        // Spec §3.2: capabilities.streaming MUST be true. Even in Chunk 1A
        // (sync only) we advertise streaming=true so the wire shape matches
        // Python — Chunk 1B will wire the real SSE handlers behind it.
        capabilities.put("streaming", true);
        capabilities.put("pushNotifications", false);
        capabilities.put("stateTransitionHistory", false);

        Map<String, Object> card = new LinkedHashMap<>();
        card.put("name", name);
        card.put("description", description);
        card.put("version", version);
        card.put("capabilities", capabilities);
        card.put("defaultInputModes", new ArrayList<>(DEFAULT_INPUT_MODES));
        card.put("defaultOutputModes", new ArrayList<>(DEFAULT_OUTPUT_MODES));
        card.put("skills", List.of(skill));

        if (publicUrl != null && !publicUrl.isBlank()) {
            card.put("url", publicUrl);
        }

        // Spec §3.2 / §6.1: authentication.schemes is a list of scheme
        // names. For bearer-token surfaces we emit ["bearer"]; otherwise an
        // empty list (NOT "none" — A2A v1.0 has no "none" scheme).
        Map<String, Object> authentication = new LinkedHashMap<>();
        if (surface.bearerAuth()) {
            authentication.put("schemes", List.of("bearer"));
        } else {
            authentication.put("schemes", List.of());
        }
        card.put("authentication", authentication);

        return card;
    }

    /**
     * Try to pull the local {@code @MeshTool} input schema for the first
     * declared dependency that happens to be a tool registered on this
     * process. Returns {@code null} when no dependency resolves to a local
     * tool — cross-agent dependencies don't carry schema info on the
     * decorator at registration time, so the card simply omits
     * {@code skills[0].metadata.input_schema} in that case (spec §3.2:
     * SHOULD-emit, not MUST-emit).
     */
    private Map<String, Object> locateUnderlyingInputSchema(MeshA2ARegistry.SurfaceMetadata surface) {
        if (toolRegistry == null) {
            return null;
        }
        for (MeshRouteRegistry.DependencySpec dep : surface.dependencies()) {
            MeshToolRegistry.ToolMetadata tool = toolRegistry.getTool(dep.getCapability());
            if (tool != null && tool.inputSchema() != null && !tool.inputSchema().isEmpty()) {
                return new LinkedHashMap<>(tool.inputSchema());
            }
        }
        return null;
    }

    /**
     * Convenience: compute a local-fallback URL when no public FQDN is
     * available yet. Format: {@code http://{host}:{port}{path}}. Mirrors
     * Python's {@code _local_fallback_url} (mesh/a2a.py:236-247) — sufficient
     * for local dev / CI before the first heartbeat round-trip.
     */
    public static String localFallbackUrl(String host, int port, String path) {
        if (host == null || host.isBlank() || port <= 0) {
            return null;
        }
        // IPv6 literals (e.g. "::1") must be wrapped in brackets when paired
        // with a port — otherwise the result is an ambiguous, invalid URL like
        // "http://::1:9090/...". Detect by colon-presence: an IPv6 literal
        // contains at least one ":" and is NOT already bracketed.
        String hostPart = host;
        if (host.indexOf(':') >= 0 && host.charAt(0) != '[') {
            hostPart = "[" + host + "]";
        }
        return "http://" + hostPart + ":" + port + path;
    }

    /**
     * Convert a card map to its canonical JSON string form. Provided as a
     * helper for the dispatcher (which writes it to the HTTP response body)
     * and for tests.
     */
    public String toJson(Map<String, Object> card) {
        try {
            return objectMapper.writeValueAsString(card);
        } catch (Exception e) {
            // Rethrow so the dispatcher returns a real 5xx — silently shipping
            // "{}" hides serialization bugs and produces an A2A-invalid card.
            log.warn("Failed to serialize A2A agent card: {}", e.getMessage());
            throw new RuntimeException("Failed to serialize A2A agent card", e);
        }
    }

    /**
     * Helper for tests: parse a JSON string into a generic map. Kept out of
     * the hot path; the dispatcher always serializes outgoing cards directly.
     */
    public Map<String, Object> parseCard(String json) {
        try {
            return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            throw new RuntimeException("Failed to parse agent card JSON", e);
        }
    }
}
