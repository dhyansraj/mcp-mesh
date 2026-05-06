# MeshJob DDDI Resolver Contract

Each language SDK (Python, TypeScript, Java) implements parameter resolution
for tools decorated with `@mesh.tool`. With MeshJob added to the type system,
the resolver MUST handle two distinct injectable types:

- `MeshTool`: remote capability proxy → positional dependency injection
- `MeshJob`: job controller (producer-side) or proxy (consumer-side) → orthogonal injection (no positional cost)

This document defines the resolver behavior all three SDKs must match.

## Classification

For each parameter in the tool function signature:

| Annotation | Classification | Positional? |
|---|---|---|
| `MeshTool` | Mesh dependency | Yes — assigns next positional slot |
| `MeshJob` | Job injectable | No — recorded by signature position only |
| Other | User argument | N/A — passed by caller |

## Positional indexing rule

Iterate parameters in declaration order. Maintain a `mesh_tool_position_counter`
starting at 0. For each `MeshTool`-annotated param, assign current counter and
increment. For `MeshJob`-annotated params, do NOT touch the counter — instead
record the param's signature position in a separate `mesh_job_param_index` field.

## Reference example

Function signature:

```python
async def plan_trip(
    user_id: str,                          # signature pos 0 — user arg
    weather_lookup: MeshTool = None,       # signature pos 1 — MeshTool position 0
    job: MeshJob = None,                   # signature pos 2 — MeshJob param
    flight_search: MeshTool = None,        # signature pos 3 — MeshTool position 1
):
    ...
```

Resolver output:

- `mesh_tool_deps[0]` = weather_lookup metadata, signature position 1
- `mesh_tool_deps[1]` = flight_search metadata, signature position 3 (NOT 2 — MeshJob skipped)
- `mesh_job_param_index = Some(2)`
- User passes `user_id` at signature position 0

## Tool invocation

When the runtime invokes the tool:

- User-arg slots: filled from caller payload
- `mesh_tool_deps` slots: filled from resolved capability proxies
- `mesh_job_param_index` slot: filled from `JobController` (if invoked as a job — `X-Mesh-Job-Id` header present OR claim path) or `None` (if invoked as a regular tool call)

## Equivalence across SDKs

| SDK | Annotation lookup | Test seam |
|---|---|---|
| Python | `inspect.signature` + `typing.get_type_hints` | `tests/test_resolver_meshjob.py` |
| TypeScript | `reflect-metadata` decorator | `__tests__/resolver-meshjob.spec.ts` |
| Java | `java.lang.reflect.Parameter.getAnnotations()` | `MeshJobResolverTest.java` |

All three test files MUST cover the same scenarios:

1. Function with MeshTool only → unchanged from prior behavior
2. Function with MeshJob only → MeshTool count = 0, MeshJob index recorded
3. Function with both, MeshJob in middle → MeshTool positions correct (skip MeshJob)
4. Function with neither → no DDDI metadata
5. Function with MeshJob trailing → MeshJob index = last signature position

## Edge cases (REQUIRED)

These are explicit because past resolvers have stumbled here.

### Multiple `MeshJob` parameters

Disallowed in Phase 1. Resolver MUST reject (raise / throw / return error)
at registration time with a clear message: *"a tool function may declare at
most one MeshJob parameter"*. Future revisions may relax this for
multi-job orchestration scenarios; until then, fail fast at decorator
evaluation rather than silently picking one.

### `MeshJob` mixed with `MeshTool` at any position

Permitted. The resolver MUST NOT enforce a trailing-position rule for
`MeshJob`. Producer/consumer functions are ergonomic to write with the
job param wherever it reads naturally; the resolver decouples
declaration order from positional indexing per the rule above.

### Default values

`MeshJob` parameters typically default to `None` / `null` / `Optional.empty()`
so the function remains callable in tests without a job context. The
resolver MUST NOT require a default — any valid declaration shape is
acceptable. The runtime is responsible for providing the value (controller
or `None`).

### Optional / Union types

`Optional[MeshJob]`, `MeshJob | None`, etc., MUST classify as `MeshJob`. The
resolver unwraps the Optional/Union before annotation matching. Same
behavior already applies to `Optional[MeshTool]` per existing semantics.

## Tool invocation: when `MeshJob` is present but the call is NOT a job

Any tool with a `MeshJob` parameter can still be invoked as a regular
synchronous `tools/call` (no `X-Mesh-Job-Id` header, no claim path). In
that case the runtime passes `None` (or the language equivalent) for the
`MeshJob` slot. The user function MUST handle `None` — typically by
treating the call as a "fast path" execution that doesn't update progress
or check cancellation.

## Implementation sequence

Each SDK's resolver fix is tracked under that SDK's section in `MESHJOB_DESIGN.org`.
This contract is the source of truth — if a per-SDK implementation diverges,
fix the implementation, not this contract. Bug reports against the
resolver SHOULD reference the scenario number from the test-file checklist
above.
