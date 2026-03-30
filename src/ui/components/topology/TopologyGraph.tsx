"use client";

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
import { buildGraphFromAgents, computeStructureHash } from "@/lib/topology";
import { extractAgentName } from "@/lib/api";
import { useMesh } from "@/lib/mesh-context";
import { AgentNode } from "./AgentNode";
import { TopologySidebar } from "./TopologySidebar";

const nodeTypes = { agentNode: AgentNode };

interface TopologyGraphProps {
  agents: Agent[];
}

// Forward-only: selected agent + the providers it depends on (downstream)
function getForwardNeighborIds(selectedId: string, agents: Agent[]): Set<string> {
  const ids = new Set<string>([selectedId]);

  const selected = agents.find((a) => a.id === selectedId);
  if (selected) {
    for (const dep of selected.dependency_resolutions ?? []) {
      if (dep.provider_agent_id) ids.add(dep.provider_agent_id);
    }
    for (const llm of selected.llm_tool_resolutions ?? []) {
      if (llm.provider_agent_id) ids.add(llm.provider_agent_id);
    }
    for (const prov of selected.llm_provider_resolutions ?? []) {
      if (prov.provider_agent_id) ids.add(prov.provider_agent_id);
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
    const sourceName = extractAgentName(edge.source);
    const targetName = extractAgentName(edge.target);
    const stat = statsMap.get(`${sourceName}->${targetName}`);
    if (!stat) return edge;

    // Keep the original capability label, append latency
    const originalLabel = edge.label ? `${edge.label}  ${stat.avg_latency_ms.toFixed(0)}ms` : `${stat.avg_latency_ms.toFixed(0)}ms`;

    return {
      ...edge,
      label: originalLabel,
      style: {
        ...edge.style,
        stroke: getEdgeHeatColor(stat.error_rate),
        strokeWidth: computeStrokeWidth(stat.call_count, maxCallCount),
      },
    };
  });
}

export function TopologyGraph({ agents }: TopologyGraphProps) {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [sidebarAgent, setSidebarAgent] = useState<Agent | null>(null);
  const { setPaused, edgeStats, traceActivity } = useMesh();

  // Structural hash: only relayout when agents or edges change, not on data-only updates
  const structureHash = useMemo(() => computeStructureHash(agents), [agents]);
  const prevHashRef = useRef<string>("");
  const layoutCacheRef = useRef<{ nodes: Node[]; edges: Edge[] }>({ nodes: [], edges: [] });

  const { layoutedNodes, rawEdges } = useMemo(() => {
    if (structureHash === prevHashRef.current && layoutCacheRef.current.nodes.length > 0) {
      // Structure unchanged — reuse cached positions, update node data only
      const agentMap = new Map(agents.map((a) => [a.id, a]));
      const updatedNodes = layoutCacheRef.current.nodes.map((node) => {
        const agent = agentMap.get(node.id);
        if (!agent) return node;
        return { ...node, data: { ...node.data, agent } };
      });
      // Rebuild edges (they carry status/style info that may change)
      const { edges: freshEdges } = buildGraphFromAgents(agents);
      return { layoutedNodes: updatedNodes, rawEdges: freshEdges };
    }

    // Structure changed — full relayout
    const result = buildGraphFromAgents(agents);
    prevHashRef.current = structureHash;
    layoutCacheRef.current = result;
    return { layoutedNodes: result.nodes, rawEdges: result.edges };
  }, [agents, structureHash]);

  const layoutedEdges = useMemo(
    () => mergeEdgeStatsIntoEdges(rawEdges, edgeStats),
    [rawEdges, edgeStats]
  );

  // Compute highlighted neighbor set
  const highlightedIds = useMemo(() => {
    if (!selectedAgentId) return null;
    return getForwardNeighborIds(selectedAgentId, agents);
  }, [selectedAgentId, agents]);

  // Apply dimming + trace count to nodes
  const styledNodes = useMemo(() => {
    return layoutedNodes.map((node) => {
      const agentName = extractAgentName(node.id);
      return {
        ...node,
        data: {
          ...node.data,
          dimmed: highlightedIds ? !highlightedIds.has(node.id) : false,
          traceCount: traceActivity[agentName] || 0,
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

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      if (selectedAgentId === node.id) {
        // Toggle off — deselect
        setSelectedAgentId(null);
        setSidebarAgent(null);
        setPaused(false);
      } else {
        // Select new node
        const agent = agents.find((a) => a.id === node.id) ?? null;
        setSelectedAgentId(node.id);
        setSidebarAgent(agent);
        setPaused(true);
      }
    },
    [agents, selectedAgentId, setPaused]
  );

  const onPaneClick = useCallback(() => {
    setSelectedAgentId(null);
    setSidebarAgent(null);
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
          nodeStrokeColor="#264a6e"
          nodeColor="#112d4e"
          nodeBorderRadius={8}
          maskColor="rgba(10, 22, 40, 0.8)"
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

      <TopologySidebar agent={sidebarAgent} onClose={() => setSidebarAgent(null)} />
    </div>
  );
}
