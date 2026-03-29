"use client";

import { useCallback, useMemo, useState, useEffect } from "react";
import {
  ReactFlow,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Agent } from "@/lib/types";
import { buildGraphFromAgents } from "@/lib/topology";
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

export function TopologyGraph({ agents }: TopologyGraphProps) {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [sidebarAgent, setSidebarAgent] = useState<Agent | null>(null);
  const { setPaused } = useMesh();

  const { nodes: layoutedNodes, edges: layoutedEdges } = useMemo(
    () => buildGraphFromAgents(agents),
    [agents]
  );

  // Compute highlighted neighbor set
  const highlightedIds = useMemo(() => {
    if (!selectedAgentId) return null;
    return getForwardNeighborIds(selectedAgentId, agents);
  }, [selectedAgentId, agents]);

  // Apply dimming to nodes
  const styledNodes = useMemo(() => {
    if (!highlightedIds) return layoutedNodes;
    return layoutedNodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        dimmed: !highlightedIds.has(node.id),
      },
    }));
  }, [layoutedNodes, highlightedIds]);

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

      <TopologySidebar agent={sidebarAgent} onClose={() => setSidebarAgent(null)} />
    </div>
  );
}
