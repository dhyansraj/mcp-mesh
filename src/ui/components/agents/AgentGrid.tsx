import { useState, useEffect, useRef } from "react";
import { Bot, X, Layers } from "lucide-react";
import { AgentGroup } from "@/lib/agent-group";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AgentCard } from "./AgentCard";
import { AgentGroupDetail, StatusDot } from "./AgentGroupDetail";

interface AgentGridProps {
  groups: AgentGroup[];
}

export function AgentGrid({ groups }: AgentGridProps) {
  // Drill-in reuses the Topology sidebar pattern: clicking a card opens a
  // right-side slide-over rendering the shared AgentGroupDetail (group summary
  // + per-instance accordion), mirroring the Topology sidebar's look.
  const [selected, setSelected] = useState<AgentGroup | null>(null);

  if (groups.length === 0) {
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
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {groups.map((group) => (
          <AgentCard key={group.name} group={group} onClick={() => setSelected(group)} />
        ))}
      </div>
      <AgentGroupDrawer group={selected} onClose={() => setSelected(null)} />
    </>
  );
}

interface AgentGroupDrawerProps {
  group: AgentGroup | null;
  onClose: () => void;
}

// Right-side slide-over that mirrors the Topology sidebar's chrome (status dot,
// name, ×N replica badge, close button, scrollable AgentGroupDetail body).
function AgentGroupDrawer({ group, onClose }: AgentGroupDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!group) return;
    closeButtonRef.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [group, onClose]);

  if (!group) return null;
  const isReplicated = group.replicaCount > 1;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        className="fixed right-0 top-0 h-full w-[360px] z-50 border-l border-border bg-card shadow-2xl flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <StatusDot status={group.aggregateStatus} />
            <h2 className="text-sm font-semibold text-foreground truncate">{group.name}</h2>
            {isReplicated && (
              <span className="inline-flex items-center gap-0.5 rounded-full border border-primary/40 bg-primary/15 px-1.5 py-0.5 text-[10px] font-semibold text-primary shrink-0">
                <Layers className="h-2.5 w-2.5" />×{group.replicaCount}
              </span>
            )}
          </div>
          <button
            ref={closeButtonRef}
            onClick={onClose}
            aria-label="Close panel"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scrollable content */}
        <ScrollArea className="flex-1 overflow-auto">
          <div className="p-4">
            <AgentGroupDetail name={group.name} instances={group.instances} />
          </div>
        </ScrollArea>
      </div>
    </>
  );
}
