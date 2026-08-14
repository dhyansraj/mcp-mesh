// THROWAWAY PROTOTYPE — the scripted arc for the scroll demo.
//
// Thirteen beats across five chapters. Every agent is a Python MCP agent until
// chapter 05; the mesh is deliberately uniform until then.
//
// Node membership is NOT discrete here: every beat carries the full cast, and
// reveal/withdrawal is expressed as per-node opacity (0 = not yet revealed).
// That lets the driver interpolate everything continuously.
//
// TOPOLOGY NOTE: planner-agent is the hub. `@mesh.llm(filter=[...])` is
// declared on the CONSUMER, so `llm_tool_resolutions` live on planner-agent's
// record and lib/topology.ts draws the cyan tier-2 edges out of it. Providers
// are leaves. Swapping providers therefore moves exactly one edge.
//
// INSERTION ORDER MATTERS: dagre breaks within-rank ties partly by insertion
// order, so the cast is listed in REVEAL order. Late arrivals land to the
// right, where the camera crops them out of early beats instead of leaving a
// hole in the middle. See buildWorld's return statement.
import type { Agent, DependencyResolution, LLMProviderResolution, LLMToolResolution } from "@/lib/types";

export const FLIGHT = "flight-agent-ba2b3bc8";
export const HOTEL = "hotel-agent-91af6b30";
export const POI = "poi-agent-2f88c614";
export const PREFS = "user-prefs-agent-4c17d9e2";
export const WEATHER = "weather-agent-7d3e05a1";
export const WEATHER_2 = "weather-agent-3c9b1f04";
export const WEATHER_3 = "weather-agent-e18a6d5b";
export const PLANNER = "planner-agent-d50a7712";
export const CLAUDE = "claude-provider-8b3f4c90";
export const OPENAI = "openai-provider-e62a1d47";
export const GATEWAY = "gateway-0a4e77c3";
export const BUDGET = "budget-analyst-5f21b8e6";
export const ADVENTURE = "adventure-advisor-c93d20af";
export const LOGISTICS = "logistics-planner-71e4a9d2";

/** lib/topology.ts collapses replicas into `group:<name>`. */
export const WEATHER_GROUP = "group:weather-agent";

// Edge ids follow lib/topology.ts's `${kind}|${src}|${dst}|${label}` format.
export const E_FLIGHT_PREFS = `dep|${FLIGHT}|${PREFS}|user_preferences`;
export const E_PLANNER_PREFS = `dep|${PLANNER}|${PREFS}|user_preferences`;
export const E_PLANNER_CLAUDE = `prov|${PLANNER}|${CLAUDE}|provider:llm`;
export const E_PLANNER_OPENAI = `prov|${PLANNER}|${OPENAI}|provider:llm`;
export const E_GATEWAY_PLANNER = `dep|${GATEWAY}|${PLANNER}|trip_planning`;
export const E_PLANNER_BUDGET = `dep|${PLANNER}|${BUDGET}|budget_analysis`;
export const E_PLANNER_ADVENTURE = `dep|${PLANNER}|${ADVENTURE}|adventure_advice`;
export const E_PLANNER_LOGISTICS = `dep|${PLANNER}|${LOGISTICS}|logistics_planning`;
export const SPECIALIST_EDGES = [E_PLANNER_BUDGET, E_PLANNER_ADVENTURE, E_PLANNER_LOGISTICS];
export const SPECIALIST_LLM_EDGES = [
  `prov|${BUDGET}|${CLAUDE}|provider:llm`,
  `prov|${ADVENTURE}|${CLAUDE}|provider:llm`,
  `prov|${LOGISTICS}|${CLAUDE}|provider:llm`,
];

// poi -> weather and planner -> weather exist in BOTH a single-instance and a
// replica-collapsed form, with different target node keys. Both are in the
// stable edge set; opacity picks which one is live.
export const E_POI_WEATHER = `dep|${POI}|${WEATHER}|weather_forecast`;
export const E_POI_WEATHER_G = `dep|${POI}|${WEATHER_GROUP}|weather_forecast`;
export const E_TOOL_WEATHER = `llm|${PLANNER}|${WEATHER}|llm:weather_forecast`;
export const E_TOOL_WEATHER_G = `llm|${PLANNER}|${WEATHER_GROUP}|llm:weather_forecast`;

const TOOL_CAPS: Array<[string, string, string]> = [
  [FLIGHT, "flight_search", "search_flights"],
  [HOTEL, "hotel_search", "search_hotels"],
  [WEATHER, "weather_forecast", "get_forecast"],
  [POI, "poi_search", "search_poi"],
];

/** Planner's tier-2 fan, single-instance form. */
export const TOOL_EDGES = TOOL_CAPS.map(
  ([target, cap]) => `llm|${PLANNER}|${target}|llm:${cap}`
);
/**
 * planner -> flight. Called out by name because B5 is built on it: paired with
 * E_FLIGHT_PREFS it puts one incoming and one outgoing edge on the same card,
 * which is the entire point of that beat.
 */
