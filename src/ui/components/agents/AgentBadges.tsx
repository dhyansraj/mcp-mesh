import { Agent } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface AgentBadgesProps {
  agent: Agent;
  /**
   * Dense variant for tight rows (table cells, topology chips). Uses smaller
   * padding + 9px text vs the default 10px.
   */
  dense?: boolean;
}

// An agent is MeshJob-capable only when it owns a REAL task=true producer.
// The registry surfaces a per-capability `task` flag (from the stored kwargs);
// the universal framework `__mesh_job_*` helper tools are present on every
// agent and carry no `task` flag, so they no longer light up this badge.
function hasMeshJob(agent: Agent): boolean {
  return Boolean(agent.capabilities?.some((c) => c.task === true));
}

// unavailableBadgeCount returns how many of the agent's capabilities should
// surface an "unavailable" badge (issue #1249). Two suppressions apply:
//   - `available === undefined` means the registry didn't report availability
//     (older versions) and is treated as available.
//   - a NON-healthy agent contributes zero: the registry marks EVERY capability
//     of an unhealthy agent available:false with reason "agent unhealthy",
//     which is redundant with the agent's own red status dot. The
//     capability-level signal is only interesting on a healthy agent, where it
//     reveals a broken required-dependency chain the status alone wouldn't show.
// Exported so list-level views (AgentCard) gate their badge row on the same
// predicate and never render an empty badge row.
export function unavailableBadgeCount(agent: Agent): number {
  if (agent.status !== "healthy") return 0;
  return agent.capabilities?.filter((c) => c.available === false).length ?? 0;
}

export function AgentBadges({ agent, dense }: AgentBadgesProps) {
  const sizing = dense ? "px-1 py-0 text-[9px]" : "px-1.5 py-0 text-[10px]";
  const meshJob = hasMeshJob(agent);
  const unavailable = unavailableBadgeCount(agent);

  if (!agent.a2a_producer && !agent.a2a_consumer && !meshJob && unavailable === 0) {
    return null;
  }

  return (
    <>
      {agent.a2a_producer && (
        <Badge
          variant="outline"
          className={cn("bg-emerald-500/20 text-emerald-300 border-emerald-500/30", sizing)}
        >
          A2A producer
        </Badge>
      )}
      {agent.a2a_consumer && (
        <Badge
          variant="outline"
          className={cn("bg-violet-500/20 text-violet-300 border-violet-500/30", sizing)}
        >
          A2A consumer
        </Badge>
      )}
      {meshJob && (
        <Badge
          variant="outline"
          className={cn("bg-amber-500/20 text-amber-300 border-amber-500/30", sizing)}
        >
          MeshJob
        </Badge>
      )}
      {unavailable > 0 && (
        <Badge
          variant="outline"
          className={cn("bg-red-500/20 text-red-300 border-red-500/30", sizing)}
          title={`${unavailable} capabilit${unavailable === 1 ? "y" : "ies"} unavailable — a required dependency chain is broken`}
        >
          {unavailable} unavailable
        </Badge>
      )}
    </>
  );
}
