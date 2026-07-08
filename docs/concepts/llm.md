# LLM Agents

> A tool whose body is an LLM that calls the agent's own resolved mesh capabilities as tools

An **LLM agent** is an ordinary mesh tool whose implementation delegates its reasoning to a language model. You decorate a tool with `@mesh.llm` (Python), `@MeshLlm` (Java), or `mesh.llm()` (TypeScript), and the framework injects an `llm` handle. Calling that handle runs an agentic loop: the model reasons about the request, requests tool calls, mesh dispatches each call to a resolved capability, feeds the result back, and repeats until the model produces a final answer.

The mesh-native idea is the one worth internalizing up front: **the tools the LLM can call are the agent's resolved mesh dependencies.** The LLM does not hold a hardcoded tool list — it discovers a live, filtered slice of the mesh, and every tool it invokes rides the same DDDI resolution, health-aware routing, and hot-swap as any other dependency. The LLM turns *reasoning* into a mesh primitive; the capabilities it orchestrates stay ordinary capabilities.

## Why this exists

Wiring an LLM into an application usually means owning a lot of plumbing: holding the vendor API key, maintaining the tool schema the model sees, marshalling the model's tool-call requests into real function calls, threading results back, and looping until the model is done. Every one of those is a place where the tool catalog drifts from what's actually deployed.

An LLM agent folds that plumbing into the mesh. The tool catalog the model sees is derived from live capability resolution, so it can never name a provider that isn't there. The API key lives in one place — a separate **provider agent** — not scattered across every consumer. And the loop, the schema translation, and the result marshalling are framework concerns. What you write is the prompt, the context shape, and the filter that decides which capabilities this agent is allowed to reach.

## The tool-calling loop

The `llm` handle drives an agentic loop. Conceptually, one iteration is:

```
prompt ──► LLM provider ──► "call tool X with args"  (model decides)
                                   │
                                   ▼
                      mesh resolves capability X ──► provider agent
                                   │
                                   ▼
                          result fed back to the LLM
                                   │
                              (loop until the model stops requesting tools,
                               bounded by max_iterations)
                                   ▼
                              final answer
```

The model chooses *whether* and *which* tool to call; the mesh decides *where* that call lands. A `max_iterations` bound (per-runtime name and default vary — see the SDK guides) caps the loop so a confused model can't spin forever. When the model stops requesting tools, its final message is the tool's result.

Crucially, each tool call inside the loop is a normal mesh call. It goes through the resolved proxy for that capability, honors health-aware routing, threads calling-job identity / call context, and appears in the audit trail exactly like a direct dependency invocation. The LLM is a *caller* in the mesh, not a side channel around it.

## Capability-based tool discovery

This is the differentiator. The tools an LLM agent can call are not a static list bundled with the agent — they are the agent's **resolved mesh dependencies**, selected by a capability/tag filter.

You declare a `filter` describing the capabilities this agent may reach (by tag, by capability name, or a wildcard for "everything visible"), plus a `filter_mode` that decides whether every match is offered or one best-match provider per capability. At runtime the framework resolves that filter against the live registry and hands the model the schemas of the currently available matching tools.

The consequences are the ones you'd want from anything mesh-native:

- **Tools hot-swap under the LLM.** If a better provider for a filtered capability appears, or the current one goes unhealthy, the next loop iteration reflects it — the model's tool catalog tracks the live topology with no redeploy.
- **Tools heal like dependencies.** A provider that drops out simply stops being offered; when it returns, it's offered again. There is no stale tool list to invalidate.
- **The blast radius is a filter, not a hardcode.** Widening or narrowing what the agent can do is a matter of tags, not code that enumerates specific endpoints.

This is DDDI applied to *tool discovery*: instead of injecting one resolved proxy into a parameter, the LLM agent injects a resolved, filtered *set* of proxies as the model's callable surface. See [DDDI](dddi.md) for the underlying resolution model and [Service Views](service-views.md) for the other place a consumer aggregates many capabilities behind one handle.

## Provider abstraction

An LLM agent never talks to a vendor directly. It selects an **LLM provider** — a separately deployed agent that publishes an `llm` capability and holds the vendor API key — through the same capability/tag selector the mesh uses for everything else. Consumers carry no keys; swapping vendors, applying rate limits, or centralizing cost tracking happens at the provider, and consumers are unchanged.

Under the provider, mesh routes to native adapters for the major vendors — Anthropic, OpenAI, and Gemini — with a LiteLLM path as the general fallback for the long tail of models. The important property is that all of them honor **one contract**: the same loop, the same tool-call dispatch, the same structured-output behavior, regardless of which vendor answers. Vendor-specific quirks (for example, prompt-shaping needed to make structured output coexist with tool calls) are handled inside the adapter, not pushed onto the agent author.

A consumer can also **override the model** the provider would otherwise use, and pass **model parameters** (token limits, temperature, and similar) either as decorator-level defaults or at call time, with call-time values taking precedence. A model override that doesn't match the provider's vendor degrades gracefully to the provider's default rather than failing hard. The exact parameter names and precedence rules are per-runtime — the SDK guides are authoritative.

## Structured output and `response_model`

An LLM agent can return plain text or a validated structured object. Structured output is where mesh draws a deliberate distinction between two schemas that are easy to conflate:

- The tool's **output schema** — what callers of this mesh tool receive. This is driven by the tool's declared return type, exactly like any other mesh tool.
- The **LLM-emitted schema** (`response_model` / `responseModel`, or the Java `generate(X.class)` type) — the shape the model is required to produce and is validated against.

By default the LLM is asked to emit the tool's return type, so the two coincide. Specifying a separate `response_model` decouples them: the model emits only a focused subset of fields it should actually reason about, and the tool's handler combines that subset with deterministic, function-computed fields to build the fuller payload callers receive. This keeps the model from being forced to emit — and possibly hallucinate — fields that the function can compute exactly. Separating "what the LLM produces" from "what the tool returns" is the same separation-of-concerns instinct that runs through the rest of mesh: the model owns reasoning, the handler owns the contract.

## Per-SDK guides

This page stays at the concept level. The exact decorators, parameter names, provider setup, prompt templating, and structured-output syntax live in the runtime guides:

- [LLM Integration (Python)](../python/llm/index.md) — `@mesh.llm`, `@mesh.llm_provider`, Jinja2 prompts
- [LLM Integration (Java)](../java/llm/index.md) — `@MeshLlm`, `@MeshLlmProvider`, the fluent `MeshLlmAgent` builder
- [LLM Integration (TypeScript)](../typescript/llm/index.md) — `mesh.llm()`, `addLlmProvider()`, Zod schemas

## See Also

- [DDDI](dddi.md) — the resolution primitive the LLM's tool catalog rides on
- [Service Views](service-views.md) — the other consumer-side aggregation of many capabilities
- [Tag Matching](tag-matching.md) — how the provider and tool filters pick and score capabilities
- [Schema Matching](schema-matching.md) — output-shape disambiguation for the tools the LLM calls
- [Routes & Gateways](routes.md) — the other place agents expose behavior to the outside world
