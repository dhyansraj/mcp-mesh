// Edge construction and edge COLOUR in buildGraphFromAgents.
//
// None of this was covered when issue #1521 was found: the only topology test
// was buildIdToNodeKey, so the builder colouring a dependency edge by the
// CALLER's agent_type — while the legend described the target — was something
// no test in this suite could see, for as long as it existed.
//
// The rule these tests hold: an edge's colour describes WHAT IS BEING CALLED.
// The provider's matching capability decides `dep` colour; nothing reads the
// consumer's type.
//
// The colours a person sees are the builder's output AFTER the traffic merge,
// so one block asserts against that rather than against the builder (#1530),
// and the last one renders the legend. The middle blocks compare modules and
// builder output with each other, which is only part of the palette contract —
// they cannot see a swatch written back to a literal colour, and they could not
// see the merge painting over every stroke they had just checked.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Edge } from "@xyflow/react";
import type { Agent, Capability, DependencyResolution, EdgeStat } from "../lib/types";
import { buildGraphFromAgents } from "../lib/topology";
import { mergeEdgeStatsIntoEdges } from "../components/topology/TopologyGraph";
import { extractAgentName, formatDuration } from "../lib/api";
import {
  EDGE_COLORS,
  EDGE_HEAT_COLORS,
  EDGE_HEAT_LEGEND,
  EDGE_LEGEND,
} from "../lib/edge-palette";
import { EdgeLegend } from "../components/topology/EdgeLegend";

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "svc-00000000",
    name: "svc",
    agent_type: "mcp_agent",
    status: "healthy",
    endpoint: "http://svc:8080",
    total_dependencies: 0,
    dependencies_resolved: 0,
    capabilities: [],
    ...overrides,
  };
}

const cap = (name: string, task?: boolean): Capability => ({
  function_name: `fn_${name}`,
  name,
  version: "1.0.0",
  ...(task === undefined ? {} : { task }),
});

const dep = (
  capability: string,
  provider: string,
  status: DependencyResolution["status"] = "available"
): DependencyResolution => ({
  function_name: "consume",
  capability,
  status,
  provider_agent_id: provider,
});

/** Every edge's stroke, keyed by edge id. */
function strokes(agents: Agent[]): Record<string, string> {
  const { edges } = buildGraphFromAgents(agents);
  return Object.fromEntries(edges.map((e) => [e.id, e.style?.stroke as string]));
}

/** The one edge in a two-agent fixture. */
function onlyEdge(agents: Agent[]) {
  const { edges } = buildGraphFromAgents(agents);
  expect(edges).toHaveLength(1);
  return edges[0];
}

const provider = (id: string, name: string, caps: Capability[]) =>
  makeAgent({ id, name, capabilities: caps });

const consumer = (
  id: string,
  name: string,
  deps: DependencyResolution[],
  overrides: Partial<Agent> = {}
) =>
  makeAgent({
    id,
    name,
    dependency_resolutions: deps,
    total_dependencies: deps.length,
    dependencies_resolved: deps.filter((d) => d.status === "available").length,
    ...overrides,
  });

