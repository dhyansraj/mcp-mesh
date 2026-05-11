/**
 * Builds A2A v1.0 AgentCard JSON for `GET {path}/.well-known/agent.json`
 * (spec §3).
 *
 * One card per surface — multi-skill grouping under a single card is v2
 * scope (spec Appendix B item 1). Mirrors the Python builder
 * `_mcp_mesh.engine.a2a_card.build_agent_card` and Java's
 * `MeshA2ACardBuilder.build`.
 *
 * Auto-populates from the surface's mount config (skill id, name,
 * description, tags) and the resolved `auth` scheme. Cross-agent dependency
 * input schemas are not surfaced today (mirrors Python — Chunk 1B may add
 * `skills[0].metadata.input_schema` when a local `agent.addTool`
 * registration is co-resident).
 */
import type { A2ASurfaceMetadata } from "./registry.js";

/**
 * A2A v1.0 default input modes. Materialised at card-render time (not at
 * heartbeat-emit time per spec §2.1).
 */
export const DEFAULT_INPUT_MODES: readonly string[] = ["application/json"];

/**
 * A2A v1.0 default output modes. Materialised at card-render time.
 */
export const DEFAULT_OUTPUT_MODES: readonly string[] = ["application/json"];

/**
 * Per-render context the SDK supplies to {@link buildAgentCard}. The agent
 * name / version typically come from the API runtime's resolved config; the
 * `publicUrl` is the registry-stamped FQDN cached per `(path, skillId)`,
 * with a local-fallback (`http://{host}:{port}{path}`) when no stamped URL
 * is available yet (spec §2.4).
 */
export interface CardRenderContext {
  /** Agent display name (mirrors `mesh.agent(name=...)` value). */
  readonly agentName: string;
  /** Agent version (semver). Defaults to `"1.0.0"` on the card. */
  readonly agentVersion?: string;
  /** Free-form agent description; falls back to `agentName` on the card. */
  readonly agentDescription?: string;
  /**
   * The producer's public `POST {path}` URL. MUST be omitted (NOT emitted
   * as `""`) when no URL is available — clients should fail loudly rather
   * than chase a blank URL. Resolution order at mount time:
   *   1. Registry-stamped FQDN from {@link A2APublicUrlCache} (populated
   *      from `surface_updated` heartbeat responses).
   *   2. Local-fallback `http://{host}:{port}{path}` per spec §2.4.
   *   3. Omitted (`undefined`) when neither host nor cached URL is known.
   */
  readonly publicUrl?: string;
}

/**
 * Build the agent card JSON for a single surface.
 *
 * The returned plain object is JSON-serializable with deterministic key
 * order (modern JS Maps + plain object literals preserve insertion order
 * per ECMA-262).
 */
export function buildAgentCard(
  surface: A2ASurfaceMetadata,
  ctx: CardRenderContext
): Record<string, unknown> {
  const name =
    ctx.agentName && ctx.agentName.length > 0 ? ctx.agentName : "agent";
  const version =
    ctx.agentVersion && ctx.agentVersion.length > 0 ? ctx.agentVersion : "1.0.0";
  const description =
    ctx.agentDescription && ctx.agentDescription.length > 0
      ? ctx.agentDescription
      : name;

  const skill: Record<string, unknown> = {
    id: surface.skillId,
    name: surface.skillName,
    description:
      surface.description.length > 0 ? surface.description : surface.skillName,
    tags: [...surface.tags],
    inputModes: [...DEFAULT_INPUT_MODES],
    outputModes: [...DEFAULT_OUTPUT_MODES],
  };

  // Spec §3.2: capabilities.streaming MUST be true. Even in Chunk 1A (sync
  // only) we advertise streaming=true so the wire shape matches Python /
  // Java — Chunk 1B wires the real SSE handlers behind it.
  const capabilities: Record<string, unknown> = {
    streaming: true,
    pushNotifications: false,
    stateTransitionHistory: false,
  };

  const card: Record<string, unknown> = {
    name,
    description,
    version,
    capabilities,
    defaultInputModes: [...DEFAULT_INPUT_MODES],
    defaultOutputModes: [...DEFAULT_OUTPUT_MODES],
    skills: [skill],
  };

  if (ctx.publicUrl && ctx.publicUrl.length > 0) {
    card.url = ctx.publicUrl;
  }

  // Spec §3.2 / §6.1: authentication.schemes is a list. For bearer-token
  // surfaces emit ["bearer"]; otherwise an empty list (NOT "none" — A2A
  // v1.0 has no "none" scheme).
  card.authentication = {
    schemes: surface.auth === "bearer" ? ["bearer"] : [],
  };

  return card;
}
