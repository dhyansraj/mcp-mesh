import { Layers } from "lucide-react";
import { AgentGroup } from "@/lib/agent-group";
import { Badge } from "@/components/ui/badge";
import {
  formatRelativeTime,
  getAgentTypeLabel,
  getRuntimeBadgeColor,
  getRuntimeLabel,
  getStatusBgColor,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { AgentBadges, unavailableBadgeCount } from "./AgentBadges";
import type { Agent } from "@/lib/types";

interface AgentCardProps {
  group: AgentGroup;
  onClick: () => void;
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
  // Unavailable-capability badge fires when a healthy agent's required
  // dependency chain is broken (issue #1249); suppressed on unhealthy agents.
  if (unavailableBadgeCount(agent) > 0) return true;
  // MeshJob badge fires only for real task=true producers (see AgentBadges).
  return Boolean(agent.capabilities?.some((c) => c.task === true));
}

// Health tally suffix for the replica badge, e.g. " · 2 healthy / 1 down".
// Omitted entirely when every replica is healthy.
function replicaHealthSuffix(group: AgentGroup): string {
  const healthy = group.instances.filter((i) => i.status === "healthy").length;
  const down = group.replicaCount - healthy;
  if (down === 0) return "";
  return ` · ${healthy} healthy / ${down} down`;
}

export function AgentCard({ group, onClick }: AgentCardProps) {
  // The representative (newest) instance sources the shared runtime/type/
  // version/description/badges shown for the collapsed group.
  const agent = group.representative;
  // Match AgentDetail's whitespace-defensive description handling (issue
  // #969) so an empty header reads the same in both views.
  const description = agent.description?.trim() ?? "";
  const showBadgeRow = hasAnyAgentBadge(agent);
  const isReplicated = group.replicaCount > 1;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-h-[180px] flex-col rounded-lg border border-border bg-background/40 p-4 text-left",
        "hover:border-primary/40 hover:bg-accent/10 transition-colors",
      )}
    >
      <div className="mb-2 flex items-center gap-2">
        <span
          className={cn(
            "inline-flex h-2.5 w-2.5 shrink-0 rounded-full",
            getStatusBgColor(group.aggregateStatus),
          )}
          aria-label={group.aggregateStatus}
        />
        <h3 className="truncate text-sm font-semibold text-foreground" title={group.name}>
          {group.name}
        </h3>
        {isReplicated && (
          <span
            className="inline-flex items-center gap-0.5 rounded-full border border-primary/40 bg-primary/15 px-1.5 py-0.5 text-[10px] font-semibold text-primary shrink-0"
            title={`${group.replicaCount} replicas`}
          >
            <Layers className="h-2.5 w-2.5" />×{group.replicaCount}
            {replicaHealthSuffix(group)}
          </span>
        )}
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
            getDepsColor(group.dependenciesResolved, group.totalDependencies),
          )}
        >
          {group.dependenciesResolved}/{group.totalDependencies} deps
        </span>
        <span className="text-muted-foreground">{formatRelativeTime(group.lastSeen)}</span>
      </div>
    </button>
  );
}
