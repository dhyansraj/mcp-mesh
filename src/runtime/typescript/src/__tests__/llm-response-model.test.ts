/**
 * Unit tests for mesh.llm() responseModel option (issue #1094).
 *
 * `responseModel` specifies the schema the LLM must emit and is validated
 * against (it feeds the provider's structured-output schema and the response
 * parser). When omitted it falls back to `returns`. `returns` continues to
 * type what `execute` returns to callers.
 */

import { describe, it, expect, expectTypeOf } from "vitest";
import { z } from "zod";
import { llm } from "../llm.js";

const BigSchema = z.object({
  id: z.string(),
  title: z.string(),
  body: z.string(),
  metadata: z.record(z.string(), z.unknown()),
});

const SmallSchema = z.object({
  id: z.string(),
});

const baseConfig = {
  provider: { capability: "llm-service" },
  parameters: z.object({ query: z.string() }),
};

describe("mesh.llm responseModel", () => {
  it("uses responseModel as returnSchema when both responseModel and returns are provided", () => {
    const tool = llm({
      ...baseConfig,
      name: "tool-with-response-model",
      responseModel: SmallSchema,
      returns: BigSchema,
      execute: async () => ({
        id: "1",
        title: "t",
        body: "b",
        metadata: {},
      }),
    });

    // returnSchema drives provider output schema + ResponseParser; must be the
    // responseModel, not the (broader) returns type.
    expect(tool._meshLlmConfig.returnSchema).toBe(SmallSchema);
    expect(tool._meshLlmConfig.returnSchema).not.toBe(BigSchema);
  });

  it("falls back to returns when responseModel is omitted (back-compat)", () => {
    const tool = llm({
      ...baseConfig,
      name: "tool-with-returns-only",
      returns: BigSchema,
      execute: async () => ({
        id: "1",
        title: "t",
        body: "b",
        metadata: {},
      }),
    });

    expect(tool._meshLlmConfig.returnSchema).toBe(BigSchema);
  });

  it("leaves returnSchema undefined when neither is provided (string mode)", () => {
    const tool = llm({
      ...baseConfig,
      name: "tool-with-neither",
      execute: async () => "hello",
    });

    expect(tool._meshLlmConfig.returnSchema).toBeUndefined();
  });

  it("types the injected llm callable by responseModel when provided", () => {
    llm({
      ...baseConfig,
      name: "tool-type-response-model",
      responseModel: SmallSchema,
      returns: BigSchema,
      execute: async (_args, { llm: llmCallable }) => {
        // The injected callable is typed by responseModel (SmallSchema), not returns.
        expectTypeOf(llmCallable).returns.resolves.toEqualTypeOf<
          z.infer<typeof SmallSchema>
        >();
        // execute's own return type still follows `returns` (BigSchema).
        return { id: "1", title: "t", body: "b", metadata: {} };
      },
    });
  });

  it("types the injected llm callable by returns when no responseModel", () => {
    llm({
      ...baseConfig,
      name: "tool-type-returns",
      returns: BigSchema,
      execute: async (_args, { llm: llmCallable }) => {
        expectTypeOf(llmCallable).returns.resolves.toEqualTypeOf<
          z.infer<typeof BigSchema>
        >();
        return { id: "1", title: "t", body: "b", metadata: {} };
      },
    });
  });
});