export const E_TOOL_FLIGHT = `llm|${PLANNER}|${FLIGHT}|llm:flight_search`;
/** Same fan with weather collapsed into its replica group. */
export const TOOL_EDGES_G = TOOL_EDGES.map((e) =>
  e === E_TOOL_WEATHER ? E_TOOL_WEATHER_G : e
);

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------

function base(
  id: string,
  capability: string | null,
  fn: string,
  tags: string[],
  description: string
): Agent {
  const name = id.replace(/-[0-9a-f]{8}$/, "");
  return {
    id,
    name,
    agent_type: "mcp_agent",
    runtime: "python",
    version: "1.0.0",
    description,
    status: "healthy",
    endpoint: `http://${name}:9090`,
    total_dependencies: 0,
    dependencies_resolved: 0,
    capabilities: capability
      ? [{ function_name: fn, name: capability, version: "1.0.0", tags }]
      : [],
  };
}

const dep = (
  fn: string,
  capability: string,
  provider: string,
  tool: string
): DependencyResolution => ({
  function_name: fn,
  capability,
  status: "available",
  provider_agent_id: provider,
  mcp_tool: tool,
});

const prov = (
  fn: string,
  provider: string,
  status: LLMProviderResolution["status"]
): LLMProviderResolution => ({
  function_name: fn,
  required_capability: "llm",
  status,
  provider_agent_id: provider,
  mcp_tool: "chat",
});

const toolFilters = (fn: string): LLMToolResolution[] =>
  TOOL_CAPS.map(([target, cap, tool]) => ({
    function_name: fn,
    filter_capability: cap,
    filter_tags: ["travel"],
    filter_mode: "any",
    status: "available" as const,
    provider_agent_id: target,
    mcp_tool: tool,
    provider_capability: cap,
  }));

export interface WorldConfig {
  flightWired: boolean;
  poiWired: boolean;
  /** planner's dependency counter — [resolved, total]. */
  plannerCounter: [number, number];
  claudeProviderStatus: LLMProviderResolution["status"];
  claudeStatus: Agent["status"];
  weatherRuntime: Agent["runtime"];
  hotelRuntime: Agent["runtime"];
  /** 1 = single instance, 3 = replica group (real bucketing, real group card). */
  weatherReplicas: 1 | 3;
  /** Chapter 05 resolution shot: light up the real A2A / MeshJob badge fields. */
  badges: boolean;
}

function specialist(id: string, capability: string, fn: string, tags: string[], desc: string, task: boolean): Agent {
  const a = base(id, capability, fn, tags, desc);
  a.total_dependencies = 1;
  a.dependencies_resolved = 1;
  a.llm_provider_resolutions = [prov(fn, CLAUDE, "available")];
  if (task) a.capabilities[0].task = true;
  return a;
}

// Every beat gets the full cast; opacity decides what the viewer sees.
export function buildWorld(cfg: WorldConfig): Agent[] {
  const flight = base(FLIGHT, "flight_search", "search_flights", ["flights", "travel"], "Finds flights");
  if (cfg.flightWired) {
    flight.dependency_resolutions = [dep("search_flights", "user_preferences", PREFS, "get_preferences")];
    flight.total_dependencies = 1;
    flight.dependencies_resolved = 1;
  }

  const hotel = base(HOTEL, "hotel_search", "search_hotels", ["hotels", "travel"], "Finds hotels");
  hotel.runtime = cfg.hotelRuntime;

  const poi = base(POI, "poi_search", "search_poi", ["poi", "travel"], "Points of interest");
  if (cfg.poiWired) {
    poi.dependency_resolutions = [dep("search_poi", "weather_forecast", WEATHER, "get_forecast")];
    poi.total_dependencies = 1;
    poi.dependencies_resolved = 1;
  }

  const prefs = base(PREFS, "user_preferences", "get_preferences", ["preferences", "travel"], "Traveller profile");

  const weatherIds = cfg.weatherReplicas === 3 ? [WEATHER, WEATHER_2, WEATHER_3] : [WEATHER];
  const weathers = weatherIds.map((id, i) => {
    const w = base(id, "weather_forecast", "get_forecast", ["weather", "travel"], "Forecasts");
    // Same declared NAME across replicas — that is what lib/agent-group.ts
    // buckets on, and what makes topology.ts emit a real group node.
    w.name = "weather-agent";
    w.runtime = cfg.weatherRuntime;
    w.endpoint = `http://weather-agent-${i}:9090`;
    w.last_seen = `2026-08-13T09:0${i}:00Z`;
    return w;
  });

  const planner = base(PLANNER, "trip_planning", "plan_trip", ["planner", "travel", "llm"], "Plans the trip");
  planner.dependencies_resolved = cfg.plannerCounter[0];
  planner.total_dependencies = cfg.plannerCounter[1];
  planner.dependency_resolutions = [
    dep("plan_trip", "user_preferences", PREFS, "get_preferences"),
    dep("plan_trip", "budget_analysis", BUDGET, "analyse_budget"),
    dep("plan_trip", "adventure_advice", ADVENTURE, "advise"),
    dep("plan_trip", "logistics_planning", LOGISTICS, "plan_logistics"),
  ];
  planner.llm_provider_resolutions = [
    prov("plan_trip", CLAUDE, cfg.claudeProviderStatus),
    prov("plan_trip", OPENAI, "available"),
  ];
  planner.llm_tool_resolutions = toolFilters("plan_trip");
  if (cfg.badges) planner.a2a_consumer = true;

  const claude = base(CLAUDE, "llm", "chat", ["claude"], "Anthropic Claude");
  claude.status = cfg.claudeStatus;

  const openai = base(OPENAI, "llm", "chat", ["openai", "gpt"], "OpenAI GPT");

  // The REST entry point: provides nothing, depends on trip_planning.
  // agent_type "api" makes topology.ts colour its outgoing edge pink.
  const gateway = base(GATEWAY, null, "handle_request", [], "REST entry point");
  gateway.agent_type = "api";
  gateway.dependency_resolutions = [dep("handle_request", "trip_planning", PLANNER, "plan_trip")];
  gateway.total_dependencies = 1;
  gateway.dependencies_resolved = 1;

  const budget = specialist(BUDGET, "budget_analysis", "analyse_budget", ["specialist", "budget", "llm"], "Budget specialist", cfg.badges);
  const adventure = specialist(ADVENTURE, "adventure_advice", "advise", ["specialist", "adventure", "llm"], "Adventure specialist", false);
  const logistics = specialist(LOGISTICS, "logistics_planning", "plan_logistics", ["specialist", "logistics", "llm"], "Logistics specialist", false);
  if (cfg.badges) {
    adventure.a2a_consumer = true;
    logistics.a2a_producer = true;
  }

  // REVEAL ORDER — see the header note.
  return [flight, hotel, poi, prefs, ...weathers, planner, claude, openai, gateway, budget, adventure, logistics];
}

