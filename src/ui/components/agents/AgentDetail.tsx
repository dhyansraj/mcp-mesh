"use client";

import { Agent } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getDepStatusColor } from "@/lib/api";

interface AgentDetailProps {
  agent: Agent;
}

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    available: "bg-green-600/20 text-green-400 border-green-500/30",
    unavailable: "bg-red-600/20 text-red-400 border-red-500/30",
    unresolved: "bg-yellow-600/20 text-yellow-400 border-yellow-500/30",
  };

  return (
    <Badge variant="outline" className={`text-xs ${colorMap[status] || ""}`}>
      {status}
    </Badge>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <p className="py-6 text-center text-sm text-muted-foreground">{message}</p>
  );
}

export function AgentDetail({ agent }: AgentDetailProps) {
  const hasLLM =
    (agent.llm_tool_resolutions && agent.llm_tool_resolutions.length > 0) ||
    (agent.llm_provider_resolutions && agent.llm_provider_resolutions.length > 0);

  const capabilities = agent.capabilities ?? [];

  const defaultTab = capabilities.length > 0
    ? "capabilities"
    : agent.dependency_resolutions && agent.dependency_resolutions.length > 0
      ? "dependencies"
      : "capabilities";

  return (
    <div className="px-4 py-4">
      <Tabs defaultValue={defaultTab}>
        <TabsList>
          <TabsTrigger value="capabilities">
            Capabilities ({capabilities.length})
          </TabsTrigger>
          <TabsTrigger value="dependencies">
            Dependencies ({agent.dependency_resolutions?.length || 0})
          </TabsTrigger>
          {hasLLM && (
            <TabsTrigger value="llm">
              LLM ({(agent.llm_tool_resolutions?.length || 0) + (agent.llm_provider_resolutions?.length || 0)})
            </TabsTrigger>
          )}
        </TabsList>

        {/* Capabilities Tab */}
        <TabsContent value="capabilities" className="mt-3">
          {capabilities.length === 0 ? (
            <EmptyState message="No capabilities" />
          ) : (
            <div className="space-y-2">
              {capabilities.map((cap, idx) => (
                <div
                  key={`${cap.function_name}-${idx}`}
                  className="rounded-lg border border-border/50 px-4 py-3"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-foreground font-mono">
                      {cap.function_name}
                    </span>
                    <Badge variant="outline" className="text-xs">
                      {cap.name} v{cap.version}
                    </Badge>
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
              ))}
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
      </Tabs>
    </div>
  );
}
