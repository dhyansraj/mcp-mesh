# MeshJob DDDI Resolver Contract

Each language SDK (Python, TypeScript, Java) implements parameter resolution
for tools decorated with `@mesh.tool`. With MeshJob added to the type system,
the resolver MUST handle two distinct injectable types under a unified
positional contract:

- `MeshTool`: remote capability proxy → positional dependency injection
- `MeshJob`: job submitter (consumer-side) / controller (producer-side) → positional dependency injection (same `dep_index` namespace as `MeshTool`)

This document defines the resolver behavior all three SDKs must match.

## Injection rule (unified positional)

Dependencies inject positionally into `MeshTool` OR `MeshJob` parameters in
**parameter declaration order**. The slot's type determines what gets
injected (`MeshTool` proxy vs `MeshJob` submitter). Parameter names are
free-form; capability names in `dependencies[]` match by position, not by
name.

Iterate parameters in declaration order, maintaining a single
`dep_index_counter` starting at 0. For each parameter annotated as either
`MeshTool` or `MeshJob`, assign the current counter value and increment.
For any other annotation (user argument), do NOT touch the counter.

## Classification

| Annotation | Classification | Consumes `dep_index`? |
|---|---|---|
| `MeshTool` | Mesh dependency | Yes — next positional slot |
| `MeshJob` | Job injectable | Yes — next positional slot |
| Other | User argument | No — passed by caller |

## Unresolved dependencies

If `dependencies[i]` cannot be resolved at injection time (no agent
advertises that capability), the corresponding parameter slot stays
`None`. Positions do NOT shift to fill the gap; each `dep_index` strictly
pairs with one parameter position.

## MeshJob slots specifically

A `MeshJob` slot at `dep_index = i` receives a `MeshJobSubmitter` (or
language equivalent) bound to `capability=dependencies[i]` whenever the
runtime knows where to submit (e.g. Python: `MCP_MESH_REGISTRY_URL`
environment variable is set). Runtime claim availability — whether an
agent picks up the submitted job — is a separate concern handled at
`submitter.submit(...)` time.

## Reference example

Function signature:

```python
async def plan_trip(
    user_id: str,                          # signature pos 0 — user arg
    weather_lookup: MeshTool = None,       # signature pos 1 — dep_index 0
    job: MeshJob = None,                   # signature pos 2 — dep_index 1
    flight_search: MeshTool = None,        # signature pos 3 — dep_index 2
):
    ...
```

With `dependencies = ["weather_capability", "trip_workflow", "flight_capability"]`:

- `dep_index 0 → weather_lookup` receives a `MeshTool` proxy for `weather_capability`
- `dep_index 1 → job` receives a `MeshJobSubmitter` for `trip_workflow`
- `dep_index 2 → flight_search` receives a `MeshTool` proxy for `flight_capability`
- User passes `user_id` at signature position 0

## Tool invocation

When the runtime invokes the tool:

- User-arg slots: filled from caller payload
- `MeshTool` slots: filled from resolved capability proxies (or `None` if unresolved)
- `MeshJob` slots: filled from a `MeshJobSubmitter` constructed for the bound capability (or `None` when the runtime can't construct one — e.g. registry URL unset)

If the call is itself a job (producer-side, `X-Mesh-Job-Id` header
present OR claim path), the runtime additionally binds the
`JobController` contextvar so the user function can read job context via
`mesh.jobs.current_job()` / write progress via the appropriate helper.

## Equivalence across SDKs

> **Note (status of cross-SDK parity)**: This unified positional contract is currently implemented in the Python SDK only. The TypeScript and Java SDKs are tracked under separate work; their dependency-injection paths may still resolve MeshJob params orthogonally to McpMeshTool slots. Cross-SDK alignment of the unified positional contract is a follow-up.

| SDK | Annotation lookup | Test seam |
|---|---|---|
| Python | `inspect.signature` + `typing.get_type_hints` | `tests/test_resolver_meshjob.py` |
| TypeScript | `reflect-metadata` decorator | `__tests__/resolver-meshjob.spec.ts` |
| Java | `java.lang.reflect.Parameter.getAnnotations()` | `MeshJobResolverTest.java` |

All three test files MUST cover the same scenarios:

1. Function with MeshTool only → each MeshTool slot consumes the next `dep_index`
2. Function with MeshJob only → the single MeshJob slot consumes `dep_index 0`
3. Function with both, MeshJob in middle → slots take `dep_index` in declaration order; the MeshJob slot's `dep_index` matches its place in the parameter list
4. Function with neither → no DDDI metadata
5. Function with MeshJob trailing → the MeshJob slot consumes the last `dep_index`

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
job param wherever it reads naturally. Under the unified positional
contract each typed slot — `MeshTool` or `MeshJob` — consumes the next
`dep_index` in declaration order.

### Parameter name vs capability name

`MeshJob` parameter names are free-form. The binding from
`dependencies[i]` to a parameter is **positional only** — the parameter
name does NOT need to match the capability string. A parameter named
`workflow` paired with `dependencies=["run_my_thing"]` receives a
submitter bound to capability `"run_my_thing"`.

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

## Tool invocation: producer-side vs consumer-side `MeshJob`

A `MeshJob` parameter plays two distinct roles depending on the call path:

- **Consumer-side** (this tool *submits* jobs to a remote `task=True`
  capability): the runtime injects a `MeshJobSubmitter` bound to the
  capability at this slot's `dep_index`. The user calls
  `await submitter.submit(...)` to enqueue work.
- **Producer-side** (this tool *is* the `task=True` target being claimed
  / dispatched as a job): the runtime injects the per-call
  `JobController` so the function can write progress, check
  cancellation, and emit events. This applies when the tool is invoked
  with `X-Mesh-Job-Id` (or via the claim path).

Any tool with a `MeshJob` parameter can also be invoked as a regular
synchronous `tools/call` (no `X-Mesh-Job-Id` header, not a consumer
submission). In that case the runtime passes `None` for the `MeshJob`
slot, and the user function MUST handle `None` — typically by treating
the call as a "fast path" execution that doesn't update progress or
check cancellation.

## Implementation sequence

Each SDK's resolver fix is tracked under that SDK's section in `MESHJOB_DESIGN.org`.
This contract is the source of truth — if a per-SDK implementation diverges,
fix the implementation, not this contract. Bug reports against the
resolver SHOULD reference the scenario number from the test-file checklist
above.