describe("dep edge colour is decided by the provider", () => {
  it("an ordinary capability is a plain dependency", () => {
    const edge = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222")]),
      provider("prov-22222222", "prov", [cap("reports")]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.dependency);
    expect(edge.animated).toBe(true);
  });

  it("a task=true capability is a job", () => {
    const edge = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222")]),
      provider("prov-22222222", "prov", [cap("reports", true)]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.job);
  });

  it("matches on the resolved capability, not merely on the provider owning some task", () => {
    // The provider is a MeshJob producer, but NOT for the capability this edge
    // resolved. Colouring by "the provider has a task somewhere" would repaint
    // every other edge into that agent.
    const edge = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222")]),
      provider("prov-22222222", "prov", [cap("reports"), cap("bulk_export", true)]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.dependency);
  });

  it("matches the resolved FUNCTION when one capability name is on two functions", () => {
    // A capability name is not unique within an agent: two functions can
    // declare the same name and be told apart by tags, and only one of them
    // need be a job. The resolution says which function won, in `mcp_tool`,
    // and that is the only field that can answer this.
    const twoFunctions = makeAgent({
      id: "prov-22222222",
      name: "prov",
      capabilities: [
        { function_name: "run_now", name: "reports", version: "1.0.0" },
        { function_name: "run_overnight", name: "reports", version: "1.0.0", task: true },
      ],
    });

    const toTheJob = onlyEdge([
      consumer("caller-11111111", "caller", [
        { ...dep("reports", "prov-22222222"), mcp_tool: "run_overnight" },
      ]),
      twoFunctions,
    ]);
    expect(toTheJob.style?.stroke).toBe(EDGE_COLORS.job);

    const toTheOther = onlyEdge([
      consumer("caller-11111111", "caller", [
        { ...dep("reports", "prov-22222222"), mcp_tool: "run_now" },
      ]),
      twoFunctions,
    ]);
    expect(toTheOther.style?.stroke).toBe(EDGE_COLORS.dependency);
  });

  it("falls back to the capability name when the wire carries no mcp_tool", () => {
    // Registries predating that field, and any resolution that simply lacks
    // it. Ambiguous where a name is shared, which is the best available answer
    // rather than a choice — and strictly better than drawing nothing.
    const edge = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222")]),
      provider("prov-22222222", "prov", [cap("reports", true)]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.job);
  });

  it("an mcp_tool naming no known function is not a job", () => {
    // Skew between the resolution and the snapshot's capability list. The
    // precise key missed, and a silent fall back to the name would paint an
    // edge whose provenance nothing in the payload supports.
    const edge = onlyEdge([
      consumer("caller-11111111", "caller", [
        { ...dep("reports", "prov-22222222"), mcp_tool: "renamed_since" },
      ]),
      provider("prov-22222222", "prov", [cap("reports", true)]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.dependency);
  });

  it("a duplicated agent id is LAST WINS, including when the last declares no job", () => {
    // Two records for one id should not reach the UI at all. If they do, the
    // later one describes the agent — so a capability that has stopped being a
    // task stops colouring its edge, rather than the earlier copy holding the
    // colour indefinitely.
    const wasAJob = makeAgent({ id: "prov-22222222", name: "prov", capabilities: [cap("reports", true)] });
    const isNot = makeAgent({ id: "prov-22222222", name: "prov", capabilities: [cap("reports")] });
    const caller = consumer("caller-11111111", "caller", [dep("reports", "prov-22222222")]);

    const { edges: nowPlain } = buildGraphFromAgents([caller, wasAJob, isNot]);
    expect(nowPlain[0].style?.stroke).toBe(EDGE_COLORS.dependency);

    const { edges: nowJob } = buildGraphFromAgents([caller, isNot, wasAJob]);
    expect(nowJob[0].style?.stroke).toBe(EDGE_COLORS.job);
  });

  it("task=false and an absent task flag are both ordinary (older registries)", () => {
    const explicit = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222")]),
      provider("prov-22222222", "prov", [cap("reports", false)]),
    ]);
    expect(explicit.style?.stroke).toBe(EDGE_COLORS.dependency);

    const absent = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222")]),
      provider("prov-22222222", "prov", [cap("reports")]),
    ]);
    expect(absent.style?.stroke).toBe(EDGE_COLORS.dependency);
  });
});

describe("the caller's agent_type does not colour anything (issue #1521)", () => {
  // Every member of the union, so a type the builder has never seen cannot be
  // the one that still colours an edge.
  const cases: Array<Agent["agent_type"]> = [
    "mcp_agent",
    "mesh_tool",
    "decorator_agent",
    "api",
    "a2a",
  ];

  it.each(cases)("a %s caller into an ordinary provider draws a plain dependency", (type) => {
    const edge = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222")], {
        agent_type: type,
      }),
      provider("prov-22222222", "prov", [cap("reports")]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.dependency);
  });

  it("an @mesh.route gateway no longer draws pink — the same edge as any other caller", () => {
    const gatewayEdge = onlyEdge([
      // A route agent publishes no capability of its own, which is exactly why
      // it can never BE a provider and why the pink branch was unreachable.
      consumer("gateway-11111111", "gateway", [dep("trip_planning", "planner-22222222")], {
        agent_type: "api",
        capabilities: [],
      }),
      provider("planner-22222222", "planner", [cap("trip_planning")]),
    ]);
    const mcpEdge = onlyEdge([
      consumer("plain-11111111", "plain", [dep("trip_planning", "planner-22222222")]),
      provider("planner-22222222", "planner", [cap("trip_planning")]),
    ]);
    // Named, not merely compared: two edges with no stroke at all would be
    // equal to each other and unequal to the job colour, so the comparison on
    // its own passes for a builder that has stopped styling anything.
    expect(gatewayEdge.style?.stroke).toBe(EDGE_COLORS.dependency);
    expect(gatewayEdge.style?.stroke).toBe(mcpEdge.style?.stroke);
    expect(gatewayEdge.style?.stroke).not.toBe(EDGE_COLORS.job);
  });

  it("an api caller into a job provider IS a job edge — the provider still decides", () => {
    const edge = onlyEdge([
      consumer("gateway-11111111", "gateway", [dep("bulk_export", "prov-22222222")], {
        agent_type: "api",
      }),
      provider("prov-22222222", "prov", [cap("bulk_export", true)]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.job);
  });
});

