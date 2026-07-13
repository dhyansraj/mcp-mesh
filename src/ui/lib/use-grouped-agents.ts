import { useMemo } from "react";
import { Agent } from "./types";
import { AgentGroup, groupAgentsByName } from "./agent-group";

// Memoized replica-collapse for Dashboard/Agents consumers. Recomputes only
// when the agents array identity changes.
export function useGroupedAgents(agents: Agent[]): AgentGroup[] {
  return useMemo(() => groupAgentsByName(agents), [agents]);
}
