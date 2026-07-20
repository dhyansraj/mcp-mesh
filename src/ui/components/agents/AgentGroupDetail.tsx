import { Globe, Hash, Clock, Cpu, Tag, GitBranch, Puzzle, Zap, BrainCircuit, Layers } from "lucide-react";
import { Agent } from "@/lib/types";
import { formatRelativeTime, getRuntimeLabel, getAgentTypeLabel, getDepStatusColor } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { cn } from "@/lib/utils";

// Shared drill-in primitives for a collapsed agent group. Extracted from the
// Topology sidebar so both the Topology sidebar and the Agents page can render
// an identical group summary + per-instance detail view.

export function StatusDot({ status }: { status: string }) {
  const color =
    status === "healthy"
      ? "bg-green-500"
      : status === "unhealthy"
        ? "bg-red-500"
        : "bg-yellow-500";
  return <span className={cn("inline-block h-2 w-2 rounded-full shrink-0", color)} />;
}

function DepStatusBadge({ status }: { status: string }) {
  const colors =
    status === "available"
      ? "bg-green-500/15 text-green-400 border-green-500/30"
      : status === "unavailable"
        ? "bg-red-500/15 text-red-400 border-red-500/30"
        : "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
  return (
    <span className={cn("inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium", colors)}>
      {status}
    </span>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">{children}</h3>;
}

// Per-agent detail block — used for both single-agent selection and each
// expanded accordion item in a group selection.
export function AgentDetailBlock({ agent }: { agent: Agent }) {
  const deps = agent.dependency_resolutions ?? [];
  const llmTools = agent.llm_tool_resolutions ?? [];
  const llmProviders = agent.llm_provider_resolutions ?? [];

  return (
    <div className="space-y-5">
      {/* General info */}
      <div className="space-y-2">
        <SectionTitle>Details</SectionTitle>
        <div className="space-y-1.5 text-xs">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Globe className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate font-mono" title={agent.endpoint}>{agent.endpoint}</span>
          </div>
          {agent.entity_id && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Hash className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate font-mono">{agent.entity_id}</span>
            </div>
          )}
          <div className="flex items-center gap-2 text-muted-foreground">
            <Cpu className="h-3.5 w-3.5 shrink-0" />
            <span>
              {getRuntimeLabel(agent.runtime)}
              {agent.version ? ` v${agent.version}` : ""}
              {" / "}
              {getAgentTypeLabel(agent.agent_type)}
            </span>
          </div>
          {agent.created_at && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Clock className="h-3.5 w-3.5 shrink-0" />
              <span>Created {formatRelativeTime(agent.created_at)}</span>
            </div>
          )}
          {agent.last_seen && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Clock className="h-3.5 w-3.5 shrink-0" />
              <span>Last seen {formatRelativeTime(agent.last_seen)}</span>
            </div>
          )}
        </div>
      </div>

      {/* Capabilities */}
      {(agent.capabilities ?? []).length > 0 && (
        <div>
          <SectionTitle>Capabilities ({(agent.capabilities ?? []).length})</SectionTitle>
          <div className="space-y-2">
            {(agent.capabilities ?? []).map((cap) => (
              <div key={cap.function_name} className="rounded-md border border-border bg-background/50 p-2">
                <div className="flex items-center gap-1.5 mb-1">
                  <Puzzle className="h-3 w-3 text-primary shrink-0" />
                  <span className="text-xs font-medium text-foreground truncate">{cap.function_name}</span>
                </div>
                <p className="text-[10px] text-muted-foreground mb-1">
                  {cap.name} v{cap.version}
                </p>
                {cap.available === false && (
                  <p
                    className="text-[10px] text-red-400 mb-1"
                    title={cap.unavailable_reason || "A required dependency chain is broken"}
                  >
                    unavailable{cap.unavailable_reason ? `: ${cap.unavailable_reason}` : ""}
                  </p>
                )}
                {cap.description && (
                  <p className="text-[10px] text-muted-foreground/80 mb-1">{cap.description}</p>
                )}
                {cap.tags && cap.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {cap.tags.map((tag) => (
                      <Badge key={tag} variant="outline" className="text-[9px] px-1.5 py-0">
                        <Tag className="h-2.5 w-2.5 mr-0.5" />
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Dependency Resolutions */}
      {deps.length > 0 && (
        <div>
          <SectionTitle>Dependencies ({deps.length})</SectionTitle>
          <div className="space-y-2">
            {deps.map((dep, idx) => (
              <div key={`${dep.function_name}-${dep.capability}-${idx}`} className="rounded-md border border-border bg-background/50 p-2">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <GitBranch className={cn("h-3 w-3 shrink-0", getDepStatusColor(dep.status))} />
                    <span className="text-xs font-medium text-foreground truncate">{dep.function_name}</span>
                  </div>
                  <DepStatusBadge status={dep.status} />
                </div>
                <p className="text-[10px] text-muted-foreground">
                  {dep.capability}
                  {dep.mcp_tool ? ` · ${dep.mcp_tool}` : ""}
                </p>
                {dep.endpoint && (
                  <p className="text-[10px] text-muted-foreground/80 font-mono truncate" title={dep.endpoint}>
                    {dep.endpoint}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* LLM Tool Resolutions */}
      {llmTools.length > 0 && (
        <div>
          <SectionTitle>LLM Tool Resolutions ({llmTools.length})</SectionTitle>
          <div className="space-y-2">
            {llmTools.map((llm, idx) => (
              <div key={`${llm.function_name}-${llm.filter_capability}-${idx}`} className="rounded-md border border-border bg-background/50 p-2">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <Zap className={cn("h-3 w-3 shrink-0", getDepStatusColor(llm.status))} />
                    <span className="text-xs font-medium text-foreground truncate">{llm.function_name}</span>
                  </div>
                  <DepStatusBadge status={llm.status} />
                </div>
                <p className="text-[10px] text-muted-foreground">
                  {llm.filter_capability}
                  {llm.mcp_tool ? ` · ${llm.mcp_tool}` : ""}
                </p>
                {llm.endpoint && (
                  <p className="text-[10px] text-muted-foreground/80 font-mono truncate" title={llm.endpoint}>
                    {llm.endpoint}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* LLM Provider Resolutions */}
      {llmProviders.length > 0 && (
        <div>
          <SectionTitle>LLM Provider Resolutions ({llmProviders.length})</SectionTitle>
          <div className="space-y-2">
            {llmProviders.map((prov, idx) => (
              <div key={`${prov.function_name}-${prov.required_capability}-${idx}`} className="rounded-md border border-border bg-background/50 p-2">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <BrainCircuit className={cn("h-3 w-3 shrink-0", getDepStatusColor(prov.status))} />
                    <span className="text-xs font-medium text-foreground truncate">{prov.function_name}</span>
                  </div>
                  <DepStatusBadge status={prov.status} />
                </div>
                <p className="text-[10px] text-muted-foreground">
                  {prov.required_capability}
                  {prov.mcp_tool ? ` · ${prov.mcp_tool}` : ""}
                </p>
                {prov.endpoint && (
                  <p className="text-[10px] text-muted-foreground/80 font-mono truncate" title={prov.endpoint}>
                    {prov.endpoint}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

interface AgentGroupDetailProps {
  /** Canonical group name (agent.name). */
  name: string;
  /** All instances in the group. Order is preserved for the accordion. */
  instances: Agent[];
}

// Group drill-in: an aggregate summary (instance count, shared/divergent
// endpoint, aggregate dependency resolution) followed by a per-instance
// accordion of AgentDetailBlock. Aggregate figures are derived from the
// instances so the component is self-contained and reusable standalone.
export function AgentGroupDetail({ name, instances }: AgentGroupDetailProps) {
  // Determine whether all replicas share a single endpoint. If so, show it
  // directly; otherwise indicate divergence — per-instance endpoints are
  // available in the accordion below.
  const uniqueEndpoints = Array.from(
    new Set(instances.map((i) => i.endpoint).filter((e): e is string => !!e))
  );
  const sharedEndpoint = uniqueEndpoints.length === 1 ? uniqueEndpoints[0] : "";
  const endpointsDiffer = uniqueEndpoints.length > 1;

  const totalDependencies = instances.reduce((sum, a) => sum + (a.total_dependencies ?? 0), 0);
  const dependenciesResolved = instances.reduce((sum, a) => sum + (a.dependencies_resolved ?? 0), 0);

  return (
    <div className="space-y-5">
      {/* Group summary */}
      <div className="space-y-2">
        <SectionTitle>Group</SectionTitle>
        <div className="space-y-1.5 text-xs">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Layers className="h-3.5 w-3.5 shrink-0" />
            <span>{instances.length} instances</span>
          </div>
          {sharedEndpoint && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Globe className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate font-mono" title={sharedEndpoint}>{sharedEndpoint}</span>
            </div>
          )}
          {endpointsDiffer && (
            <div
              className="flex items-center gap-2 text-muted-foreground"
              title={uniqueEndpoints.join("\n")}
            >
              <Globe className="h-3.5 w-3.5 shrink-0" />
              <span>Endpoints: {uniqueEndpoints.length} (varies — see instances)</span>
            </div>
          )}
          <div className="flex items-center gap-2 text-muted-foreground">
            <GitBranch className="h-3.5 w-3.5 shrink-0" />
            <span>
              Dependencies {dependenciesResolved}/{totalDependencies} resolved (aggregate)
            </span>
          </div>
        </div>
      </div>

      {/* Instance accordion */}
      <div>
        <SectionTitle>Instances</SectionTitle>
        <Accordion type="single" collapsible className="rounded-md border border-border bg-background/50 px-2">
          {instances.map((inst) => (
            <AccordionItem key={inst.id} value={inst.id}>
              <AccordionTrigger>
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <StatusDot status={inst.status} />
                  <span className="truncate font-mono text-[11px]">{inst.id}</span>
                  {inst.last_seen && (
                    <span className="text-[10px] text-muted-foreground shrink-0 ml-auto pr-2">
                      {formatRelativeTime(inst.last_seen)}
                    </span>
                  )}
                </div>
              </AccordionTrigger>
              <AccordionContent>
                <AgentDetailBlock agent={inst} />
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </div>
    </div>
  );
}
