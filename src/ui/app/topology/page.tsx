import { Header } from "@/components/layout/Header";
import { ConnectionError } from "@/components/layout/ConnectionError";
import { TopologyGraph } from "@/components/topology/TopologyGraph";
import { useMesh } from "@/lib/mesh-context";
import { Loader2, Network } from "lucide-react";

export default function TopologyPage() {
  const { agents, loading, error, refresh } = useMesh();

  if (error) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Topology" subtitle="Agent dependency graph" />
        <ConnectionError error={error} onRetry={refresh} />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Topology" subtitle="Agent dependency graph" />
      <div className="flex-1 relative">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">Loading agents...</p>
          </div>
        ) : agents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <Network className="h-12 w-12 text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">
              No agents registered. Start some agents to see the topology.
            </p>
          </div>
        ) : (
          <TopologyGraph agents={agents} />
        )}
      </div>
    </div>
  );
}