const HEALTHY: WorldConfig = {
  flightWired: true,
  poiWired: true,
  plannerCounter: [2, 2],
  claudeProviderStatus: "available",
  claudeStatus: "healthy",
  weatherRuntime: "python",
  hotelRuntime: "python",
  weatherReplicas: 1,
  badges: false,
};

/** Canonical dagre input — single-instance form. */
export const MAXIMAL: Agent[] = buildWorld(HEALTHY);
/** Second build, only to harvest the replica-collapsed edge/node ids. */
export const MAXIMAL_REPLICAS: Agent[] = buildWorld({ ...HEALTHY, weatherReplicas: 3 });

// ---------------------------------------------------------------------------
// Beats
// ---------------------------------------------------------------------------

export const CHAPTERS = ["01 ARRIVE", "02 THINK", "03 SURVIVE", "04 OPEN", "05 GROW"];
export const BUILT_CHAPTERS = 5;

export const ACCENT = "#f97316";
export const ACCENT_ALERT = "#ef4444";

/**
 * Division of labour, per copy.md: the TITLE carries the need (why this moment
 * exists), the SUB-LINE carries the code that caused it, the DESCRIPTION
 * carries what the mesh did about it. Title and description both explaining
 * mechanism is what left the motive unspoken in the previous draft.
 *
 * Inline markup in `sub` and `desc`: `backticks` set monospace code,
 * *asterisks* set an italic annotation. See `inline()` in scroll.tsx.
 */
export interface Beat {
  chapter: number;
  title: string;
  sub: string;
  /** Body copy for the left gutter, under the sub-line. */
  desc?: string;
  accent: string;
  world: WorldConfig;
  /** Pinned scroll travel for this beat, in viewport heights. */
  weight: number;
  /**
   * Drop the reserved text gutter and let the graph have the whole panel.
   * Final frame only — the copy collapses to title + CTA there, so the
   * reclaimed width reads as a reveal rather than as an inconsistency.
   */
  fullBleed?: boolean;
  nodes: Record<string, number>;
  edges: Record<string, number>;
  /**
   * Edge ids drawn at ~1.5x their normal stroke for this beat. Opacity alone
   * could not separate the two edges B5 is about from the fan they sit in,
   * because the fan is the same colour family and leaves the same node.
   */
  emphasis?: string[];
  focus: string[];
  maxZoom?: number;
  /** 0..1 highlight ring on weather-agent (B11's badge change is tiny). */
  pulse?: number;
}

const spread = (ids: string[], v: number): Record<string, number> =>
  Object.fromEntries(ids.map((i) => [i, v]));

