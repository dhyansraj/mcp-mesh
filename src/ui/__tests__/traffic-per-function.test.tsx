// Traffic attributed per CALLED FUNCTION rather than per agent pair (#1531).
//
// The bug this covers: edge stats were keyed by (source, target) alone, so a
// pair exchanging a regular tool, an LLM-filtered tool and a MeshJob drew three
// correctly-coloured edges and gave all three the same latency, the same heat
// colour and the same stroke width — the average across all of it. Two of those
// three numbers described traffic that edge never carried.
//
// Both surfaces are asserted: the graph merge (which joins a stat row to the
// edge that produced it) and the Traffic table (which now shows the rows).
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { Edge } from "@xyflow/react";
import type { Agent, EdgeStat, TrafficResponse } from "../lib/types";
import { buildGraphFromAgents } from "../lib/topology";
import { mergeEdgeStatsIntoEdges } from "../components/topology/TopologyGraph";
import { TrafficTable } from "../components/dashboard/TrafficTable";
import { EDGE_COLORS, EDGE_HEAT_COLORS } from "../lib/edge-palette";

// The dashboard's TrafficTable reads its rows straight off the SSE feed through
// useMesh(); stub the context so it can be rendered without a live provider.
const mockEdgeStats: EdgeStat[] = [];
vi.mock("../lib/mesh-context", () => ({
  useMesh: () => ({ edgeStats: mockEdgeStats, traceActivity: {}, setPaused: () => {} }),
}));

function makeStat(overrides: Partial<EdgeStat> & Pick<EdgeStat, "source" | "target" | "target_function">): EdgeStat {
  return {
    call_count: 10,
    error_count: 0,
    error_rate: 0,
    avg_latency_ms: 5,
    p99_latency_ms: 9,
    max_latency_ms: 12,
    min_latency_ms: 1,
    ...overrides,
  };
}

function makeEdge(overrides: Partial<Edge> = {}): Edge {
  return {
    id: "dep|caller-11111111|prov-22222222|reports",
    source: "caller-11111111",
    target: "prov-22222222",
    label: "reports",
    animated: true,
    data: { originalLabel: "reports", targetFunctions: ["run_report"] },
    style: { stroke: EDGE_COLORS.dependency },
    ...overrides,
  };
}

describe("the graph joins a stat to the edge that produced it", () => {
  it("gives two edges of one pair their OWN numbers", () => {
    const fast = makeEdge({
      id: "fast",
      label: "lookup",
      data: { originalLabel: "lookup", targetFunctions: ["lookup"] },
    });
    const slow = makeEdge({
      id: "slow",
      label: "summary",
      data: { originalLabel: "summary", targetFunctions: ["summarise"] },
    });

    const merged = mergeEdgeStatsIntoEdges([fast, slow], [
      makeStat({ source: "caller", target: "prov", target_function: "lookup", avg_latency_ms: 4, call_count: 100 }),
      makeStat({ source: "caller", target: "prov", target_function: "summarise", avg_latency_ms: 1500, call_count: 10 }),
    ]);

    // The label carries the latency, formatted; assert on the milliseconds
    // rather than on formatDuration's exact rendering.
    expect(merged[0].label).toContain("lookup");
    expect(String(merged[0].label)).toMatch(/4/);
    expect(String(merged[1].label)).toMatch(/1\.5|1500/);
    expect(String(merged[0].label)).not.toBe(String(merged[1].label));

    // Stroke width is relative to the busiest FUNCTION, so the 100-call edge is
    // drawn heavier than the 10-call one between the very same two agents —
    // impossible when one number covered both.
    expect(Number(merged[0].style?.strokeWidth)).toBeGreaterThan(
      Number(merged[1].style?.strokeWidth)
    );
  });

  it("keeps one edge's errors off its healthy sibling", () => {
    const healthy = makeEdge({
      id: "healthy",
      data: { originalLabel: "a", targetFunctions: ["healthy_tool"] },
    });
    const broken = makeEdge({
      id: "broken",
      data: { originalLabel: "b", targetFunctions: ["broken_tool"] },
    });

    const merged = mergeEdgeStatsIntoEdges([healthy, broken], [
      makeStat({ source: "caller", target: "prov", target_function: "healthy_tool", error_rate: 0 }),
      makeStat({ source: "caller", target: "prov", target_function: "broken_tool", error_rate: 100, error_count: 10 }),
    ]);

    expect(merged[0].style?.stroke).toBe(EDGE_HEAT_COLORS.clean);
    expect(merged[1].style?.stroke).toBe(EDGE_HEAT_COLORS.failing);
  });

  it("does not match a row belonging to a different pair", () => {
    const edge = makeEdge({ data: { originalLabel: "reports", targetFunctions: ["run_report"] } });
    const merged = mergeEdgeStatsIntoEdges([edge], [
      // Right function, wrong caller.
      makeStat({ source: "someone-else", target: "prov", target_function: "run_report" }),
    ]);
    expect(merged[0]).toBe(edge);
  });
});

