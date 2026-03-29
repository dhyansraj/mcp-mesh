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
import { AgentNode } from "./AgentNode";
import { TopologySidebar } from "./TopologySidebar";

const nodeTypes = { agentNode: AgentNode };

interface TopologyGraphProps {
  agents: Agent[];
}

export function TopologyGraph({ agents }: TopologyGraphProps) {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  const { nodes: layoutedNodes, edges: layoutedEdges } = useMemo(
    () => buildGraphFromAgents(agents),
    [agents]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutedEdges);

  useEffect(() => {
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [layoutedNodes, layoutedEdges, setNodes, setEdges]);

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      const agent = agents.find((a) => a.id === node.id) ?? null;
      setSelectedAgent(agent);
    },
    [agents]
  );

  const onPaneClick = useCallback(() => {
    setSelectedAgent(null);
  }, []);

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
        />
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#264a6e"
        />
      </ReactFlow>

      <TopologySidebar agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </div>
  );
}
