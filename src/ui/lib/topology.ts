import dagre from "dagre";
import { type Node, type Edge } from "@xyflow/react";
import { Agent, DependencyResolution } from "./types";
import { groupKeyOf, aggregateStatus } from "./agent-group";
import { EDGE_COLORS } from "./edge-palette";

// Returns the canonical grouping key for an agent — the declared `agent.name`
// (falling back to the full id when empty). Replica bucketing keys off this
// name, which aligns with the registry's edge/trace stat keys (accumulator.go
// keys by the declared agent name).
export function getAgentBaseName(agent: Agent): string {
  return groupKeyOf(agent);
}

// Group key used for collapsed (multi-replica) nodes.
function groupKey(base: string): string {
  return `group:${base}`;
}

interface GroupInfo {
  base: string;
  instances: Agent[];
}

// Bucket agents by base name and return base -> group info map.
function bucketAgents(agents: Agent[]): Map<string, GroupInfo> {
  const buckets = new Map<string, GroupInfo>();
  for (const a of agents) {
    const base = getAgentBaseName(a);
    const existing = buckets.get(base);
    if (existing) {
      existing.instances.push(a);
    } else {
      buckets.set(base, { base, instances: [a] });
    }
  }
  return buckets;
}

// Given a set of agents, compute mapping from agent ID to either a group key
// (when the agent belongs to a group of >=2 replicas) or its own ID (single).
function buildIdToNodeKeyFromBuckets(buckets: Map<string, GroupInfo>): Map<string, string> {
  const idMap = new Map<string, string>();
  for (const { base, instances } of buckets.values()) {
    if (instances.length >= 2) {
      const key = groupKey(base);
      for (const inst of instances) {
        idMap.set(inst.id, key);
      }
    } else {
      idMap.set(instances[0].id, instances[0].id);
    }
  }
  return idMap;
}

// Public helper: map each agent's full ID to its node key in the collapsed
// topology graph. Single agents map to their own ID; replicas of a base name
// all map to the shared `group:<base>` key. Callers outside topology.ts use
// this to resolve edge endpoints and highlight neighbors.
export function buildIdToNodeKey(agents: Agent[]): Map<string, string> {
  return buildIdToNodeKeyFromBuckets(bucketAgents(agents));
}

// Compute a structural fingerprint: sorted node keys + sorted edge pairs.
// Node keys already account for grouping, so the hash is stable as long as
// the collapsed structure is identical.
export function computeStructureHash(agents: Agent[]): string {
  const buckets = bucketAgents(agents);
  const idMap = buildIdToNodeKeyFromBuckets(buckets);

  const nodeKeys = Array.from(new Set(idMap.values())).sort();

  // Edge discriminator keys mirror the addEdge key format (kind|src|dst|label)
  // so the structural hash changes when, e.g., a new capability is added to
  // an existing src->dst pair.
  const edgePairs: string[] = [];
  for (const agent of agents) {
    const src = idMap.get(agent.id);
    if (!src) continue;
    for (const dep of agent.dependency_resolutions ?? []) {
      if (dep.provider_agent_id) {
        const dst = idMap.get(dep.provider_agent_id);
        if (dst) edgePairs.push(`dep|${src}|${dst}|${dep.capability}`);
      }
    }
    for (const llm of agent.llm_tool_resolutions ?? []) {
      if (llm.provider_agent_id) {
        const dst = idMap.get(llm.provider_agent_id);
        if (dst) edgePairs.push(`llm|${src}|${dst}|${llm.filter_capability}`);
      }
    }
    for (const prov of agent.llm_provider_resolutions ?? []) {
      if (prov.provider_agent_id) {
        const dst = idMap.get(prov.provider_agent_id);
        if (dst) edgePairs.push(`prov|${src}|${dst}|${prov.required_capability}`);
      }
    }
  }

  const uniqueEdgePairs = Array.from(new Set(edgePairs)).sort();
  return nodeKeys.join(",") + "|" + uniqueEdgePairs.join(",");
}

