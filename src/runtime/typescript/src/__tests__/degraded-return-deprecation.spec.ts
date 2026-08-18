/**
 * `degraded` as a health-check RETURN VALUE is deprecated (issue #1515).
 *
 * The question a health check answers is binary: stay in dependency
 * resolution, or withdraw. `degraded` and `healthy` are the same answer to it —
 * both keep the heartbeat alive and both keep consumers routing here — so the
 * third word buys a 503 on an endpoint nothing probes and costs the failure
 * rate of a name that reads like withdrawal to everyone who picks it when
 * their upstream is down.
 *
 * Two things are pinned here, and the second matters more than the first:
 *
 * 1. selecting `degraded` warns, naming the CONSEQUENCE rather than the value;
 * 2. **behaviour is unchanged.** A check returning `degraded` still produces a
 *    `degraded` verdict, which still heartbeats and still resolves. Remapping
 *    it to `unhealthy` would fix the common intent and silently withdraw every
 *    agent whose author used the word correctly.
 *
 * The runtime's OWN degraded verdicts — a check that threw, one that missed
 * its deadline, an unusable return type, an unreadable status string — must
 * NOT warn: nothing the author can act on happened.
 *
 * Lives in its own file rather than alongside the #1476 verdict table because
 * the warning is deduplicated at module scope, and that file returns
 * `degraded` in several unrelated cases that would consume the one warning.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  normalizeHealthResult,
  runHealthCheck,
  __resetDegradedReturnWarning,
} from "../health-check.js";

// The consequence, not the value. An author who reads "degraded is deprecated"
// learns nothing; one who reads "consumers will keep routing to it" learns
// whether they meant it.
const WARNING_FRAGMENTS = [
  "stays in dependency resolution",
  "consumers will keep routing to it",
  "Return false to withdraw",
];

describe("degraded return-value deprecation (#1515)", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    __resetDegradedReturnWarning();
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    warnSpy.mockRestore();
    __resetDegradedReturnWarning();
  });

  const deprecationCalls = (): string[] =>
    warnSpy.mock.calls
      .map((c) => String(c[0]))
      .filter((m) => m.includes("keep routing to it"));

  describe("a verdict the author selected", () => {
    it("warns, naming the consequence", () => {
      const verdict = normalizeHealthResult({
        status: "degraded",
        errors: ["upstream slow"],
      });

      expect(verdict.status).toBe("degraded");
      const warnings = deprecationCalls();
      expect(warnings).toHaveLength(1);
      for (const fragment of WARNING_FRAGMENTS) {
        expect(warnings[0]).toContain(fragment);
      }
    });

    // `toStatus` trims and lowercases, so the deprecation must follow it: a
    // guard on the exact literal would let " DEGRADED " through silently while
    // routing it identically.
    it.each(["  degraded  ", "DEGRADED", "  DeGrAdEd "])(
      "warns for %j too",
      (status) => {
        expect(normalizeHealthResult({ status }).status).toBe("degraded");
        expect(deprecationCalls()).toHaveLength(1);
      },
    );

    it("warns once per process, not once per refresh", async () => {
      // At the 15s default TTL a per-tick warning is ~5,760 identical lines a
      // day from an agent doing exactly what its author intended, which trains
      // an operator to filter the line rather than read it.
      for (let i = 0; i < 5; i++) {
        expect(normalizeHealthResult({ status: "degraded" }).status).toBe(
          "degraded",
        );
      }
      await runHealthCheck(() => ({ status: "degraded" }), "provider");

      expect(deprecationCalls()).toHaveLength(1);
    });
  });

  describe("behaviour is unchanged", () => {
    it("still reports degraded, so the agent stays in resolution", () => {
      const verdict = normalizeHealthResult({
        status: "degraded",
        checks: { cache_warm: false },
        errors: ["cache cold"],
      });

      expect(verdict.status).toBe("degraded");
      expect(verdict.status).not.toBe("unhealthy");
      expect(verdict.checks).toEqual({ cache_warm: false });
      expect(verdict.errors).toEqual(["cache cold"]);
    });

    it("only unhealthy withdraws, and it still does", () => {
      expect(normalizeHealthResult({ status: "unhealthy" }).status).toBe(
        "unhealthy",
      );
      expect(normalizeHealthResult(false).status).toBe("unhealthy");
      expect(deprecationCalls()).toHaveLength(0);
    });
  });

  describe("verdicts the runtime assigned stay silent", () => {
    it("a check that throws does not warn", async () => {
      const verdict = await runHealthCheck(() => {
        throw new Error("probe blew up");
      }, "provider");

      expect(verdict.status).toBe("degraded");
      expect(deprecationCalls()).toHaveLength(0);
    });

    it.each([
      ["an unusable return type", 42],
      ["null", null],
      ["an unreadable status string", { status: "down" }],
    ])("%s does not warn", async (_label, raw) => {
      expect(normalizeHealthResult(raw).status).toBe("degraded");
      expect(deprecationCalls()).toHaveLength(0);
    });

    it("healthy does not warn", () => {
      expect(normalizeHealthResult({ status: "healthy" }).status).toBe(
        "healthy",
      );
      expect(normalizeHealthResult(true).status).toBe("healthy");
      expect(deprecationCalls()).toHaveLength(0);
    });
  });
});