describe("unavailable and unresolved are unchanged", () => {
  it("unavailable is red and not animated", () => {
    const edge = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222", "unavailable")]),
      provider("prov-22222222", "prov", [cap("reports")]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.unavailable);
    // The style has to BE there for its dash to be meaningfully absent: an edge
    // with no style at all satisfies the undefined check while being drawn by
    // React Flow's defaults.
    expect(edge.style).toBeDefined();
    expect(edge.style).toHaveProperty("strokeDasharray", undefined);
    expect(edge.animated).toBe(false);
  });

  it("unresolved is grey and dashed", () => {
    const edge = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222", "unresolved")]),
      provider("prov-22222222", "prov", [cap("reports")]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.unresolved);
    expect(edge.style?.strokeDasharray).toBe("5 5");
  });

  it("status wins over the job colour — a broken job edge is still red", () => {
    const edge = onlyEdge([
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222", "unavailable")]),
      provider("prov-22222222", "prov", [cap("reports", true)]),
    ]);
    expect(edge.style?.stroke).toBe(EDGE_COLORS.unavailable);
  });

  it("llm tool and llm provider edges keep their own colours", () => {
    const agents: Agent[] = [
      makeAgent({
        id: "planner-11111111",
        name: "planner",
        llm_tool_resolutions: [
          {
            function_name: "plan",
            filter_capability: "reports",
            status: "available",
            provider_agent_id: "prov-22222222",
          },
          {
            function_name: "plan",
            filter_capability: "missing",
            status: "unresolved",
            provider_agent_id: "prov-22222222",
          },
        ],
        llm_provider_resolutions: [
          {
            function_name: "plan",
            required_capability: "llm",
            status: "available",
            provider_agent_id: "model-33333333",
          },
          {
            function_name: "plan",
            required_capability: "llm2",
            status: "unavailable",
            provider_agent_id: "model-33333333",
          },
        ],
      }),
      // task=true on the provider must NOT leak into llm/prov edges: those are
      // not dependency resolutions and are never job invocations.
      provider("prov-22222222", "prov", [cap("reports", true)]),
      provider("model-33333333", "model", [cap("llm", true)]),
    ];
    const s = strokes(agents);
    expect(s["llm|planner-11111111|prov-22222222|llm:reports"]).toBe(EDGE_COLORS.llmTool);
    expect(s["llm|planner-11111111|prov-22222222|llm:missing"]).toBe(EDGE_COLORS.unavailable);
    expect(s["prov|planner-11111111|model-33333333|provider:llm"]).toBe(EDGE_COLORS.llmProvider);
    expect(s["prov|planner-11111111|model-33333333|provider:llm2"]).toBe(EDGE_COLORS.unavailable);
  });
});