// Per-agent index of the capabilities declared `task=true` — the MeshJob
// producers. Keyed by the FULL agent id (not the node key) because a dependency
// resolution names the exact provider instance it resolved to, which may be one
// replica of a collapsed group.
//
// Built from the same `agents` array the edge loop walks, so a provider that is
// not in the snapshot simply has no entry and its edge is coloured as an
// ordinary dependency. That is also the pre-registry-support case: `task` is
// absent on older registries, and absent must mean "not a job".
interface TaskIndexEntry {
  /**
   * `capability.function_name` — the precise key. A resolution's `mcp_tool` is
   * written from the winning capability's function name (registry:
   * resolver.go picks `cap.FunctionName`, ent_service.go emits it as
   * `mcp_tool`), so the two are the same column and match exactly.
   */
  functions: Set<string>;
  /**
   * `capability.name`. Only consulted when a resolution carries no `mcp_tool`,
   * which is every resolution from a registry predating that field. Ambiguous
   * by nature: one capability name may be declared on two functions of the
   * same agent, distinguished by tags, and only one of them may be a job.
   */
  names: Set<string>;
}

function buildTaskCapabilityIndex(agents: Agent[]): Map<string, TaskIndexEntry> {
  const index = new Map<string, TaskIndexEntry>();
  for (const agent of agents) {
    const entry: TaskIndexEntry = { functions: new Set(), names: new Set() };
    for (const cap of agent.capabilities ?? []) {
      if (cap.task === true) {
        entry.functions.add(cap.function_name);
        entry.names.add(cap.name);
      }
    }
    // Written unconditionally, so a duplicated agent id is LAST WINS rather
    // than last-non-empty-wins. A snapshot should never carry an id twice, but
    // if it does, the later record is the one that describes the agent — the
    // same rule every other id-keyed map in this file follows. Skipping empty
    // entries would let a stale earlier copy keep colouring edges as jobs after
    // the capability stopped being one.
    index.set(agent.id, entry);
  }
  return index;
}

// Whether a resolved dependency landed on a `task=true` capability, i.e. is a
// MeshJob invocation rather than an ordinary call.
function resolvesToJob(
  index: Map<string, TaskIndexEntry>,
  providerAgentId: string,
  dep: DependencyResolution
): boolean {
  const entry = index.get(providerAgentId);
  if (!entry) return false;
  // `mcp_tool` names the exact function the dependency resolved to, so when it
  // is on the wire it decides on its own — falling back to the capability name
  // here would re-admit the ambiguity it exists to settle.
  if (dep.mcp_tool) return entry.functions.has(dep.mcp_tool);
  return entry.names.has(dep.capability);
}