const TOOLS = [FLIGHT, HOTEL, WEATHER, POI];
const SPECIALISTS = [BUDGET, ADVENTURE, LOGISTICS];
const DEP_EDGES = [E_FLIGHT_PREFS, E_POI_WEATHER];
// Chapter 03 frames ONLY the three agents the chapter is about. The tool row
// is in these beats at ~0.25 wash and contributed nothing to the composition,
// but including it in the focus box stretched the frame to the graph's full
// 1720px width — which, once the left gutter was reserved, dropped the zoom to
// 0.50 at 1440 and made the arc's climax the least legible frame on the page.
// The demoted tools slide left under the gutter mask, which is where wash
// belongs.
const SURVIVE = [PLANNER, CLAUDE, OPENAI];
const SUNK = { [PREFS]: 0.08, [WEATHER]: 0.08 };
const SUNK_E = { [E_TOOL_WEATHER]: 0.06, [E_POI_WEATHER]: 0.05, [E_PLANNER_PREFS]: 0.05, [E_FLIGHT_PREFS]: 0.05 };

/** Everything that exists in the single-instance world. */
const ALL_SINGLE = [FLIGHT, HOTEL, POI, PREFS, WEATHER, PLANNER, CLAUDE, OPENAI, GATEWAY, ...SPECIALISTS];
/** Same, with weather collapsed. */
const ALL_GROUPED = [FLIGHT, HOTEL, POI, PREFS, WEATHER_GROUP, PLANNER, CLAUDE, OPENAI, GATEWAY, ...SPECIALISTS];

/** Steady-state mesh in chapters 04-05: everything wired and healthy. */
const FULL: WorldConfig = { ...HEALTHY, plannerCounter: [5, 5] };

// Background wash for the established mesh once chapters 04-05 take over.
const CH45_NODES = {
  ...spread(TOOLS, 0.32),
  [PREFS]: 0.25,
  [CLAUDE]: 0.4,
  [OPENAI]: 0.25,
  [PLANNER]: 1,
};
const CH45_EDGES = {
  ...spread(TOOL_EDGES, 0.18),
  ...spread(DEP_EDGES, 0.14),
  [E_PLANNER_PREFS]: 0.14,
  [E_PLANNER_CLAUDE]: 0.3,
  [E_PLANNER_OPENAI]: 0.18,
};