describe("an edge with no recorded traffic keeps its structural style", () => {
  // No traffic recorded and zero traffic are DIFFERENT FACTS, and the second is
  // a claim the payload does not support. Python streaming tools publish no span
  // at all, and Java's synthetic dependency tools create capability rows no span
  // ever names — both real edges, both permanently without a row. Neither was
  // visible before, because a pair-level average lent them a sibling's numbers.

  it("is returned untouched when its function has no row", () => {
    const edge = makeEdge({ data: { originalLabel: "reports", targetFunctions: ["streaming_tool"] } });
    const merged = mergeEdgeStatsIntoEdges([edge], [
      makeStat({ source: "caller", target: "prov", target_function: "some_other_tool" }),
    ]);
    // Identity, not equality: nothing was rebuilt, so no default can have crept
    // into the style or the label.
    expect(merged[0]).toBe(edge);
    expect(merged[0].style?.stroke).toBe(EDGE_COLORS.dependency);
    expect(merged[0].style?.strokeWidth).toBeUndefined();
    expect(merged[0].label).toBe("reports");
  });

  it("is not painted with a pair-level fallback when a SIBLING edge has traffic", () => {
    // The precise regression: the same two agents are exchanging plenty of
    // traffic on another tool. That must not reach this edge.
    const silent = makeEdge({ id: "silent", data: { originalLabel: "stream", targetFunctions: ["streaming_tool"] } });
    const busy = makeEdge({ id: "busy", data: { originalLabel: "lookup", targetFunctions: ["lookup"] } });

    const merged = mergeEdgeStatsIntoEdges([silent, busy], [
      makeStat({ source: "caller", target: "prov", target_function: "lookup", error_rate: 50, call_count: 900 }),
    ]);

    expect(merged[0]).toBe(silent);
    expect(merged[0].style?.stroke).toBe(EDGE_COLORS.dependency);
    expect(merged[1].style?.stroke).toBe(EDGE_HEAT_COLORS.failing);
  });

  it("is returned untouched when the resolution carried no mcp_tool at all", () => {
    // Then the edge has no function to join on. Matching on the pair instead
    // would be the old behaviour, reintroduced through the back door.
    const edge = makeEdge({ data: { originalLabel: "reports" } });
    const merged = mergeEdgeStatsIntoEdges([edge], [
      makeStat({ source: "caller", target: "prov", target_function: "run_report" }),
    ]);
    expect(merged[0]).toBe(edge);
  });
});

