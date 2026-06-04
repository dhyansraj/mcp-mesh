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

export function AgentBadges({ agent, dense }: AgentBadgesProps) {
  const sizing = dense ? "px-1 py-0 text-[9px]" : "px-1.5 py-0 text-[10px]";
  const meshJob = hasMeshJob(agent);

  if (!agent.a2a_producer && !agent.a2a_consumer && !meshJob) {
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
    </>
  );
}