export const BEATS: Beat[] = [
  {
    chapter: 0,
    title: "It starts with one.",
    sub: '`@mesh.tool(capability="flight_search")`',
    desc: "This is the mesh dashboard. Every card is a running agent; every line is a dependency the mesh resolved on its own. Right now there is one agent — a plain Python function that searches flights. No server code, no registration call, no config file.",
    accent: ACCENT,
    // 0.9vh is the page's standard dwell for a beat carrying a full
    // description: it puts reading density near 300 characters per vh. Every
    // beat below now carries one, so the weights are near-uniform.
    weight: 0.9,
    world: { ...HEALTHY, flightWired: false, poiWired: false },
    nodes: { [FLIGHT]: 1 },
    edges: {},
    focus: [FLIGHT],
    maxZoom: 1.45,
  },
  {
    chapter: 0,
    title: "It needs what it doesn't have.",
    sub: '`dependencies=["user_preferences"]`',
    desc: "The flight agent needs preferences it cannot provide itself. It names the capability — not a host, not a port, not a URL — and the mesh finds whoever offers it and injects it as a callable parameter. Four more agents come up, and two relationships form without either side being told where the other lives.",
    accent: ACCENT,
    weight: 0.9,
    world: HEALTHY,
    nodes: { [FLIGHT]: 1, [HOTEL]: 0.5, [POI]: 1, [PREFS]: 1, [WEATHER]: 1 },
    edges: { [E_FLIGHT_PREFS]: 1, [E_POI_WEATHER]: 1 },
    focus: [FLIGHT, HOTEL, POI, PREFS, WEATHER],
    maxZoom: 0.95,
  },
  {
    chapter: 1,
    title: "Now it needs to reason.",
    sub: '`@mesh.llm(provider={"capability": "llm"})`',
    desc: "Some problems don't decompose into function calls. The planner needs a model, so it asks for one the same way anything else asks for anything — by capability. It imports no vendor SDK and reads no API key. A provider agent advertises `llm`, and that is the whole integration.",
    accent: ACCENT,
    weight: 0.9,
    world: HEALTHY,
    nodes: { ...spread(TOOLS, 0.28), [PREFS]: 0.28, [PLANNER]: 1, [CLAUDE]: 1 },
    edges: { ...spread(DEP_EDGES, 0.18), [E_PLANNER_PREFS]: 0.3, [E_PLANNER_CLAUDE]: 1 },
    focus: [PLANNER, CLAUDE],
    maxZoom: 1.0,
  },
  {
    chapter: 1,
    title: "Reasoning picks its own collaborators.",
    sub: '`filter=[{"capability": "flight_search"}, …]`',
    desc: "Instead of a fixed call graph, the planner declares what *kind* of help the model may recruit. The mesh resolves everything matching and hands them over as callable tools. Add a new agent to the mesh tomorrow and the model can reach it — with no redeploy and no change to this code.",
    accent: ACCENT,
    weight: 0.9,
    world: HEALTHY,
    nodes: { ...spread(TOOLS, 1), [PREFS]: 0.22, [PLANNER]: 1, [CLAUDE]: 0.4 },
    edges: {
      ...spread(DEP_EDGES, 0.15),
      [E_PLANNER_PREFS]: 0.15,
      [E_PLANNER_CLAUDE]: 0.4,
      ...spread(TOOL_EDGES, 1),
    },
    focus: [PLANNER, ...TOOLS],
    maxZoom: 0.85,
  },
  {
    // Reciprocity. No new nodes, no new edges, no layout change — the beat is
    // a re-framing of state that has been on screen since B2. flight-agent
    // holds E_FLIGHT_PREFS outbound (green, solid) and E_TOOL_FLIGHT inbound
    // (cyan, dashed) at once; everything else drops to a hard wash so the two
    // directions are the only thing with contrast on the panel.
    chapter: 1,
    // Broken after "asked" — the natural wrap splits "that / asked are now
    // asked", which buries the repetition the line is built on.
    title: "And the ones that asked\nare now asked.",
    sub: '`capability="flight_search"` — *consumed, and consuming*',
    desc: "Every consumer is also a provider. The flight agent that needed preferences a moment ago is now what the planner is looking for; the same card carries an edge in each direction. No one brokered the introduction and nothing was registered twice. This is the whole idea — not a call graph with a root, but a set of mutual needs that happen to resolve.",
    accent: ACCENT,
    weight: 0.9,
    world: HEALTHY,
    // THREE cards and TWO edges carry this frame, and nothing else may
    // compete. The first pass dimmed the rest but left all four tool edges
    // leaving the planner at similar weight, so the one arriving at flight was
    // not distinguishable and the reciprocity read as ordinary fan-out.
    nodes: {
      ...spread(TOOLS, 0.07),
      [FLIGHT]: 1,
      // Both ends of both edges have to be legible or only half the
      // relationship is on screen. prefs is the far end of the OUTGOING edge;
      // planner is the far end of the INCOMING one.
      [PREFS]: 0.85,
      [PLANNER]: 0.85,
      [CLAUDE]: 0.08,
    },
    edges: {
      // Barely there, not merely dimmed: these three are the ones the eye
      // was confusing with the edge that matters.
      ...spread(TOOL_EDGES, 0.02),
      [E_PLANNER_PREFS]: 0.04,
      [E_PLANNER_CLAUDE]: 0.05,
      [E_POI_WEATHER]: 0.03,
      [E_FLIGHT_PREFS]: 1,
      [E_TOOL_FLIGHT]: 1,
    },
    // Heavier stroke on exactly the two, so they read as a matched pair rather
    // than as one dependency edge and one tool edge that happen to touch.
    emphasis: [E_FLIGHT_PREFS, E_TOOL_FLIGHT],
    focus: [FLIGHT, PREFS, PLANNER],
    maxZoom: 1.05,
  },
  {
    chapter: 2,
    title: "A better one arrives.",
    sub: '`provider={"capability":"llm","tags":["+claude"]}`',
    desc: "A second provider joins, offering the same `llm` capability. The planner never named an endpoint, so nothing has to be rewired to consider it — it expresses a *preference* with a tag and the registry scores the candidates. Both remain eligible. One simply wins.",
    accent: ACCENT,
    weight: 0.9,
    world: HEALTHY,
    nodes: { ...spread(TOOLS, 0.3), ...SUNK, [PLANNER]: 1, [CLAUDE]: 1, [OPENAI]: 0.55 },
    edges: {
      ...spread(TOOL_EDGES, 0.22),
      ...SUNK_E,
      [E_PLANNER_CLAUDE]: 1,
      [E_PLANNER_OPENAI]: 0.3,
    },
    focus: SURVIVE,
    maxZoom: 0.85,
  },
  {
    chapter: 2,
    title: "It dies.",
    sub: "`meshctl stop claude-provider`",
    desc: "The preferred provider stops. Its heartbeat lapses, the registry ages it out, and the planner's dependency count drops. Nothing crashed and nothing was alerted. The mesh has simply stopped counting on something that is no longer there.",
    accent: ACCENT_ALERT,
    weight: 1.0,
    world: { ...HEALTHY, plannerCounter: [1, 2], claudeProviderStatus: "unavailable", claudeStatus: "unhealthy" },
    nodes: { ...spread(TOOLS, 0.26), ...SUNK, [PLANNER]: 1, [CLAUDE]: 1, [OPENAI]: 0.5 },
    edges: {
      ...spread(TOOL_EDGES, 0.2),
      ...SUNK_E,
      [E_PLANNER_CLAUDE]: 1,
      [E_PLANNER_OPENAI]: 0.26,
    },
    focus: SURVIVE,
    maxZoom: 0.85,
  },
  {
    chapter: 2,
    title: "Life goes on.",
    sub: "*no deploy · no config · no code change*",
    desc: "The planner's requirement was a capability, not an address — and something else already satisfies it. Traffic moves. Exactly one edge on this screen changed; every other relationship is untouched, and no agent was restarted to make it happen.",
    accent: ACCENT,
    weight: 1.0,
    world: { ...HEALTHY, claudeProviderStatus: "unavailable", claudeStatus: "unhealthy" },
    nodes: { ...spread(TOOLS, 0.3), ...SUNK, [PLANNER]: 1, [CLAUDE]: 0, [OPENAI]: 1 },
    edges: {
      ...spread(TOOL_EDGES, 0.28),
      ...SUNK_E,
      [E_PLANNER_CLAUDE]: 0,
      [E_PLANNER_OPENAI]: 1,
    },
    focus: SURVIVE,
    maxZoom: 0.85,
  },
  {
    chapter: 2,
    title: "The old one returns.",
    sub: "`+claude` *scores higher — both are ready*",
    desc: "It comes back, and traffic returns to it. Not because the substitute failed — it stayed healthy and connected the entire time — but because preference is scored continuously, not decided once at startup. Relationships here are never permanent, in either direction.",
    accent: ACCENT,
    weight: 1.0,
    world: HEALTHY,
    nodes: { ...spread(TOOLS, 0.3), ...SUNK, [PLANNER]: 1, [CLAUDE]: 1, [OPENAI]: 0.5 },
    edges: {
      ...spread(TOOL_EDGES, 0.28),
      ...SUNK_E,
      [E_PLANNER_CLAUDE]: 1,
      [E_PLANNER_OPENAI]: 0.28,
    },
    focus: SURVIVE,
    maxZoom: 0.85,
  },

  // ---------------------------------------------------- 04 OPEN
  {
    chapter: 3,
    title: "The outside world wants in.",
    sub: '`@mesh.route(dependencies=["trip_planning"])`',
    desc: "A five-line HTTP handler inherits the entire mesh. It provides no capability of its own and contains no business logic — it declares what it needs and becomes a front door. The same agents are also reachable over MCP and A2A without changing a line.",
    accent: ACCENT,
    weight: 0.9,
    world: FULL,
    nodes: { ...CH45_NODES, [GATEWAY]: 1 },
    edges: { ...CH45_EDGES, [E_GATEWAY_PLANNER]: 1 },
    focus: [GATEWAY, PLANNER],
    maxZoom: 1.0,
  },
  {
    chapter: 3,
    title: "One need, many minds.",
    sub: "`-> BudgetAnalysis` — *typed, validated, retried*",
    desc: "Three specialists resolve as ordinary callables and run at once. Each returns a typed model rather than a blob of text, and the mesh retries the call if a response doesn't match the schema. Fan-out costs one line, because parallelism was never the hard part — knowing who to call was.",
    accent: ACCENT,
    weight: 0.9,
    world: FULL,
    nodes: { ...CH45_NODES, [GATEWAY]: 0.35, ...spread(SPECIALISTS, 1) },
    edges: {
      ...CH45_EDGES,
      [E_GATEWAY_PLANNER]: 0.3,
      ...spread(SPECIALIST_EDGES, 1),
      ...spread(SPECIALIST_LLM_EDGES, 0.12),
    },
    focus: [PLANNER, ...SPECIALISTS],
    maxZoom: 0.9,
  },

  // ---------------------------------------------------- 05 GROW
  {
    chapter: 4,
    title: "Rewritten. Nobody noticed.",
    // Broken before the separator rather than after it: at 48 characters this
    // wraps at 1440, and a "·" stranded at the end of line one is a wart.
    sub: "`weather-agent -> TypeScript`\n`· hotel-agent -> Java`",
    desc: "Two agents were replaced with implementations in different languages. Same capabilities, same names, same relationships. Look at the graph: nothing moved. Their dependents were never told, because a dependent asks for a capability and has no way to express a preference about the language behind it.",
    accent: ACCENT,
    weight: 0.9,
    world: { ...FULL, weatherRuntime: "typescript", hotelRuntime: "java" },
    // Deliberately identical to B10's wash apart from the weather spotlight:
    // the ONLY thing that changes in this beat is one runtime badge.
    nodes: {
      ...CH45_NODES,
      [GATEWAY]: 0.3,
      ...spread(SPECIALISTS, 0.3),
      [WEATHER]: 1,
      [HOTEL]: 1,
      [POI]: 0.5,
    },
    edges: {
      ...CH45_EDGES,
      [E_GATEWAY_PLANNER]: 0.25,
      ...spread(SPECIALIST_EDGES, 0.2),
      ...spread(SPECIALIST_LLM_EDGES, 0.08),
      [E_TOOL_WEATHER]: 0.9,
      [E_POI_WEATHER]: 0.5,
    },
    focus: [HOTEL, WEATHER, POI],
    maxZoom: 1.15,
    pulse: 1,
  },
  {
    chapter: 4,
    title: "More of it. Same relationships.",
    sub: "`replicaCount: 3`",
    // ACCURACY: this deliberately does NOT say the mesh routes across healthy
    // instances. audit.md:153 — "The registry does not load balance… it
    // selects exactly one winner per dependency, deterministically."
    // Distribution is Kubernetes', through Service DNS.
    desc: "Three instances register under one name and collapse into a single card. Nothing re-resolves and no consumer is reconfigured — behind a Kubernetes Service the mesh resolves the name once and Kubernetes spreads the calls across whoever is healthy.",
    accent: ACCENT,
    weight: 0.9,
    world: { ...FULL, weatherRuntime: "typescript", hotelRuntime: "java", weatherReplicas: 3 },
    nodes: {
      ...CH45_NODES,
      [WEATHER]: 0,
      [WEATHER_GROUP]: 1,
      [GATEWAY]: 0.3,
      ...spread(SPECIALISTS, 0.3),
      [POI]: 0.6,
    },
    edges: {
      ...CH45_EDGES,
      ...spread(TOOL_EDGES, 0.18),
      [E_TOOL_WEATHER]: 0,
      [E_POI_WEATHER]: 0,
      [E_TOOL_WEATHER_G]: 0.9,
      [E_POI_WEATHER_G]: 0.6,
      [E_GATEWAY_PLANNER]: 0.25,
      ...spread(SPECIALIST_EDGES, 0.2),
      ...spread(SPECIALIST_LLM_EDGES, 0.08),
    },
    focus: [WEATHER_GROUP, POI, PLANNER],
    maxZoom: 1.0,
  },
  {
    chapter: 4,
    title: "Nothing here was wired by hand.",
    // 60 characters against a 44-character single-line budget at 1440, so it
    // wraps wherever it is allowed to. Broken at the second separator instead:
    // two balanced lines, and no "·" left dangling at the end of line one on
    // the frame most likely to be screenshotted.
    sub: "`twelve agents · three languages`\n`· every edge resolved itself`",
    // No desc — the resolution shot is title + sub, which is what buys the
    // graph the full panel width back. The CTA has moved to the reveal.
    accent: ACCENT,
    weight: 1.2,
    fullBleed: true,
    world: { ...FULL, weatherRuntime: "typescript", hotelRuntime: "java", weatherReplicas: 3, badges: true },
    // Resolution shot: spotlight OFF. Everything bright.
    nodes: { ...spread(ALL_GROUPED, 1), [WEATHER]: 0 },
    edges: {
      ...spread(TOOL_EDGES_G, 0.85),
      ...spread(DEP_EDGES, 0.85),
      [E_POI_WEATHER]: 0,
      [E_TOOL_WEATHER]: 0,
      [E_POI_WEATHER_G]: 0.85,
      [E_PLANNER_PREFS]: 0.85,
      [E_PLANNER_CLAUDE]: 0.9,
      [E_PLANNER_OPENAI]: 0.5,
      [E_GATEWAY_PLANNER]: 1,
      ...spread(SPECIALIST_EDGES, 0.9),
      ...spread(SPECIALIST_LLM_EDGES, 0.18),
    },
    focus: ALL_GROUPED,
    maxZoom: 0.8,
  },
];

