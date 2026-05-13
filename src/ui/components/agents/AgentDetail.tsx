import { Agent, Capability } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getAgentTypeLabel, getDepStatusColor, extractAgentName } from "@/lib/api";
import { useMesh } from "@/lib/mesh-context";
import { AgentTraces } from "./AgentTraces";
import { AgentBadges } from "./AgentBadges";
import { useState } from "react";

interface AgentDetailProps {
  agent: Agent;
}

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    available: "bg-green-600/20 text-green-400 border-green-500/30",
    unavailable: "bg-red-600/20 text-red-400 border-red-500/30",
    unresolved: "bg-yellow-600/20 text-yellow-400 border-yellow-500/30",
  };

  const fallback = "bg-gray-600/20 text-gray-400 border-gray-500/30";

  return (
    <Badge variant="outline" className={`text-xs ${colorMap[status] || fallback}`}>
      {status}
    </Badge>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <p className="py-6 text-center text-sm text-muted-foreground">{message}</p>
  );
}

// Issue #970: shared row renderer so the visible + framework capability lists
// can share styling. The `framework` flag adds a muted badge so users can tell
// __mesh_job_* tools apart at a glance when they're shown.
function renderCapabilityRow(cap: Capability, key: string, framework: boolean) {
  return (
    <div
      key={key}
      className="rounded-lg border border-border/50 px-4 py-3"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-medium text-foreground font-mono">
          {cap.function_name}
        </span>
        <Badge variant="outline" className="text-xs">
          {cap.name} v{cap.version}
        </Badge>
        {framework && (
          <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-muted-foreground border-muted-foreground/30">
            framework
          </Badge>
        )}
        {cap.tags?.map((tag) => (
          <Badge key={tag} variant="secondary" className="text-[10px] px-1.5 py-0">
            {tag}
          </Badge>
        ))}
      </div>
      {cap.description && (
        <p className="mt-1 text-xs text-muted-foreground">{cap.description}</p>
      )}
      {cap.llm_filter && (
        <div className="mt-2 text-xs text-muted-foreground">
          <span className="text-cyan-400">LLM Filter:</span>{" "}
          {cap.llm_filter.capability || "any"}
          {cap.llm_filter.mode && ` (${cap.llm_filter.mode})`}
          {cap.llm_filter.tags && cap.llm_filter.tags.length > 0 && (
            <span> tags: {cap.llm_filter.tags.join(", ")}</span>
          )}
        </div>
      )}
      {cap.llm_provider && (
        <div className="mt-2 text-xs text-muted-foreground">
          <span className="text-orange-400">LLM Provider:</span>{" "}
          {cap.llm_provider.capability || "any"}
          {cap.llm_provider.version && ` v${cap.llm_provider.version}`}
          {cap.llm_provider.namespace && ` ns:${cap.llm_provider.namespace}`}
          {cap.llm_provider.tags && cap.llm_provider.tags.length > 0 && (
            <span> tags: {cap.llm_provider.tags.join(", ")}</span>
          )}
        </div>
      )}
    </div>
  );
}

