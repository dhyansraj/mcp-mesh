import { useCallback, useMemo, useRef, useState, useEffect } from "react";
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Agent, EdgeStat } from "@/lib/types";
import { buildGraphFromAgents, buildIdToNodeKey, computeStructureHash } from "@/lib/topology";
import { edgeRowKey, edgeStatKey } from "@/lib/edge-stats";
import { EDGE_HEAT_COLORS } from "@/lib/edge-palette";
import { extractAgentName, formatDuration } from "@/lib/api";
import { useMesh } from "@/lib/mesh-context";
import { AgentNode } from "./AgentNode";
import { EdgeLegend } from "./EdgeLegend";
import { TopologySidebar, type SidebarSelection } from "./TopologySidebar";

const nodeTypes = { agentNode: AgentNode };

interface TopologyGraphProps {
  agents: Agent[];
}

// Given a node ID ("group:<base>" or raw agent ID), return its base agent name
// for cross-referencing with edgeStats / traceActivity which are keyed by base.
function nodeKeyToBaseName(nodeKey: string): string {
  if (nodeKey.startsWith("group:")) return nodeKey.slice("group:".length);
  return extractAgentName(nodeKey);
}

// Forward-only: selected node + its downstream node keys. Works whether the
// selection is a group or a single agent. Replicas of the same selected group
// share dependencies, so we union across all instances.
function getForwardNeighborIds(
  selectedNodeId: string,
  agents: Agent[],
  idToNodeKey: Map<string, string>
): Set<string> {
  const ids = new Set<string>([selectedNodeId]);

  // Collect the agent IDs contributing to this selected node (1 for single, N for group).
  const contributingAgentIds: string[] = [];
  for (const [agentId, nodeKey] of idToNodeKey.entries()) {
    if (nodeKey === selectedNodeId) contributingAgentIds.push(agentId);
  }

  const contributing = new Set(contributingAgentIds);
  for (const agent of agents) {
    if (!contributing.has(agent.id)) continue;
    for (const dep of agent.dependency_resolutions ?? []) {
      const dst = dep.provider_agent_id ? idToNodeKey.get(dep.provider_agent_id) : undefined;
      if (dst) ids.add(dst);
    }
    for (const llm of agent.llm_tool_resolutions ?? []) {
      const dst = llm.provider_agent_id ? idToNodeKey.get(llm.provider_agent_id) : undefined;
      if (dst) ids.add(dst);
    }
    for (const prov of agent.llm_provider_resolutions ?? []) {
      const dst = prov.provider_agent_id ? idToNodeKey.get(prov.provider_agent_id) : undefined;
      if (dst) ids.add(dst);
    }
  }

  return ids;
}

// Traffic heat, NOT edge kind. The scale is its own axis and its own constant
// (lib/edge-palette.ts) for the reasons written there, and it shares no value
// with the kind palette — a stroke from here can never be read as a kind.
//
// `null` MEANS SAY NOTHING, and an edge with no errors gets it (issue #1530).
// The caller then leaves that edge's kind stroke alone, because "this one is
// fine" is true of nearly every edge on a healthy mesh and is not worth the
// only channel that can say what an edge is. Errors do take the channel: at
// that point the error is the more urgent of the two facts.
function getEdgeHeatColor(errorRate: number): string | null {
  // Negated rather than `<= 0` so that zero, a negative and a rate that is not
  // a number at all all come out as nothing to say. Written the other way
  // round, a non-finite value fails both comparisons below and leaves with the
  // loudest colour on the scale — the one outcome a rate reporting nothing
  // must not produce. The field is required and both server paths populate it,
  // so this is a guard rather than a case that is expected to arise.
  if (!(errorRate > 0)) return null;
  // THE UNIT IS A PERCENTAGE, 0-100. Both registry paths that emit this field
  // multiply the ratio by 100 before sending it (tracing/manager.go,
  // tracing/accumulator.go), and the Traffic table prints it with a % sign
  // against this same boundary. Were it a fraction instead, every real rate
  // would land under 10 and `failing` would be unreachable — so the unit, not
  // the number, is what makes both bands appear.
  if (errorRate < 10) return EDGE_HEAT_COLORS.elevated;
  return EDGE_HEAT_COLORS.failing;
}