// ---------------------------------------------------------------------------
// The reveal — epilogue, after the topology completes
// ---------------------------------------------------------------------------
// The graph clears and the subject changes from a topology to the things a
// topology cannot draw. That switch is what lets the page cover security,
// deployment and observability honestly: they are never drawn, so nothing has
// to be faked into the picture to talk about them.
//
// Not a sixth chapter — the rail reads complete and then leaves.

/**
 * Pinned travel for the epilogue, in viewport heights.
 *
 * 6.9. The ENTRANCE is sequenced like the exit — B14's copy is gone before the
 * headline arrives, with an empty beat between, rather than crossfading into it
 * in the same place. Both empty beats were then halved: they held for 3-4
 * scroll notches, which reads as a stall rather than a breath.
 *
 * Was 6.6, up from the 2.6 of the first pass. The six phases total 1334 characters
 * — the length of six beat descriptions — and the first pass gave them a fifth
 * of the dwell the beats get. The grid is now readable across ~4.4vh (≈304
 * characters per vh, in line with the topology's ~290), then holds, then
 * empties the panel completely before the CTA arrives into it.
 *
 * The last 0.6vh of the increase buys that empty frame: the CTA works because
 * nothing competes with it, so the grid and headline finish leaving before it
 * starts arriving.
 */