export function AgentDetail({ agent }: AgentDetailProps) {
  const hasLLM =
    (agent.llm_tool_resolutions && agent.llm_tool_resolutions.length > 0) ||
    (agent.llm_provider_resolutions && agent.llm_provider_resolutions.length > 0);

  const capabilities = agent.capabilities ?? [];
  // Issue #970: framework-internal MeshJob tools (__mesh_job_*) are noise in
  // the UI by default — partition them out and show user-visible capabilities,
  // with a toggle to reveal the framework set. Mirrors the CLI's --tools view
  // which hides them unless --show-framework is passed (cli/list.go:85).
  const fw = capabilities.filter((c) => c.function_name?.startsWith("__mesh_job_"));
  const visible = capabilities.filter((c) => !c.function_name?.startsWith("__mesh_job_"));
  const [showFw, setShowFw] = useState(false);
  const agentName = extractAgentName(agent.id);
  const { traceActivity } = useMesh();
  // Belt-and-suspenders: registry validation trims whitespace at registration
  // (issue #969), but defend against whitespace-only values that could enter
  // the DB through manual edits / imports so the placeholder still renders.
  const description = agent.description?.trim() ?? "";

  const defaultTab = visible.length > 0
    ? "capabilities"
    : agent.dependency_resolutions && agent.dependency_resolutions.length > 0
      ? "dependencies"
      : "capabilities";

  return (
    <div className="px-4 py-4">
      {/* Issue #969: agent header with description. Renders the persisted
          @mesh.agent(description=...) value, with an explicit placeholder
          when none was supplied so an empty description is unambiguous. */}
      <div className="mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="text-sm font-semibold text-foreground">{agent.name}</h3>
          <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-muted-foreground">
            {getAgentTypeLabel(agent.agent_type)}
          </Badge>
          <AgentBadges agent={agent} />
        </div>
        {description ? (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        ) : (
          <p className="mt-1 text-sm italic text-muted-foreground/60">No description provided</p>
        )}
      </div>
      <Tabs defaultValue={defaultTab}>
        <TabsList>
          <TabsTrigger value="capabilities">
            Capabilities ({visible.length})
          </TabsTrigger>
          <TabsTrigger value="dependencies">
            Dependencies ({agent.dependency_resolutions?.length || 0})
          </TabsTrigger>
          {hasLLM && (
            <TabsTrigger value="llm">
              LLM ({(agent.llm_tool_resolutions?.length || 0) + (agent.llm_provider_resolutions?.length || 0)})
            </TabsTrigger>
          )}
          <TabsTrigger value="traces">Traces</TabsTrigger>
        </TabsList>

        {/* Capabilities Tab */}
        <TabsContent value="capabilities" className="mt-3">
          {capabilities.length === 0 ? (
            <EmptyState message="No capabilities" />
          ) : (
            <div className="space-y-2">
              {visible.length === 0 && fw.length > 0 && !showFw && (
                <p className="py-3 text-center text-xs text-muted-foreground">
                  Only framework-internal capabilities are registered.
                </p>
              )}
              {visible.map((cap, idx) => renderCapabilityRow(cap, `visible-${idx}`, false))}
              {showFw && fw.map((cap, idx) => renderCapabilityRow(cap, `fw-${idx}`, true))}
              {fw.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowFw((v) => !v)}
                  className="mt-1 text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
                >
                  {showFw ? "Hide framework tools" : `Show framework tools (${fw.length})`}
                </button>
              )}
            </div>
          )}
        </TabsContent>

        {/* Dependencies Tab */}
        <TabsContent value="dependencies" className="mt-3">
          {!agent.dependency_resolutions || agent.dependency_resolutions.length === 0 ? (
            <EmptyState message="No dependencies" />
          ) : (
            <div className="space-y-2">
              {agent.dependency_resolutions.map((dep, idx) => (
                <div
                  key={`${dep.function_name}-${idx}`}
                  className="rounded-lg border border-border/50 px-4 py-3"
                >
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-foreground font-mono">
                        {dep.function_name}
                      </span>
                      <Badge variant="outline" className="text-xs">
                        {dep.capability}
                      </Badge>
                      {dep.tags?.map((tag) => (
                        <Badge key={tag} variant="secondary" className="text-[10px] px-1.5 py-0">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                    <StatusBadge status={dep.status} />
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    {dep.provider_agent_id && (
                      <span>
                        Provider: <span className={getDepStatusColor(dep.status)}>{dep.provider_agent_id}</span>
                      </span>
                    )}
                    {dep.mcp_tool && <span>MCP Tool: {dep.mcp_tool}</span>}
                    {dep.endpoint && (
                      <span className="font-mono truncate max-w-xs">
                        {dep.endpoint}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        {/* LLM Tab */}
        {hasLLM && (
          <TabsContent value="llm" className="mt-3">
            {/* LLM Tool Resolutions */}
            {agent.llm_tool_resolutions && agent.llm_tool_resolutions.length > 0 && (
              <div className="mb-4">
                <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Tool Resolutions
                </h4>
                <div className="space-y-2">
                  {agent.llm_tool_resolutions.map((res, idx) => (
                    <div
                      key={`tool-${res.function_name}-${idx}`}
                      className="rounded-lg border border-border/50 px-4 py-3"
                    >
                      <div className="flex items-center justify-between flex-wrap gap-2">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-foreground font-mono">
                            {res.function_name}
                          </span>
                          <Badge variant="outline" className="text-xs">
                            {res.filter_capability}
                          </Badge>
                          {res.filter_mode && (
                            <span className="text-xs text-muted-foreground">({res.filter_mode})</span>
                          )}
                          {res.filter_tags?.map((tag) => (
                            <Badge key={tag} variant="secondary" className="text-[10px] px-1.5 py-0">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                        <StatusBadge status={res.status} />
                      </div>
                      {(res.provider_agent_id || res.provider_function_name || res.endpoint) && (
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                          {res.provider_agent_id && (
                            <span>Provider: <span className={getDepStatusColor(res.status)}>{res.provider_agent_id}</span></span>
                          )}
                          {res.provider_function_name && <span>Function: {res.provider_function_name}</span>}
                          {res.provider_capability && <span>Capability: {res.provider_capability}</span>}
                          {res.endpoint && (
                            <span className="font-mono truncate max-w-xs">{res.endpoint}</span>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* LLM Provider Resolutions */}
            {agent.llm_provider_resolutions && agent.llm_provider_resolutions.length > 0 && (
              <div>
                <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Provider Resolutions
                </h4>
                <div className="space-y-2">
                  {agent.llm_provider_resolutions.map((res, idx) => (
                    <div
                      key={`provider-${res.function_name}-${idx}`}
                      className="rounded-lg border border-border/50 px-4 py-3"
                    >
                      <div className="flex items-center justify-between flex-wrap gap-2">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-foreground font-mono">
                            {res.function_name}
                          </span>
                          <Badge variant="outline" className="text-xs">
                            {res.required_capability}
                          </Badge>
                          {res.required_tags?.map((tag) => (
                            <Badge key={tag} variant="secondary" className="text-[10px] px-1.5 py-0">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                        <StatusBadge status={res.status} />
                      </div>
                      {(res.provider_agent_id || res.provider_function_name || res.endpoint) && (
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                          {res.provider_agent_id && (
                            <span>Provider: <span className={getDepStatusColor(res.status)}>{res.provider_agent_id}</span></span>
                          )}
                          {res.provider_function_name && <span>Function: {res.provider_function_name}</span>}
                          {res.endpoint && (
                            <span className="font-mono truncate max-w-xs">{res.endpoint}</span>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </TabsContent>
        )}

        {/* Traces Tab */}
        <TabsContent value="traces" className="mt-3">
          <AgentTraces agentName={agentName} refreshKey={traceActivity[agentName] || 0} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
