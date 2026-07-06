import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { AgentDetail } from "../components/agents/AgentDetail";
import type { Agent } from "../lib/types";

// AgentDetail calls useMesh() at the top level for traceActivity; stub the
// context so we can render it without a live MeshProvider (which does network
// fetches + SSE). The Traces tab (which uses traceActivity) is not the active
// tab, so an empty map is sufficient.
vi.mock("../lib/mesh-context", () => ({
  useMesh: () => ({ traceActivity: {} }),
}));

const agent: Agent = {
  id: "media-agent-abc123",
  name: "media-agent",
  agent_type: "mcp_agent",
  status: "healthy",
  endpoint: "http://localhost:9000",
  total_dependencies: 1,
  dependencies_resolved: 1,
  capabilities: [
    { function_name: "make_caption", name: "media.caption", version: "1.0.0" },
    { function_name: "make_thumbnail", name: "media.thumbnail", version: "1.0.0" },
    { function_name: "say_hello", name: "greet", version: "1.0.0" },
  ],
  dependency_resolutions: [
    {
      function_name: "make_caption",
      capability: "vision.describe",
      status: "available",
      provider_agent_id: "vision-agent-xyz",
    },
  ],
};

describe("AgentDetail service grouping (RFC #1280)", () => {
  it("renders a service group header with a method count for dotted capabilities", () => {
    render(<AgentDetail agent={agent} />);

    // Service header for the "media" group.
    const header = screen.getByText("media");
    expect(header).toBeInTheDocument();
    // The header badge counts the two dotted methods under "media".
    expect(screen.getByText("2 methods")).toBeInTheDocument();
  });

  it("renders each dotted method row prominently under the group", () => {
    render(<AgentDetail agent={agent} />);

    // Method segments are shown (split from media.caption / media.thumbnail).
    expect(screen.getByText("caption")).toBeInTheDocument();
    expect(screen.getByText("thumbnail")).toBeInTheDocument();
    // The full dotted capability names remain visible in the name badges.
    expect(screen.getByText(/media\.caption v1\.0\.0/)).toBeInTheDocument();
    expect(screen.getByText(/media\.thumbnail v1\.0\.0/)).toBeInTheDocument();
  });

  it("renders an undotted capability outside any service group", () => {
    render(<AgentDetail agent={agent} />);

    // The undotted "greet" capability has no method-segment header — only its
    // function name and the flat name badge appear.
    expect(screen.getByText("say_hello")).toBeInTheDocument();
    expect(screen.getByText(/greet v1\.0\.0/)).toBeInTheDocument();
    // No "greet" service header is rendered (would appear as its own group).
    expect(screen.queryByText("1 method")).not.toBeInTheDocument();
  });

  it("groups dotted dependency resolutions by their capability's service", () => {
    // Radix Tabs keeps only the active TabsContent mounted and switching tabs
    // needs a full pointer sequence, so use a fixture with no capabilities:
    // AgentDetail's defaultTab logic then makes "dependencies" the active tab.
    const depAgent: Agent = {
      ...agent,
      capabilities: [],
      dependency_resolutions: [
        {
          function_name: "make_caption",
          capability: "vision.describe",
          status: "available",
          provider_agent_id: "vision-agent-xyz",
        },
        {
          function_name: "make_ocr",
          capability: "vision.ocr",
          status: "available",
          provider_agent_id: "vision-agent-xyz",
        },
      ],
    };
    render(<AgentDetail agent={depAgent} />);

    const visionHeader = screen.getByText("vision");
    expect(visionHeader).toBeInTheDocument();
    expect(screen.getByText("2 methods")).toBeInTheDocument();
    const group = visionHeader.closest("div")?.parentElement as HTMLElement;
    expect(group).toBeTruthy();
    expect(within(group).getByText("vision.describe")).toBeInTheDocument();
    expect(within(group).getByText("vision.ocr")).toBeInTheDocument();
  });
});
