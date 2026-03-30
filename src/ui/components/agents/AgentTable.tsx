"use client";

import { useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Agent } from "@/lib/types";
import {
  formatRelativeTime,
  getStatusBgColor,
  getRuntimeLabel,
  getAgentTypeLabel,
} from "@/lib/api";
import { ChevronDown, ChevronRight, Bot } from "lucide-react";
import { AgentDetail } from "./AgentDetail";

interface AgentTableProps {
  agents: Agent[];
}

function getRuntimeBadgeColor(runtime?: string): string {
  switch (runtime) {
    case "python":
      return "bg-blue-600/20 text-blue-400 border-blue-500/30";
    case "typescript":
      return "bg-cyan-600/20 text-cyan-400 border-cyan-500/30";
    case "java":
      return "bg-orange-600/20 text-orange-400 border-orange-500/30";
    default:
      return "";
  }
}

function getDepsColor(resolved: number, total: number): string {
  if (total === 0) return "text-muted-foreground";
  if (resolved === total) return "text-green-400";
  if (resolved === 0) return "text-red-400";
  return "text-orange-400";
}

export function AgentTable({ agents }: AgentTableProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (agents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <Bot className="mb-3 h-12 w-12 opacity-40" />
        <p className="text-sm font-medium">No agents registered</p>
        <p className="text-xs mt-1">Agents will appear here once they connect to the mesh</p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-8" />
          <TableHead className="w-12">Status</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Runtime</TableHead>
          <TableHead>Version</TableHead>
          <TableHead>Dependencies</TableHead>
          <TableHead>Last Seen</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {agents.map((agent) => {
          const isExpanded = expandedId === agent.id;

          return (
            <AgentRow
              key={agent.id}
              agent={agent}
              isExpanded={isExpanded}
              onToggle={() => setExpandedId(isExpanded ? null : agent.id)}
            />
          );
        })}
      </TableBody>
    </Table>
  );
}

interface AgentRowProps {
  agent: Agent;
  isExpanded: boolean;
  onToggle: () => void;
}

function AgentRow({ agent, isExpanded, onToggle }: AgentRowProps) {
  return (
    <>
      <TableRow
        className="cursor-pointer"
        onClick={onToggle}
      >
        <TableCell>
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </TableCell>
        <TableCell>
          <span
            className={`inline-flex h-2.5 w-2.5 rounded-full ${getStatusBgColor(agent.status)}`}
          />
        </TableCell>
        <TableCell className="font-medium text-foreground">{agent.name}</TableCell>
        <TableCell className="text-muted-foreground">
          {getAgentTypeLabel(agent.agent_type)}
        </TableCell>
        <TableCell>
          {agent.runtime ? (
            <Badge
              variant="outline"
              className={`text-xs ${getRuntimeBadgeColor(agent.runtime)}`}
            >
              {getRuntimeLabel(agent.runtime)}
            </Badge>
          ) : (
            <span className="text-muted-foreground">&mdash;</span>
          )}
        </TableCell>
        <TableCell className="text-muted-foreground font-mono text-xs">
          {agent.version || "\u2014"}
        </TableCell>
        <TableCell>
          <span className={`font-mono text-xs ${getDepsColor(agent.dependencies_resolved, agent.total_dependencies)}`}>
            {agent.dependencies_resolved}/{agent.total_dependencies}
          </span>
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {formatRelativeTime(agent.last_seen)}
        </TableCell>
      </TableRow>
      {isExpanded && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={8} className="bg-background/50 p-0">
            <AgentDetail agent={agent} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
