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
import { extractAgentName, formatDuration } from "@/lib/api";
import { useMesh } from "@/lib/mesh-context";
import { AgentNode } from "./AgentNode";
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

function getEdgeHeatColor(errorRate: number): string {
  if (errorRate === 0) return "#22c55e";
  if (errorRate < 10) return "#eab308";
  return "#ef4444";
}

function computeStrokeWidth(callCount: number, maxCount: number): number {
  if (maxCount <= 0) return 1;
  const ratio = callCount / maxCount;
  return 1 + ratio * 3; // min 1, max 4
}

function mergeEdgeStatsIntoEdges(edges: Edge[], edgeStats: EdgeStat[]): Edge[] {
  if (edgeStats.length === 0) return edges;

  const statsMap = new Map<string, EdgeStat>();
  for (const stat of edgeStats) {
    statsMap.set(`${stat.source}->${stat.target}`, stat);
  }

  const maxCallCount = Math.max(...edgeStats.map((e) => e.call_count), 1);

  return edges.map((edge) => {
    const sourceName = nodeKeyToBaseName(edge.source);
    const targetName = nodeKeyToBaseName(edge.target);
    const stat = statsMap.get(`${sourceName}->${targetName}`);
    if (!stat) return edge;

    // Use stored original label to prevent accumulation on repeated merges
    const baseLabel = (edge.data?.originalLabel as string) || edge.label || "";
    const mergedLabel = baseLabel ? `${baseLabel}  ${formatDuration(stat.avg_latency_ms)}` : `${formatDuration(stat.avg_latency_ms)}`;

    return {
      ...edge,
      label: mergedLabel,
      style: {
        ...edge.style,
        stroke: getEdgeHeatColor(stat.error_rate),
        strokeWidth: computeStrokeWidth(stat.call_count, maxCallCount),
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
        totalDependencies: data.total_dependencies as number,
        dependenciesResolved: data.dependencies_resolved as number,
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

      {/* Legend */}
      <div className="absolute top-4 left-4 z-10 rounded-lg border border-border bg-card/90 backdrop-blur-sm px-3 py-2.5 shadow-lg">
        <p className="text-[10px] font-medium text-muted-foreground mb-1.5 uppercase tracking-wider">Edges</p>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-5 h-0.5 bg-[#22c55e] rounded" />
            <span className="text-[10px] text-muted-foreground">Dependency</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-5 h-0.5 bg-[#ec4899] rounded" />
            <span className="text-[10px] text-muted-foreground">API dependency</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-5 h-0.5 bg-[#22d3ee] rounded" />
            <span className="text-[10px] text-muted-foreground">LLM tool</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-5 h-0.5 bg-[#a855f7] rounded" />
            <span className="text-[10px] text-muted-foreground">LLM provider</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-5 h-0.5 bg-[#ef4444] rounded" />
            <span className="text-[10px] text-muted-foreground">Unavailable</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-5 h-0.5 border-t border-dashed border-[#6b7280]" />
            <span className="text-[10px] text-muted-foreground">Unresolved</span>
          </div>
        </div>
      </div>

      <TopologySidebar selection={sidebarSelection} onClose={onPaneClick} />
    </div>
  );
}