describe("replicas collapsing into one edge", () => {
  // Two provider replicas under one name, so the target collapses to
  // `group:prov`, and two consumer replicas resolving one to each. Both
  // contributions land on the SAME edge key, which is where a colour
  // disagreement can now exist at all.
  const mixedGroup = (jobFirst: boolean): Agent[] => {
    const jobbing = provider("prov-22222222", "prov", [cap("reports", true)]);
    const plain = provider("prov-33333333", "prov", [cap("reports")]);
    const providers = jobFirst ? [jobbing, plain] : [plain, jobbing];
    return [
      consumer("caller-11111111", "caller", [dep("reports", providers[0].id)]),
      consumer("caller-44444444", "caller", [dep("reports", providers[1].id)]),
      ...providers,
    ];
  };

  it("collapses to a single edge between the two group nodes", () => {
    const { nodes, edges } = buildGraphFromAgents(mixedGroup(true));
    expect(nodes.map((n) => n.id).sort()).toEqual(["group:caller", "group:prov"]);
    expect(edges).toHaveLength(1);
    expect(edges[0].id).toBe("dep|group:caller|group:prov|reports");
  });

  it("draws the job colour when ANY replica behind it is a job, in either order", () => {
    for (const jobFirst of [true, false]) {
      const { edges } = buildGraphFromAgents(mixedGroup(jobFirst));
      expect(edges[0].style?.stroke).toBe(EDGE_COLORS.job);
    }
  });

  it("stays a plain dependency when no replica is a job", () => {
    const agents: Agent[] = [
      consumer("caller-11111111", "caller", [dep("reports", "prov-22222222")]),
      consumer("caller-44444444", "caller", [dep("reports", "prov-33333333")]),
      provider("prov-22222222", "prov", [cap("reports")]),
      provider("prov-33333333", "prov", [cap("reports")]),
    ];
    const { edges } = buildGraphFromAgents(agents);
    expect(edges).toHaveLength(1);
    expect(edges[0].style?.stroke).toBe(EDGE_COLORS.dependency);
  });

  it("a degraded replica still wins over a healthy job one, in either order", () => {
    // Both orders, and the reason is the job branch rather than the worst-of
    // rule it is checking: that branch reaches for the job colour only while
    // the edge it would overwrite is healthy. Drop that conjunct as
    // redundant-looking and the degraded contribution seen FIRST is repainted
    // as a job by the healthy one arriving second — a broken edge drawn as a
    // working MeshJob. Fixing one order cannot see it.
    const degradedFirst = (jobFirst: boolean): Agent[] => {
      const jobbing = provider("prov-22222222", "prov", [cap("reports", true)]);
      const plain = provider("prov-33333333", "prov", [cap("reports")]);
      const jobCaller = consumer("caller-11111111", "caller", [dep("reports", jobbing.id)]);
      const brokenCaller = consumer("caller-44444444", "caller", [
        dep("reports", plain.id, "unresolved"),
      ]);
      return jobFirst
        ? [jobCaller, brokenCaller, jobbing, plain]
        : [brokenCaller, jobCaller, jobbing, plain];
    };

    for (const jobFirst of [true, false]) {
      const { edges } = buildGraphFromAgents(degradedFirst(jobFirst));
      expect(edges).toHaveLength(1);
      expect(edges[0].style?.stroke).toBe(EDGE_COLORS.unresolved);
      expect(edges[0].style?.strokeDasharray).toBe("5 5");
    }
  });

  it("unavailable beats unresolved when replicas disagree, in either order", () => {
    // The remaining order-dependence, between the two cases above: both
    // contributions are degraded, so neither the worst-of merge nor the job
    // escalation fires and the map kept whichever arrived first. One order
    // alone cannot see it — it passes for the builder that has no rule at all.
    //
    // The unresolved contribution carries a provider id, which a registry does
    // not currently emit (see the note in addEdge): without one the edge loop
    // drops the dep and there is nothing to merge. The precedence is a property
    // of the merge, and is asserted as one.
    const disagreeing = (unavailableFirst: boolean): Agent[] => {
      const left = provider("prov-22222222", "prov", [cap("reports")]);
      const right = provider("prov-33333333", "prov", [cap("reports")]);
      const brokenCaller = consumer("caller-11111111", "caller", [
        dep("reports", left.id, "unavailable"),
      ]);
      const pendingCaller = consumer("caller-44444444", "caller", [
        dep("reports", right.id, "unresolved"),
      ]);
      return unavailableFirst
        ? [brokenCaller, pendingCaller, left, right]
        : [pendingCaller, brokenCaller, left, right];
    };

    for (const unavailableFirst of [true, false]) {
      const { edges } = buildGraphFromAgents(disagreeing(unavailableFirst));
      expect(edges).toHaveLength(1);
      expect(edges[0].style?.stroke).toBe(EDGE_COLORS.unavailable);
      // The dash has to go with the colour: half a merge leaves a red edge
      // still drawn dashed, which is the grey row's styling under the red row's
      // colour and describes neither state.
      expect(edges[0].style).toHaveProperty("strokeDasharray", undefined);
      expect(edges[0].animated).toBe(false);
    }
  });
});

