import { Agent } from "./types";

// A collapsed view of one logical agent and all of its running replicas.
// The canonical grouping key is the declared agent name (`agent.name`), which
// aligns with the registry's edge/trace stat keys. Replicas of the same name
// collapse into a single group; a lone instance is a group of one.
export interface AgentGroup {
  /** Canonical key = agent.name (falls back to agent.id when name is empty). */
  name: string;
  /** All instances in the (already health-filtered) set, newest first. */
  instances: Agent[];
  replicaCount: number;
  /** Worst-of across instances: unhealthy > unknown > healthy. */
  aggregateStatus: "healthy" | "unhealthy" | "unknown";
  /**
   * Newest instance by last_seen (tie: created_at). Source of the runtime,
   * type, version, description, capabilities and badges shown for the group.
   */
  representative: Agent;
  /** Σ total_dependencies across instances. */
  totalDependencies: number;
  /** Σ dependencies_resolved across instances. */
  dependenciesResolved: number;
  /** Unique, non-empty endpoint values across instances (for drill-in). */
  endpoints: string[];
  /** Most-recent last_seen across instances, if any instance reported one. */
  lastSeen?: string;
}

// Canonical grouping key for an agent: the declared name, falling back to the
// full id when the name is empty (older/degenerate registrations).
export function groupKeyOf(agent: Agent): string {
  return agent.name || agent.id;
}

// Worst-of aggregation for a group's status.
// Any unhealthy -> unhealthy; else any unknown -> unknown; else healthy.
export function aggregateStatus(
  instances: Agent[],
): "healthy" | "unhealthy" | "unknown" {
  let hasUnknown = false;
  for (const a of instances) {
    if (a.status === "unhealthy") return "unhealthy";
    if (a.status === "unknown") hasUnknown = true;
  }
  return hasUnknown ? "unknown" : "healthy";
}

// Recency comparator: newest first by last_seen, tie-broken by created_at.
// Missing timestamps sort last (treated as the empty string). ISO-8601 strings
// compare correctly lexicographically.
function byRecencyDesc(a: Agent, b: Agent): number {
  const la = a.last_seen ?? "";
  const lb = b.last_seen ?? "";
  if (la !== lb) return la < lb ? 1 : -1;
  const ca = a.created_at ?? "";
  const cb = b.created_at ?? "";
  if (ca !== cb) return ca < cb ? 1 : -1;
  return 0;
}

// Collapse a health-filtered agent set into one group per canonical name.
// Groups are sorted by name (localeCompare); instances within a group are
// sorted newest-first by last_seen (tie: created_at).
export function groupAgentsByName(agents: Agent[]): AgentGroup[] {
  const buckets = new Map<string, Agent[]>();
  for (const a of agents) {
    const key = groupKeyOf(a);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(a);
    else buckets.set(key, [a]);
  }

  const groups: AgentGroup[] = [];
  for (const [name, raw] of buckets.entries()) {
    const instances = [...raw].sort(byRecencyDesc);
    const totalDependencies = instances.reduce(
      (sum, a) => sum + (a.total_dependencies ?? 0),
      0,
    );
    const dependenciesResolved = instances.reduce(
      (sum, a) => sum + (a.dependencies_resolved ?? 0),
      0,
    );
    const endpoints = Array.from(
      new Set(instances.map((a) => a.endpoint).filter((e): e is string => !!e)),
    );
    const lastSeen = instances.reduce<string | undefined>((max, a) => {
      if (!a.last_seen) return max;
      return !max || a.last_seen > max ? a.last_seen : max;
    }, undefined);

    groups.push({
      name,
      instances,
      replicaCount: instances.length,
      aggregateStatus: aggregateStatus(instances),
      representative: instances[0],
      totalDependencies,
      dependenciesResolved,
      endpoints,
      lastSeen,
    });
  }

  groups.sort((a, b) => a.name.localeCompare(b.name));
  return groups;
}