export function buildGraphFromAgents(agents: Agent[]): { nodes: Node[]; edges: Edge[] } {
  const buckets = bucketAgents(agents);
  const idMap = buildIdToNodeKeyFromBuckets(buckets);
  const taskCapabilities = buildTaskCapabilityIndex(agents);

  // Build nodes: one per group (collapsed) or single agent.
  const nodes: Node[] = [];
  for (const { base, instances } of buckets.values()) {
    if (instances.length >= 2) {
      const aggDepsTotal = instances.reduce((sum, a) => sum + (a.total_dependencies ?? 0), 0);
      const aggDepsResolved = instances.reduce((sum, a) => sum + (a.dependencies_resolved ?? 0), 0);
      nodes.push({
        id: groupKey(base),
        type: "agentNode",
        position: { x: 0, y: 0 },
        data: {
          kind: "group",
          name: base,
          instances,
          status: aggregateStatus(instances),
          total_dependencies: aggDepsTotal,
          dependencies_resolved: aggDepsResolved,
        },
      });
    } else {
      nodes.push({
        id: instances[0].id,
        type: "agentNode",
        position: { x: 0, y: 0 },
        data: { kind: "single", agent: instances[0] },
      });
    }
  }

  const validNodeKeys = new Set(nodes.map((n) => n.id));

  // Build edges then dedupe by (source,target,kind,label) after rewrite.
  // Edge merging note: when multiple replicas' edges collapse into one, we keep
  // the first seen edge's base style/label and let downstream edge-stats merge
  // update the label/stroke. This is a simplification — latency/call stats are
  // not summed here because edgeStats are keyed by base name (extractAgentName),
  // which already aligns with the group node ID. See mergeEdgeStatsIntoEdges
  // in TopologyGraph.tsx.
  type EdgeKind = "dep" | "llm" | "prov";
  const edgeMap = new Map<string, Edge>();

  function addEdge(kind: EdgeKind, src: string, dst: string, label: string, base: Edge) {
    const key = `${kind}|${src}|${dst}|${label}`;
    const existing = edgeMap.get(key);
    if (!existing) {
      edgeMap.set(key, base);
      return;
    }
    // Worst-of merge: when replicas collapse into one collapsed group edge,
    // prefer the degraded edge style (dashed/unresolved/unavailable) over the
    // healthy animated style so the group edge reflects any failing replica.
    // Healthy edges are animated with no strokeDasharray; degraded edges are
    // non-animated and/or dashed.
    const existingHealthy =
      existing.animated === true && !existing.style?.strokeDasharray;
    const incomingHealthy =
      base.animated === true && !base.style?.strokeDasharray;
    if (existingHealthy && !incomingHealthy) {
      edgeMap.set(key, { ...existing, animated: base.animated, style: base.style });
      return;
    }
    // Two DEGRADED contributions can disagree too, and the worst-of rule above
    // cannot separate them: it compares animation and dashes to decide which is
    // degraded, and both of these are. One replica's dependency landed on a
    // provider that is no longer healthy; another's matched nothing at all. The
    // gap sits exactly between the two cases that ARE order-independent — the
    // healthy-vs-degraded merge above and the job escalation below — so first
    // seen would win by snapshot order, and the same mesh could draw this edge
    // either way from one poll to the next as the agents array is reordered.
    //
    // UNAVAILABLE WINS, in the same direction as both neighbouring rules: it is
    // this palette's broader degraded signal, the one llm and prov edges stroke
    // for BOTH of their degraded states, which is what the legend row saying
    // "Unavailable — or LLM unresolved" describes. The other style is the narrow
    // claim that nothing satisfies the dependency yet, asserted for dep edges
    // alone, and it should only be shown when that is true of every replica
    // behind a collapsed edge — one replica having matched a provider is
    // evidence that something does satisfy it.
    //
    // Not reachable from a registry snapshot as things stand: a resolution is
    // only given a provider_agent_id when it resolves (ent_service.go writes the
    // id and "available" together, or neither), and the one transition that
    // keeps that id afterwards sets "unavailable"
    // (UpdateDependencyStatusOnAgentOffline). The edge loop skips a dep with no
    // provider id, so the pair cannot meet here today. Written as a rule anyway
    // — it is an invariant of a different process, this file cannot enforce it,
    // and nothing here would notice it being relaxed.
    const existingUnresolved = existing.style?.stroke === EDGE_COLORS.unresolved;
    const incomingUnavailable = base.style?.stroke === EDGE_COLORS.unavailable;
    if (!existingHealthy && !incomingHealthy && existingUnresolved && incomingUnavailable) {
      edgeMap.set(key, { ...existing, animated: base.animated, style: base.style });
      return;
    }
    // Two healthy contributions can now disagree on COLOUR, which they never
    // could while colour was a property of the caller: the caller is the same
    // agent for both, but the providers are two replicas that may disagree
    // about whether the resolved capability is a task — a half-rolled-out
    // change, or a mixed-version group. The merge above compares animation and
    // dashes only, so first-seen would have won by snapshot order.
    //
    // The job colour escalates, matching the worst-of rule's direction: a
    // collapsed edge is drawn as a job when ANY replica behind it is one,
    // because calling into that group can land on the long-running instance.
    // Order-independent by construction.
    if (
      existingHealthy &&
      incomingHealthy &&
      base.style?.stroke === EDGE_COLORS.job &&
      existing.style?.stroke !== EDGE_COLORS.job
    ) {
      edgeMap.set(key, { ...existing, style: base.style });
    }
  }

  for (const agent of agents) {
    const src = idMap.get(agent.id);
    if (!src || !validNodeKeys.has(src)) continue;

    for (const dep of agent.dependency_resolutions ?? []) {
      if (!dep.provider_agent_id) continue;
      const dst = idMap.get(dep.provider_agent_id);
      if (!dst || !validNodeKeys.has(dst)) continue;

      // Coloured by WHAT IS BEING CALLED (issue #1521): the provider's matching
      // capability decides, not the caller. A `task=true` capability is a
      // MeshJob invocation rather than an ordinary call, and that is a property
      // of the callee alone.
      const availableColor = resolvesToJob(taskCapabilities, dep.provider_agent_id, dep)
        ? EDGE_COLORS.job
        : EDGE_COLORS.dependency;
      const label = dep.capability;
      addEdge("dep", src, dst, label, {
        id: `dep|${src}|${dst}|${label}`,
        source: src,
        target: dst,
        label,
        animated: dep.status === "available",
        data: { originalLabel: label },
        style: {
          stroke:
            dep.status === "available"
              ? availableColor
              : dep.status === "unavailable"
                ? EDGE_COLORS.unavailable
                : EDGE_COLORS.unresolved,
          strokeDasharray: dep.status === "unresolved" ? "5 5" : undefined,
        },
      });
    }

    for (const llm of agent.llm_tool_resolutions ?? []) {
      if (!llm.provider_agent_id) continue;
      const dst = idMap.get(llm.provider_agent_id);
      if (!dst || !validNodeKeys.has(dst)) continue;

      // The job colour is scoped to dependency edges ON PURPOSE. An
      // `@mesh.llm(filter=...)` tool can resolve onto a `task=true` capability,
      // and this edge stays the LLM-tool colour when it does: the edge kind is
      // what the reader is being told here — a model reaching for a tool — and
      // that is a different fact from how the callee runs. The kind is decided
      // before the callee is consulted, so no `task` lookup happens on this
      // path at all.
      const label = `llm:${llm.filter_capability}`;
      addEdge("llm", src, dst, label, {
        id: `llm|${src}|${dst}|${label}`,
        source: src,
        target: dst,
        label,
        animated: llm.status === "available",
        data: { originalLabel: label },
        style: {
          stroke: llm.status === "available" ? EDGE_COLORS.llmTool : EDGE_COLORS.unavailable,
          strokeDasharray: llm.status !== "available" ? "5 5" : undefined,
        },
      });
    }

    for (const prov of agent.llm_provider_resolutions ?? []) {
      if (!prov.provider_agent_id) continue;
      const dst = idMap.get(prov.provider_agent_id);
      if (!dst || !validNodeKeys.has(dst)) continue;

      const label = `provider:${prov.required_capability}`;
      addEdge("prov", src, dst, label, {
        id: `prov|${src}|${dst}|${label}`,
        source: src,
        target: dst,
        label,
        animated: prov.status === "available",
        data: { originalLabel: label },
        style: {
          stroke: prov.status === "available" ? EDGE_COLORS.llmProvider : EDGE_COLORS.unavailable,
          strokeDasharray: prov.status !== "available" ? "5 5" : undefined,
        },
      });
    }
  }

  const edges: Edge[] = Array.from(edgeMap.values());

  return applyDagreLayout(nodes, edges);
}

function applyDagreLayout(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  if (nodes.length === 0) return { nodes, edges };

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 80, ranksep: 100, marginx: 40, marginy: 40 });

  const nodeWidth = 280;
  // Slightly taller than the visual node to add vertical spacing between rows
  const nodeHeight = 140;

  for (const node of nodes) {
    g.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const layoutedNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: {
        x: pos.x - nodeWidth / 2,
        y: pos.y - nodeHeight / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}
