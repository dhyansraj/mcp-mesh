import { Link } from "react-router-dom";
import { Agent } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  formatRelativeTime,
  getAgentTypeLabel,
  getRuntimeBadgeColor,
  getRuntimeLabel,
  getStatusBgColor,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { AgentBadges } from "./AgentBadges";

interface AgentCardProps {
  agent: Agent;
}

// Same logic as AgentTable.getDepsColor — inlined per the issue brief to
// avoid an export-just-for-grid refactor of AgentTable.
function getDepsColor(resolved: number, total: number): string {
  if (total === 0) return "text-muted-foreground";
  if (resolved === total) return "text-green-400";
  if (resolved === 0) return "text-red-400";
  return "text-orange-400";
}

// Mirrors AgentBadges' internal gating so we can omit the dedicated badge
// row entirely when no badges would render (avoids an awkward empty row).
// Kept in sync with AgentBadges.tsx — if that component grows new badges,
// extend this check too.
function hasAnyAgentBadge(agent: Agent): boolean {
  if (agent.a2a_producer || agent.a2a_consumer) return true;
  return Boolean(
    agent.capabilities?.some((c) => c.function_name?.startsWith("__mesh_job_")),
  );
}

export function AgentCard({ agent }: AgentCardProps) {
  // Match AgentDetail's whitespace-defensive description handling (issue
  // #969) so an empty header reads the same in both views.
  const description = agent.description?.trim() ?? "";
  const showBadgeRow = hasAnyAgentBadge(agent);

  return (
    <Link
      to={`/agents/${encodeURIComponent(agent.id)}`}
      className={cn(
        "flex min-h-[180px] flex-col rounded-lg border border-border bg-background/40 p-4",
        "hover:border-primary/40 hover:bg-accent/10 transition-colors",
      )}
    >
      <div className="mb-2 flex items-center gap-2">
        <span
          className={cn(
            "inline-flex h-2.5 w-2.5 shrink-0 rounded-full",
            getStatusBgColor(agent.status),
          )}
          aria-label={agent.status}
        />
        <h3 className="truncate text-sm font-semibold text-foreground" title={agent.name}>
          {agent.name}
        </h3>
      </div>

      {description ? (
        <p className="mb-3 line-clamp-2 text-xs text-muted-foreground">{description}</p>
      ) : (
        <p className="mb-3 line-clamp-2 text-xs italic text-muted-foreground/60">
          No description provided
        </p>
      )}

      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        {agent.runtime && (
          <Badge
            variant="outline"
            className={cn("text-xs", getRuntimeBadgeColor(agent.runtime))}
          >
            {getRuntimeLabel(agent.runtime)}
          </Badge>
        )}
        <Badge variant="outline" className="text-xs text-muted-foreground">
          {getAgentTypeLabel(agent.agent_type)}
        </Badge>
        {agent.version && (
          <span className="font-mono text-[10px] text-muted-foreground">
            v{agent.version}
          </span>
        )}
      </div>

      {showBadgeRow && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <AgentBadges agent={agent} />
        </div>
      )}

      <div className="mt-auto flex items-center justify-between text-xs">
        <span
          className={cn(
            "font-mono",
            getDepsColor(agent.dependencies_resolved, agent.total_dependencies),
          )}
        >
          {agent.dependencies_resolved}/{agent.total_dependencies} deps
        </span>
        <span className="text-muted-foreground">{formatRelativeTime(agent.last_seen)}</span>
      </div>
    </Link>
  );
}
