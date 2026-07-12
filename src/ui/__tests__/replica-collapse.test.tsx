import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Agent } from "../lib/types";
import { groupAgentsByName } from "../lib/agent-group";
import { AgentGrid } from "../components/agents/AgentGrid";
import { AgentTable } from "../components/agents/AgentTable";
import { StatsCards } from "../components/dashboard/StatsCards";

// AgentTable calls useMesh() for traceActivity; stub it so we can render
// without a live MeshProvider (network + SSE).
vi.mock("../lib/mesh-context", () => ({
  useMesh: () => ({ traceActivity: {} }),
}));

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "svc-00000000",
    name: "svc",
    agent_type: "mcp_agent",
    status: "healthy",
    endpoint: "http://svc:8080",
    runtime: "python",
    total_dependencies: 1,
    dependencies_resolved: 1,
    capabilities: [{ function_name: "do_thing", name: "svc.thing", version: "1.0.0" }],
    ...overrides,
  };
}

const twoReplicas: Agent[] = [
  makeAgent({ name: "fortuna", id: "fortuna-aaaa1111", last_seen: "2026-06-01T00:00:00Z" }),
  makeAgent({ name: "fortuna", id: "fortuna-bbbb2222", last_seen: "2026-05-01T00:00:00Z" }),
];

describe("replica collapse — Agents grid", () => {
  it("renders ONE card with a ×N badge for two same-name instances", () => {
    const groups = groupAgentsByName(twoReplicas);
    render(<AgentGrid groups={groups} />);

    // Single group heading.
    const headings = screen.getAllByText("fortuna");
    expect(headings).toHaveLength(1);
    // Replica badge shows the collapsed count.
    expect(screen.getByText(/×2/)).toBeInTheDocument();
  });
});

describe("replica collapse — Agents table", () => {
  it("renders ONE row with a ×N badge for two same-name instances", () => {
    const groups = groupAgentsByName(twoReplicas);
    render(<AgentTable groups={groups} />);

    expect(screen.getAllByText("fortuna")).toHaveLength(1);
    expect(screen.getByText(/×2/)).toBeInTheDocument();
  });
});

describe("replica collapse — Dashboard stats", () => {
  it("counts two same-name instances as ONE logical agent", () => {
    render(<StatsCards agents={twoReplicas} />);

    // "Total Agents" value should be 1, not 2 (replicas collapse).
    const totalLabel = screen.getByText("Total Agents");
    const card = totalLabel.closest("div")?.parentElement as HTMLElement;
    expect(card).toBeTruthy();
    expect(card.textContent).toContain("1");
    expect(card.textContent).not.toContain("2");
  });
});
