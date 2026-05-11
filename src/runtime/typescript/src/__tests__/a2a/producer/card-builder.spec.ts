/**
 * Unit tests for `card-builder.ts` (spec §3 + Appendix B item 1).
 *
 * Coverage:
 * - Single skill per card (Appendix B item 1).
 * - `capabilities.streaming === true` (spec §3.2).
 * - Auth schemes: `["bearer"]` vs `[]` (spec §6.1).
 * - Skill metadata populated from surface (id/name/description/tags).
 * - Empty `url` omitted (Appendix A nuance — never emit blank URLs).
 * - Public URL passthrough.
 * - Defaults applied for missing optional fields.
 *
 * Mirrors Java's `MeshA2ACardBuilderTest`.
 */
import { describe, it, expect } from "vitest";

import {
  buildAgentCard,
  DEFAULT_INPUT_MODES,
  DEFAULT_OUTPUT_MODES,
} from "../../../a2a/producer/card-builder.js";
import type { A2ASurfaceMetadata } from "../../../a2a/producer/registry.js";

function makeSurface(
  overrides: Partial<A2ASurfaceMetadata> = {},
): A2ASurfaceMetadata {
  return {
    path: "/agents/date",
    skillId: "get-date",
    skillName: "Get Date",
    description: "Get the current UTC date",
    tags: ["system", "date"],
    dependencies: [],
    auth: "",
    routeId: "route_0_A2A:/agents/date",
    ...overrides,
  };
}

describe("buildAgentCard (spec §3)", () => {
  /** Spec §3.2 + Appendix B item 1: one skill per card. */
  it("emits exactly one skill per card (Appendix B item 1)", () => {
    const card = buildAgentCard(makeSurface(), {
      agentName: "date-agent",
      publicUrl: "https://example.com/agents/date",
    });
    expect(Array.isArray(card.skills)).toBe(true);
    expect((card.skills as unknown[]).length).toBe(1);
  });

  /** Spec §3.2: capabilities.streaming MUST be true (real boolean). */
  it("capabilities.streaming === true (spec §3.2)", () => {
    const card = buildAgentCard(makeSurface(), { agentName: "x" });
    const caps = card.capabilities as Record<string, unknown>;
    expect(caps.streaming).toBe(true);
    // Defensive: not the string "true" or anything truthy-but-non-boolean.
    expect(typeof caps.streaming).toBe("boolean");
  });

  /** Spec §6.1: authentication.schemes === ["bearer"] when auth=bearer. */
  it("authentication.schemes === ['bearer'] when surface.auth==='bearer'", () => {
    const card = buildAgentCard(makeSurface({ auth: "bearer" }), {
      agentName: "x",
    });
    const auth = card.authentication as Record<string, unknown>;
    expect(auth.schemes).toEqual(["bearer"]);
  });

  /** Spec §6.1: authentication.schemes === [] (NOT "none") when no auth. */
  it("authentication.schemes === [] when surface.auth is empty", () => {
    const card = buildAgentCard(makeSurface({ auth: "" }), {
      agentName: "x",
    });
    const auth = card.authentication as Record<string, unknown>;
    expect(auth.schemes).toEqual([]);
  });

  /** Spec §3.2: skill metadata populated from surface. */
  it("populates skill id / name / description / tags from surface", () => {
    const card = buildAgentCard(
      makeSurface({
        skillId: "weather",
        skillName: "Weather Forecast",
        description: "Get forecast for a city",
        tags: ["weather", "forecast", "external"],
      }),
      { agentName: "weather-agent" },
    );
    const skill = (card.skills as Array<Record<string, unknown>>)[0];
    expect(skill.id).toBe("weather");
    expect(skill.name).toBe("Weather Forecast");
    expect(skill.description).toBe("Get forecast for a city");
    expect(skill.tags).toEqual(["weather", "forecast", "external"]);
    expect(skill.inputModes).toEqual([...DEFAULT_INPUT_MODES]);
    expect(skill.outputModes).toEqual([...DEFAULT_OUTPUT_MODES]);
  });

  /** Spec conformance §3.2 + Appendix A: blank url MUST be omitted, not "". */
  it("omits url field when publicUrl is undefined / empty", () => {
    const cardNoUrl = buildAgentCard(makeSurface(), { agentName: "x" });
    expect(Object.prototype.hasOwnProperty.call(cardNoUrl, "url")).toBe(false);

    const cardEmpty = buildAgentCard(makeSurface(), {
      agentName: "x",
      publicUrl: "",
    });
    expect(Object.prototype.hasOwnProperty.call(cardEmpty, "url")).toBe(false);
  });

  /** Spec §3.2: publicUrl passes through to card.url. */
  it("emits the supplied publicUrl as card.url", () => {
    const card = buildAgentCard(makeSurface(), {
      agentName: "x",
      publicUrl: "https://prod.example.com/agents/date",
    });
    expect(card.url).toBe("https://prod.example.com/agents/date");
  });

  /** Defaults: agentName "" → "agent", agentVersion undefined → "1.0.0". */
  it("applies defaults for missing optional context fields", () => {
    const card = buildAgentCard(makeSurface(), { agentName: "" });
    expect(card.name).toBe("agent");
    expect(card.version).toBe("1.0.0");
    // description defaults to name when not supplied
    expect(card.description).toBe("agent");
  });

  /** Skill description falls back to skillName when description is empty. */
  it("falls back skill.description to skillName when empty", () => {
    const card = buildAgentCard(
      makeSurface({ description: "", skillName: "My Skill" }),
      { agentName: "x" },
    );
    const skill = (card.skills as Array<Record<string, unknown>>)[0];
    expect(skill.description).toBe("My Skill");
  });
});
