"use client";

import { Header } from "@/components/layout/Header";
import { AgentTable } from "@/components/agents/AgentTable";
import { Button } from "@/components/ui/button";
import { useMesh } from "@/lib/mesh-context";
import { Loader2, AlertCircle, RefreshCw, Eye, EyeOff } from "lucide-react";

export default function AgentsPage() {
  const { agents, loading, error, refresh, showAll, setShowAll } = useMesh();

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
        <div className="flex flex-1 flex-col items-center justify-center gap-4">
          <AlertCircle className="h-10 w-10 text-destructive" />
          <p className="text-sm text-muted-foreground">{error.message}</p>
          <Button variant="outline" size="sm" onClick={refresh}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Agents" subtitle="Registered agents and capabilities" />
      <div className="flex-1 p-6 overflow-auto">
        <div className="flex items-center justify-end mb-4">
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
        <AgentTable agents={agents} />
      </div>
    </div>
  );
}
