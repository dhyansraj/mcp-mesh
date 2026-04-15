import dagre from "dagre";
import { type Node, type Edge } from "@xyflow/react";
import { Agent } from "./types";
import { extractAgentName } from "./api";

// Returns the base name for an agent by stripping the registry-assigned
// "-{8hex}" suffix from the full agent ID.
//
// Modern SDKs send `name` (base, e.g. "fortuna") and `agent_id` (full, e.g.
// "fortuna-abc12345") as distinct fields. We still derive the base from
// `agent.id` here for two reasons:
//   1. Robustness across SDK versions — older agents collapsed `name == id`,
//      so trusting `name` as the base would mis-group them.
//   2. Single source of truth for display grouping — all replica bucketing
//      happens off the normalized ID suffix, keeping the UI independent of
//      whatever the sending SDK chose to put in `name`.
export function getAgentBaseName(agent: Agent): string {
  return extractAgentName(agent.id);
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

// Worst-of aggregation for group status.
// Any unhealthy -> unhealthy; any unknown -> unknown; else healthy.
function aggregateStatus(instances: Agent[]): "healthy" | "unhealthy" | "unknown" {
  let hasUnknown = false;
  for (const a of instances) {
    if (a.status === "unhealthy") return "unhealthy";
    if (a.status === "unknown") hasUnknown = true;
  }
  return hasUnknown ? "unknown" : "healthy";
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

  const edgePairs: string[] = [];
  for (const agent of agents) {
    const src = idMap.get(agent.id);
    if (!src) continue;
    for (const dep of agent.dependency_resolutions ?? []) {
      if (dep.provider_agent_id) {
        const dst = idMap.get(dep.provider_agent_id);
        if (dst) edgePairs.push(`${src}->${dst}`);
      }
    }
    for (const llm of agent.llm_tool_resolutions ?? []) {
      if (llm.provider_agent_id) {
        const dst = idMap.get(llm.provider_agent_id);
        if (dst) edgePairs.push(`${src}->llm:${dst}`);
      }
    }
    for (const prov of agent.llm_provider_resolutions ?? []) {
      if (prov.provider_agent_id) {
        const dst = idMap.get(prov.provider_agent_id);
        if (dst) edgePairs.push(`${src}->prov:${dst}`);
      }
    }
  }

  const uniqueEdgePairs = Array.from(new Set(edgePairs)).sort();
  return nodeKeys.join(",") + "|" + uniqueEdgePairs.join(",");
}

export function buildGraphFromAgents(agents: Agent[]): { nodes: Node[]; edges: Edge[] } {
  const buckets = bucketAgents(agents);
  const idMap = buildIdToNodeKeyFromBuckets(buckets);

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
    if (edgeMap.has(key)) return;
    edgeMap.set(key, base);
  }

  for (const agent of agents) {
    const src = idMap.get(agent.id);
    if (!src || !validNodeKeys.has(src)) continue;
    const isApi = agent.agent_type === "api";

    for (const dep of agent.dependency_resolutions ?? []) {
      if (!dep.provider_agent_id) continue;
      const dst = idMap.get(dep.provider_agent_id);
      if (!dst || !validNodeKeys.has(dst)) continue;

      const availableColor = isApi ? "#ec4899" : "#22c55e";
      const label = dep.capability;
      addEdge("dep", src, dst, label, {
        id: `dep|${src}|${dst}|${label}`,
        source: src,
        target: dst,
        label,
        animated: dep.status === "available",
        data: { originalLabel: label },
        style: {
          stroke: dep.status === "available" ? availableColor : dep.status === "unavailable" ? "#ef4444" : "#6b7280",
          strokeDasharray: dep.status === "unresolved" ? "5 5" : undefined,
        },
      });
    }

    for (const llm of agent.llm_tool_resolutions ?? []) {
      if (!llm.provider_agent_id) continue;
      const dst = idMap.get(llm.provider_agent_id);
      if (!dst || !validNodeKeys.has(dst)) continue;

      const label = `llm:${llm.filter_capability}`;
      addEdge("llm", src, dst, label, {
        id: `llm|${src}|${dst}|${label}`,
        source: src,
        target: dst,
        label,
        animated: llm.status === "available",
        data: { originalLabel: label },
        style: {
          stroke: llm.status === "available" ? "#22d3ee" : "#ef4444",
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
          stroke: prov.status === "available" ? "#a855f7" : "#ef4444",
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