export const REVEAL_VH = 6.9;

/** Canonical order per docs/dev-to-production.md; Observe loops to Develop. */
export const REVEAL = {
  // An assertion, not an admission. The previous line ("And everything the
  // graph can't show") opened the epilogue by naming a limitation, at exactly
  // the point the piece should accelerate. The claim here is a paradigm one:
  // existing infrastructure was built for services that sit still, and agents
  // are not that. "Expects" carries the metaphor so the vocabulary doesn't
  // have to. The six phases below are the proof.
  title: "Infrastructure that expects agents.",
  // copy.md's single-line form: the header is full width, so the hard break
  // the 350px rail needed is gone. Three threes, then the payoff.
  sub: "`MCP · A2A · REST` — *three protocols, three languages, three vendors, one decorator*",
  phases: [
    {
      label: "LEARN",
      body: "The man pages are compiled into the binary, so they describe the version you actually have rather than whatever shipped last. Seventeen topics answer in Python, TypeScript or Java. A `--raw` mode turns your AI coding assistant into a mesh expert, and a ten-day tutorial ships inside the CLI.",
    },
    {
      label: "DEVELOP",
      body: "Python, TypeScript, and Java agents discover and call each other through a shared Rust core. One scaffold command emits the agent, its Dockerfile, and its Helm values. Claude, GPT, and Gemini are native; a hundred more arrive through LiteLLM, the Vercel AI SDK, or Spring AI.",
    },
    {
      label: "TEST",
      // The previous line ("the production code IS the test code") implied you
      // test against a production agent. The mechanism is the opposite:
      // local-registry substitution, with the consumer unchanged.
      body: "Nothing points at a URL, so nothing needs repointing to test. Run an ordinary agent as a stand-in on your laptop — no mock framework, no special annotation — and the local registry wires your consumer to it. What differs between laptop and production is who registered, never your code.",
    },
    {
      label: "DEPLOY",
      // "Nothing names where anything lives" is the claim at the right
      // altitude. An earlier draft explained the port override, which argued a
      // level below the actual point: traffic has to reach an IP before a port
      // matters, so if the address is not a requirement the port obviously
      // is not either. Explaining it conceded the frame.
      // Helm charts are not mentioned here — DEVELOP already claims the
      // scaffold emits them.
      body: "The same agent code runs on a laptop, in Docker Compose, and on Kubernetes with no changes. Nothing in it names where anything lives, so there is nothing to repoint when it moves. The health probes Kubernetes wants are already served, and scaling is one value in a file.",
    },
    {
      label: "SECURE",
      body: "Every inter-agent call is mutually authenticated. Identity is checked with X.509 before a registration is accepted, backed by files, HashiCorp Vault PKI, or SPIRE workload identity. Certificates rotate through the heartbeat without a restart — and on Linux, private keys live in tmpfs and never touch disk.",
    },
    {
      label: "OBSERVE",
      body: "Spans cross language boundaries into one trace tree: a Python call into Java into TypeScript reads as a single trace. Redis carries the stream, Tempo stores it, and three Grafana dashboards come prebuilt. `meshctl trace` renders the call tree in your terminal.",
    },
  ],
  // Gets the panel to itself — see the reveal timeline in scroll.tsx. Set on
  // one line, as copy.md has it, because a centred frame has the width for it.
  // `meshctl` is the CLI and ships via npm. `pip install mcp-mesh` is the
  // Python SDK — which the scaffold's generated requirements.txt pulls in —
  // so leading with it next to a `meshctl` command told the reader to run a
  // binary the install they just ran does not provide.
  cta: {
    title: "Build one yourself.",
    sub: "`npm install -g @mcpmesh/cli` · `meshctl scaffold`",
  },
};

