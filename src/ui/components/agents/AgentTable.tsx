"use client";

import { useMemo, useState } from "react";
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
  getRuntimeBadgeColor,
  getAgentTypeLabel,
  extractAgentName,
} from "@/lib/api";
import { useMesh } from "@/lib/mesh-context";
import { ChevronDown, ChevronRight, Bot, Activity, ArrowUp, ArrowDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { AgentDetail } from "./AgentDetail";

interface AgentTableProps {
  agents: Agent[];
}

type SortKey = "name" | "type" | "runtime" | "deps" | "last_seen";
type SortDir = "asc" | "desc";

function getDepsColor(resolved: number, total: number): string {
  if (total === 0) return "text-muted-foreground";
  if (resolved === total) return "text-green-400";
  if (resolved === 0) return "text-red-400";
  return "text-orange-400";
}

function sortAgents(agents: Agent[], key: SortKey, dir: SortDir): Agent[] {
  const sorted = [...agents].sort((a, b) => {
    let cmp = 0;
    switch (key) {
      case "name":
        cmp = a.name.localeCompare(b.name);
        break;
      case "type":
        cmp = a.agent_type.localeCompare(b.agent_type);
        break;
      case "runtime":
        cmp = (a.runtime || "").localeCompare(b.runtime || "");
        break;
      case "deps":
        cmp = a.dependencies_resolved - b.dependencies_resolved;
        break;
      case "last_seen":
        cmp = (a.last_seen || "").localeCompare(b.last_seen || "");
        break;
    }
    return dir === "asc" ? cmp : -cmp;
  });
  return sorted;
}

function SortableHead({
  label,
  sortKey,
  currentKey,
  currentDir,
  onSort,
  className,
}: {
  label: string;
  sortKey: SortKey;
  currentKey: SortKey;
  currentDir: SortDir;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = currentKey === sortKey;
  return (
    <TableHead
      className={cn("cursor-pointer select-none hover:text-foreground", className)}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active && (currentDir === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        ))}
      </span>
    </TableHead>
  );
}

export function AgentTable({ agents }: AgentTableProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const { traceActivity } = useMesh();

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sorted = useMemo(() => sortAgents(agents, sortKey, sortDir), [agents, sortKey, sortDir]);

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
          <SortableHead label="Name" sortKey="name" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortableHead label="Type" sortKey="type" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortableHead label="Runtime" sortKey="runtime" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <TableHead>Version</TableHead>
          <SortableHead label="Dependencies" sortKey="deps" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
          <SortableHead label="Last Seen" sortKey="last_seen" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((agent) => {
          const isExpanded = expandedId === agent.id;

          return (
            <AgentRow
              key={agent.id}
              agent={agent}
              isExpanded={isExpanded}
              onToggle={() => setExpandedId(isExpanded ? null : agent.id)}
              traceCount={traceActivity[extractAgentName(agent.id)] || 0}
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
  traceCount: number;
}

function AgentRow({ agent, isExpanded, onToggle, traceCount }: AgentRowProps) {
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
        <TableCell className="font-medium text-foreground">
          <span className="inline-flex items-center gap-1.5">
            {agent.name}
            {traceCount > 0 && (
              <span className="inline-flex items-center gap-0.5 text-cyan-400" title={`${traceCount} recent trace(s)`}>
                <Activity className="h-3 w-3 animate-pulse" />
                <span className="text-[10px] font-mono">{traceCount}</span>
              </span>
            )}
          </span>
        </TableCell>
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
