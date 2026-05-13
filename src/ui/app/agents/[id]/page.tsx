import { Link, useNavigate, useParams } from "react-router-dom";
import { Header } from "@/components/layout/Header";
import { ConnectionError } from "@/components/layout/ConnectionError";
import { AgentDetail } from "@/components/agents/AgentDetail";
import { useMesh } from "@/lib/mesh-context";
import { ArrowLeft, Bot, Loader2 } from "lucide-react";

/**
 * Local back-link button used in both the not-found and success branches
 * below. Kept inline (not in components/) since it's only useful here.
 */
function BackToAgentsButton() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate("/agents")}
      className="mb-4 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-3 w-3" />
      All agents
    </button>
  );
}

/**
 * Issue #968: Agent detail route. Sources its data from the same
 * useMesh() agent list the index page uses — there is deliberately no
 * dedicated /api/agents/{id} endpoint, since the mesh roster is bounded
 * and already cached client-side.
 */
export default function AgentDetailPage() {
  const params = useParams<{ id: string }>();
  const { agents, loading, error, refresh } = useMesh();

  // useParams already decodes the path segment, so we don't double-decode.
  const id = params.id ?? "";

  if (loading) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Agent" subtitle="Agent detail" />
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col h-full">
        <Header title="Agent" subtitle="Agent detail" />
        <ConnectionError error={error} onRetry={refresh} />
      </div>
    );
  }

  const agent = agents.find((a) => a.id === id);

  if (!agent) {
    // Not-found is an empty result, not a connection error — render a
    // friendly empty state with a back link rather than ConnectionError.
    return (
      <div className="flex flex-col h-full">
        <Header title="Agent" subtitle="Agent detail" />
        <div className="flex-1 p-6 overflow-auto">
          <BackToAgentsButton />
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <Bot className="mb-3 h-12 w-12 opacity-40" />
            <p className="text-sm font-medium">Agent not found</p>
            <p className="text-xs mt-1">
              No agent with id <span className="font-mono">{id}</span> is registered.
            </p>
            <Link
              to="/agents"
              className="mt-4 text-xs text-primary hover:underline"
            >
              Back to all agents
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <Header title={agent.name} subtitle="Agent detail" />
      <div className="flex-1 p-6 overflow-auto">
        <BackToAgentsButton />
        <AgentDetail agent={agent} />
      </div>
    </div>
  );
}