describe("one edge standing for several provider functions", () => {
  // Routine, not exotic. An edge is keyed `kind|src|dst|label`, and an LLM tool
  // edge's label is `llm:<filter_capability>` — but the registry writes one
  // resolution row PER MATCHED TOOL, and a TAGS-ONLY filter leaves the
  // capability empty, so every tool that filter matched on one provider lands
  // on the identical label `llm:`. One line on screen, N functions behind it.
  //
  // Joining that line to one of the N and showing its numbers as the edge's own
  // is what snapshot order would decide. These two agents produce it.
  const tagsOnlyFilter = (toolNames: string[]): Agent[] => [
    {
      id: "caller-11111111",
      name: "caller",
      agent_type: "mcp_agent",
      status: "healthy",
      endpoint: "http://caller:8080",
      total_dependencies: 0,
      dependencies_resolved: 0,
      capabilities: [],
      llm_tool_resolutions: toolNames.map((tool) => ({
        function_name: "chat",
        filter_capability: "",
        filter_tags: ["reporting"],
        status: "available" as const,
        provider_agent_id: "prov-22222222",
        mcp_tool: tool,
      })),
    },
    {
      id: "prov-22222222",
      name: "prov",
      agent_type: "mcp_agent",
      status: "healthy",
      endpoint: "http://prov:8080",
      total_dependencies: 0,
      dependencies_resolved: 0,
      capabilities: toolNames.map((tool) => ({
        function_name: tool,
        name: tool,
        version: "1.0.0",
        tags: ["reporting"],
      })),
    },
  ];

  it("collapses onto one edge that names ALL of them, in a fixed order", () => {
    const forward = buildGraphFromAgents(tagsOnlyFilter(["lookup", "summarise", "export"]));
    const reversed = buildGraphFromAgents(tagsOnlyFilter(["export", "summarise", "lookup"]));

    expect(forward.edges).toHaveLength(1);
    expect(reversed.edges).toHaveLength(1);

    // Sorted, so the two arrival orders are byte-identical rather than merely
    // containing the same names.
    expect(forward.edges[0].data?.targetFunctions).toEqual(["export", "lookup", "summarise"]);
    expect(reversed.edges[0].data?.targetFunctions).toEqual(
      forward.edges[0].data?.targetFunctions
    );
  });

  it("shows the SUM of its functions, not whichever one arrived first", () => {
    const stats: EdgeStat[] = [
      makeStat({ source: "caller", target: "prov", target_function: "lookup", call_count: 90, avg_latency_ms: 10, error_count: 0, error_rate: 0 }),
      makeStat({ source: "caller", target: "prov", target_function: "summarise", call_count: 10, avg_latency_ms: 1000, error_count: 5, error_rate: 50 }),
    ];

    const { edges } = buildGraphFromAgents(tagsOnlyFilter(["lookup", "summarise"]));
    const merged = mergeEdgeStatsIntoEdges(edges, stats);

    // 90 calls at 10ms plus 10 at 1000ms is 10,900ms over 100 calls = 109ms.
    // NOT 10 (first-seen), NOT 1000 (other-seen), and not the 505 an unweighted
    // mean of the two averages would give.
    expect(String(merged[0].label)).toContain("109");
    expect(String(merged[0].label)).not.toContain("505");

    // 5 errors in 100 calls is 5%, which is elevated — neither the clean edge
    // the fast tool alone would paint nor the failing one the slow tool would.
    expect(merged[0].style?.stroke).toBe(EDGE_HEAT_COLORS.elevated);
  });

  it("gives the same answer whichever order the rows arrive in", () => {
    const rows: EdgeStat[] = [
      makeStat({ source: "caller", target: "prov", target_function: "lookup", call_count: 90, avg_latency_ms: 10 }),
      makeStat({ source: "caller", target: "prov", target_function: "summarise", call_count: 10, avg_latency_ms: 1000, error_count: 5, error_rate: 50 }),
    ];
    const graph = () => buildGraphFromAgents(tagsOnlyFilter(["lookup", "summarise"])).edges;

    const forward = mergeEdgeStatsIntoEdges(graph(), rows);
    const backward = mergeEdgeStatsIntoEdges(graph(), [...rows].reverse());

    expect(forward[0].label).toBe(backward[0].label);
    expect(forward[0].style?.stroke).toBe(backward[0].style?.stroke);
    expect(forward[0].style?.strokeWidth).toBe(backward[0].style?.strokeWidth);
  });

  it("reports only the functions that have rows, and nothing when none do", () => {
    const { edges } = buildGraphFromAgents(tagsOnlyFilter(["lookup", "never_called"]));

    // Partial coverage: one of the two functions was recorded. The edge shows
    // that traffic rather than blanking, and rather than averaging in a zero
    // for a function that simply has no observations.
    const partial = mergeEdgeStatsIntoEdges(edges, [
      makeStat({ source: "caller", target: "prov", target_function: "lookup", call_count: 90, avg_latency_ms: 10 }),
    ]);
    expect(String(partial[0].label)).toContain("10");

    // No coverage at all: structural style, untouched.
    const none = mergeEdgeStatsIntoEdges(edges, [
      makeStat({ source: "caller", target: "prov", target_function: "unrelated" }),
    ]);
    expect(none[0]).toBe(edges[0]);
  });

  it("scales stroke width against the busiest EDGE, so a sum cannot overflow the scale", () => {
    // The collapsed edge's 100 calls exceed either row on its own. A denominator
    // taken from the rows would put this edge past the top of the scale.
    const { edges } = buildGraphFromAgents(tagsOnlyFilter(["lookup", "summarise"]));
    const merged = mergeEdgeStatsIntoEdges(edges, [
      makeStat({ source: "caller", target: "prov", target_function: "lookup", call_count: 50 }),
      makeStat({ source: "caller", target: "prov", target_function: "summarise", call_count: 50 }),
    ]);
    expect(Number(merged[0].style?.strokeWidth)).toBeLessThanOrEqual(4);
    expect(Number(merged[0].style?.strokeWidth)).toBeCloseTo(4);
  });
});