function computeStrokeWidth(callCount: number, maxCount: number): number {
  if (maxCount <= 0) return 1;
  const ratio = callCount / maxCount;
  return 1 + ratio * 3; // min 1, max 4
}

// What one edge's stat rows add up to. Only these three numbers are drawn, and
// all three combine exactly: a count sums, and a per-row mean recovers its total
// by multiplying back through the count it was taken over.
interface EdgeTraffic {
  callCount: number;
  errorRate: number;
  avgLatencyMs: number;
}

// Sum the stat rows belonging to one drawn edge, or null when it has none.
//
// An edge stands for its whole `data.targetFunctions` set, which is usually one
// function and is several whenever the registry emitted a resolution row per
// matched tool under a shared label (see topology.ts). Summing is what makes
// the answer independent of which member came first in the snapshot; picking
// one member would not be.
//
// Rows are matched by (base source name, base target name, function), so a
// function with no row contributes nothing rather than a zero: an edge whose
// set is partly covered reports the traffic that was actually recorded.
function aggregateEdgeTraffic(
  edge: Edge,
  statsMap: Map<string, EdgeStat>
): EdgeTraffic | null {
  const targetFunctions = edge.data?.targetFunctions;
  if (!Array.isArray(targetFunctions) || targetFunctions.length === 0) return null;

  const sourceName = nodeKeyToBaseName(edge.source);
  const targetName = nodeKeyToBaseName(edge.target);

  let callCount = 0;
  let totalLatencyMs = 0;
  let totalErrorRate = 0;
  let matched = 0;

  for (const fn of targetFunctions) {
    if (typeof fn !== "string" || fn === "") continue;
    const stat = statsMap.get(edgeStatKey(sourceName, targetName, fn));
    if (!stat) continue;
    matched++;
    callCount += stat.call_count;
    totalLatencyMs += stat.avg_latency_ms * stat.call_count;
    // Weighted from the row's OWN error rate rather than recomputed from its
    // error count. The two are the same number on every payload the registry
    // produces (both server paths derive the rate from the counts), and
    // weighting the reported field means this never contradicts the rate the
    // Traffic table prints for the same row.
    totalErrorRate += stat.error_rate * stat.call_count;
  }

  if (matched === 0) return null;
  if (callCount === 0) return { callCount: 0, errorRate: 0, avgLatencyMs: 0 };

  return {
    callCount,
    errorRate: totalErrorRate / callCount,
    avgLatencyMs: totalLatencyMs / callCount,
  };
}

