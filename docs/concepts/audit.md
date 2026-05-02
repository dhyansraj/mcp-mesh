# Audit Trail

> Inspect every decision the registry made when wiring your agent's dependencies

When a consumer asks "why did my dependency wire to producer X instead of Y?" — or worse, "why didn't it wire at all?" — the dependency-resolution audit trail has the answer. The registry records every stage of every non-trivial resolution decision, and `meshctl audit` reads it back.

## Overview

Every time the registry resolves a dependency for a consumer, it records the stage-by-stage outcome as a `dependency_resolved` (or `dependency_unresolved`) event in the registry event log. Each event captures which candidates entered each filter stage, which were dropped (and why), and the final winner. `meshctl audit` reads those events back so you can answer "why was this provider chosen?" or "why didn't my dependency wire?" without trawling logs.

## The 6-stage pipeline

When a consumer asks the registry to resolve a dependency, candidates flow through these stages in order:

1. **`health`** — drop unhealthy or deregistering candidates first. Running this stage first keeps the downstream stage tables clean (no stale agents listed in the tag-eviction trace).
2. **`capability_match`** — survivors from the indexed query for `capability=X`. This stage records the universe the rest of the pipeline operates on.
3. **`tags`** — apply required / preferred / excluded tag filters and compute scores. See [Tag Matching](tag-matching.md).
4. **`version`** — apply semver constraint (`>=2.0.0`, `^1.4`, etc.).
5. **`schema`** — apply the opt-in schema check. When the consumer didn't ask for schema matching, this stage is a pass-through and `spec.schema_mode` reads `"none"`. See [Schema Matching](schema-matching.md).
6. **`tiebreaker`** — pick the winner from the surviving set. Currently `HighestScoreFirst` (highest tag-match score, first encountered if tied).

Each stage records `kept` (survivors) and `evicted` (with a typed reason). The chosen producer is recorded on the `tiebreaker` stage and at the top level of the trace.

## Emission gating

The registry deliberately doesn't emit an event for every resolution — single-candidate forced choices that resolve cleanly are silent. There's nothing to debug. Events fire when:

- For `dependency_resolved`:
    - **≥2 candidates** entered any stage of the pipeline (a real choice was made), OR
    - The chosen producer **changed** since the last resolution (re-wiring observable for ops).

- For `dependency_unresolved`:
    - **≥1 eviction** happened (something was filtered out), OR
    - **≥2 candidates** entered any stage, OR
    - A previous resolution had succeeded and now no longer does (regression observable).

This keeps the audit table noise-free while guaranteeing that any decision worth investigating is captured. The single-candidate-evicted case is included specifically so a missing dependency that previously had a candidate is visible.

## meshctl audit examples

```bash
# Tabular summary - last 20 events (default)
meshctl audit hello-world

# Pretty-printed stage tree (most useful for "why?" questions)
meshctl audit hello-world --explain

# Limit how far back to look
meshctl audit hello-world --explain --limit 5

# Focus on a single dep slot of a single function
meshctl audit hello-world --function lookupEmployee --dep 0

# Hide unresolved events (rare; default includes them)
meshctl audit hello-world --include-unresolved=false

# Raw JSON envelope from /events for programmatic / CI consumption
meshctl audit hello-world --json | jq '.events[] | select(.data.chosen.agent_id == "hr-v2")'

# Talk to a remote registry
meshctl audit hello-world --registry-url https://registry.prod.example.com
```

!!! note "Prefix matching"
    The agent identifier is matched as a prefix, so `meshctl audit hello-world` resolves any unique agent whose ID starts with `hello-world` (typical scaffolded form is `hello-world-<8-char-uid>`).

## The audit envelope

Each event's `data` field is an `AuditTrace`:

```json
{
  "consumer": "hr-report-7f3a2b",
  "dep_index": 0,
  "spec": {
    "capability": "lookup_employee",
    "tags": ["api", "+fast"],
    "version_constraint": ">=2.0.0",
    "schema_mode": "subset"
  },
  "stages": [
    { "stage": "health",           "kept": ["hr-v2:lookup", "legacy-emp:lookup"] },
    { "stage": "capability_match", "kept": ["hr-v2:lookup", "legacy-emp:lookup"] },
    { "stage": "tags",             "kept": ["hr-v2:lookup", "legacy-emp:lookup"] },
    { "stage": "version",
      "kept":    ["hr-v2:lookup"],
      "evicted": [
        { "id": "legacy-emp:lookup", "reason": "VersionConstraintFailed",
          "details": { "version": "1.4.0", "constraint": ">=2.0.0" } }
      ]
    },
    { "stage": "schema",     "kept": ["hr-v2:lookup"] },
    { "stage": "tiebreaker", "kept": ["hr-v2:lookup"],
      "chosen": "hr-v2:lookup", "reason": "HighestScoreFirst" }
  ],
  "chosen": {
    "agent_id":      "hr-v2",
    "endpoint":      "http://hr-v2:8080",
    "function_name": "lookup"
  },
  "prior_chosen": "legacy-emp"
}
```

Candidate IDs use the form `<agent_id>:<function_name>` so two functions on the same agent that share a capability with different tags can be distinguished. Older events stored before this convention may use bare agent IDs — renderers display them as-is.

## Eviction reason taxonomy

Reasons are typed (not freeform strings) so audit consumers can pattern-match. The current set:

| Reason                       | Meaning                                                              |
| ---------------------------- | -------------------------------------------------------------------- |
| `MissingTag`                 | Provider lacks a required tag                                        |
| `ExtraTagDisallowed`         | Provider has a tag the consumer explicitly excluded (`-tag`)         |
| `VersionConstraintFailed`    | Provider's version doesn't satisfy the consumer's semver constraint  |
| `SchemaIncompatible`         | Provider's schema doesn't satisfy the consumer's `match_mode`        |
| `Unhealthy`                  | Provider was not healthy at resolution time                          |
| `Deregistering`              | Provider is in the middle of a graceful shutdown                     |
| `Unreachable`                | Provider's endpoint can't be reached for invocation                  |

`SchemaIncompatible` carries structured `details` describing the mismatch:

```json
{
  "id": "legacy-emp:lookup",
  "reason": "SchemaIncompatible",
  "details": {
    "mode": "subset",
    "consumer_hash": "sha256:abc...",
    "producer_hash": "sha256:xyz...",
    "reasons": [
      { "field": "department", "reason": "missing_field" },
      { "field": "id",         "reason": "type_mismatch",
        "expected": "integer", "actual": "string" }
    ]
  }
}
```

## Tiebreaker

After all filter stages, the surviving candidates are ordered by tag-match score (descending) and the first one wins. The audit records this as `reason: "HighestScoreFirst"` on the tiebreaker stage.

Configurable tiebreakers (round-robin, latency-aware, etc.) are out of scope for v1 — the audit trail is forward-compatible: future tiebreakers will record their own name in the same `reason` field.

## See Also

- [Tag Matching](tag-matching.md) — Tag scoring and `+`/`-` operators
- [Schema Matching](schema-matching.md) — Schema check details and `MCP_MESH_SCHEMA_STRICT`
- [Architecture](architecture.md) — System overview
- [Registry](registry.md) — Event log and registration
