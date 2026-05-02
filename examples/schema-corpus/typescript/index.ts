/**
 * Schema-corpus producer (TypeScript) — 12-pattern matrix for issue #547 Phase 7.
 *
 * One agent declaring twelve tools, each producing a different schema pattern from
 * the cross-runtime canonical-form spike. Paired with Python and Java corpus
 * producers to prove end-to-end that all twelve patterns canonicalize to the same
 * hash across runtimes.
 *
 * Pattern source: ~/workspace/schema-spike-547/typescript/extract.ts.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

// ===== Pattern 1: Primitives =====
const Primitives = z.object({
  id: z.string(),
  age: z.number().int(),
  active: z.boolean(),
  score: z.number(),
});

// ===== Pattern 2: Optional =====
// Pair nullable+optional so the schema shape matches Pydantic's Optional[str] = None.
const WithOptional = z.object({
  name: z.string(),
  nickname: z.string().nullable().optional(),
});

// ===== Pattern 3: WithDate =====
// Pydantic emits format=date for Python's `date`; Zod 3.20+ has z.string().date()
// which produces {type: "string", format: "date"} natively, matching the canonical shape.
const WithDate = z.object({
  hireDate: z.string().date(),
});

// ===== Pattern 4: WithEnum =====
const WithEnum = z.object({
  role: z.enum(["admin", "user", "guest"]),
});

// ===== Pattern 5: Nested =====
const Employee = z.object({
  name: z.string(),
  dept: z.string(),
});

const Nested = z.object({
  employee: Employee,
});

// ===== Pattern 6: WithArray =====
const WithArray = z.object({
  tags: z.array(z.string()),
});

// ===== Pattern 7: CaseConversion (camelCase input — already canonical) =====
const CaseConversion = z.object({
  marketCap: z.number(),
  hireDate: z.string().date(),
  isActive: z.boolean(),
});

// ===== Pattern 8: DiscriminatedUnion =====
const Dog = z.object({ kind: z.literal("dog"), breed: z.string() });
const Cat = z.object({ kind: z.literal("cat"), indoor: z.boolean() });
const WithAnimal = z.object({
  pet: z.discriminatedUnion("kind", [Dog, Cat]),
});

// ===== Pattern 9: Recursive =====
type TreeNodeT = { value: string; children: TreeNodeT[] };
const TreeNode: z.ZodType<TreeNodeT> = z.lazy(() =>
  z.object({
    value: z.string(),
    children: z.array(TreeNode),
  }),
);

// ===== Pattern 10: Inheritance =====
const EmployeeBase = z.object({ name: z.string(), dept: z.string() });
const Manager = EmployeeBase.extend({ reports: z.number().int() });
const WithManager = z.object({ person: Manager });

// ===== Pattern 11: NumberConstraints =====
const WithScore = z.object({
  value: z.number().int().min(0).max(100),
});

// ===== Pattern 12: UntaggedUnion =====
const WithEither = z.object({
  value: z.union([z.string(), z.number().int()]),
});

// ===== Agent + tools =====

const server = new FastMCP({ name: "Schema Corpus (TS)", version: "1.0.0" });

const agent = mesh(server, {
  name: "corpus-ts",
  httpPort: 9210,
  description: "Schema-corpus producer (TypeScript) — 12 patterns for issue #547 Phase 7",
});

agent.addTool({
  name: "get_primitives",
  capability: "corpus_primitives",
  description: "Pattern 1: Primitives (str, int, bool, float)",
  parameters: z.object({}),
  outputSchema: Primitives,
  execute: async () =>
    JSON.stringify({ id: "A1", age: 42, active: true, score: 3.14 }),
});

agent.addTool({
  name: "get_optional",
  capability: "corpus_optional",
  description: "Pattern 2: Optional[str] field",
  parameters: z.object({}),
  outputSchema: WithOptional,
  execute: async () => JSON.stringify({ name: "Alice", nickname: null }),
});

agent.addTool({
  name: "get_with_date",
  capability: "corpus_with_date",
  description: "Pattern 3: date field (Pydantic emits format=date)",
  parameters: z.object({}),
  outputSchema: WithDate,
  execute: async () => JSON.stringify({ hireDate: "2024-01-15" }),
});

agent.addTool({
  name: "get_with_enum",
  capability: "corpus_with_enum",
  description: "Pattern 4: enum with values [admin, user, guest]",
  parameters: z.object({}),
  outputSchema: WithEnum,
  execute: async () => JSON.stringify({ role: "admin" }),
});

agent.addTool({
  name: "get_nested",
  capability: "corpus_nested",
  description: "Pattern 5: Nested model (Employee inside Nested)",
  parameters: z.object({}),
  outputSchema: Nested,
  execute: async () =>
    JSON.stringify({ employee: { name: "Alice", dept: "Engineering" } }),
});

agent.addTool({
  name: "get_with_array",
  capability: "corpus_with_array",
  description: "Pattern 6: list[str]",
  parameters: z.object({}),
  outputSchema: WithArray,
  execute: async () => JSON.stringify({ tags: ["alpha", "beta"] }),
});

agent.addTool({
  name: "get_case_conversion",
  capability: "corpus_case_conversion",
  description: "Pattern 7: camelCase input (already canonical for TS)",
  parameters: z.object({}),
  outputSchema: CaseConversion,
  execute: async () =>
    JSON.stringify({ marketCap: 1.0e9, hireDate: "2024-01-15", isActive: true }),
});

agent.addTool({
  name: "get_discriminated_union",
  capability: "corpus_discriminated_union",
  description: "Pattern 8: DiscriminatedUnion (Dog|Cat by 'kind')",
  parameters: z.object({}),
  outputSchema: WithAnimal,
  execute: async () => JSON.stringify({ pet: { kind: "dog", breed: "Lab" } }),
});

agent.addTool({
  name: "get_recursive",
  capability: "corpus_recursive",
  description: "Pattern 9: Recursive TreeNode (self-reference)",
  parameters: z.object({}),
  outputSchema: TreeNode as unknown as z.ZodTypeAny,
  execute: async () =>
    JSON.stringify({
      value: "root",
      children: [{ value: "child", children: [] }],
    }),
});

agent.addTool({
  name: "get_inheritance",
  capability: "corpus_inheritance",
  description: "Pattern 10: Inheritance (Manager extends EmployeeBase, flattened)",
  parameters: z.object({}),
  outputSchema: WithManager,
  execute: async () =>
    JSON.stringify({
      person: { name: "Alice", dept: "Engineering", reports: 5 },
    }),
});

agent.addTool({
  name: "get_number_constraints",
  capability: "corpus_number_constraints",
  description: "Pattern 11: NumberConstraints (.int().min(0).max(100))",
  parameters: z.object({}),
  outputSchema: WithScore,
  execute: async () => JSON.stringify({ value: 50 }),
});

agent.addTool({
  name: "get_untagged_union",
  capability: "corpus_untagged_union",
  description: "Pattern 12: UntaggedUnion (str|int, no discriminator)",
  parameters: z.object({}),
  outputSchema: WithEither,
  execute: async () => JSON.stringify({ value: "forty-two" }),
});
