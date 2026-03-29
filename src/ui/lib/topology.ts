import dagre from "dagre";
import { type Node, type Edge } from "@xyflow/react";
import { Agent } from "./types";

export function buildGraphFromAgents(agents: Agent[]): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = agents.map((agent) => ({
    id: agent.id,
    type: "agentNode",
    position: { x: 0, y: 0 },
    data: { agent },
  }));

  const edges: Edge[] = [];
  const agentIds = new Set(agents.map((a) => a.id));
  const seenEdgeIds = new Set<string>();

  function uniqueEdgeId(base: string): string {
    let id = base;
    let i = 2;
    while (seenEdgeIds.has(id)) {
      id = `${base}-${i++}`;
    }
    seenEdgeIds.add(id);
    return id;
  }

  for (const agent of agents) {
    for (const dep of agent.dependency_resolutions ?? []) {
      if (dep.provider_agent_id && agentIds.has(dep.provider_agent_id)) {
        edges.push({
          id: uniqueEdgeId(`${agent.id}-${dep.function_name}-${dep.capability}-${dep.provider_agent_id}`),
          source: agent.id,
          target: dep.provider_agent_id,
          label: dep.capability,
          animated: dep.status === "available",
          style: {
            stroke: dep.status === "available" ? "#22c55e" : dep.status === "unavailable" ? "#ef4444" : "#6b7280",
            strokeDasharray: dep.status === "unresolved" ? "5 5" : undefined,
          },
        });
      }
    }

    for (const llm of agent.llm_tool_resolutions ?? []) {
      if (llm.provider_agent_id && agentIds.has(llm.provider_agent_id)) {
        edges.push({
          id: uniqueEdgeId(`${agent.id}-llm-${llm.function_name}-${llm.provider_agent_id}`),
          source: agent.id,
          target: llm.provider_agent_id,
          label: `llm:${llm.filter_capability}`,
          animated: llm.status === "available",
          style: {
            stroke: llm.status === "available" ? "#22d3ee" : "#ef4444",
            strokeDasharray: llm.status !== "available" ? "5 5" : undefined,
          },
        });
      }
    }

    for (const prov of agent.llm_provider_resolutions ?? []) {
      if (prov.provider_agent_id && agentIds.has(prov.provider_agent_id)) {
        edges.push({
          id: uniqueEdgeId(`${agent.id}-prov-${prov.function_name}-${prov.provider_agent_id}`),
          source: agent.id,
          target: prov.provider_agent_id,
          label: `provider:${prov.required_capability}`,
          animated: prov.status === "available",
          style: {
            stroke: prov.status === "available" ? "#a855f7" : "#ef4444",
            strokeDasharray: prov.status !== "available" ? "5 5" : undefined,
          },
        });
      }
    }
  }

  return applyDagreLayout(nodes, edges);
}

function applyDagreLayout(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  if (nodes.length === 0) return { nodes, edges };

  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 80, ranksep: 100, marginx: 40, marginy: 40 });

  const nodeWidth = 280;
  const nodeHeight = 100;

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
