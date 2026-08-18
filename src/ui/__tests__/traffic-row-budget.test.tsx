// The Traffic page has to ASK FOR ENOUGH ROWS to show a route's functions.
//
// The defect this covers, measured against a live mesh carrying traffic on 42
// agent pairs: the page rendered 40 rows across 40 distinct routes, not one of
// them showing a second function, while the same endpoint at limit=100 returned
// 87 rows over 42 routes — 19 of them multi-function and one with 8. Nothing was
// wrong with the merge, the grouping or the rendering. The page asked for 20.
//
// WHY 20 BECAME WRONG WITHOUT ANYONE CHANGING IT. The server hands out a short
// budget FAIRLY ACROSS PAIRS: every pair's busiest function, then every pair's
// second, and so on. That is right for the topology graph, which wants coverage.
// Against 40+ pairs a budget of 20 spends every slot on the first pass, so the
// response is exactly one row per route by construction — the page becomes
// structurally incapable of showing the per-function detail it exists for, and
// it looks correct while doing it, because one row per route is precisely what
// the page used to be.
//
// WHY THE EXISTING SUITE MISSED IT. The Go tests assert fairness ACROSS pairs
// and the UI tests assert the merge and the grouping WITHIN a route, each with a
// fixture smaller than the budget. Nobody asserted the one property that spans
// the two: the number the page requests has to clear the number of routes it
// expects back, or fairness flattens the result before any of that code runs.
import { describe, it, expect, vi, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { EdgeStat, TrafficResponse } from "../lib/types";
import { TRAFFIC_ROW_LIMIT } from "../lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

// Shaped like the measured mesh: 42 routes, 19 of them carrying more than one
// function, the busiest carrying 8.
const ROUTE_COUNT = 42;
const MULTI_FUNCTION_ROUTES = 19;
const BUSIEST_ROUTE_FUNCTIONS = 8;

function functionsOnRoute(route: number): number {
  if (route === 0) return BUSIEST_ROUTE_FUNCTIONS;
  return route < MULTI_FUNCTION_ROUTES ? 2 : 1;
}

function liveShapedResponse(): TrafficResponse {
  const edge_stats: EdgeStat[] = [];
  for (let route = 0; route < ROUTE_COUNT; route++) {
    const id = String(route).padStart(2, "0");
    for (let fn = 0; fn < functionsOnRoute(route); fn++) {
      edge_stats.push({
        source: `caller-${id}`,
        target: `provider-${id}`,
        target_function: `tool_${id}_${fn}`,
        call_count: 100 - fn,
        error_count: 0,
        error_rate: 0,
        avg_latency_ms: 5,
        p99_latency_ms: 9,
        max_latency_ms: 12,
        min_latency_ms: 1,
      });
    }
  }
  return {
    enabled: true,
    window: "all",
    total_calls: edge_stats.reduce((n, e) => n + e.call_count, 0),
    total_errors: 0,
    edge_stats,
    agent_stats: [],
    model_stats: [],
  };
}

/** The `limit` the page put on the wire, as a number. */
function requestedLimit(fetchMock: ReturnType<typeof vi.fn>): number {
  expect(fetchMock).toHaveBeenCalled();
  const url = String(fetchMock.mock.calls[0][0]);
  const value = new URL(url, "http://localhost").searchParams.get("limit");
  expect(value).not.toBeNull();
  return Number(value);
}

async function renderTrafficPage(response: TrafficResponse) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => response });
  vi.stubGlobal("fetch", fetchMock);
  const { default: TrafficPage } = await import("../app/traffic/page");
  render(<TrafficPage />);
  return fetchMock;
}

describe("the row budget the Traffic page requests", () => {
  it("clears the number of routes, so a route can be served a second function", async () => {
    const response = liveShapedResponse();
    const fetchMock = await renderTrafficPage(response);
    await waitFor(() => expect(screen.getByText("tool_00_0")).toBeInTheDocument());

    const routes = new Set(response.edge_stats.map((e) => `${e.source}->${e.target}`));
    expect(routes.size).toBe(ROUTE_COUNT);

    // THE PROPERTY. Fair-across-pairs truncation spends its first `routes` slots
    // on one row each, so anything at or below the route count comes back one
    // row per route however many functions those routes have. A budget of 20
    // against these 42 routes passes every other assertion in this suite and
    // still puts a single function on screen per route.
    expect(requestedLimit(fetchMock)).toBeGreaterThan(routes.size);
  });

  it("does not exceed the ceiling the endpoint clamps to, which would silently reduce it", () => {
    // Asking for 500 and being served 100 is indistinguishable at the call site
    // from asking for 100 — the request states an intent the response does not
    // honour, and the next reader sizes the page against a number that never
    // reached it. Parsed from the Go source rather than restated, so lowering
    // the ceiling fails here instead of on a live mesh.
    // __dirname, not import.meta.url: under the jsdom environment the module
    // URL has an http scheme and readFileSync rejects it.
    const handler = readFileSync(
      path.resolve(__dirname, "..", "..", "core", "ui", "traffic_handler.go"),
      "utf8"
    );
    const declared = handler.match(/trafficMaxLimit\s*=\s*(\d+)/);
    expect(declared, "trafficMaxLimit is no longer a named constant in traffic_handler.go").not.toBeNull();

    const ceiling = Number(declared![1]);
    expect(TRAFFIC_ROW_LIMIT).toBeLessThanOrEqual(ceiling);
    expect(TRAFFIC_ROW_LIMIT).toBe(ceiling);
  });

  it("is the number that actually goes on the wire", async () => {
    const fetchMock = await renderTrafficPage(liveShapedResponse());
    await waitFor(() => expect(screen.getByText("tool_00_0")).toBeInTheDocument());
    expect(requestedLimit(fetchMock)).toBe(TRAFFIC_ROW_LIMIT);
  });
});

describe("every row the server sends reaches the table", () => {
  // The budget only matters if the page draws what it is given. A client-side
  // cap on top of it would reintroduce the same symptom one layer up, and a cap
  // sized like the old server budget would reintroduce it exactly.

  it("renders all 8 functions of the busiest route, together", async () => {
    await renderTrafficPage(liveShapedResponse());
    await waitFor(() => expect(screen.getByText("tool_00_0")).toBeInTheDocument());

    for (let fn = 0; fn < BUSIEST_ROUTE_FUNCTIONS; fn++) {
      expect(screen.getByText(`tool_00_${fn}`)).toBeInTheDocument();
    }
    // One row per function of that one route, so its route name repeats.
    expect(screen.getAllByText("caller-00")).toHaveLength(BUSIEST_ROUTE_FUNCTIONS);
  });

  it("draws a row for every stat, not a screenful of them", async () => {
    const response = liveShapedResponse();
    await renderTrafficPage(response);
    await waitFor(() => expect(screen.getByText("tool_00_0")).toBeInTheDocument());

    const table = screen.getByText("Route").closest("table");
    expect(table).not.toBeNull();
    // Header row plus one row per stat. More rows than routes is the point: the
    // table is scrollable, and depth below the fold is still depth.
    const rows = within(table!).getAllByRole("row");
    expect(rows).toHaveLength(response.edge_stats.length + 1);
    expect(response.edge_stats.length).toBeGreaterThan(ROUTE_COUNT);
  });
});