describe("replica grouping still lines the two sides up", () => {
  // Stats are recorded per REAL agent name; the graph collapses replicas into
  // one node keyed `group:<name>`. The merge resolves a node key back to that
  // base name, and adding the function as a third component must not disturb it.
  const twoReplicasEachSide: Agent[] = [
    {
      id: "caller-aaaa1111",
      name: "caller",
      agent_type: "mcp_agent",
      status: "healthy",
      endpoint: "http://caller:8080",
      total_dependencies: 1,
      dependencies_resolved: 1,
      capabilities: [],
      dependency_resolutions: [
        { function_name: "consume", capability: "reports", status: "available", provider_agent_id: "prov-cccc3333", mcp_tool: "run_report" },
      ],
    },
    {
      id: "caller-bbbb2222",
      name: "caller",
      agent_type: "mcp_agent",
      status: "healthy",
      endpoint: "http://caller2:8080",
      total_dependencies: 1,
      dependencies_resolved: 1,
      capabilities: [],
      dependency_resolutions: [
        { function_name: "consume", capability: "reports", status: "available", provider_agent_id: "prov-dddd4444", mcp_tool: "run_report" },
      ],
    },
    {
      id: "prov-cccc3333",
      name: "prov",
      agent_type: "mcp_agent",
      status: "healthy",
      endpoint: "http://prov:8080",
      total_dependencies: 0,
      dependencies_resolved: 0,
      capabilities: [{ function_name: "run_report", name: "reports", version: "1.0.0" }],
    },
    {
      id: "prov-dddd4444",
      name: "prov",
      agent_type: "mcp_agent",
      status: "healthy",
      endpoint: "http://prov2:8080",
      total_dependencies: 0,
      dependencies_resolved: 0,
      capabilities: [{ function_name: "run_report", name: "reports", version: "1.0.0" }],
    },
  ];

  it("matches a stat keyed by base agent name onto the collapsed group edge", () => {
    const { nodes, edges } = buildGraphFromAgents(twoReplicasEachSide);
    expect(nodes.map((n) => n.id).sort()).toEqual(["group:caller", "group:prov"]);
    expect(edges).toHaveLength(1);
    expect(edges[0].data?.targetFunctions).toEqual(["run_report"]);

    const merged = mergeEdgeStatsIntoEdges(edges, [
      makeStat({ source: "caller", target: "prov", target_function: "run_report", avg_latency_ms: 42 }),
    ]);
    expect(String(merged[0].label)).toMatch(/42/);
    expect(merged[0].style?.stroke).toBe(EDGE_HEAT_COLORS.clean);
  });
});

describe("the Traffic table shows one row per called function", () => {
  const response: TrafficResponse = {
    enabled: true,
    window: "all",
    total_calls: 3,
    total_errors: 0,
    edge_stats: [
      makeStat({ source: "caller", target: "prov", target_function: "summarise", avg_latency_ms: 1500, call_count: 3 }),
      makeStat({ source: "caller", target: "prov", target_function: "lookup", avg_latency_ms: 4, call_count: 77 }),
    ],
    agent_stats: [],
    model_stats: [],
  };

  it("renders both rows of a single route, each with its own function and numbers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => response })
    );
    const { default: TrafficPage } = await import("../app/traffic/page");
    render(<TrafficPage />);

    await waitFor(() => expect(screen.getByText("lookup")).toBeInTheDocument());
    expect(screen.getByText("summarise")).toBeInTheDocument();

    // Two rows for ONE route: the route names appear twice over.
    expect(screen.getAllByText("caller")).toHaveLength(2);
    expect(screen.getAllByText("prov")).toHaveLength(2);

    // And the numbers belong to their own row rather than to the pair.
    const lookupRow = screen.getByText("lookup").closest("tr");
    expect(lookupRow).not.toBeNull();
    expect(within(lookupRow!).getByText("77")).toBeInTheDocument();
    expect(within(lookupRow!).getByText("4.0ms")).toBeInTheDocument();

    const summariseRow = screen.getByText("summarise").closest("tr");
    expect(within(summariseRow!).getByText("3")).toBeInTheDocument();
    expect(within(summariseRow!).getByText("1500.0ms")).toBeInTheDocument();

    vi.unstubAllGlobals();
  });

  it("shows the same rows on the dashboard's own traffic widget", () => {
    // A SECOND surface renders these rows, fed by SSE rather than by the
    // windowed endpoint. Keyed by the route alone it would now emit duplicate
    // React keys for one route's several functions, and draw rows that look
    // identical while carrying different numbers.
    mockEdgeStats.length = 0;
    mockEdgeStats.push(...response.edge_stats);
    render(<TrafficTable />);

    expect(screen.getByText("Function")).toBeInTheDocument();
    expect(screen.getAllByText("caller")).toHaveLength(2);

    const lookupRow = screen.getByText("lookup").closest("tr");
    expect(within(lookupRow!).getByText("77")).toBeInTheDocument();
    const summariseRow = screen.getByText("summarise").closest("tr");
    expect(within(summariseRow!).getByText("3")).toBeInTheDocument();

    mockEdgeStats.length = 0;
  });

  it("names the column so the second value on a route is readable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => response })
    );
    const { default: TrafficPage } = await import("../app/traffic/page");
    render(<TrafficPage />);

    await waitFor(() => expect(screen.getByText("Function")).toBeInTheDocument());
    vi.unstubAllGlobals();
  });
});
