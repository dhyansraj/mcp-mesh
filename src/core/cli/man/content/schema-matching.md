# Schema Matching

> Opt-in shape compatibility for dependency resolution (issue #547)

## Overview

Schema matching is the **fourth disambiguator** the registry applies when picking a producer for one of your dependencies. It runs after capability, tag, and version filters:

```
capability → tags → version → schema → tiebreaker
```

By default it does nothing — declared dependencies resolve exactly as before. You opt in per-dependency by saying "I expect a response that looks like _this_ type." The registry then drops any candidate whose published `outputSchema` doesn't satisfy that shape.

The mesh ships a single canonical schema normalizer (Rust, embedded in every SDK). Python Pydantic models, TypeScript Zod schemas, and Java POJOs are all reduced to the same canonical JSON Schema form, content-addressed by sha256. This is what makes cross-language matching meaningful — `Employee` declared in Java and `Employee` declared in Python collapse to the same hash if they describe the same shape.

## Why this exists

Without schema matching, two agents can register the same `capability` with completely different output shapes. A consumer asking for `lookup_employee` may get wired to either — the resolver has no signal beyond the capability name and tags. In a polyglot mesh with multiple teams, this is a real "rogue producer" hazard.

```python
# Producer A returns {"id": int, "name": str}
@mesh.tool(capability="lookup_employee")
def lookup_employee(id: int) -> Employee: ...

# Producer B returns {"emp_id": str, "full_name": str, "department": str}
@mesh.tool(capability="lookup_employee")
def lookup_employee(id: str) -> EmployeeRecord: ...
```

Today both register cleanly. The consumer that calls `result.id` blows up if it gets wired to B. Schema matching fixes this by letting the consumer say "I want a producer whose response has `id: int` and `name: str`" — the resolver evicts B at the schema stage with a typed audit reason.

## Two modes

| Mode     | Behavior                                                                      | When to use            |
| -------- | ----------------------------------------------------------------------------- | ---------------------- |
| `subset` | Consumer's required fields must all exist in producer's output (extras OK)    | Default opt-in         |
| `strict` | Byte-equal canonical hashes (no extra fields, identical types/nullability)    | Cross-language pinning |

`subset` is the right default for most cases — you only care that the fields you're going to access exist. `strict` is useful when you want to pin the contract end-to-end, e.g. when the producer and consumer ship together as a versioned pair.

## Per-language declaration

### Python

Producer side — output schema is inferred from the function's return type annotation. Use a Pydantic model for richest schema fidelity:

```python
from pydantic import BaseModel

class Employee(BaseModel):
    id: int
    name: str
    department: str

@mesh.tool(capability="lookup_employee")
def lookup_employee(id: int) -> Employee:
    return Employee(id=id, name="Ada", department="Engineering")
```

Consumer side — request schema-aware resolution by adding `expected_type` (and optionally `match_mode`) to the dependency dict:

```python
@mesh.tool(
    capability="hr_report",
    dependencies=[
        {
            "capability": "lookup_employee",
            "expected_type": Employee,    # Pydantic, dataclass, TypedDict, primitive...
            "match_mode": "subset",       # default when expected_type is set
        }
    ],
)
async def hr_report(employee_lookup: mesh.McpMeshTool = None): ...
```

`expected_type` accepts any Python type the SDK can convert to JSON Schema (Pydantic models, dataclasses, TypedDicts, primitives) or a pre-built JSON Schema dict.

### TypeScript

Producer side — pass a Zod schema as `outputSchema` on `addTool({})`:

```typescript
import { z } from "zod";

const EmployeeSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  department: z.string(),
});

agent.addTool({
  name: "lookup_employee",
  capability: "lookup_employee",
  parameters: z.object({ id: z.number().int() }),
  outputSchema: EmployeeSchema,
  execute: async ({ id }) => ({ id, name: "Ada", department: "Engineering" }),
});
```

Consumer side — `expectedSchema` + `matchMode` on the dependency:

```typescript
agent.addTool({
  name: "hr_report",
  capability: "hr_report",
  dependencies: [
    {
      capability: "lookup_employee",
      expectedSchema: EmployeeSchema,
      matchMode: "subset",
    },
  ],
  parameters: z.object({}),
  execute: async ({}, { lookup_employee }) => { /* ... */ },
});
```

### Java

Producer side — point `@MeshTool(outputType = ...)` at the concrete class. Java needs an explicit class because generics erasure prevents the SDK from reading return types reliably:

```java
@MeshTool(
    capability = "lookup_employee",
    outputType = Employee.class
)
public Employee lookupEmployee(@Param("id") String id) {
    return new Employee(id, "Ada", "Engineering");
}

public record Employee(@NotNull String id,
                       @NotNull String name,
                       @NotNull String department) {}
```

Consumer side — two flavors depending on which annotation you use.

For tools that consume other capabilities (`@MeshTool(dependencies = @Selector(...))`):

```java
@MeshTool(
    capability = "hr_report",
    dependencies = @Selector(
        capability = "lookup_employee",
        expectedType = Employee.class,
        schemaMode = SchemaMode.SUBSET
    )
)
public Report hrReport(McpMeshTool<Employee> employeeLookup) { ... }
```

For Spring web routes (`@MeshRoute(dependencies = @MeshDependency(...))`):

```java
@MeshRoute(dependencies = {
    @MeshDependency(
        capability = "lookup_employee",
        expectedType = Employee.class,
        schemaMode = SchemaMode.SUBSET
    )
})
@PostMapping("/report")
public ResponseEntity<Report> report(McpMeshTool<Employee> employeeLookup) { ... }
```

## Cross-language convention

Strict mode requires that the canonical form be byte-identical across languages. The normalizer lines these up:

| Java                              | Python              | TypeScript               |
| --------------------------------- | ------------------- | ------------------------ |
| `@NotNull String x`               | `x: str`            | `z.string()`             |
| `String x` (default)              | `x: str \| None`    | `z.string().nullable()`  |
| `int x` (primitive)               | `x: int`            | `z.number().int()`       |
| `Integer x` (boxed)               | `x: int \| None`    | `z.number().int().nullable()` |
| `LocalDate x` (with `@NotNull`)   | `x: date`           | `z.string().date()`      |
| `Optional<String> x`              | `x: str \| None`    | `z.string().nullable()`  |

> Note: Java's reference types are nullable by default. To match a non-nullable Python or TypeScript field under `strict` mode, annotate the Java field with `@NotNull` (`jakarta.validation.constraints.NotNull`). The normalizer drops nullability from the canonical form when the constraint is present.

For date fields specifically, TypeScript needs `z.string().date()` (not plain `z.string()`) so the canonical form picks up the `format: "date"` metadata that Pydantic's `date` type and Java's `LocalDate` both produce.

## Verdict tiers and policy knobs

The schema normalizer emits a verdict for every published schema:

| Verdict | Meaning                                                  | Default action            |
| ------- | -------------------------------------------------------- | ------------------------- |
| `OK`    | Canonicalized cleanly                                    | Register normally         |
| `WARN`  | Canonicalized with documented lossiness (logged)         | Register, attach warnings |
| `BLOCK` | Couldn't canonicalize (e.g. unsupported recursion shape) | Refuse agent startup      |

Two knobs let you adjust the strictness:

- **Cluster-wide hardening** — set `MCP_MESH_SCHEMA_STRICT=true` in the agent's environment to promote every WARN to BLOCK across all tools. Use this in production to refuse to start any agent with a lossy schema.

- **Per-tool escape hatch** — set the producer-side `output_schema_strict=False` (Python) / `outputSchemaStrict: false` (TypeScript) / `outputSchemaStrict = false` (Java) to demote BLOCK to WARN for that one tool. The override **wins** even when `MCP_MESH_SCHEMA_STRICT=true` is set cluster-wide:

```python
# This tool will register even if its output schema only WARNs or BLOCKs
@mesh.tool(capability="experimental_thing", output_schema_strict=False)
def experimental(...) -> SomeWeirdRecursiveType: ...
```

```typescript
agent.addTool({
  name: "experimental",
  capability: "experimental_thing",
  outputSchema: SomeRecursiveSchema,
  outputSchemaStrict: false,
  // ...
});
```

```java
@MeshTool(capability = "experimental_thing", outputSchemaStrict = false)
public SomeWeirdType experimental(...) { ... }
```

## Known limitations

- **Java `Object` field** — can't represent untagged unions in the canonical form. This is a Java type-system limit; the normalizer emits a WARN.

- **Recursive types** — TypeScript uses zod-to-json-schema's `$refStrategy: "root"`, while Java uses post-processed `$defs/<TypeName>`. Both work in isolation. If you mix recursion patterns across the same logical type in different languages, the canonical form may differ even when the conceptual shape is identical.

- **Pydantic cross-references in the same module** — models that reference each other in one file need `model_rebuild()` to resolve forward references before schema extraction. The SDK calls this automatically as of the #547 landing — you don't need to add it yourself.

- **Strict mode is unforgiving about extras** — adding any field on the producer side (even an optional one) breaks `strict` matching. Use `subset` if you want producer evolution.

## Inspecting matches and mismatches

Schema decisions show up in the audit trail:

```bash
# See which producers were evicted with SchemaIncompatible
meshctl audit hello-world --explain | grep -A3 SchemaIncompatible

# Compare two canonical schemas by hash (e.g., consumer vs producer)
meshctl schema diff sha256:abc... sha256:def...

# List all canonical schemas the registry knows about
meshctl list --schemas
```

Eviction details include `consumer_hash`, `producer_hash`, `mode` (`subset` or `strict`), and per-field `reasons` like `missing_field` or `type_mismatch`. See `meshctl man audit` for the full audit envelope.

## See Also

- `meshctl man tags` — Tag matching (the third disambiguator)
- `meshctl man audit` — Inspecting dependency-resolution decisions
- `meshctl man dependency-injection` — Full DI pipeline
- `meshctl man environment` — `MCP_MESH_SCHEMA_STRICT` env var