// ---------------------------------------------------------------------------
// Page geometry — the ONE definition of how tall the whole thing is
// ---------------------------------------------------------------------------
// The docs page has to reserve this height before the bundle loads, and Stage
// has to render exactly it. Both now read these constants, so the reservation
// cannot drift from what renders. Stage applies them as inline styles rather
// than Tailwind classes on purpose: `h-[70vh]` is a literal Tailwind has to
// find by scanning source text, so it cannot be derived from a variable.

/** Optional internal hero, above B1. */
export const HEADER_VH = 70;
/** Resting space after the panel unpins. */
export const SPACER_VH = 25;

/**
 * The shipped bundle DOES render the threshold slide (copy.md, "THE THRESHOLD").
 *
 * It was cut once on the theory that it read as a second hero. That was wrong:
 * the problem was its copy, not its existence. Without it the page cuts from a
 * docs admonition straight into `01 ARRIVE`, which reads as a jump cut. The
 * slide is the way into the piece, and its copy has been replaced — the
 * old sub-line was the last surviving pre-reframe voice on the page.
 */
export const EMBED_SHOWS_HEADER = true;

/** Total document height of the section, in vh. */
export const pageHeightVh = (withHeader: boolean): number =>
  (withHeader ? HEADER_VH : 0) + 100 + (TOTAL_VH + REVEAL_VH) * 100 + SPACER_VH;

export const WEIGHTS = BEATS.map((b) => b.weight);
export const TOTAL_VH = WEIGHTS.reduce((a, b) => a + b, 0);
/** Cumulative start offset (in vh) of each beat, plus a final total. */
export const CUM = WEIGHTS.reduce<number[]>((acc, w) => [...acc, acc[acc.length - 1] + w], [0]);

export { ALL_SINGLE, ALL_GROUPED };
