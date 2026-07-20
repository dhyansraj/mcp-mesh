import { Agent, Capability, DependencyResolution } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getAgentTypeLabel, getDepStatusColor, extractAgentName } from "@/lib/api";
import { groupByService, splitServiceCapability } from "@/lib/service-group";
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

// RFC #1280: header for a dot-namespaced service group (Capabilities +
// Dependencies tabs). Mirrors the LLM tab's section-header styling with a
// method-count badge alongside.
function ServiceHeader({ name, count }: { name: string; count: number }) {
  return (
    <div className="flex items-center gap-2">
      <h4 className="text-xs font-medium uppercase tracking-wider text-muted-foreground font-mono">
        {name}
      </h4>
      <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-muted-foreground border-muted-foreground/30">
        {count} {count === 1 ? "method" : "methods"}
      </Badge>
    </div>
  );
}

// Issue #970: shared row renderer so the visible + framework capability lists
// can share styling. The `framework` flag adds a muted badge so users can tell
// __mesh_job_* tools apart at a glance when they're shown.
// RFC #1280: when `method` is set (row lives inside a service group) it is
// shown prominently; the full dotted name stays visible in the name badge.
function renderCapabilityRow(cap: Capability, key: string, framework: boolean, method?: string) {
  return (
    <div
      key={key}
      className="rounded-lg border border-border/50 px-4 py-3"
    >
      <div className="flex items-center gap-2 flex-wrap">
        {method && (
          <span className="text-sm font-semibold text-foreground font-mono">
            {method}
          </span>
        )}
        <span className={`text-sm font-medium font-mono ${method ? "text-muted-foreground" : "text-foreground"}`}>
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
        {cap.available === false && (
          <Badge
            variant="outline"
            className="text-[10px] px-1.5 py-0 bg-red-600/20 text-red-400 border-red-500/30"
            title={cap.unavailable_reason || "A required dependency chain is broken"}
          >
            unavailable
          </Badge>
        )}
        {cap.tags?.map((tag) => (
          <Badge key={tag} variant="secondary" className="text-[10px] px-1.5 py-0">
            {tag}
          </Badge>
        ))}
      </div>
      {cap.available === false && cap.unavailable_reason && (
        <p className="mt-1 text-xs text-red-400">{cap.unavailable_reason}</p>
      )}
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

// Dependency resolution row. Extracted so grouped (service) and ungrouped
// dependencies share one renderer (RFC #1280). Rows are unchanged from the
// prior inline markup — Provider / StatusBadge / mcp_tool / endpoint intact.
function renderDependencyRow(dep: DependencyResolution, key: string) {
  return (
    <div
      key={key}
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
  );
}

export function AgentDetail({ agent }: AgentDetailProps) {
  const hasLLM =
    (agent.llm_tool_resolutions && agent.llm_tool_resolutions.length > 0) ||
    (agent.llm_provider_resolutions && agent.llm_provider_resolutions.length > 0);

  const capabilities = agent.capabilities ?? [];
  // Issue #970: framework-internal tools (__mesh_* — MeshJob producers,
  // service-deps, etc.) are noise in the UI by default — partition them out
  // and show user-visible capabilities, with a toggle to reveal the framework
  // set. Mirrors the CLI's --tools view which hides them unless
  // --show-framework is passed (cli/list.go isFrameworkInternalTool, keyed on
  // the whole __mesh_ prefix).
  const fw = capabilities.filter((c) => c.function_name?.startsWith("__mesh_"));
  const visible = capabilities.filter((c) => !c.function_name?.startsWith("__mesh_"));
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
              {(() => {
                // RFC #1280: group dot-namespaced capabilities under a service
                // header; undotted capabilities render flat below the groups.
                const { services, ungrouped } = groupByService(visible, (c) => c.name);
                return (
                  <>
                    {services.map((svc) => (
                      <div key={`cap-svc-${svc.name}`} className="space-y-2">
                        <ServiceHeader name={svc.name} count={svc.items.length} />
                        <div className="space-y-2 border-l border-border/50 pl-3">
                          {svc.items.map((cap) =>
                            renderCapabilityRow(
                              cap,
                              `cap-${cap.function_name}-${cap.name}`,
                              false,
                              splitServiceCapability(cap.name).method,
                            ),
                          )}
                        </div>
                      </div>
                    ))}
                    {ungrouped.map((cap) => renderCapabilityRow(cap, `cap-${cap.function_name}-${cap.name}`, false))}
                  </>
                );
              })()}
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
              {(() => {
                // RFC #1280: group dot-namespaced dependencies by their
                // capability's service. One service group can have methods
                // bound to DIFFERENT provider_agent_id values.
                const { services, ungrouped } = groupByService(
                  agent.dependency_resolutions,
                  (d) => d.capability,
                );
                return (
                  <>
                    {services.map((svc) => (
                      <div key={`dep-svc-${svc.name}`} className="space-y-2">
                        <ServiceHeader name={svc.name} count={svc.items.length} />
                        <div className="space-y-2 border-l border-border/50 pl-3">
                          {svc.items.map((dep) =>
                            renderDependencyRow(dep, `dep-${dep.function_name}-${dep.capability}`),
                          )}
                        </div>
                      </div>
                    ))}
                    {ungrouped.map((dep) =>
                      renderDependencyRow(dep, `dep-${dep.function_name}-${dep.capability}`),
                    )}
                  </>
                );
              })()}
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
                      {(res.provider_agent_id || res.mcp_tool || res.endpoint) && (
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                          {res.provider_agent_id && (
                            <span>Provider: <span className={getDepStatusColor(res.status)}>{res.provider_agent_id}</span></span>
                          )}
                          {res.mcp_tool && <span>MCP Tool: {res.mcp_tool}</span>}
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
                      {(res.provider_agent_id || res.mcp_tool || res.endpoint) && (
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                          {res.provider_agent_id && (
                            <span>Provider: <span className={getDepStatusColor(res.status)}>{res.provider_agent_id}</span></span>
                          )}
                          {res.mcp_tool && <span>MCP Tool: {res.mcp_tool}</span>}
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