// Overlay recorded traffic onto the structural graph.
//
// Matching on the agent pair alone was the bug: a pair exchanging a regular
// tool, an LLM-filtered tool and a MeshJob draws three correctly-coloured
// edges, and all three were stamped with one average across all of it. Each
// edge knows which provider functions it resolved to — `data.targetFunctions`,
// written from the resolutions' `mcp_tool` — so it joins to the rows that
// actually describe it.
//
// Exported for __tests__/traffic-per-function.test.tsx: the join is the whole
// point of the change and is not observable from the rendered graph, where two
// edges differ only by a stroke width and a label suffix.
export function mergeEdgeStatsIntoEdges(edges: Edge[], edgeStats: EdgeStat[]): Edge[] {
  if (edgeStats.length === 0) return edges;

  const statsMap = new Map<string, EdgeStat>();
  for (const stat of edgeStats) {
    // edgeRowKey rather than edgeStatKey so a row missing its function is
    // indexed under the empty function instead of under `undefined`. Nothing
    // matches it either way: the topology side of the join takes its function
    // from the resolution's `mcp_tool`, which every edge-producing resolution
    // carries, so no edge is ever keyed under the empty function. Such a row
    // simply contributes to no edge, and the edge it might have described keeps
    // its structural style — the right outcome for a row that names nothing.
    statsMap.set(edgeRowKey(stat), stat);
  }

  const traffic = edges.map((edge) => aggregateEdgeTraffic(edge, statsMap));

  // The stroke-width denominator is the busiest DRAWN EDGE, not the busiest
  // row: an edge standing for several functions carries their sum, which a
  // per-row maximum would let exceed the scale's top.
  const maxCallCount = Math.max(
    ...traffic.map((t) => (t ? t.callCount : 0)),
    1
  );

  return edges.map((edge, i) => {
    // NO TRAFFIC RECORDED IS NOT ZERO TRAFFIC. An edge with no matching row
    // keeps its structural style and its plain label — no latency, no heat
    // colour, no stroke weight — rather than being drawn as an idle edge. Some
    // real edges legitimately have no row: Python streaming tools publish no
    // span at all, and Java's synthetic dependency tools create capability rows
    // no span ever names. Both were already uncovered; a pair-level average
    // used to hide them behind a sibling's numbers.
    const stat = traffic[i];
    if (!stat) return edge;

    // Use stored original label to prevent accumulation on repeated merges
    const baseLabel = (edge.data?.originalLabel as string) || edge.label || "";
    const mergedLabel = baseLabel ? `${baseLabel}  ${formatDuration(stat.avgLatencyMs)}` : `${formatDuration(stat.avgLatencyMs)}`;

    // Only an erroring edge is repainted; a clean one keeps the stroke the
    // builder gave it and is still marked as carrying traffic by the two
    // channels that do not collide with kind — the latency in its label and its
    // width. Spreading `edge.style` first is what preserves the kind colour, so
    // do not lift `stroke` out of the conditional.
    const heat = getEdgeHeatColor(stat.errorRate);

    return {
      ...edge,
      label: mergedLabel,
      style: {
        ...edge.style,
        ...(heat === null ? {} : { stroke: heat }),
        // Relative to the busiest EDGE now, not the busiest pair, which is
        // the same change of denominator the rest of this merge makes.
        strokeWidth: computeStrokeWidth(stat.callCount, maxCallCount),
      },
    };
  });
}

