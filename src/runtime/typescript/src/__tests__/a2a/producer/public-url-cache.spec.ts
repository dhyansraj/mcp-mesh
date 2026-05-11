/**
 * Unit tests for `public-url-cache.ts` (spec §2.4 + §8.2).
 *
 * Coverage:
 * - put/get round-trip
 * - put with empty / null / undefined clears the entry (Java fix from #934)
 * - Different (path, skillId) keys don't collide
 * - clear() drops all entries
 * - Singleton reset works between tests
 * - buildLocalFallbackUrl host/port/path composition
 * - IPv6 host handling (parity flag with Java #934 A6 fix)
 *
 * Mirrors Java's `MeshA2APublicUrlCacheTest`.
 */
import { describe, it, expect, beforeEach } from "vitest";

import {
  A2APublicUrlCache,
  buildLocalFallbackUrl,
} from "../../../a2a/producer/public-url-cache.js";

describe("A2APublicUrlCache (spec §8.2)", () => {
  beforeEach(() => {
    A2APublicUrlCache.reset();
  });

  /** Singleton: `getInstance()` always returns the same object until reset. */
  it("returns the same singleton across calls; reset rebuilds it", () => {
    const a = A2APublicUrlCache.getInstance();
    const b = A2APublicUrlCache.getInstance();
    expect(a).toBe(b);

    A2APublicUrlCache.reset();
    const c = A2APublicUrlCache.getInstance();
    expect(c).not.toBe(a);
  });

  /** Basic put + get round-trip. */
  it("put + get round-trip", () => {
    const c = A2APublicUrlCache.getInstance();
    c.put("/agents/date", "get-date", "https://prod.example.com/agents/date");
    expect(c.get("/agents/date", "get-date")).toBe(
      "https://prod.example.com/agents/date",
    );
  });

  /** Java #934 fix: empty URL clears the cached entry. */
  it("put with empty string clears the cached entry", () => {
    const c = A2APublicUrlCache.getInstance();
    c.put("/agents/x", "x", "https://a.example.com/x");
    expect(c.get("/agents/x", "x")).toBe("https://a.example.com/x");

    c.put("/agents/x", "x", "");
    expect(c.get("/agents/x", "x")).toBeUndefined();
  });

  /** Java #934 fix: null URL clears the cached entry. */
  it("put with null clears the cached entry", () => {
    const c = A2APublicUrlCache.getInstance();
    c.put("/agents/y", "y", "https://a.example.com/y");

    c.put("/agents/y", "y", null);
    expect(c.get("/agents/y", "y")).toBeUndefined();
  });

  /** Java #934 fix: undefined URL clears the cached entry. */
  it("put with undefined clears the cached entry", () => {
    const c = A2APublicUrlCache.getInstance();
    c.put("/agents/z", "z", "https://a.example.com/z");

    c.put("/agents/z", "z", undefined);
    expect(c.get("/agents/z", "z")).toBeUndefined();
  });

  /** Distinct (path, skillId) keys are independent. */
  it("different (path, skillId) keys do not collide", () => {
    const c = A2APublicUrlCache.getInstance();
    c.put("/p1", "s1", "https://example.com/p1");
    c.put("/p1", "s2", "https://example.com/p1-alt");
    c.put("/p2", "s1", "https://example.com/p2");

    expect(c.get("/p1", "s1")).toBe("https://example.com/p1");
    expect(c.get("/p1", "s2")).toBe("https://example.com/p1-alt");
    expect(c.get("/p2", "s1")).toBe("https://example.com/p2");
    expect(c.size()).toBe(3);
  });

  /** clear() drops every entry. */
  it("clear() removes all entries", () => {
    const c = A2APublicUrlCache.getInstance();
    c.put("/a", "a", "https://x");
    c.put("/b", "b", "https://y");
    expect(c.size()).toBe(2);

    c.clear();
    expect(c.size()).toBe(0);
    expect(c.get("/a", "a")).toBeUndefined();
  });
});

describe("buildLocalFallbackUrl (spec §2.4)", () => {
  /** Standard case: host + port + path. */
  it("composes host:port path", () => {
    expect(buildLocalFallbackUrl("localhost", 8080, "/agents/x")).toBe(
      "http://localhost:8080/agents/x",
    );
  });

  /** Missing host defaults to localhost; missing/zero port is omitted. */
  it("defaults missing host to localhost and drops zero/missing port", () => {
    expect(buildLocalFallbackUrl(undefined, 0, "/x")).toBe("http://localhost/x");
    expect(buildLocalFallbackUrl("", 0, "/x")).toBe("http://localhost/x");
    expect(buildLocalFallbackUrl(undefined, undefined, "/x")).toBe(
      "http://localhost/x",
    );
  });

  /** Custom host without port. */
  it("supports custom host without a port", () => {
    expect(buildLocalFallbackUrl("svc.example.com", undefined, "/agents/y")).toBe(
      "http://svc.example.com/agents/y",
    );
  });

  /**
   * Java #934 A6 fix parity: IPv6 hosts MUST be bracketed per RFC 3986
   * §3.2.2 so the `:port` separator isn't ambiguous with the IPv6
   * literal's own colons.
   */
  it("brackets IPv6 host literals (RFC 3986 §3.2.2 / Java #934 A6 parity)", () => {
    expect(buildLocalFallbackUrl("::1", 8080, "/x")).toBe("http://[::1]:8080/x");
    expect(buildLocalFallbackUrl("fe80::1234:5678:9abc:def0", 443, "/y")).toBe(
      "http://[fe80::1234:5678:9abc:def0]:443/y",
    );
    // No port: brackets still applied so the host is a valid `host`
    // production per RFC 3986.
    expect(buildLocalFallbackUrl("::1", undefined, "/z")).toBe("http://[::1]/z");
  });

  /**
   * A host that arrives already bracketed (caller pre-formatted it) MUST
   * NOT be wrapped a second time — `[[::1]]` is not a valid URL.
   */
  it("does not double-bracket a host already in `[...]` form", () => {
    expect(buildLocalFallbackUrl("[::1]", 8080, "/x")).toBe("http://[::1]:8080/x");
    expect(buildLocalFallbackUrl("[::1]", undefined, "/y")).toBe("http://[::1]/y");
  });
});