describe("edges nothing can be drawn to", () => {
  it("skips a resolution whose provider is not in the snapshot", () => {
    const { edges } = buildGraphFromAgents([
      consumer("caller-11111111", "caller", [dep("reports", "gone-99999999")]),
    ]);
    expect(edges).toEqual([]);
  });

  it("skips a resolution carrying no provider id", () => {
    const { edges } = buildGraphFromAgents([
      consumer("caller-11111111", "caller", [
        { function_name: "consume", capability: "reports", status: "unresolved" },
      ]),
    ]);
    expect(edges).toEqual([]);
  });
});

// The duplication this issue was half about: the legend carried its own copy of
// the six hexes, so it went on advertising a colour the builder had stopped
// emitting. Both directions are asserted, against a fixture that exercises
// every branch — a new stroke with no legend row fails, and so does a legend
// row for a stroke nothing can produce.
describe("the legend and the builder cannot drift apart", () => {
  /** One fixture reaching every colour the builder is able to emit. */
  const everyBranch: Agent[] = [
    makeAgent({
      id: "caller-11111111",
      name: "caller",
      dependency_resolutions: [
        dep("reports", "prov-22222222"),
        dep("bulk_export", "prov-22222222"),
        dep("broken", "prov-22222222", "unavailable"),
        dep("pending", "prov-22222222", "unresolved"),
      ],
      llm_tool_resolutions: [
        {
          function_name: "plan",
          filter_capability: "reports",
          status: "available",
          provider_agent_id: "prov-22222222",
        },
      ],
      llm_provider_resolutions: [
        {
          function_name: "plan",
          required_capability: "llm",
          status: "available",
          provider_agent_id: "model-33333333",
        },
      ],
    }),
    provider("prov-22222222", "prov", [
      cap("reports"),
      cap("bulk_export", true),
      cap("broken"),
      cap("pending"),
    ]),
    provider("model-33333333", "model", [cap("llm")]),
  ];

  const emitted = () =>
    new Set(buildGraphFromAgents(everyBranch).edges.map((e) => e.style?.stroke as string));

  it("every colour the BUILDER emits has a legend row", () => {
    // Half the contract. The other half — every colour the MERGE emits, which
    // is what a person actually looks at — is the block below, and was where
    // `elevated` used to escape the key entirely (issue #1530).
    const legend = new Set<string>(EDGE_LEGEND.map((e) => EDGE_COLORS[e.key]));
    expect([...emitted()].filter((c) => !legend.has(c))).toEqual([]);
  });

  it("the two axes have no colour in common", () => {
    // Not just separate modules: disjoint sets. A hex in both puts two rows in
    // the key for one stroke, and a reader has no way to tell which of the two
    // they are looking at — which is what `failing` and `unavailable` did until
    // the heat scale moved off that red (see lib/edge-palette.ts).
    const kinds = new Set<string>(Object.values(EDGE_COLORS));
    expect(Object.values(EDGE_HEAT_COLORS).filter((c) => kinds.has(c))).toEqual([]);
  });

  it("every legend row names a colour the builder can emit", () => {
    const drawn = emitted();
    expect(EDGE_LEGEND.filter((e) => !drawn.has(EDGE_COLORS[e.key])).map((e) => e.label)).toEqual(
      []
    );
  });

  it("the palette has no entry the legend does not show", () => {
    expect(EDGE_LEGEND.map((e) => e.key).sort()).toEqual(Object.keys(EDGE_COLORS).sort());
  });

  it("only the dependency-unresolved edge is drawn dashed-and-grey", () => {
    // What the "Unresolved dependency" row claims. llm/prov edges render their
    // unresolved state red, which is why the red row's label has to cover it.
    const dashedGrey = buildGraphFromAgents(everyBranch).edges.filter(
      (e) => e.style?.stroke === EDGE_COLORS.unresolved
    );
    expect(dashedGrey.map((e) => e.id)).toEqual(["dep|caller-11111111|prov-22222222|pending"]);
    expect(dashedGrey[0].style?.strokeDasharray).toBe("5 5");
  });
});

