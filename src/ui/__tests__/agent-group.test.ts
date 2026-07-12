import { describe, it, expect } from "vitest";
import { Agent } from "../lib/types";
import { groupKeyOf, aggregateStatus, groupAgentsByName } from "../lib/agent-group";
import { buildIdToNodeKey } from "../lib/topology";

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "svc-00000000",
    name: "svc",
    agent_type: "mcp_agent",
    status: "healthy",
    endpoint: "http://svc:8080",
    total_dependencies: 0,
    dependencies_resolved: 0,
    capabilities: [],
    ...overrides,
  };
}

describe("groupKeyOf", () => {
  it("uses agent.name as the canonical key", () => {
    expect(groupKeyOf(makeAgent({ name: "fortuna", id: "fortuna-abc12345" }))).toBe("fortuna");
  });

  it("falls back to id when name is empty", () => {
    expect(groupKeyOf(makeAgent({ name: "", id: "legacy-99999999" }))).toBe("legacy-99999999");
  });
});

describe("aggregateStatus", () => {
  it("returns healthy when all instances are healthy", () => {
    expect(aggregateStatus([makeAgent(), makeAgent()])).toBe("healthy");
  });

  it("is worst-of: healthy + unhealthy -> unhealthy", () => {
    expect(
      aggregateStatus([makeAgent({ status: "healthy" }), makeAgent({ status: "unhealthy" })]),
    ).toBe("unhealthy");
  });

  it("is worst-of: healthy + unknown -> unknown", () => {
    expect(
      aggregateStatus([makeAgent({ status: "healthy" }), makeAgent({ status: "unknown" })]),
    ).toBe("unknown");
  });

  it("prefers unhealthy over unknown", () => {
    expect(
      aggregateStatus([makeAgent({ status: "unknown" }), makeAgent({ status: "unhealthy" })]),
    ).toBe("unhealthy");
  });
});

describe("groupAgentsByName", () => {
  it("collapses two instances of the same name into one group of replicaCount 2", () => {
    const groups = groupAgentsByName([
      makeAgent({ name: "fortuna", id: "fortuna-aaaa1111" }),
      makeAgent({ name: "fortuna", id: "fortuna-bbbb2222" }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].name).toBe("fortuna");
    expect(groups[0].replicaCount).toBe(2);
    expect(groups[0].instances).toHaveLength(2);
  });

  it("keeps a single instance as a group of one", () => {
    const groups = groupAgentsByName([makeAgent({ name: "solo", id: "solo-11112222" })]);
    expect(groups).toHaveLength(1);
    expect(groups[0].replicaCount).toBe(1);
    expect(groups[0].representative.id).toBe("solo-11112222");
  });

  it("aggregates status worst-of across instances", () => {
    const groups = groupAgentsByName([
      makeAgent({ name: "svc", id: "svc-1", status: "healthy" }),
      makeAgent({ name: "svc", id: "svc-2", status: "unhealthy" }),
    ]);
    expect(groups[0].aggregateStatus).toBe("unhealthy");
  });

  it("sums dependency totals across instances", () => {
    const groups = groupAgentsByName([
      makeAgent({ name: "svc", id: "svc-1", total_dependencies: 3, dependencies_resolved: 2 }),
      makeAgent({ name: "svc", id: "svc-2", total_dependencies: 4, dependencies_resolved: 4 }),
    ]);
    expect(groups[0].totalDependencies).toBe(7);
    expect(groups[0].dependenciesResolved).toBe(6);
  });

  it("collects unique non-empty endpoints", () => {
    const groups = groupAgentsByName([
      makeAgent({ name: "svc", id: "svc-1", endpoint: "http://a:8080" }),
      makeAgent({ name: "svc", id: "svc-2", endpoint: "http://a:8080" }),
      makeAgent({ name: "svc", id: "svc-3", endpoint: "http://b:8080" }),
      makeAgent({ name: "svc", id: "svc-4", endpoint: "" }),
    ]);
    expect(groups[0].endpoints).toEqual(["http://a:8080", "http://b:8080"]);
  });

  it("picks the most-recent last_seen and newest representative", () => {
    const groups = groupAgentsByName([
      makeAgent({ name: "svc", id: "svc-old", last_seen: "2026-01-01T00:00:00Z" }),
      makeAgent({ name: "svc", id: "svc-new", last_seen: "2026-06-01T00:00:00Z" }),
    ]);
    expect(groups[0].lastSeen).toBe("2026-06-01T00:00:00Z");
    expect(groups[0].representative.id).toBe("svc-new");
    // Instances sorted newest-first.
    expect(groups[0].instances.map((i) => i.id)).toEqual(["svc-new", "svc-old"]);
  });

  it("breaks a last_seen tie by created_at for the representative", () => {
    const groups = groupAgentsByName([
      makeAgent({ name: "svc", id: "svc-a", last_seen: "2026-06-01T00:00:00Z", created_at: "2026-05-01T00:00:00Z" }),
      makeAgent({ name: "svc", id: "svc-b", last_seen: "2026-06-01T00:00:00Z", created_at: "2026-05-10T00:00:00Z" }),
    ]);
    expect(groups[0].representative.id).toBe("svc-b");
  });

  it("groups an empty-name agent under its id", () => {
    const groups = groupAgentsByName([makeAgent({ name: "", id: "legacy-77778888" })]);
    expect(groups[0].name).toBe("legacy-77778888");
    expect(groups[0].replicaCount).toBe(1);
  });

  it("sorts groups by name", () => {
    const groups = groupAgentsByName([
      makeAgent({ name: "zeta", id: "zeta-1" }),
      makeAgent({ name: "alpha", id: "alpha-1" }),
      makeAgent({ name: "media", id: "media-1" }),
    ]);
    expect(groups.map((g) => g.name)).toEqual(["alpha", "media", "zeta"]);
  });
});

describe("buildIdToNodeKey (topology re-key)", () => {
  it("maps two same-name instances' ids to the same group:<name> key", () => {
    const map = buildIdToNodeKey([
      makeAgent({ name: "fortuna", id: "fortuna-aaaa1111" }),
      makeAgent({ name: "fortuna", id: "fortuna-bbbb2222" }),
    ]);
    expect(map.get("fortuna-aaaa1111")).toBe("group:fortuna");
    expect(map.get("fortuna-bbbb2222")).toBe("group:fortuna");
  });

  it("maps a lone instance to its own id (no group collapse)", () => {
    const map = buildIdToNodeKey([makeAgent({ name: "solo", id: "solo-11112222" })]);
    expect(map.get("solo-11112222")).toBe("solo-11112222");
  });
});
