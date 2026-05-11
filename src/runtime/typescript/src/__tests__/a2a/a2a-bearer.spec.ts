/**
 * Tests for A2ABearer (issue #917).
 *
 * Mirrors Java's A2ABearerTest + Python's TestA2ABearer:
 *   - rejects null/empty/whitespace tokens;
 *   - mutual exclusion of token vs tokenEnv;
 *   - rotation: env-var changes between calls take effect.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { A2ABearer } from "../../a2a/a2a-bearer.js";
import { A2AAuthError } from "../../a2a/errors.js";

describe("A2ABearer", () => {
  const ENV_VAR = "A2A_BEARER_TEST_TOKEN";
  const originalEnv = process.env[ENV_VAR];

  beforeEach(() => {
    delete process.env[ENV_VAR];
  });
  afterEach(() => {
    if (originalEnv === undefined) delete process.env[ENV_VAR];
    else process.env[ENV_VAR] = originalEnv;
  });

  it("constructs from a literal token", () => {
    const b = new A2ABearer({ token: "abc123" });
    expect(b.authorizationHeader()).toBe("Bearer abc123");
  });

  it("constructs from an env var and resolves at call time", () => {
    const b = new A2ABearer({ tokenEnv: ENV_VAR });
    process.env[ENV_VAR] = "from-env";
    expect(b.authorizationHeader()).toBe("Bearer from-env");
    // Rotation between calls should be honoured.
    process.env[ENV_VAR] = "rotated";
    expect(b.authorizationHeader()).toBe("Bearer rotated");
  });

  it("throws when neither token nor tokenEnv is supplied", () => {
    expect(() => new A2ABearer({})).toThrow(A2AAuthError);
  });

  it("throws when both token and tokenEnv are supplied", () => {
    expect(() => new A2ABearer({ token: "x", tokenEnv: "Y" })).toThrow(
      A2AAuthError,
    );
  });

  it("throws on blank literal token", () => {
    expect(() => new A2ABearer({ token: "   " })).toThrow(A2AAuthError);
  });

  it("throws on blank tokenEnv name", () => {
    expect(() => new A2ABearer({ tokenEnv: "   " })).toThrow(A2AAuthError);
  });

  it("throws at call time when env var resolves to empty", () => {
    const b = new A2ABearer({ tokenEnv: ENV_VAR });
    process.env[ENV_VAR] = "";
    expect(() => b.authorizationHeader()).toThrow(A2AAuthError);
  });

  it("throws at call time when env var is unset", () => {
    const b = new A2ABearer({ tokenEnv: ENV_VAR });
    expect(() => b.authorizationHeader()).toThrow(A2AAuthError);
  });
});