// What the graph is actually STROKED with, which is the builder's output after
// mergeEdgeStatsIntoEdges has had it (issue #1530).
//
// The builder's colours were never the last word: the merge repainted any edge
// with a stat row, a zero error rate included, so on any mesh with tracing on
// the kind palette was thrown away nearly everywhere — and the colour it was
// replaced with, `clean`, said only "this one is fine", which was true of
// nearly every edge. Now heat paints ONLY over an edge with errors, so both
// axes are legible at once and the legend can cover both.
//
// These assertions are deliberately made against the merge rather than the
// builder: the previous contract was scoped to the builder and passed happily
// while `elevated` was on screen with nothing in the key to explain it.
describe("the colours the merge actually puts on screen", () => {
  /** Every edge kind, each carrying an mcp_tool so a stat row can join to it. */
  const everyKindUnderTraffic: Agent[] = [
    makeAgent({
      id: "caller-11111111",
      name: "caller",
      dependency_resolutions: [
        { ...dep("reports", "prov-22222222"), mcp_tool: "fn_reports" },
        { ...dep("bulk_export", "prov-22222222"), mcp_tool: "fn_bulk_export" },
        { ...dep("broken", "prov-22222222", "unavailable"), mcp_tool: "fn_broken" },
        { ...dep("pending", "prov-22222222", "unresolved"), mcp_tool: "fn_pending" },
      ],
      llm_tool_resolutions: [
        {
          function_name: "plan",
          filter_capability: "reports",
          status: "available",
          provider_agent_id: "prov-22222222",
          mcp_tool: "fn_reports",
        },
      ],
      llm_provider_resolutions: [
        {
          function_name: "plan",
          required_capability: "llm",
          status: "available",
          provider_agent_id: "model-33333333",
          mcp_tool: "fn_llm",
        },
      ],
    }),
    provider("prov-22222222", "prov", [
      cap("reports"),
      cap("bulk_export", true),
      cap("broken"),
      cap("pending"),
    ]),
    provider("model-33333333", "model", [cap("llm")]),
  ];

  const AVG_LATENCY_MS = 5;
  /**
   * Large enough that every rate below is a whole number of errors: at a
   * hundred calls, 9.99% is not a count anything could have recorded, and
   * `error_count` would have had to round to a figure disagreeing with
   * `error_rate`. Nothing reads the count today — the merge weights the rate
   * the row reports — but TopologyGraph.tsx keeps the option of deriving one
   * from the other open, and a boundary fixture whose two fields describe
   * different meshes would flip bands silently on the day it is taken.
   */
  const CALL_COUNT = 10_000;
  /** Every band and both sides of the boundary, in percent. */
  const RATES = [0, 0.5, 9.99, 10, 100];

  /** One stat row per (base source, base target, function) an edge joins on. */
  function rowsAt(errorRate: number, edges: Edge[]): EdgeStat[] {
    const rows = new Map<string, EdgeStat>();
    for (const edge of edges) {
      for (const fn of (edge.data?.targetFunctions as string[]) ?? []) {
        const source = extractAgentName(edge.source);
        const target = extractAgentName(edge.target);
        rows.set(`${source}|${target}|${fn}`, {
          source,
          target,
          target_function: fn,
          call_count: CALL_COUNT,
          error_count: (CALL_COUNT * errorRate) / 100,
          error_rate: errorRate,
          avg_latency_ms: AVG_LATENCY_MS,
          p99_latency_ms: 9,
          max_latency_ms: 12,
          min_latency_ms: 1,
        });
      }
    }
    return [...rows.values()];
  }

  /** Stroke by edge id, before and after the merge, at one error rate. */
  function strokesAt(errorRate: number) {
    const { edges } = buildGraphFromAgents(everyKindUnderTraffic);
    const merged = mergeEdgeStatsIntoEdges(edges, rowsAt(errorRate, edges));
    const byId = (list: Edge[]) =>
      Object.fromEntries(list.map((e) => [e.id, e.style?.stroke as string]));
    return { built: byId(edges), merged: byId(merged), builtEdges: edges, mergedEdges: merged };
  }

  /**
   * The strokes HEAT put on the graph, and only those: each merged edge's
   * stroke against the same edge's built stroke, keeping the ones that changed.
   *
   * Derived rather than read off the merged output, because the property being
   * asserted is about what the merge paints and must not depend on which hexes
   * the two palettes happen to hold. A union of every merged stroke lets an
   * edge KIND stand in for a heat colour that shares its value — which is what
   * made the reverse legend check below pass for `failing` while heat had
   * painted nothing at all.
   */
  function heatStrokes(rates: number[]): Set<string> {
    const painted = new Set<string>();
    for (const rate of rates) {
      const { built, merged } = strokesAt(rate);
      for (const [id, stroke] of Object.entries(merged)) {
        if (stroke !== built[id]) painted.add(stroke);
      }
    }
    return painted;
  }

  it("every kind of edge in the fixture really does pick up its stat row", () => {
    // Otherwise the tests below would pass by joining to nothing. Two tells,
    // both written only for a matched edge: the latency appended to the label,
    // asserted as the whole string rather than by looking for a digit in it,
    // and a stroke width where the builder set none.
    const { builtEdges, mergedEdges } = strokesAt(0);
    expect(mergedEdges).toHaveLength(6);
    mergedEdges.forEach((edge, i) => {
      expect(String(edge.label)).toBe(
        `${String(builtEdges[i].label)}  ${formatDuration(AVG_LATENCY_MS)}`
      );
      expect(builtEdges[i].style?.strokeWidth).toBeUndefined();
      expect(edge.style?.strokeWidth).toBeGreaterThan(1);
    });
  });

  it("an edge with no errors keeps the colour its KIND gave it", () => {
    const { built, merged } = strokesAt(0);
    // Every kind, by id, unchanged — not merely "some green survived".
    expect(merged).toEqual(built);
    expect(new Set(Object.values(merged))).toEqual(
      new Set([
        EDGE_COLORS.dependency,
        EDGE_COLORS.job,
        EDGE_COLORS.llmTool,
        EDGE_COLORS.llmProvider,
        EDGE_COLORS.unavailable,
        EDGE_COLORS.unresolved,
      ])
    );
  });

  it("an edge with errors is repainted whatever kind it is", () => {
    // Including the MeshJob edge, whose colour #1521 added and which the old
    // merge meant a reader could never see under traffic — and which now, quite
    // deliberately, still yields to an error.
    const { built, merged } = strokesAt(50);
    expect(new Set(Object.values(merged))).toEqual(new Set([EDGE_HEAT_COLORS.failing]));
    expect(merged).not.toEqual(built);
  });

  it("bands on either side of the ten-percent boundary", () => {
    // The unit is a percentage, 0-100, on both registry paths that emit it.
    //
    // Read off RATES rather than from its own literals, so that this is also
    // the record of what the two legend checks below cover: they union over the
    // same list, and a band dropped from it would leave them asserting less
    // while still passing.
    const strokeOf = (rate: number) => {
      const { merged } = strokesAt(rate);
      return merged["dep|caller-11111111|prov-22222222|reports"];
    };
    expect(RATES.map(strokeOf)).toEqual([
      EDGE_COLORS.dependency, // 0 — no errors, so the kind colour stands
      EDGE_HEAT_COLORS.elevated, // 0.5
      EDGE_HEAT_COLORS.elevated, // 9.99, the last rate under the boundary
      EDGE_HEAT_COLORS.failing, // 10, the boundary itself
      EDGE_HEAT_COLORS.failing, // 100
    ]);
  });

  it("a rate that reports nothing paints nothing", () => {
    // Defensive: the field is required and both server paths populate it. What
    // is being pinned is the DIRECTION of the failure — a rate that is negative
    // or not a number at all must fall out as nothing to say, not through both
    // band comparisons and into the colour reserved for the worst edges on the
    // graph, which is where the natural way of writing the guard sends it.
    for (const rate of [-1, Number.NaN]) {
      const { built, merged } = strokesAt(rate);
      expect(merged).toEqual(built);
    }
  });

  it("every colour the MERGE can emit has a legend row", () => {
    // The contract the old one was scoped short of. The union over the whole
    // range of error rates is every stroke that can reach a person, and the
    // union of the two legends is every colour the key explains. Every stroke
    // is the right set in THIS direction: an unexplained colour is unexplained
    // whichever axis put it there.
    const key = new Set<string>([
      ...EDGE_LEGEND.map((e) => EDGE_COLORS[e.key]),
      ...EDGE_HEAT_LEGEND.map((e) => EDGE_HEAT_COLORS[e.key]),
    ]);
    const reachable = new Set<string>();
    for (const rate of RATES) {
      for (const stroke of Object.values(strokesAt(rate).merged)) reachable.add(stroke);
    }
    expect([...reachable].filter((c) => !key.has(c))).toEqual([]);
  });

  it("every heat row names a colour the merge actually paints", () => {
    // The other direction, which is what caught the stale row in #1521, and the
    // one that is easy to write vacuously: over every merged stroke, a heat row
    // is satisfied by any edge KIND holding the same colour, with heat never
    // having run. Over the strokes the merge CHANGED it says what it means —
    // remove a branch from `getEdgeHeatColor` and this fails, whatever the two
    // palettes contain.
    //
    // A row for the healthy case would fail here too: nothing repaints a clean
    // edge any more, so no stroke it could name is ever one the merge changed.
    // That is why `EDGE_HEAT_COLORS` no longer holds a value for it.
    const painted = heatStrokes(RATES);
    expect(
      EDGE_HEAT_LEGEND.filter((e) => !painted.has(EDGE_HEAT_COLORS[e.key])).map((e) => e.label)
    ).toEqual([]);
  });

  it("the heat legend shows every heat colour there is", () => {
    expect(EDGE_HEAT_LEGEND.map((e) => e.key).sort()).toEqual(
      Object.keys(EDGE_HEAT_COLORS).sort()
    );
  });
});

