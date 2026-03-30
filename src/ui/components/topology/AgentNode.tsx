"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Agent } from "@/lib/types";
import { getRuntimeLabel } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Bot, Puzzle, GitBranch, Activity } from "lucide-react";

function getRuntimeColor(runtime?: string): string {
  switch (runtime) {
    case "python":
      return "bg-yellow-500/20 text-yellow-400 border-yellow-500/40";
    case "typescript":
      return "bg-blue-500/20 text-blue-400 border-blue-500/40";
    case "java":
      return "bg-orange-500/20 text-orange-400 border-orange-500/40";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}

function getNodeBorderColor(status: string, depsResolved: number, depsTotal: number): string {
  if (status === "unhealthy") return "border-red-500/60";
  if (status === "unknown") return "border-yellow-500/60";
  // Healthy agent — border reflects dependency resolution
  if (depsTotal === 0) return "border-green-500/60"; // No deps = fully resolved
  if (depsResolved === depsTotal) return "border-green-500/60";
  if (depsResolved === 0) return "border-red-500/60";
  return "border-yellow-500/60"; // Partially resolved
}

function getStatusDotColor(status: string): string {
  switch (status) {
    case "healthy":
      return "bg-green-500";
    case "unhealthy":
      return "bg-red-500";
    default:
      return "bg-yellow-500";
  }
}

function AgentNodeComponent({ data }: NodeProps) {
  const agent = data.agent as Agent;
  const dimmed = data.dimmed as boolean | undefined;
  const traceCount = (data.traceCount as number) || 0;
  const depsResolved = agent.dependencies_resolved;
  const depsTotal = agent.total_dependencies;
  const capCount = agent.capabilities?.length ?? 0;

  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-primary !border-primary !w-2 !h-2" />
      <div
        className={cn(
          "rounded-lg border-2 bg-card shadow-lg px-4 py-3 min-w-[240px] max-w-[280px]",
          "transition-all duration-300 hover:shadow-xl hover:shadow-primary/10",
          getNodeBorderColor(agent.status, depsResolved, depsTotal),
          dimmed && "opacity-20"
        )}
      >
        <div className="flex items-start gap-2 mb-2">
          <Bot className="h-4 w-4 text-primary shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-foreground truncate" title={agent.name}>
              {agent.name}
            </p>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", getStatusDotColor(agent.status))} />
              <span className="text-[10px] text-muted-foreground capitalize">{agent.status}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={cn(
              "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium",
              getRuntimeColor(agent.runtime)
            )}
          >
            {getRuntimeLabel(agent.runtime)}
          </span>

          {depsTotal > 0 && (
            <span className={cn(
              "inline-flex items-center gap-1 text-[10px]",
              depsResolved === depsTotal ? "text-green-400" : depsResolved === 0 ? "text-red-400" : "text-yellow-400"
            )}>
              <GitBranch className="h-3 w-3" />
              {depsResolved}/{depsTotal}
            </span>
          )}

          {capCount > 0 && (
            <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
              <Puzzle className="h-3 w-3" />
              {capCount}
            </span>
          )}

          {traceCount > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[10px] text-cyan-400">
              <Activity className="h-3 w-3 animate-pulse" />
              {traceCount}
            </span>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-primary !border-primary !w-2 !h-2" />
    </>
  );
}

export const AgentNode = memo(AgentNodeComponent);
