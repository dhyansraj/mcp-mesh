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

// Issue #970: framework-internal MeshJob capabilities are prefixed with
// __mesh_job_ — same convention as the CLI's isFrameworkInternalTool
// (src/core/cli/list.go:2023). No backend signal is needed; presence of any
// such capability marks the agent as MeshJob-capable.
function hasMeshJob(agent: Agent): boolean {
  return Boolean(
    agent.capabilities?.some((c) => c.function_name?.startsWith("__mesh_job_")),
  );
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
