import { Bot } from "lucide-react";
import { Agent } from "@/lib/types";
import { AgentCard } from "./AgentCard";

interface AgentGridProps {
  agents: Agent[];
}

export function AgentGrid({ agents }: AgentGridProps) {
  if (agents.length === 0) {
    // Mirror AgentTable's empty state copy verbatim so the toggle doesn't
    // change wording. Deliberately inlined — see issue brief.
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <Bot className="mb-3 h-12 w-12 opacity-40" />
        <p className="text-sm font-medium">No agents registered</p>
        <p className="text-xs mt-1">Agents will appear here once they connect to the mesh</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {agents.map((agent) => (
        <AgentCard key={agent.id} agent={agent} />
      ))}
    </div>
  );
}
