import { X, Layers } from "lucide-react";
import { Agent } from "@/lib/types";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AgentDetailBlock, AgentGroupDetail, StatusDot } from "@/components/agents/AgentGroupDetail";

export type SidebarSelection =
  | { kind: "single"; agent: Agent }
  | {
      kind: "group";
      name: string;
      instances: Agent[];
      status: string;
      totalDependencies: number;
      dependenciesResolved: number;
    };

interface TopologySidebarProps {
  selection: SidebarSelection | null;
  onClose: () => void;
}

export function TopologySidebar({ selection, onClose }: TopologySidebarProps) {
  if (!selection) return null;

  if (selection.kind === "single") {
    const agent = selection.agent;
    return (
      <div className="absolute right-0 top-0 h-full w-[360px] z-50 border-l border-border bg-card shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <StatusDot status={agent.status} />
            <h2 className="text-sm font-semibold text-foreground truncate">{agent.name}</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close sidebar"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scrollable content */}
        <ScrollArea className="flex-1 overflow-auto">
          <div className="p-4">
            <AgentDetailBlock agent={agent} />
          </div>
        </ScrollArea>
      </div>
    );
  }

  // Group selection
  const { name, instances, status } = selection;

  return (
    <div className="absolute right-0 top-0 h-full w-[360px] z-50 border-l border-border bg-card shadow-2xl flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <StatusDot status={status} />
          <h2 className="text-sm font-semibold text-foreground truncate">{name}</h2>
          <span className="inline-flex items-center gap-0.5 rounded-full border border-primary/40 bg-primary/15 px-1.5 py-0.5 text-[10px] font-semibold text-primary shrink-0">
            <Layers className="h-2.5 w-2.5" />×{instances.length}
          </span>
        </div>
        <button
          onClick={onClose}
          aria-label="Close sidebar"
          className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Scrollable content */}
      <ScrollArea className="flex-1 overflow-auto">
        <div className="p-4">
          <AgentGroupDetail name={name} instances={instances} />
        </div>
      </ScrollArea>
    </div>
  );
}