export function TopologyGraph({ agents }: TopologyGraphProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const { setPaused, edgeStats, traceActivity } = useMesh();

  // Structural hash: only relayout when agents or edges change, not on data-only updates
  const structureHash = useMemo(() => computeStructureHash(agents), [agents]);
  const prevHashRef = useRef<string>("");
  const layoutCacheRef = useRef<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] });

  const { layoutedNodes, rawEdges, idToNodeKey } = useMemo(() => {
    // Always build the id->nodeKey map (cheap, needed for neighbor highlight).
    // Shared with buildGraphFromAgents so grouping rules live in one place.
    const mapping = buildIdToNodeKey(agents);

    if (structureHash === prevHashRef.current && layoutCacheRef.current.nodes.length > 0) {
      // Structure unchanged — reuse cached positions, rebuild data.
      // We still do a fresh buildGraphFromAgents to get up-to-date node data
      // (status/deps for groups, agent snapshot for singles) and fresh edges.
      const fresh = buildGraphFromAgents(agents);
      const freshNodeMap = new Map(fresh.nodes.map((n) => [n.id, n]));
      const updatedNodes = layoutCacheRef.current.nodes.map((node) => {
        const freshNode = freshNodeMap.get(node.id);
        if (!freshNode) return node;
        return { ...node, data: freshNode.data };
      });
      return { layoutedNodes: updatedNodes, rawEdges: fresh.edges, idToNodeKey: mapping };
    }

    // Structure changed — full relayout
    const result = buildGraphFromAgents(agents);
    prevHashRef.current = structureHash;
    layoutCacheRef.current = result;
    return { layoutedNodes: result.nodes, rawEdges: result.edges, idToNodeKey: mapping };
  }, [agents, structureHash]);

  const layoutedEdges = useMemo(
    () => mergeEdgeStatsIntoEdges(rawEdges, edgeStats),
    [rawEdges, edgeStats]
  );

  // Compute highlighted neighbor set
  const highlightedIds = useMemo(() => {
    if (!selectedNodeId) return null;
    return getForwardNeighborIds(selectedNodeId, agents, idToNodeKey);
  }, [selectedNodeId, agents, idToNodeKey]);

  // Apply dimming + trace count to nodes
  const styledNodes = useMemo(() => {
    return layoutedNodes.map((node) => {
      const baseName = nodeKeyToBaseName(node.id);
      return {
        ...node,
        data: {
          ...node.data,
          dimmed: highlightedIds ? !highlightedIds.has(node.id) : false,
          traceCount: traceActivity[baseName] || 0,
        },
      };
    });
  }, [layoutedNodes, highlightedIds, traceActivity]);

  // Apply dimming to edges
  const styledEdges = useMemo(() => {
    if (!highlightedIds) return layoutedEdges;
    return layoutedEdges.map((edge) => {
      const connected = highlightedIds.has(edge.source) && highlightedIds.has(edge.target);
      if (connected) return edge;
      return {
        ...edge,
        style: { ...edge.style, opacity: 0.08 },
        labelStyle: { opacity: 0.08 },
      };
    });
  }, [layoutedEdges, highlightedIds]);

  const [nodes, setNodes, onNodesChange] = useNodesState(styledNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(styledEdges);

  useEffect(() => {
    setNodes(styledNodes);
    setEdges(styledEdges);
  }, [styledNodes, styledEdges, setNodes, setEdges]);

  // Derive sidebar selection from the selected node so the reference stays
  // stable across heartbeat ticks when underlying node data hasn't meaningfully
  // changed. Keying on a serialized fingerprint of the relevant node.data
  // fields prevents the sidebar (and its Radix Accordion) from re-rendering
  // — and losing open-item state — on every graph tick.
  const selectedNode = useMemo(
    () => (selectedNodeId ? layoutedNodes.find((n) => n.id === selectedNodeId) : undefined),
    [selectedNodeId, layoutedNodes]
  );

  const selectionFingerprint = useMemo(() => {
    if (!selectedNode) return "";
    const data = selectedNode.data;
    if (data.kind === "group") {
      const instances = (data.instances as Agent[]) ?? [];
      const instanceSig = instances
        .map((a) => `${a.id}:${a.status}:${a.last_seen ?? ""}:${a.endpoint ?? ""}`)
        .join("|");
      return `group|${data.name}|${data.status}|${data.total_dependencies}|${data.dependencies_resolved}|${instanceSig}`;
    }
    const a = data.agent as Agent;
    return `single|${a.id}|${a.status}|${a.last_seen ?? ""}|${a.endpoint ?? ""}`;
  }, [selectedNode]);

  const sidebarSelection = useMemo<SidebarSelection | null>(() => {
    if (!selectedNode) return null;
    const data = selectedNode.data;
    if (data.kind === "group") {
      return {
        kind: "group",
        name: data.name as string,
        instances: data.instances as Agent[],
        status: data.status as string,
      };
    }
    return { kind: "single", agent: data.agent as Agent };
    // Intentionally keyed on the fingerprint (not selectedNode) so the object
    // identity only changes when user-visible fields actually change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionFingerprint]);

  // If a previously selected node disappears (e.g., group collapsed or agent
  // removed), clear selection state so the sidebar closes and the graph
  // resumes ticking.
  useEffect(() => {
    if (selectedNodeId && !selectedNode) {
      setSelectedNodeId(null);
      setPaused(false);
    }
  }, [selectedNodeId, selectedNode, setPaused]);

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      if (selectedNodeId === node.id) {
        // Toggle off — deselect
        setSelectedNodeId(null);
        setPaused(false);
      } else {
        // Select new node — sidebar selection is derived via useMemo above.
        setSelectedNodeId(node.id);
        setPaused(true);
      }
    },
    [selectedNodeId, setPaused]
  );

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setPaused(false);
  }, [setPaused]);

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Controls
          className="!bg-card !border-border !rounded-lg !shadow-lg [&>button]:!bg-card [&>button]:!border-border [&>button]:!text-foreground [&>button:hover]:!bg-muted"
        />
        <MiniMap
          nodeStrokeColor="#22d3ee"
          nodeColor="#22d3ee"
          nodeBorderRadius={8}
          maskColor="rgba(10, 22, 40, 0.4)"
          className="!bg-background !border-border !rounded-lg"
          pannable
          zoomable
        />
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#264a6e"
        />
      </ReactFlow>

      <EdgeLegend />

      <TopologySidebar selection={sidebarSelection} onClose={onPaneClick} />
    </div>
  );
}