// Everything above this line is data: two modules and a builder, compared with
// each other. None of it renders anything, so none of it can see the half of
// the contract that reaches a person — the swatches. Restating a colour there
// as a literal is the precise regression lib/edge-palette.ts was written to
// prevent, and until this block existed it passed the whole suite.
describe("the legend a person actually sees", () => {
  /** What the DOM gives back for a colour written as a hex. */
  const asRendered = (hex: string) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
  };

  const swatchFor = (key: string) => screen.getByTestId(`edge-legend-swatch-${key}`);
  // A separate id space, because the two key sets are unrelated and could one
  // day hold the same word — see the note on the element itself.
  const heatSwatchFor = (key: string) => screen.getByTestId(`edge-legend-heat-swatch-${key}`);

  it("renders one row per legend entry, labels and all", () => {
    render(<EdgeLegend />);
    for (const entry of EDGE_LEGEND) {
      expect(swatchFor(entry.key)).toBeInTheDocument();
      expect(screen.getByText(entry.label)).toBeInTheDocument();
    }
  });

  it("paints every swatch the colour the builder strokes that edge with", () => {
    render(<EdgeLegend />);
    for (const entry of EDGE_LEGEND) {
      const swatch = swatchFor(entry.key);
      const painted = entry.dashed
        ? swatch.style.borderColor
        : swatch.style.backgroundColor;
      expect(painted).toBe(asRendered(EDGE_COLORS[entry.key]));
    }
  });

  it("renders the heat rows too, in the heat colours", () => {
    // `elevated` was a colour on screen with no row at all (issue #1530): a
    // reader saw it and the key could not tell them what it was.
    render(<EdgeLegend />);
    for (const entry of EDGE_HEAT_LEGEND) {
      expect(screen.getByText(entry.label)).toBeInTheDocument();
      expect(heatSwatchFor(entry.key).style.backgroundColor).toBe(
        asRendered(EDGE_HEAT_COLORS[entry.key])
      );
    }
  });

  it("says that an error colour supersedes the kind rows", () => {
    // The two groups are disjoint colours, so the caption is not there to break
    // a tie — it is there because an erroring edge shows nothing of its kind,
    // and without saying so the key reads as six rows describing every edge on
    // screen when in fact any of them can be missing.
    render(<EdgeLegend />);
    expect(screen.getByText(/overrides/i)).toBeInTheDocument();
  });

  it("carries no colour of its own — every swatch reads it from the palette", () => {
    render(<EdgeLegend />);
    // A hex named anywhere in the markup other than in an element's own style
    // is a colour that has stopped being derived: written into the component,
    // it can drift from the stroke the builder emits, which is how the two came
    // apart the first time (issue #1521).
    //
    // Read off document.body rather than the render result's own root, whose
    // name is a utility candidate: Tailwind extracts from any text under
    // src/ui, this file included, and that one word is worth 282 bytes of
    // rules the dashboard never uses. See __tests__/spa-css-isolation.test.ts.
    for (const el of document.body.querySelectorAll("*")) {
      expect(el.className).not.toMatch(/#[0-9a-fA-F]{3,8}/);
    }
    for (const entry of EDGE_LEGEND) {
      const swatch = swatchFor(entry.key);
      const painted = entry.dashed
        ? swatch.style.borderColor
        : swatch.style.backgroundColor;
      // Empty means the colour arrived some other way — a literal class, most
      // likely — and the assertion above it would then be comparing nothing.
      expect(painted).not.toBe("");
    }
    for (const entry of EDGE_HEAT_LEGEND) {
      expect(heatSwatchFor(entry.key).style.backgroundColor).not.toBe("");
    }
  });
});
