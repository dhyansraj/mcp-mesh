import { useMemo } from "react";
import { Header } from "@/components/layout/Header";
import { AgentTable } from "@/components/agents/AgentTable";
import { AgentGrid } from "@/components/agents/AgentGrid";
import { Button } from "@/components/ui/button";
import { ConnectionError } from "@/components/layout/ConnectionError";
import { useMesh } from "@/lib/mesh-context";
import { useLocalStorage } from "@/lib/use-local-storage";
import { Eye, EyeOff, LayoutGrid, List, Loader2 } from "lucide-react";

export default function AgentsPage() {
  const { agents, loading, error, refresh, showAll, setShowAll } = useMesh();
  // Issue #968: persist the list/grid toggle across reloads. The validator
  // narrows the cached value back to the union so a hand-edited localStorage
  // entry can't crash the page.
  const [view, setView] = useLocalStorage<"list" | "grid">(
    "mesh.ui.agents.view",
    "list",
    (v): v is "list" | "grid" => v === "list" || v === "grid",
  );

  // Issue #990: server payload order isn't stable, so cards reshuffle on
  // every 30s refresh / SSE event. Sort once at the page level so both
  // grid and table views consume the same ordered list.
  const sortedAgents = useMemo(
    () => [...agents].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })),
    [agents],
  );

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Agents" subtitle="Registered agents and capabilities" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Agents" subtitle="Registered agents and capabilities" />
        <ConnectionError error={error} onRetry={refresh} />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Agents" subtitle="Registered agents and capabilities" />
      <div className="flex-1 p-6 overflow-auto">
        <div className="flex items-center justify-end gap-2 mb-4">
          <div className="inline-flex items-center gap-1 rounded-md border border-border p-0.5">
            <Button
              variant={view === "list" ? "default" : "ghost"}
              size="sm"
              onClick={() => setView("list")}
              className="h-7 px-2 text-xs"
              title="List view"
              aria-label="List view"
              aria-pressed={view === "list"}
            >
              <List className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant={view === "grid" ? "default" : "ghost"}
              size="sm"
              onClick={() => setView("grid")}
              className="h-7 px-2 text-xs"
              title="Grid view"
              aria-label="Grid view"
              aria-pressed={view === "grid"}
            >
              <LayoutGrid className="h-3.5 w-3.5" />
            </Button>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowAll(!showAll)}
            className="text-xs"
          >
            {showAll ? (
              <><EyeOff className="mr-1.5 h-3.5 w-3.5" />Healthy only</>
            ) : (
              <><Eye className="mr-1.5 h-3.5 w-3.5" />Show all</>
            )}
          </Button>
        </div>
        {view === "grid" ? <AgentGrid agents={sortedAgents} /> : <AgentTable agents={sortedAgents} />}
      </div>
    </div>
  );
}
