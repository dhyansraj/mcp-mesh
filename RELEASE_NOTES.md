# MCP Mesh Release Notes

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v3.2.3...HEAD)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v3.2.1...v3.2.3)

## v3.2.3 (2026-07-21)

A patch release: vendor-contract fixes for current Anthropic and Gemini models, a corrected `meshctl scaffold` default, two meshui fixes, and a release-pipeline fix so the Java SDK reaches Maven Central. No wire, registry, resolution, or declaration-syntax changes.

> **v3.2.2 was never fully published.** Its Java SDK failed Maven Central validation, so the Java artifacts and `mcpmesh/java-runtime:3.2.2` do not exist. Everything from 3.2.2 is included here — upgrade straight to 3.2.3.

### 🤖 LLM

- **Sampling parameters are no longer sent to models that reject them (#1344).** Anthropic removed `temperature`/`top_p`/`top_k` on Opus 4.7/4.8, Sonnet 5 and Fable 5, where passing them returns a 400. They are now dropped for those families with a warning, in Python, TypeScript and Java. Models that still accept them are unaffected.
- **Gemini thinking-config conflicts are resolved before the request is sent (#1346).** `thinking_level` and `thinking_budget` together is a Google-side 400; mesh keeps `thinking_level` and drops the other. No model gating was added — measurement showed a version gate would be wrong on arrival.
- **A consumer's `max_iterations` now reaches the provider-managed loop (#1356).** It was previously ignored on the delegated path, where the provider hardcoded 10. It is forwarded only when explicitly set, so a provider's `MESH_LLM_MAX_ITERATIONS` still governs consumers that set nothing. ⚠️ If you declared a cap on a delegated consumer, it now takes effect.

### 🛠 CLI and meshui

- **`meshctl scaffold` emitted a retired Gemini model (#1345).** The gemini default was `gemini/gemini-1.5-pro`, which 404s on first call; it is now `gemini/gemini-2.5-flash`. Agents scaffolded before this release need the model updated by hand.
- **The agent detail panel shows the resolved MCP tool and endpoint (#1350)**, matching what `meshctl` already printed.
- **The Jobs page no longer crashes when the registry is unreachable (#1352)** — it shows the connection-error screen instead.

### 📦 Release and CI

- **Java SDK publication fixed (#1357).** The BOM was the only artifact Maven did not sign, and Central rejected the deployment for it; it is now signed on the same path as every other module. Publication is also verified before the job reports success, and the Java image build fails fast when the SDK is missing rather than 37 minutes later.
- **Two test surfaces now run in CI (#1348, #1352)** — the `_mcp_mesh` unit tree (928 tests) and the meshui dashboard (type check plus 36 tests). Neither had ever executed; eight tests covering the v3.2.1 Haiku 4.5 change were failing and are now fixed.

### ⚠️ Notes

- Java `@MeshLlm(maxIterations)`'s annotation default changes from `10` to an unset sentinel. Behavior is unchanged.
- No upgrade action is required beyond the scaffolded-Gemini note above.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v3.2.0...v3.2.1)

## v3.2.1 (2026-07-17)

A patch that promotes Claude Haiku 4.5 to Anthropic's native structured-output path.

### 🤖 LLM: Haiku 4.5 native `output_config` (#1341)

mesh routed every Claude Haiku model through the synthetic-tool structured-output fallback — a stale exclusion mirrored from an older allow-list that predates Haiku 4.5's structured-output support and lumped all Haiku in with genuinely-unsupported older models. **Haiku 4.5 now uses Anthropic's first-class `output_config` primitive**, matching the current supported set (Fable 5, Opus 4.8, Sonnet 5, Haiku 4.5). The native path is cheaper and more reliable than the synthetic-tool workaround, which matters for cost-driven Haiku usage doing structured output with tools. Pre-4.5 Haiku (3.x) stays on the synthetic-tool path — it genuinely rejects the field. Validated end to end: Haiku 4.5 with a structured response schema and a function tool in the same call resolves via the native `output_config` path, the tool loop completes, and there is no 400.

### ⚠️ Notes

- **Optimization, not a behavior break.** A non-matching model id still degrades to the synthetic-tool path; this change only promotes Haiku 4.5 from synthetic-tool to native. No wire, registry, resolution, or declaration-syntax changes; non-Haiku models are unaffected.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v3.1.0...v3.2.0)

## v3.2.0 (2026-07-16)

A capability and modernization release. LLM model support is broadened to the current Claude and OpenAI generations — Claude Sonnet 5, and OpenAI GPT-5 reasoning models used with function tools — the Java runtime moves from spring-ai 2.0.0-M4 to 2.0.0 GA, and meshui collapses live agent replicas into a single grouped entry. Nothing touches the wire protocol, the registry, dependency resolution, or the declaration syntax; runtime model-id handling remains pass-through, so new provider models work without a mesh change. The one migration item is a Java Gemini/Vertex configuration-key change inherited from the spring-ai upgrade.

### 🤖 LLM: current-model support — Sonnet 5, GPT-5 reasoning + tools (#1333, #1337)

Model handling in mesh is pass-through and keyed on the provider vendor, so a newly released model generally works with no code change. Two manually maintained surfaces are refreshed to match the current generation, and one genuine capability gap is closed.

Anthropic: the native `output_config` structured-output allow-list is refreshed to cover the current models (Claude Sonnet 5, Opus 4.6/4.8, Fable 5); an id it doesn't match continues to degrade to the synthetic-tool path rather than failing, so the change is an optimization refresh, not a behavior break. The `meshctl scaffold` default Claude model is now `claude-sonnet-5`.

OpenAI: the GPT-5-family sampling-parameter gate now recognizes chat variants version-agnostically — a versioned chat id such as `gpt-5.6-chat` is correctly treated as a chat model while a reasoning point release such as `gpt-5.6` stays restricted. More substantially, **GPT-5 reasoning models now work with function tools.** OpenAI rejects reasoning + function tools on `/v1/chat/completions`; the Python runtime now routes those requests to the OpenAI Responses API so reasoning and tools coexist, while non-reasoning models and no-tools calls stay on chat.completions unchanged. Because mesh delegation is provider-managed — the provider's runtime makes the vendor call — any consumer, in any language, can use a GPT-5 reasoning model with tools by delegating to a Python provider. TypeScript providers already route OpenAI through the Responses API by default; a Java-provider equivalent awaits spring-ai's Responses support (#1335).

### ☕ Java: spring-ai 2.0.0 GA (#1339)

The Java runtime moves from the spring-ai 2.0.0-M4 milestone to the 2.0.0 GA release. There is no framework jump — mesh was already on Spring Boot 4 / Java 17 — and the embedded MCP SDK is unchanged, so the custom HTTP transport is untouched. The GA API changes are internal to the LLM handlers, and mesh's own `@MeshAgent` / `@MeshTool` / `@MeshLlm` / `@MeshRoute` surface is unchanged. The provider-side no-execute tool-delegation semantics — the provider returns the model's tool calls and mesh executes them — are preserved and were validated end to end against OpenAI, Anthropic, and Gemini.

⚠️ **Migration — Java Gemini/Vertex users only.** spring-ai 2.0 GA consolidated its Google support into the google-genai SDK and dropped the separate Vertex AI module. If you run a Java Gemini provider, update the configuration keys `spring.ai.vertex.ai.gemini.*` → `spring.ai.google.genai.*` (`api-key` for AI Studio, or `project` / `location` for the Vertex AI backend). The `vertex_ai` / `vertexai` provider aliases now resolve to the single google-genai Gemini model, with the backend selected by that configuration. If you call spring-ai APIs directly (beyond mesh's decorators), review spring-ai's own 2.0 migration notes as well.

### 🖥️ meshui: replicas collapse into a single ×N entry (#1330)

Live agent replicas that share an agent name now collapse into one `×N` entry across the Topology, Agents, and Dashboard views, with worst-of aggregate health and a drill-in for per-instance detail — matching the "one logical agent, N pods" mental model rather than rendering N near-identical rows. Edge wiring and per-instance trace lookups are unaffected.

### 📚 Docs: "Why MCP Mesh?" reframed around DDDI (#1329)

The positioning page now leads with the single idea the platform is built on — Distributed Dynamic Dependency Injection — and frames the feature surface as consequences of that primitive, rather than opening with an operations feature list.

### ⚠️ Notes

- **No wire, registry, resolution, or declaration-syntax changes.** Runtime model-id handling is pass-through; new Claude and OpenAI models work without a mesh change.
- **One migration item — Java Gemini/Vertex configuration keys** — from the spring-ai 2.0 GA upgrade (see above). All other Java behavior is unchanged, and non-Java runtimes are unaffected.
- **Known limitation.** OpenAI GPT-5 reasoning-plus-tools works through Python and TypeScript providers today; the Java-provider path awaits spring-ai's Responses API support (#1335). Native Responses streaming and multimodal input on the Python path are tracked follow-ups (#1336).

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v3.0.1...v3.1.0)

## v3.1.0 (2026-07-08)

A service-view refinement release: two RFC-1280 declaration surfaces shipped in v3.0.0 are corrected — the producer-side sugar is withdrawn and the Java view annotation is renamed for consistency — alongside a documentation buildout that gives the service-view, LLM, and HTTP-route features proper conceptual homes.

Both surface changes landed in v3.0.0 roughly two days before this release with effectively no adoption, so they are corrected now, cleanly, rather than carried forward. Neither touches the wire protocol, the registry, or dependency resolution; the consumer-side service view (the RFC-1280 headline) is unchanged.

### 💥 Breaking changes

Two, both narrow and both against surfaces introduced in v3.0.0 (~2 days ago, minimal adoption). Removing or renaming public API in a minor is technically a breaking change; each is corrected here with an actionable failure rather than a silent one, and neither affects the wire, the registry, or the consumer service view.

1. **Producer-side service-view sugar withdrawn (#1320).** `@mesh.service("prefix")` (Python), `agent.addService("prefix", …)` (TypeScript), and `@McpMeshService("prefix")` on a class (Java) are removed. Using any of them now fails fast at decoration/registration with a message pointing to the explicit form. Migrate by declaring each tool explicitly: `@mesh.tool(capability="prefix.method")` / `agent.addTool({ capability: "prefix.method", … })` / `@MeshTool(capability = "prefix.method")`.
2. **`@McpMeshService` → `@MeshService` (#1322, Java only).** The consumer service-view annotation is renamed to join the `@Mesh*` family. Rename `@McpMeshService` → `@MeshService` (and the import). The injected proxy type `McpMeshTool` is unchanged; Python (`@mesh.service`) and TypeScript (`mesh.serviceView`) are unchanged.

### ✂️ Producer-side service-view sugar withdrawn (#1320)

The producer sugar derived the published capability as `"{prefix}.{methodName}"` — deriving the cross-runtime wire identifier from a language method name, which recoupled the wire contract to a language construct: a local, idiomatic method rename would silently change the capability and break every consumer, `meshctl call`, and LLM tool-name continuity (the exact coupling #680 removed). It could also express none of `tags`, `version`, or `dependencies` — the sweep published `capability` only, with `version` pinned to the `1.0.0` default — so any real producer fell back to an explicit `@MeshTool` anyway. The sugar's entire value, deriving the name, *was* the coupling, so it is removed rather than patched. Consumer views and dot-namespaced capabilities are unaffected: publish a dotted capability explicitly with `@mesh.tool(capability="media.caption")` / `addTool` / `@MeshTool`. The removal is uniform across all three runtimes, with a fast-fail actionable error at the former call sites.

### 🏷️ `@McpMeshService` → `@MeshService` (#1322)

The Java annotation family is uniformly `@Mesh*` (`@MeshAgent`, `@MeshTool`, `@MeshRoute`, `@MeshDependency`, `@MeshInject`, `@MeshDependsOn`, `@MeshLlm`, `@MeshA2A`); `@McpMeshService` was the lone `Mcp`-prefixed annotation. Unlike the injected proxy *type* `McpMeshTool` — whose prefix disambiguates it from the `@MeshTool` annotation — the annotation had no such collision, so its prefix was pure inconsistency. It is renamed to `@MeshService`, which also aligns Java with Python's already-correct `@mesh.service`. Java-only, a hard rename with no alias (same minimal-adoption rationale); `McpMeshTool`, Python, and TypeScript are unchanged.

### 📚 Docs: concept homes for service views, LLM, and routes (#1323, #1324)

The documentation gains proper conceptual coverage for three features that previously lived only in per-SDK guides or reference tables. A dedicated **service-views** page — the mkdocs concept page plus a new `meshctl man service-views` topic with `--java`/`--typescript` variants — documents when a service view fits (a single consumer using most of a cohesive dotted group) versus the anti-pattern of injecting a fat view into thin handlers, where it fans out to one dependency edge per method and can over-gate. New **LLM Agents** and **Routes & Gateways** concept pages cover the tool-calling loop and capability-based tool discovery, and the `@MeshRoute` HTTP-gateway perimeter respectively — the latter framing routes-versus-tools by protocol and role (both are network-reachable over Streamable HTTP, not "internal versus external"). The Concepts nav is reordered into a foundation → capability-model → control-plane → agent-capabilities → state → operations arc, and the seven-page Multimodal group is consolidated into a single concept page so it reads like the others. Consumer-side gaps surfaced in review are closed on both the mkdocs and `meshctl man` surfaces: the Java "a view is rejected in `@MeshRoute`" rule, the dotted-`@MeshInject` route pattern (with the `@MeshDependency(required=…)` default), a multi-`@Param` view-method example, union-plus-dotted capability coexistence, and a note that a facade call threads calling-job identity like any ordinary tool call.

### ⚠️ Notes

- **Two breaking changes, both against v3.0.0-only surfaces with minimal adoption.** If you adopted the producer sugar (`@mesh.service("prefix")` / `addService` / `@McpMeshService("prefix")` on a class), switch to explicit `@mesh.tool` / `addTool` / `@MeshTool` with a dotted capability. If you used the Java `@McpMeshService` consumer view, rename it to `@MeshService`. Both former forms now fail fast with an actionable message.
- **No wire, registry, or resolution changes.** The consumer service view, dot-namespaced capabilities, and all dependency-resolution behavior are unchanged.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v3.0.0...v3.0.1)

## v3.0.1 (2026-07-07)

A patch that fixes a Kubernetes regression in v3.0.0 and hardens dependency re-wire plus the `meshctl list` view.

v3.0.0 was a consolidation-and-modernization release that claimed no breaking changes; that claim was wrong for Kubernetes deployments running Python providers, which hit a FastMCP host-validation `421 Misdirected Request` on every cross-pod call. v3.0.1 fixes that regression, pins the Python transport dependencies so it can't silently recur, makes a running consumer self-heal a stale dependency edge without a manual restart, and cleans up the `meshctl list` default view. All changes are internal hardening of existing contracts — no API, declaration-syntax, or wire changes.

### 🩹 Kubernetes: Python providers reachable by Service DNS (#1313)

Python mesh providers addressed by a non-localhost `Host` — a Kubernetes Service DNS name — were rejecting every `/mcp` call with **`421 Misdirected Request`**, breaking all cross-pod tool and LLM-provider calls to Python providers in Kubernetes (a `localhost` / `127.0.0.1` `Host` still returned `200`, which is why local development never surfaced it). The cause was a recent transitive `mcp`/`fastmcp` default flip to `enable_dns_rebinding_protection=True` with a localhost-only `allowed_hosts`: mesh built its Streamable-HTTP app without configuring transport security and inherited the localhost-only guard. This was **not an intentional bump** — the Python pins were unchanged loose ranges (`fastmcp>=3.0.0,<4`, `mcp>=1.26.0,<2`) with no lockfile, so a rebuild simply resolved a newer release where the security default had already changed. The fix sets **`host_origin_protection=False`** at all four `FastMCP.http_app(...)` call sites — mesh is an internal service mesh addressed by Service DNS, so the DNS-rebinding browser threat model does not apply to server-to-server calls — and **pins `fastmcp==3.4.3` / `mcp==1.28.1`** in both pyproject files so an upstream security-default flip can no longer land silently on a rebuild. A regression test proves a served app now accepts a non-localhost `Host` (`200`, not `421`), with the negative proving the default guard would `421`. Affects Python providers only.

### 🔁 Dependency re-wire hardening — never restart a consumer (#1316)

A running consumer no longer needs a manual restart to pick up a topology change. The pipeline records a dependency edge as *delivered* on enqueue rather than on apply, and the mitigating reconcile that re-drives believed-delivered edges ran only inside the full-heartbeat path — which fires on a registry topology signal, never on a wall clock — so a downstream apply-drop under a subsequently stable topology could leave a consumer wired to an old provider indefinitely. The reconcile is now also driven from an independent ~10s clock tick (cancellation-safe, `MissedTickBehavior::Skip`, sharing the existing throttle so the two drivers never double-fire), so any stale edge self-heals within the interval regardless of cause. Each SDK apply path is made **idempotent** — it skips rebuilding a proxy when the incoming resolution equals what is already wired (keyed on `endpoint`/`function`/`kwargs`/`agent_id`) — so the periodic re-emit is free in steady state and rebuilds only a genuinely stale edge, across both the mcp and `@mesh.route`/api consumer paths in all three runtimes. Finally, `agent_id` is added to the dependency diff gate so an in-place provider restart (same endpoint, fresh UUID) is now detected as a change. The reconcile deliberately does not tick during a registry-down window (retain-on-disconnect holds), and no per-consumer notification/ack state is introduced.

### 🩺 `meshctl list`: healthy-only default + CAPS column (#1317)

The default `meshctl list` view is healthy-only again. A prior change had promoted a "blocking" down instance to a red row in the default table, which could make the per-instance header and per-name footer counts contradict what was on screen (`8 agents (8 healthy)` printed above a visible unhealthy row). The default view now keeps only live rows; down and blocking-down instances join the hidden `N down hidden (use --all)` footer, making the counts self-consistent by construction (`--all` and the JSON default are unchanged). A new **`CAPS`** column, parallel to `DEPS`, shows `available/total` provided capabilities — right-aligned and red when `available < total` — excluding the synthetic `__mesh_*` family from the total and treating nil/older registries as available (no spurious markers). It replaces the trailing `(N capabilities unavailable)` free text on the default rows; per-capability reasons stay in `--verbose`.

### 📚 Docs (#1311, #1318)

One consolidated pass over the mkdocs site (net −14,072 / +342 lines): 19 orphan and duplicate pages pruned — including six AI-generated observability deep-dives that taught Prometheus/Grafana rather than mesh's own offering — the Service Views concept page (RFC #1280) added and wired into the Concepts nav, Multimodal folded into Concepts, and site-wide staleness corrected (the heartbeat interval was documented as 30s/90s but the real defaults are **5s / 20s**, a TypeScript quickstart taught a nonexistent `new MeshAgent`/`app.tool` API, and a fictional multimodal S3 bucket default was removed). Separately, stale `meshctl man` claims were fixed (#1318): A2A producers are supported in Java (`@MeshA2A`) and TypeScript (`mesh.a2a.mount`) today with sync/long-running/SSE parity — not "future work" — and a `media.md` example is corrected to the canonical `import mesh`.

### ⚠️ Notes

- **No breaking changes and no coordinated upgrade is required — but Kubernetes deployments running Python providers on v3.0.0 are affected.** They hit the FastMCP host-validation `421 Misdirected Request` on every cross-pod call; v3.0.1 fixes it, so upgrade the Python runtime images. This corrects the v3.0.0 "no breaking changes" line for Kubernetes Python deployments.
- **`fastmcp` and `mcp` are now exact-pinned** (`fastmcp==3.4.3` / `mcp==1.28.1`) for reproducible Python images; a full transitive lockfile is a noted follow-up.
- **The re-wire fix removes a manual step:** restarting a consumer after a topology change is no longer necessary — a stale dependency edge self-heals within the reconcile interval.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.8.2...v3.0.0)

## v3.0.0 (2026-07-06)

The consolidation milestone: dot-namespaced capabilities become **typed service views** across all three runtimes, MeshJob gains durable event resume and a typed supersession signal, and the Java runtime moves to the MCP Java SDK 2.0 GA — additively, with behavior held constant.

v2.8 turned the dependency graph availability-aware and hardened MeshJob for multi-replica consumers; v3.0 builds the higher-level surface on top of it. A group of dot-namespaced capabilities can now be consumed as a single typed facade — a *view* — while each capability remains the atom, so per-method resolution can land on different provider agents and rebind independently (the differentiator from Feign/gRPC-style single-target clients). Alongside the view story, the interactive-jobs surface reaches completeness: an opt-in durable `recvEvent` cursor lets a re-claimed handler resume instead of replaying from zero, and a typed supersession error lets a fenced executor unwind with one catch. The Java runtime adopts the MCP Java SDK 2.0 GA and gains `structuredContent` parity with the Python provider, and the untyped single-parameter injection heuristic is deprecated. Because the new declaration surfaces are additive and the SDK bump holds behavior constant, v3.0.0 is a consolidation-and-modernization release rather than a hard break.

### 💥 Breaking changes

**None.** v3.0.0 introduces no breaking changes. Service views are additive declaration surfaces — existing dependency specs serialize byte-identically and a mesh with no views is unaffected; the MCP Java SDK 2.0 upgrade holds runtime behavior constant (`validateToolInputs(false)`); the capability-name grammar is widened strictly, so every previously valid name remains valid; and the untyped single-parameter injection heuristic is deprecated with a runtime warning, not removed. The two things to be aware of on upgrade — the heuristic deprecation and the Java SDK bump — are detailed in ⚠️ Notes.

### 🧩 Service views — typed aggregation of dot-namespaced capabilities (RFC #1280: #1284, #1286, #1288, #1290, #1292)

A service view is a consumer-owned typed aggregation of ordinary capability dependencies: a group of dot-namespaced capabilities (`media.caption`, `media.thumbnail`, …) surfaced as one facade whose methods each bind a single capability. The capability stays the atom and there are **zero wire/registry changes** — a view's methods expand into ordinary `DependencySpec` edges through the existing required-wins dedupe — so each method delegates to its own per-capability resolved proxy and **methods of one view may resolve to different provider agents** and rebind dynamically. A view binds on all four dependency constructs (capability, tag, version, schema), method by method.

- **Consumer facade** (#1284) — Java `@McpMeshService` on an interface whose abstract methods each carry a method-level `@Selector`. A Spring-Data-style interface scan produces one dynamic-proxy facade bean per view, with boot-fail validation (missing/blank selectors, scalar single params, conflicting resolved types across views and other consumer sources, unsatisfiable floor). An opt-in `minAvailable` floor fails fast with `MeshServiceUnavailableException`, settle-grace-aware and racing all pending edges; self-produced capabilities soft-fail with a WARN and settle release.
- **View as a `@MeshTool` parameter** (#1286) — the same view interface used as a tool parameter expands into N ordinary dependency edges on that tool (a type-detected slot, following the MeshJob precedent, disjoint from the explicit-`@Selector` index range so existing signatures are byte-unchanged). This is the tool-scoped path where `required = true` view methods participate in the tool's pre-invoke guard — the structured `{"error":"dependency_unavailable","capability":...}` refusal on both direct and claim paths, lease released, handler never run.
- **Producer sugar + dotted capabilities** (#1288) — class-level `@McpMeshService("prefix")` on a Spring bean publishes each eligible public method as capability `prefix.<methodName>` through the existing registration machinery (an explicit `@MeshTool` on a method wins). The capability-name grammar is widened cross-runtime — one or more dot-separated `^[a-zA-Z][a-zA-Z0-9_-]*$` segments, applied identically in the Go registry validator and the Python validator — promoting dot-namespacing from an accident (it previously worked only because the tools path bypassed the validator) to a first-class contract. The widening is strict: every pre-existing name remains valid.
- **Display grouping** (#1290) — dot-namespaced capabilities render as grouped services, derived entirely from the name (group = segments before the last dot), display-only. New `meshctl list --services` prints a mesh-wide SERVICE / METHOD / AGENT / STATUS table with one deduped provider row per (capability, agent) and a structured `--json` shape (`services`/`ungrouped` always arrays, never null); `--verbose` groups dotted capabilities under `service/ (N methods)` headers with per-method provider bindings. The meshui `AgentDetail` tabs group in exact CLI parity. Note: `meshctl list --tools` now hides the whole reserved `__mesh_*` synthetic family (previously only `__mesh_job_*`, so the `__mesh_*_deps` view carriers had been leaking) and sorts by capability so members cluster; `--show-framework` reveals synthetics in both views.
- **Python & TypeScript declaration idioms** (#1292) — completing three-runtime parity. Python: consumer `@mesh.service` classes of `@mesh.selector(...)` async stubs (and view-typed `@mesh.tool` parameters) plus producer `@mesh.service("prefix")` sugar; TypeScript: `mesh.serviceView({methods, minAvailable?})` (a Symbol-branded single `dependencies` entry that expands in-place to a byte-identical edge layout) plus `agent.addService("prefix", …)`, which carries the SDK's first capability-name validation. Required edges refuse pre-invoke on both direct and claim paths; the `min_available` / `minAvailable` floor races all pending settle keys. Cross-runtime proof: Python and TypeScript view consumers bind a Java producer's dotted capabilities with **byte-identical structured refusal envelopes** across all three runtimes, and one `--services` view groups services produced by Java, Python, and TypeScript simultaneously.

On refusal semantics: a `required = true` method on a **bean-path** facade behaves exactly like a class-level required dependency (registry-carrier availability, required-wins, route-perimeter promotion) but does **not** add a tool-boundary pre-invoke refusal, because the framework cannot know which tools call a class-level aggregation — the tool-scoped refusal is available by declaring the view as a tool parameter instead.

### ⏳ Jobs completeness: durable event resume + typed supersession (#1277 — #1298, #1299, #1300; #1278 — #1301)

Two additions bring the interactive-MeshJob surface to completeness. **Durable `recvEvent` cursors** (#1277) let a re-claimed handler resume from its last processed position instead of replaying from seq 0. The registry framework-persists a per-job, per-filter `recv_cursor` via the same epoch-guarded UPDATE as progress (a superseded delta never advances it), as a per-key MAX merge, omitted from every reclaim clear-chain so it survives sweep and force-reclaim. The Rust core maintains a lagging `durable_cursors` alongside the receipt-advanced cursor and stamps the lagging value on deltas, so a crash replays the un-flushed tail — **at-least-once, never a skip**. Resume is opt-in and default-off: only `@mesh.tool(resume_cursor=True)` / `resumeCursor` / `@MeshTool(resumeCursor=true)` on a `task` tool, seeded only when the claim response carries a usable cursor, changes behavior. The persisted cursor is exposed on `GET /jobs/{id}` and `meshctl job status`, and the reclaim-resume path is proven end-to-end on real natives across all three runtimes (resume consumes each event once vs a `resume_cursor`-off control that replays it). **Durable resume requires sequential-per-filter consumption** — a handler that prefetches or processes a filter's events concurrently (`recv→spawn→recv`) must **not** enable `resume_cursor`, because resume would skip the in-flight event; the contract can't be policed for async-spawn handlers, so it is stated prominently in the job docs.

**Typed supersession signal** (#1278) gives a provider a standard typed way to reject a superseded caller so the caller unwinds with **one catch** instead of string-matching an envelope after every mutating call. A provider raises `mesh.SupersededError` (Python) / `MeshSupersededError` (TypeScript) / `MeshSupersededException` (Java); the framework serializes it to the reserved app envelope `{"error":"claim_superseded"[, "detail":…]}` (compact, byte-identical across runtimes), and the injected proxy on the caller structurally parses that envelope (JSON parse plus exact `error ==` check, never substring) and re-raises the typed error — distinct from a generic tool failure, across buffered, streaming/SSE, and local/self-dependency paths. It reuses the existing `claim_superseded` vocabulary, so there are no Rust/registry/wire changes. The integration UC on real natives surfaced two transport-path bugs the unit tests missed: a Python double-invoke where the typed raise was swallowed by an outer `except Exception` and fell through to the FastMCP fallback, and — carried as a **general fix** — TypeScript `UserError` identity being flattened crossing the tool-isolation worker boundary, which had corrupted the reserved envelope for *any* `UserError` thrown from an isolated tool body, not just this feature.

### ⬆️ MCP Java SDK 2.0 (#1305, closes #1304)

The Java runtime upgrades `io.modelcontextprotocol.sdk:mcp` **1.1.3 → 2.0.0** (GA, the first major since 1.x, tracking the 2025-11-25 MCP spec). The bump is deliberately isolated to the SDK-major variable — all touch-points confined to `mcp-mesh-spring-boot-starter`, no schema-path modernization, no transport or Jackson migration (mesh is already on Jackson 3 and a stateless Streamable-HTTP server, so the SSE→Streamable-HTTP deprecation is a no-op). The one behavioral point: 2.0 turns tool-input validation on by default, so mesh sets **`validateToolInputs(false)`** to hold behavior exactly constant — preserving mesh's lenient cross-runtime coercion and soft-fail semantics (strictness stays opt-in per the design philosophy), and ensuring validation never preempts the dependency-unavailable / superseded / settle-grace logic. Verified on a rebuilt Java native across the empty-return, service-view, superseded-signal, and full MeshJob suites, with no envelope or `structuredContent` drift. Deliberate adoption of SDK-native input validation is tracked separately in #1303.

### 🔀 Java `structuredContent` parity (#1282, in #1302)

Java `tools/call` responses now **additively** populate `structuredContent` for object-shaped returns, mirroring the Python/FastMCP rules including the #1250/#1251 empty-return contract: object-shaped (Map/POJO) becomes the object as a Map with no wrap marker, while non-object returns become `{"result": X}` plus the `{"fastmcp":{"wrap_result":true}}` meta marker, byte-identical to the Python provider. So plain, spec-compliant MCP clients and generic envelope tooling no longer see runtime-dependent shapes from Java. The change is strictly additive — `content[0].text` is unchanged and all three runtimes' proxies recover text-first (reading `structuredContent` only when the content array is empty), so mesh-internal Java↔{Python,TypeScript,Java} round-trips stay byte-identical, including `[]`/`{}`/`""`/`null`. TypeScript parity remains out of scope and is tracked in #925 (TS removed the field in #917 because FastMCP TS's strict zod schema rejects it).

### 🧹 Hygiene + docs (#1293 batch — #1294, #1295, #1296, #1297; lease docs #1279 in #1302)

A cleanup batch spanning all three runtimes. The **untyped single-parameter injection heuristic is deprecated as of v3** (#1294) — explicit `param: McpMeshTool = None`-style typing is the canonical form, and the heuristic's runtime warning is now a deprecation notice (removal targeted for the next major), fired only when a dependency is actually injected. The batch also scopes a producer-sugar DI-warning false positive, derives Python `@mesh.selector` `expected_type` from the stub return annotation for structured types (Java parity, conservative — bare containers and scalars derive nothing), adds TypeScript capability-name validation at `addTool` at parity with the Go/Python produced-name check (#1296), sweeps user-facing docs to the supported `@mcpmesh/sdk` FastMCP import idiom, and adds a vitest runner with initial service-grouping coverage for the meshui SPA (#1297). Separately (#1279, in #1302), the job lease docs gain a parked-gap-vs-compute-bound-gap contrast on all four surfaces: a handler parked in `recvEvent` renews its lease automatically (the poll *is* the renewal), while a long synchronous compute-bound stretch renews nothing and needs a periodic `update_progress` keepalive or a `max_duration` sized to the longest gap — explicitly naming the blanket "multiply `max_duration` to be safe" as the wrong fix.

### ⚠️ Notes

- **The untyped single-parameter injection heuristic is deprecated** (#1294). Its runtime warning is now a deprecation notice and is the only discovery surface — docs teach only the explicit `McpMeshTool`-typed form. Injection behavior is unchanged; removal is targeted for the next major.
- **MCP Java SDK 2.0: no action required.** `validateToolInputs(false)` holds mesh's lenient coercion and soft-fail semantics constant; deliberate adoption of SDK-native input validation is tracked in #1303.
- **The capability-name grammar is widened, strictly.** Names may now be dot-separated segments (each `^[a-zA-Z][a-zA-Z0-9_-]*$`); every previously valid name remains valid, so this is not a breaking change.
- **TypeScript `structuredContent` parity is still tracked in #925.** Java (#1282) and the Python provider now emit it; TypeScript follows when #925 unblocks upstream. Mesh-internal round-trips are text-first and unaffected either way.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.8.1...v2.8.2)

## v2.8.2 (2026-07-04)

A reliability patch closing two field-reported gaps: process-group teardown on `meshctl stop`/watch reload, and the `required=true` pre-invoke guard on the direct `tools/call` dispatch path.

v2.8.1 made required-dependency claim-gating race-free and expanded MeshJob operability; v2.8.2 closes the remaining teardown and guard edges around them. `meshctl stop` — and the equivalent watch-reload path — now verifies and force-kills the entire process group rather than the parent PID alone, so a child process that outlives its parent can no longer hold a port or keep heartbeating, and the drain probe is zombie-aware so an unreaped process group under a non-reaping container PID 1 no longer hangs the wait. In parallel, the v2.8.1 required-dependency pre-invoke guard is extended to the last unguarded dispatch path — direct `tools/call` — so a `required=true` handler never observes a null dependency on any invocation path across the runtimes.

### 🛑 Group-scoped stop + watch reload (#1274)

`meshctl stop` now scopes its graceful-then-forceful teardown to the whole process group instead of the parent PID. Previously the graceful branch verified and escalated against the parent only, so a child process (for example a spawned child JVM) could survive the stop, hold its port for minutes, and keep heartbeating. Teardown is now group-scoped end to end: `terminateAgent` polls `ESRCH`-only after `SIGKILL` and logs a WARN if a group survives. The drain probe is **zombie-aware** — on Linux an unreaped zombie process group answers `kill(-pgid, 0)` with success, so a container PID 1 that does not reap its children would otherwise hang the wait forever (macOS reaps instantly, which had masked the case locally). Watch reload routes through the same teardown logic (a regression here was caught by `tc29` and fixed). Multi-name stop (`meshctl stop a b c`) is now unit-tested and documented, along with stop's group-teardown semantics (including the `setsid`-escape caveat), the content-write reload trigger, and the by-design statement that watch is not a crash supervisor.

### 🔒 `required=true` guard on direct tool calls (#1273)

The v2.8.1 pre-invoke guard now covers the direct `tools/call` dispatch path — the last path that could reach a handler with a required dependency unresolved. The cross-runtime invariant: after the settle window, a direct call to a handler with an unavailable `required=true` dependency refuses with a structured `{"error":"dependency_unavailable","capability":...}` tool error (byte-identical envelopes across runtimes); every job-flavored invocation (claim and inbound job-header paths) releases the lease rather than failing terminally, so a transient outage never strands a job row; and a local / self-dependency dispatch raises rather than returning a refusal that could masquerade as a successful result to an LLM or local caller. The guard fires only after the settle-grace wait, so an ordinary agent restart does not burst refusals while the topology settles. Handlers therefore never observe null for a `required=true` dependency on any invocation path.

### ⚠️ Notes

- **Job status vocabulary is `working`.** The jobs docs are aligned to the runtime's actual `working` status wording (no behavior change).
- Both fixes are internal hardening of existing contracts — no API, declaration-syntax, or wire changes, and no coordinated upgrade is required.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.8.0...v2.8.1)

## v2.8.1 (2026-07-04)

A reliability and operability patch: required-dependency claim-gating and injection are made race-free, MeshJob gains calling-job identity plus operator controls, and a partial 2.8.0 version bump is corrected.

v2.8.0 turned the dependency graph availability-aware and hardened MeshJob for multi-replica consumers; v2.8.1 closes the reliability edges around it and adds the surfaces to operate it. A `required=true` job handler can no longer observe a null dependency — or burn retry attempts — while a dependency is briefly unavailable; a MeshJob-originated tool call now carries its caller's identity; and operators gain job status/reclaim, a registry drain mode, and an upgrading guide. The release also corrects a partial 2.8.0 version bump that left some published artifacts referencing 2.7 images.

### 🔒 required-dep claim-gating + injection, race-free (#1268)

The registry-side transitive availability gate (v2.8.0) is now paired with a consumer-side gate, so a `required=true` dependency is guaranteed resolved before a job runs. Claim workers skip claiming a job while any required dependency slot is locally unresolved — the job stays queued with `attempt_count` / epoch / lease untouched, so a transient dependency outage burns **zero** attempts (the earlier registry-only gate could still let a local claim proceed into a missing-dependency window). A last-resort pre-invoke guard releases the lease rather than invoking a handler with a missing dependency. Handlers therefore never observe null for a required dependency, including throughout dependency recovery. Required flags are threaded positionally into the wrappers/dispatchers across all three runtimes; Python excludes the MeshJob-paired dependency from the gate, matching the TypeScript/Java structural behavior. A new `uc35_meshjob_claim_gating` suite flaps a required dependency DOWN→UP and asserts `attempt_count == 0` on every poll through the outage window, then exactly-once execution at epoch 1 after recovery.

### 🆔 Calling-job identity (#1263)

A tool call made from within a job handler now automatically carries the caller's identity on a dedicated propagated pair, `x-mesh-calling-job-id` / `x-mesh-calling-claim-epoch` — deliberately separate from the push-dispatch protocol headers so that a nested same-instance task call cannot auto-complete the caller's own job. The pair is seeded atomically from a single job-context snapshot and replaced as a pair (never a mixed identity), forwarded by default across the registry proxy hop, and read via `MeshCallContext.callingJob()` (Java), `mesh.calling_job()` (Python), and `callingJob()` (TypeScript) — null when a handler was claimed directly rather than called from another job.

### 🛠️ Job operability: status, reclaim, drain, upgrading guide (#1264, #1265, #1266, #1267)

Operator surfaces for running MeshJob in production:

- **Job status** (#1264) — `GET /jobs/{id}` and the list endpoint now include `claim_epoch` (owner / attempts / lease were already exposed), and `meshctl job status [--json]` surfaces the full claim state.
- **Force reclaim** (#1265) — `POST /jobs/{id}/reclaim` + `meshctl job reclaim` force-supersede a claim, mirroring the lease-expiry sweep exactly (owner cleared via a guarded update, the next claim mints the epoch, terminal jobs return `409`). Enables replica eviction and fencing drills.
- **Registry drain mode** (#1267) — `POST/DELETE/GET /admin/drain` (on the isolated admin port) + `meshctl registry drain [--wait] / resume / status`. Claims pause with zero attempt burn, running jobs finish, and submissions queue. Drain state is in-memory, so a registry restart clears it.
- **Upgrading guide** (#1266) — `meshctl man upgrading` and its docs mirror document rollout order, the version-skew contract, automigrate behavior (including the drop-column downgrade caveat: a binary downgrade drops columns a newer binary added), and the freeze-vs-drain distinction.

A new `uc36_meshjob_admin` suite proves force-reclaim (epoch 2, exactly-once, the superseded execution observes cancellation) and drain (new jobs park while a mid-drain running job completes).

### 🩹 Partial 2.8.0 version bump corrected (#1271)

The 2.8.0 release shipped a **partial** version bump: the helm charts still pulled 2.7 runtime/registry images and the CLI's default runtime images were pinned to `2.7.0`, so a fresh install or scaffold silently ran on the previous minor. This is now fixed — CLI handler defaults, helm values image tags, scaffold/compose sources, docker-compose examples, and test configs are all on the current version, and a handful of ancient example stragglers are brought forward. To prevent recurrence, `scripts/bump_version.py` gains deep `examples/**` coverage (57 POMs + 17 `package.json` now bumped vs a handful before) and a post-bump coverage guard that git-greps for any surviving mesh-shaped reference to the previous version — allowlisting legitimate third-party pins — and fails non-zero on a survivor.

### 🧹 Backlog fixes (#1039, #1108, #1260)

- **Empty-list route return pinned** (#1039) — an empty list returned from a `@mesh.route` handler round-trips as `[]` (not `null`), verified fixed by the 2.8.0 empty-return work and pinned with a route-layer test through a live handler (`[]` → `[]`, `None` → `null`).
- **PyPI packaging: hatchling pin removed** (#1108) — the temporary hatchling pin is reverted; twine accepts Metadata-Version 2.5 and the upstream emission bug is fixed, so `twine check` passes on the built package.
- **Hygiene batch** (#1260) — cancel-safe napi event pull; order-independent `required=true`-wins dependency dedupe across Java beans (the route 503 perimeter promoted in lockstep, so there is no wire-vs-local split-brain); a `SemanticRejection` variant replacing an "error: 200" log line; a runnable `examples/required-dependency/` (Python + Java, scaffold-complete); and a flat eslint config for `src/ui`.

### ⚠️ Notes

- **A non-`retryOn` handler exception is terminal — regardless of `max_retries`.** This is now stated plainly across the jobs man pages and docs: `max_retries` only governs exceptions matched by `retryOn`; any other exception fails the job immediately, with no retry.
- **Drain is per-replica.** The drain flag is held in memory per registry instance, so in an HA registry topology each replica must be drained independently, and a restart clears drain state.
- **`MCP_MESH_TOOL_ISOLATION`** is now documented on both the man-page and docs surfaces.
- A runnable **`required=true` example** (`examples/required-dependency/`, Python + Java) demonstrates the availability-gated dependency contract end to end.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.7.0...v2.8.0)

## v2.8.0 (2026-07-03)

An availability-aware dependency graph via `required=true`, MeshJob execution integrity under multi-replica consumers, and exact data fidelity for empty returns and LLM replies.

v2.7 made the LLM-provider layer correct and gave MeshJob a proactive reaper; v2.8 turns the mesh's dependency graph from resolution-aware into *availability*-aware. A dependency edge can now declare `required=true`, and the registry computes capability availability **transitively** — an agent's capability is available only when the agent is healthy and every required edge resolves under full tag/version/schema matching — propagating the result through the existing dependency-update channel so consumer proxies and route perimeters gate on it with no SDK changes. Alongside it, MeshJob gains execution integrity for multi-replica consumers (claim-epoch fencing, poll-liveness, per-filter event cursors), and two data-fidelity contracts are made exact across every runtime: empty tool returns now round-trip byte-for-byte, and the `@mesh.llm` reply envelope always carries its answer as a string.

### 🔗 `required=true` — availability-aware dependencies (#1255, #1257, #1258)

A dependency edge may now opt into `required=true`. The registry computes each capability's availability **transitively** — the owning agent is healthy AND every required edge resolves under the existing resolver's full tag/version/schema matching — and propagates it through the dependency-update channel that already drives resolution, so consumers gate mesh-internal calls with **zero SDK changes**. Availability is memoized (O(nodes)), fail-closed, and the check-persist window is serialized; reason strings name the first broken edge with its constraint detail.

- **Route perimeter, all three runtimes** — a route declaring a required dependency auto-returns `503 {"error":"dependency_unavailable","capability":...}` before user code runs. Python gates in the route wrapper; Java via `MeshRouteHandlerInterceptor` (taking precedence over `failOnMissingDependency`); TypeScript via a capability-keyed perimeter judging exactly the state the handler receives.
- **Declaration syntax** — Python `required: true` on the dependency edge; Java `@Selector(required = true)` for tools and `@MeshDependency(required = true)` for routes / `@MeshDependsOn` / A2A; TypeScript `{ capability, required: true }`. Defaults `false` everywhere — existing specs serialize byte-identically and optional edges never propagate.
- **Cycle rejection** — required-edge cycles are rejected loudly at registration **and** on heartbeat metadata refresh, closing a path that bypassed the check.
- **Job claim-gating** (#1258) — `ClaimNextJob` skips a job whose target capability is unavailable under the required-deps predicate: the job stays queued with `attempt_count` / epoch / lease untouched, so a topology outage no longer burns `max_retries`. Evaluated lazily only when a candidate job exists (idle polls are byte-identical to before), fail-open with a warning on query errors, and self-healing within the claim worker's ≤5s poll ceiling.
- **Availability observability** (#1258) — `meshctl list` annotates a healthy agent that owns an unavailable capability (`(N capabilities unavailable)`), with per-tool reasons in `--verbose`, the `--tools` table, the single-tool detail view, and additive JSON fields; the mesh UI adds an availability badge with a reason tooltip on agent rows, cards, and topology nodes, plus per-capability state in the detail and topology sidebars. Registries without the fields are treated as fully available — no spurious markers.
- **Reliable dependency-update delivery** (#1256, via #1257) — dependency-update events could be silently lost at the Rust→Python bridge (a cancel-unsafe wait around an already-dequeued receive) and were never retried because the diff gate advanced on enqueue. The pull timeout now lives inside a cancel-safe future, and a throttled 10s reconcile re-emits any edge whose event didn't apply. This bug predates `required=true` and likely explains a class of historical registration-timing flakes.

Soft-fail posture is unchanged: `required` defaults false, optional edges never propagate, and a mesh with zero required edges pays effectively nothing on the hot path.

### 🔒 MeshJob execution integrity under multi-replica consumers (#1253, #1254)

MeshJob execution is made correct when the same job may be claimed and reclaimed across multiple consumer replicas or after a mid-execution reclaim.

- **Claim-epoch fencing** (#1253) — every successful claim/re-claim mints a monotonic `claim_epoch` in the same guarded update that assigns the owner. `/jobs/batch` deltas carry it; any epoch-bearing delta whose `(owner, epoch)` doesn't match the live row — cross-instance, reclaimed `owner=NULL`, or same-instance re-claim — rejects as `claim_superseded`. Epoch-less deltas keep legacy `not_owner` semantics.
- **Frame-exact supersession** (#1253) — the core translates `claim_superseded` into firing *that execution's own* cancel frame, keyed by epoch rather than top-of-stack, so a superseded zombie aborts while a healthy same-process re-claim keeps running.
- **Poll-liveness** (#1253) — an epoch-valid executor `recvEvent` poll extends the lease (capped by `total_deadline` and the `max_duration`-derived stale ceiling, preserving #1244 semantics). A handler legitimately blocked in an event gate is no longer reclaimed as wedged, so artificial `progress()` keepalives are unnecessary. The long-poll races the cancellation token, so user cancels and supersession interrupt a blocked gate promptly.
- **Per-filter event cursors** (#1254) — `recvEvent` tracks an independent cursor per canonical type-filter (exactly-once within a stream, documented at-least-once across streams), so interleaved gates with different filters can no longer permanently skip each other's events; per-filter locks replace the global receive lock, so a long-poll on one type doesn't block another.
- **Surfaces** — `claimEpoch` is exposed read-only on `JobContext` in Python, TypeScript, and Java, threaded claim→controller through the shared Rust core. A new `uc33_meshjob_replicas` integration suite proves poll-liveness (a quietly-gating handler polling through 2× its lease window keeps a single claim) and fencing (a wedged handler is re-claimed with the stale owner fenced, exactly one surviving owner). Jobs man pages (base + TS/Java), `environment.md`, and `docs/concepts/jobs.md` now document lease derivation, what renews a lease, epoch fencing, per-filter cursor semantics, and the reap-ceiling-vs-lease-window distinction.

### 🔁 Empty tool returns round-trip exactly (#1251)

An empty collection return (`[]` / `{}` / `""` / `null` / non-empty values) now round-trips byte-for-byte across every Python-provider × {Python, TypeScript, Java}-consumer pairing. The root cause was Python-side: FastMCP serialized an empty list/tuple to an MCP content array byte-identical to `None`, so consumers received `null` / `""` / exceptions instead of `[]`. Mesh now patches tool components at a registration chokepoint (covering dynamic/post-startup registrations, drift-hardened with pass-through and warn-once fallbacks) so empty collections emit a real `"[]"` text block while `None` is untouched. Consumers recover from `structuredContent` when content is empty, else resolve to `null` — never a misparsed envelope. A new `uc32_empty_return_values` suite pins the exact received values.

- **Java: untyped tool calls parse generically** — `McpMeshTool<Object>` and undeclared targets parse JSON results via one shared `deserializeDynamic` (objects → `Map`, arrays → `List`, scalars boxed, empty → `""`); typed targets keep strict deserialization and still fail loudly on shape mismatch.
- **Java: proxy cache keys on declared return type** — each declared type gets its own cached proxy (`null` and `Object` share the dynamic key), fixing a race where two consumers with different type params could resolve run-to-run differently under load.
- **Java spring-ai: the tool executor serializes non-string results as JSON** instead of `toString()`, which had mangled arrays/objects fed back to the LLM.

### 🧾 LLM reply envelope always carries the answer as a string (#1248)

The `@mesh.llm` `{role, content}` reply envelope now always carries the answer as a JSON string. On the Python structured-output path the answer is recovered from `message.parsed` / `provider_specific_fields` when the text-block join is empty (upstream client libraries move structured output between text blocks, tool-call arguments, and parsed fields across versions), and a warning naming model, mode, and a truncated raw message fires when nothing is recoverable instead of silently emitting empty content. The OpenAI native adapter recovers a `parsed`-only response only when the message has no tool calls, so content is never fabricated on an ordinary tool-call turn and replayed assistant history is byte-for-byte unchanged. As defense in depth, consumers across all three runtimes serialize dict/Map-shaped content and recover a bare envelope-less map as the answer (excluding maps carrying a truthy `error`, `tool_calls`, or `_mesh_usage`, which stay on the diagnostic path), with empty-content parse failures now including a truncated snippet of the raw provider payload.

### ⚠️ Breaking / behavior changes

- **Java: untyped tool calls parse JSON results generically** (#1251). `McpMeshTool<Object>` and undeclared targets now parse objects → `Map`, arrays → `List`, and JSON scalars → boxed values; non-JSON text is returned as-is and an empty result round-trips to `""`. Previously only JSON objects were parsed and arrays/scalars came back as raw JSON strings. Typed targets (`List` / `Map` / POJO) are unaffected.
- **TypeScript: `callMcpTool` / `extractContent` now return `unknown`** (#1251), was `string | MultiContentResult`, and an empty tool-result content array resolves to `null` instead of `""`. Consumers that assumed a string return must narrow the type.
- **Interactive MeshJobs: `recvEvent` polling now renews the lease** (#1253). A handler blocked in an event gate keeps its claim as long as it keeps polling, so artificial `progress()` keepalives added only to hold a lease can be removed. Declaring `max_duration` remains recommended for lease sizing.

### ⚠️ Upgrade notes

- **Mixed-version meshes degrade gracefully.** The `required` flag is ignored by registries that predate #1255 (capabilities read as available, exactly as before), and old SDKs are unaffected by a new registry — `claimEpoch` / availability fields are additive, and epoch-less deltas keep legacy ownership semantics. No coordinated upgrade is required; adopt `required=true` once both ends are on v2.8.0.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.6.0...v2.7.0)

## v2.7.0 (2026-07-01)

Correct LLM-provider behavior for the newest OpenAI models across every runtime, proactive MeshJob reaping with a human-in-the-loop input primitive, and observability parity.

v2.6 sharpened dependency resolution and brought Java's `@mesh.llm` to parity; v2.7 makes the provider layer *correct* for OpenAI's reasoning and gpt-5 models — which reject the sampling parameters and `max_tokens` field earlier models accept — and does it identically across Java, Python, and TypeScript. Alongside, MeshJob gains a proactive stale-job sweep and a `request_input()` primitive for human-in-the-loop pauses, and two long-standing observability gaps close: LLM token-usage telemetry now emits from Java and TypeScript consumers, and the dashboard's Traffic view gains a time-range filter.

### 🤖 Reasoning- and gpt-5-model provider correctness (#1240, #1241, #1242, #1243, #1237, #1239)

OpenAI's o-series (o1/o3/o4) and gpt-5 models reject `temperature`/`top_p` other than the default and reject the deprecated `max_tokens` field — so a provider that forwarded consumer `model_params` verbatim failed every call against those models. All three runtimes now gate these parameters against the effective model, using one identical classifier (o1/o3/o4 and `gpt-5*` except `gpt-5-chat*`), verified against the live API.

- **Sampling-param gating** — `temperature`/`top_p` are omitted (with a runtime warning, soft-fail) for restricted models and applied unchanged for every other model and vendor. Java (#1240) and Python (#1241) gate in-tree; TypeScript (#1243) gates at the mesh layer so it no longer depends on the vendor SDK version to strip them.
- **`max_tokens` → `max_completion_tokens`** — restricted OpenAI models require the newer field. Java always emits `max_completion_tokens` (#1239); Python translates a supplied `max_tokens` on both the native-SDK and LiteLLM paths (#1242); TypeScript's `maxOutputTokens` abstraction already maps correctly per model.
- **Java providers now honor their declared model** (#1240) — the handlers only ever set the request model on a per-call override, so a provider declaring `@MeshLlmProvider(model="openai/gpt-4o")` silently ran on the framework's default model instead. The declared model is now applied on every request across the OpenAI, Gemini, and Anthropic handlers, which also makes per-vendor multi-model providers work.
- **Vendor errors are no longer swallowed** (#1237) — a failed Java generation surfaced as the opaque `Error: LLM generation failed`; the underlying vendor error (status and message) now propagates to the caller instead of being logged and discarded, so provider failures are diagnosable.

### ⏸️ MeshJob stale-job reaping + `request_input()` (#1234, #1244)

MeshJob gains proactive lifecycle recovery and a human-in-the-loop primitive.

- **Proactive stale-job reaping** — abandoned or orphaned jobs (owner gone, or stuck non-terminal) no longer accumulate against constrained producers. A background sweep fails jobs that exceed a default total-runtime ceiling and posts a synthetic `stale` event so a handler parked on `recv_event(["stale"])` observes the reaping. Opt-in via **`MCP_MESH_JOB_STALE_TIMEOUT`** (a duration, default off), applied only to jobs that set no explicit `total_deadline`.
- **The ceiling honors a job's `max_duration`** (#1244) — the effective ceiling is `max(MCP_MESH_JOB_STALE_TIMEOUT, max_duration)`, so a job that declared a long per-attempt duration is never reaped before it elapses. `total_deadline` remains the full opt-out.
- **`request_input()`** — a new cross-runtime SDK primitive (Python, TypeScript, Java) that transitions a running job to `input_required` and parks it for a consumer answer via `recv_event`, giving MeshJob handlers a first-class human-in-the-loop pause. The registry reclaims a parked job whose lease lapses just like a working one.

### 📊 LLM token-usage telemetry parity (#1232)

Java and TypeScript `@mesh.llm` consumers now stamp LLM token-usage metrics (`llm_input_tokens` / `llm_output_tokens` / `llm_total_tokens` / `llm_model`) onto the consumer span, so the dashboard's "Token Usage by Model" panel and per-agent Tokens In/Out populate for Java- and TypeScript-consumer apps as they already did for Python. Both runtimes were extracting usage internally but never publishing it to a span.

### 🧩 Java structured-output schema + wiring diagnostics (#1233)

- **Closed/required response-model schema** — a Java `@mesh.llm` response-model record derived a loose (nullable-by-default) schema, so a vendor could silently drop fields. The schema is now closed and required-unless-`Optional`, matching the typed-consumer contract.
- **Unwired-slot warning** — an unresolved MeshJob submitter / dependency slot ("N/N resolved" is not the same as injected) now warns at runtime, surfacing a silently-null slot instead of failing opaquely at call time.

### 📈 Traffic time-range filter (#1245)

The dashboard's Traffic page gains a **1h / 1d / All** segmented control. Per-edge and per-agent aggregates for a bounded window are computed on demand by re-reading the timestamped `mesh:trace` stream (tail-first, bounded), so a window scopes the whole page — summary cards, per-edge table, and token/model stats — rather than only ever showing all-time counters. Windowed accuracy is bounded by `MCP_MESH_TRACE_RETENTION`; a window that exceeds the read cap is flagged as partial.

### 🧹 `meshctl list` down-agent retention (#1226)

A down agent with no unresolved dependents no longer lingers as an alarming red row — the registry retires it from the health-relevant view once nothing depends on it, so `meshctl list` reflects the live topology instead of stale down-agent noise.

### 📦 MCP SDK bumps (#1235)

- **Java MCP SDK 1.1.0 → 1.1.3** — maintenance/security patch (SSE-client transport validation, HTTP 405 handling); no breaking changes.
- **TypeScript `fastmcp` v3 → v4** — the v4 line; the sole v4 breaking change (an `OAuthProxy` redirect-URI default) does not apply to the mesh runtime.

### ⚠️ Upgrade notes

**LLM providers:**

- **Java LLM providers now use their declared model** (#1240). A provider that declared a model but unknowingly relied on the framework default now issues requests against the declared model. If a provider was implicitly running on the default, its effective model changes to what it declared — set `@MeshLlmProvider(model=...)` to the intended model.
- **Reasoning / gpt-5 models: `temperature`/`top_p` are omitted** (#1240, #1241, #1243) with a warning when a consumer sets them against an o-series or non-chat gpt-5 model (those models reject non-default values). Behavior for every other model is unchanged.

**MeshJob:**

- **`MCP_MESH_JOB_STALE_TIMEOUT` is opt-in and off by default** (#1234). When set, non-terminal jobs with no `total_deadline` that exceed `max(stale_timeout, max_duration)` are failed with a `stale:` reason. Give a long job an explicit `total_deadline` to opt out entirely, or size `max_duration` to its real runtime (#1244).

**MCP SDKs:**

- **TypeScript `fastmcp` is now v4** (#1235). If you import `OAuthProxy` directly, note v4 no longer defaults `allowedRedirectUriPatterns`; the mesh runtime itself is unaffected.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.5.0...v2.6.0)

## v2.6.0 (2026-06-29)

Capability-aware version resolution, and Java reaches feature parity with Python on the MeshJob and `@mesh.llm` contracts.

v2.5 hardened the platform; v2.6 sharpens two contracts. The registry now resolves a dependency to the **highest version** that satisfies the consumer's constraint — turning the `version` field from an undefined tiebreaker into a real, semver-aware selector. Alongside it, the Java runtime closes its remaining gaps with Python: a `task=true` MeshJob producer can now declare cross-agent dependencies, and `@mesh.llm` consumers gain per-tool model override with full `model_params` passthrough to the vendor call.

### 🎯 Highest-satisfying-version resolution (#1219)

Dependency and `@mesh.llm` provider resolution previously picked a winner by tag-match score only; the `version` constraint was applied as a hard filter but never influenced selection, so ties fell to registration order — effectively undefined. Resolution now selects deterministically by **tag score, then highest semver version, then agent id**: among providers that match capability and tags, the newest satisfying version wins.

- **`version` is a real semver constraint** (Masterminds/semver). A bare `"4.6.0"` is **exact** — consistent with how `capability` and `tags` match — while `">=4.6.0"`, `"^4.6.0"` (newest within the major), and `"~4.6.0"` (newest within the minor) opt into bounded floating. An omitted version matches any and takes the highest available.
- **Both resolution paths** — regular `@mesh.tool` dependencies and the `@mesh.llm` provider selector — share one comparator in the registry. No protocol or registration change; resolution is the shared control plane across all runtimes.
- **Upgrade note:** deployments running multiple providers of the same capability and tags at different versions that (unknowingly) relied on registration-order ties now resolve deterministically to the highest version. This is strictly more predictable; pin an exact `version` on the consumer to hold a specific provider.

### ☕ Java MeshJob + dependency-injection parity (#1221)

Java's MeshJob producer claim path was a thin reflection invoker that diverged from Python and TypeScript, whose claim path runs the full DI-wrapped handler. Three related gaps are closed so a Java agent behaves like its Python equivalent:

- **`task=true` producers can now declare `McpMeshTool`/`MeshLlmAgent` dependencies.** The claim path delegates argument-building to the resolved tool wrapper, so dependencies, LLM agents, A2A bindings, and settle-grace are injected on the claim path exactly as on the inbound path; the startup guard that rejected this combination is removed. Cancellation still aborts the injected proxy's in-flight outbound calls.
- **The consumer `MeshJobSubmitter`** is now bound off the declared dependency selector, so a remote `task=true` capability mixed with other dependencies resolves a submitter instead of silently leaving the slot null.
- **`@MeshDependsOn`-injected `@Service`/`@Component` beans** receive the same bounded settle-grace as the inbound path — a bean that calls its injected proxy during startup waits for resolution instead of throwing on a cold start.

### 🎛️ Java `@mesh.llm` model control (#1222)

The Java `@mesh.llm` surface reaches parity with Python on model selection and tuning:

- **Per-tool / per-call model override** — `@MeshLlm(model = "...")` overrides the provider's default model, carried via `model_params`. The provider honors it only when the vendor matches its own (warn and fall back otherwise); a per-call override wins over the annotation.
- **`model_params` now reach the vendor call** — `max_tokens`, `temperature`, `top_p`, and the model override are applied to the per-vendor Spring AI `ChatOptions` across the Anthropic, OpenAI, and Gemini handlers (Gemini maps `max_tokens` to `maxOutputTokens`), on the tools, structured-output, retry, and plain-text paths. The consumer previously put these on the wire but the provider dropped them.
- The v2-removed direct-LLM mode (a local API key on `@MeshLlm`) is fully retired from the Java docs; thinking/reasoning configuration continues to flow through the `model_params` escape hatch.

> **Streaming production remains a known gap on the Java runtime** (#1223): a Java agent can consume a stream but cannot yet *produce* one — there is no streaming `@MeshTool` or `@MeshLlmProvider` — because the stateless MCP transport cannot emit progress notifications. Tracked for a future release.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.4.0...v2.5.0)

## v2.5.0 (2026-06-12)

Operational hardening across the whole stack — settling-window dependency grace, a coordinated five-codebase audit, and Helm chart maturity.

v2.4 matured the `@mesh.llm` contract; v2.5 hardens the platform around it. The headline is the settling-window dependency grace: calls arriving during agent startup wait for topology to settle instead of failing instantly on a not-yet-resolved dependency — across all three runtimes. Around it, a coordinated audit of all five codebases (Python, TypeScript, Java, Rust core, Go registry/CLI) closed a long tail of concurrency, lifecycle, and observability holes, and a five-part Helm batch brings the charts to a production baseline: generated credentials, Pod Security Standards `restricted`, global datastore config, and air-gapped installs.

### ⏳ Settling-window dependency grace (#1200, #1212)

A call arriving while an agent's topology is still settling no longer fails instantly on a declared-but-unresolved dependency. The DI wrapper waits — event-driven, bounded by the remaining settle window — for the dependency to resolve, then proceeds with the real proxy; on budget expiry it proceeds with `None`/null **exactly as before**. User code never observes a pending state: parameters stay binary (real proxy or `None`), so the defensive `if dep:` idiom is untouched.

- **`MCP_MESH_SETTLE_TIMEOUT`** (float seconds, default `20`, `0` disables) bounds the window. The agent is unsettled from the first dependency declaration until all declared deps have resolved once or the window expires — then permanently settled: zero steady-state overhead and byte-identical fail-fast behavior after startup.
- **All three runtimes**, each in native idiom: Python per-dep `threading.Event` + loop-native `asyncio.Event` mirrors; TypeScript per-dep deferred promises with unref'd timers across tool, route, and claim-handler paths; Java per-consumer-slot latches.
- **Streaming paths hold the grace too** (#1212): Python `@mesh.route` streaming routes now build their SSE endpoint at decoration time (like non-streaming routes always did), eliminating a startup-ordering window where an early request could hit the plain wrapper and 500. Unsupported stream element annotations (e.g. `Stream[bytes]` — async iterators over non-`str`) now fail at decoration with a clear error instead of silently becoming a buffered non-streaming route.
- **Caller-supplied deps never wait** (the documented mock contract) — and TypeScript's `setMockDependency` is now actually implemented (it had been documented but absent from the SDK).
- Also fixed en route (#1200): a pre-existing Java injection corruption where a MeshJob-first dependency list wrote the job proxy into the wrong slot.

### 🔬 Prescriptive DI diagnostics + opt-in strict mode (#1199, Python)

DI keeps its permissive posture (soft-fail, warn, life goes on) — but the warnings now teach: every ambiguous or skipped injection configuration warns with what positional pairing selected, each skipped parameter with its resolved-type reason, and a copy-pasteable fix. **`MCP_MESH_STRICT_DI=true`** promotes exactly that ambiguity/skip class to a `StrictDIError` at decoration/startup time for teams that want rigor. Injection semantics are byte-identical in both modes — pairing is by declaration order, never by parameter name.

### 🧹 Automatic trace retention (#1216)

The `mesh:trace` Redis stream no longer grows unboundedly (the docs previously told operators to run manual `XTRIM`). **`MCP_MESH_TRACE_RETENTION`** (duration, default `24h`, `0` disables) drives a time-based trim on every consumer (re)connect — a registry returning from an outage immediately shears the backlog — and every 5 minutes thereafter. The correlator's completed-trace buffer is now age-bounded with the same duration. Exposed in Helm as `registry.observability.distributedTracing.retention`. The stream is a transport buffer; long-term queryable history remains Tempo's retention.

### 📋 `meshctl list` supersession view (#1198)

Watch-driven dev loops re-register agents under new instance ids, and the lingering prior instances read as alarming noise. `meshctl list` now shows one row per declared agent name: superseded instances collapse into a dim `(+N superseded)` suffix, the registry header splits its count (`3 healthy, 1 unhealthy, 2 superseded`), and genuinely-down agents surface via a red footer clause (`1 agent down (use --all)`). A down instance whose capability blocks a live agent's unresolved dependency is promoted to a named red row. The grep contract is preserved — default rows remain healthy-only — and `--json` output is unchanged in both modes.

### ⎈ Helm chart maturity (#1184, #1185, #1187–#1190, #1192)

A five-part batch bringing all nine charts to a production baseline. Default renders are byte-identical except where called out in the upgrade notes.

- **Single registry Redis endpoint + external-datastore TLS/auth** (#1184): `registry.redis.{host,port,password,existingSecret,tls}` is the one source (the trace stream shares it by construction); `registry.database.sslmode` with optional CA secret, URL-encoded DSN userinfo, `rediss://` with auth. Also fixes `registry.database.existingSecret`, which previously set env vars the binary never read and silently fell back to ephemeral sqlite.
- **Global datastores** (#1185): `global.postgres.*` / `global.redis.*` declared once, inherited by registry, UI, and agent charts with explicit > global > default precedence; template-time guards reject impossible combos (e.g. credentials on the bundled no-AUTH redis).
- **Generated credentials** (#1187): no chart renders a known weak password by default. Bundled postgres generates a `<fullname>-credentials` secret (lookup-reuse across upgrades, kept on uninstall); Grafana gets a chart-owned generated admin secret; `existingSecret` is supported everywhere; NOTES print the retrieval commands.
- **Pod Security Standards `restricted`** (#1188): all charts pass `restricted` by default, validated against a live enforcing namespace — non-root postgres, `readOnlyRootFilesystem` wherever feasible, seccomp + dropped capabilities. Enforced going forward by `scripts/check_helm_pss.py` in CI. Also fixes the agent's pod `securityContext`, which was gated behind the long-removed PSP flag and never rendered.
- **Air-gap + registry HA** (#1189): `global.imageRegistry` prefixes all 8 image references (including the previously hardcoded busybox init image); `global.imagePullSecrets` merges into every pod spec; registry gains topology spread defaults and a render-gated PodDisruptionBudget; HPA or `replicaCount > 1` with sqlite fails at template time.
- **Dead-config cleanup with guarded removals** (#1190, #1192): keys that silently no-op'd are removed; user-set values for removed keys fail the render with a migration message, while values files copied from old shipped defaults render clean. The registry TLS example's values nesting is fixed (it was silently ignored by the umbrella) and `security.tls.secretName` is the consumed key.

### 🛡️ Cross-runtime audit fixes

A coordinated audit across all five codebases (#1162–#1166), each area closed by an independently reviewed PR, plus adjacent fixes from the same campaign.

- **MeshJob lease enforcement** (#1168, registry): `lease_expires_at` was written at claim time but never read — a wedged handler kept a job in `working` forever. Expired-lease jobs are now reclaimed (reset while attempts remain, else failed), and every accepted non-terminal delta extends the lease by the claim window, with guarded updates so a delta racing a reclaim cannot extend a lease the instance no longer holds.
- **Phantom ports eliminated** (#1197, all runtimes): no runtime registers a port it did not bind and prove it can serve. Python pre-binds the server socket before the heartbeat starts and falls back to a kernel-assigned port on conflict (previously a port conflict produced a permanently-registered phantom endpoint); TypeScript resolves a bindable port before registration; Java's already-correct convergence is pinned by test.
- **Go registry/CLI** (#1177): health-monitor unhealthy transitions use guarded conditional updates so a concurrent heartbeat wins instead of being overwritten; dependency-resolution rows flip to `unavailable` immediately on provider unregister/unhealthy (previously up to 1h stale); the registry `/proxy/*` now streams bodies with per-chunk flush — **SSE through the registry proxy works**; `meshctl logs -f` survives log rotation.
- **Python** (#1171, #1172): positional injection reads the original-function signature consistently, fixing `IndexError`/wrong-parameter injection under decorators that hide params via `__signature__` rewrite; `@mesh.llm` `max_iterations` is call-local (concurrent calls no longer reset each other's counter); one rich `ResponseParseError` class; claim dispatchers drain concurrently under a shared 30s budget and a drain timeout can never skip registry cleanup.
- **TypeScript** (#1169, #1170, #1174, #1182, #1214): AI SDK v6 removed `maxSteps`, silently capping mesh-delegated tool loops at one step — `stopWhen(stepCountIs(n))` restores `max_iterations`; producer tool failures on SSE and streaming transports now surface as errors instead of arriving as successful string results; mesh event loops survive transient errors with bounded backoff instead of freezing topology on first failure; SIGINT/SIGTERM run full shutdown under one shared drain budget; `vertex_ai` providers honor the canonical `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` contract; `callMcpTool` publishes one span per call (was N+1 across retries), with a `call_attempts` field on retried calls.
- **Java** (#1157, #1167, #1175, #1183): dependency tags serialize as a JSON array in the route/A2A/`@MeshDependsOn` paths — the comma-joined form silently dropped all tag constraints; heartbeat and MCP-served schemas build through one shared path, so structured params publish full schemas instead of bare `{"type":"object"}` stubs; AOP-proxied (`@Transactional`/`@Async`) `@MeshLlm` beans no longer lose their provider binding; async tools honor the propagated `X-Mesh-Timeout` budget and carry trace context to pool threads; named `@MeshRoute` agents report `agent_type=api`; `MeshHandle` drains in-flight native calls before freeing.
- **Rust core** (#1178): shutdown can no longer be swallowed during reconnect backoff (a signal arriving mid-backoff previously left the agent re-registered and running forever); the trace publisher pools its Redis connection and the C-ABI publish honors its non-blocking contract with a final flush on clean shutdown; the cancel registry is redesigned as generation-tagged frames per job id, fixing waiter wake-loss on re-registration; four pyo3 paths that ran I/O with the GIL held are fixed.

### 📡 SSE timeout surfacing (#1203)

A `meshctl call` cut by its `X-Mesh-Timeout` budget mid-SSE previously printed a bare keepalive comment as the result with exit 0. meshctl now skips comment frames and errors structurally — timeout-shaped (naming the budget and the `--timeout` remedy) or protocol-shaped. The registry proxy appends a spec-compliant `: mesh-proxy-timeout budget=Ns` comment frame to SSE streams it cuts — the only in-band terminal signal possible once chunked headers are out — and the TypeScript runtime recognizes the marker, throwing a dedicated non-retried `ProxyTimeoutError`. Python's Rust-backed parser was verified already safe.

### ⚠️ Upgrade notes

**Helm:**

- **≤2.4.0 default installs with bundled postgres** (#1187): PGDATA was initialized with the old default password; upgrading with defaults generates a non-matching secret. Migration is documented in the core chart README — pin `global.postgres.password` to the old value then rotate, or reset the volume.
- **Grafana with persistence** (default on, #1187): the old `admin` password stays live after upgrade (Grafana applies the env only at first start); reset via `grafana-cli admin reset-admin-password` — NOTES carry the caveat.
- `helm template | kubectl apply` pipelines regenerate the random secrets on each render — `helm install/upgrade` is the supported path (#1187).
- Setting `distributedTracing.redisUrl` (previously inert — no template ever consumed it) now fails the render with a migration message pointing at `registry.redis.*` (#1184).
- Removed keys are guarded with shipped-default tolerance (#1190): values files copied from old shipped defaults render clean; a user-set divergent value fails loudly naming the key. Grafana/tempo `securityContext` overrides carrying pod-level fields fail with a `podSecurityContext` rename message (#1188); `security.tls.existingSecret` fails pointing at the consumed `secretName` key (#1192).
- `registry.database.existingSecret` installs that were silently running sqlite will connect to the configured Postgres after upgrade (#1184).
- `distributedTracing.enabled: false` now actually renders `"false"` — a falsy-default bug previously inverted it to `"true"` (#1216).
- `replicaCount > 1` registries gain a PodDisruptionBudget on upgrade; already-broken sqlite + multi-replica topologies now fail at template time instead of corrupting silently (#1189).

**Runtime / registry:**

- **Trace stream entries older than 24h are trimmed by default** (#1216). Set `MCP_MESH_TRACE_RETENTION=0` (or Helm `retention: "0"`) for the previous keep-forever behavior.
- **MeshJob silent handlers are reclaimed** (#1168): a handler that posts no progress within the lease window (default 300s when no `max_duration` is set) is reclaimed and re-executed where it previously ran unbounded. Post progress within the window or size `max_duration` accordingly.
- **Calls during agent startup may wait** (#1200): up to the 20s settle window before degrading to `None`. `MCP_MESH_SETTLE_TIMEOUT=0` restores instant fail-fast.
- **TypeScript call timeout is end-to-end** (#1174): `callMcpTool`'s deadline now includes the body read (previously it effectively covered only time-to-headers). Tools needing longer than the 30s default should pass an explicit timeout / `X-Mesh-Timeout`.
- **Streamed exchanges through the registry proxy are bounded** by `X-Mesh-Timeout` / the 60s default (#1177) — previously long streams were buffered then failed entirely, so this is strictly better, but the cap is newly visible. Timeout-cut `meshctl call` SSE streams now exit non-zero (#1203).
- **Java `input_schema_hash` changes** for every tool with structured/collection params on next deploy — the schemas now represent what is actually served (#1175). Pipelines snapshotting heartbeat hashes need a refresh.
- **Duplicate `@MeshTool` capability is a boot error** (Java, #1175) instead of silent last-wins; inheritance/interface/bridge patterns register exactly once and are unaffected.
- **Python streaming routes validate at decoration** (#1212): async-iterator return annotations over a non-`str` element type (e.g. `Stream[bytes]`) fail decoration instead of silently becoming buffered non-streaming routes.
- **Hidden-wrapper untyped params no longer receive injection** (Python, #1171): a `@mesh.a2a_consumer` over a single untyped user param previously received the proxy via a heuristic that only worked by accident. Injection eligibility requires the `McpMeshTool` annotation; pairing stays positional.
- **`meshctl list` default view changes** (#1198): superseded-instance suffix, down-agent footer, split header counts. `--json` output is unchanged.

### 🧪 Tests & infrastructure

- **Integration suites migrated to settle-window reliance** (#1205, #1209, #1211, #1212): 276 dependency-resolution wait steps removed across ~174 files; every integration test now exercises the cold-start DI path production actually sees, with per-UC runtimes dropping 30–45% where dep-sleeps dominated. Shared calculator fixtures now publish the capabilities consumers declare (one suite's "cross-agent call" test had never actually crossed agents).
- **Image build hardening** (#1209, #1211): transient cargo failures during the Java FFI build could ship an image with an empty native-libs dir on a green run — the build now fails loudly; npm installs gain retry config baked into the test image.
- **PSS CI gate** (#1188): `scripts/check_helm_pss.py` runs next to helm lint in the release workflow.
- **Deflaked** kill-verify reap races and a claim-dispatcher DNS dependency (#1180); a cross-runtime cancel-claim fixture race fixed in all three runtimes (#1211).

---

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.3.0...v2.4.0)

## v2.4.0 (2026-06-04)

LLM contract maturity across the polyglot trilogy — `response_model`, server-enforced structured output, and Java `@mesh.llm` parity.

v2.3 completed the MeshJob lifecycle surface; v2.4 turns to the `@mesh.llm` contract. The schema the model is asked to emit is now cleanly separable from a tool's own return type, structured output is enforced natively by the provider instead of a brittle re-prompt fallback, and Java's `@mesh.llm` reaches feature parity with Python and TypeScript. Spring users also gain richer dependency injection.

### 🧬 `response_model` on `@mesh.llm` (#1096, #1097, #1098)

Separate the structured shape the LLM produces from the tool's declared output type. Python `@mesh.llm(..., response_model=Model)` and TypeScript `responseModel:` land the feature; the Java response-model-vs-tool-output separation is documented for the upcoming SDK port.

### 🔒 Server-enforced structured output (#1100, #1101, #1102, #1103, #1107)

A version-aware provider capability registry dispatches each request to the right native primitive instead of a generic fallback path. Claude streaming honors a server-enforced `output_config`, and Gemini 3 uses native structured output even alongside tool calls (default-ON) — removing the re-prompt round-trips the generic path required.

### ☕ Java `@mesh.llm` parity (#1118, #1139, #1140, #1143)

Java's `@mesh.llm` aligns with the Python/TS contract: nested response-model schemas (via victools with a `$ref` inliner), consumer `output_mode` override, empty-`@MeshLlmProvider` default tags, and exposed A2A polling knobs.

### 🌱 Spring dependency injection (#1087, #1090, #1091)

`@MeshDependsOn` enables component-level mesh DI, `@MeshRoute` / `@MeshA2A` capabilities support constructor injection, and schema-matching now applies to `@MeshA2A` dependencies.

### 🛡️ Resilience, CLI & dashboard

- **Registry outages no longer drop resolved dependencies** (#1145). The registry is the control plane; already-resolved agent→agent endpoints are the data plane and stay live through a registry blip, refreshing on reconnect only if their hash changed — consistent across all runtimes.
- **`meshctl call` gains `--header` / `-H`** for custom request headers (#1099).
- **Accurate MeshJob badge** (#1147): the dashboard now keys on the real `task=True` capability flag instead of the framework job-control tools present on every agent, so only true job producers are tagged. Ships with grid-view default and sidebar polish.
- **Rust core**: reconnect-backoff jitter avoids thundering-herd reconnects, and job serialization is unified across language bindings (#1119, #1120).

### 🧹 Internals

Extensive cross-runtime refactoring — provider-handler consolidation, agentic-loop extraction, and registry / meshctl dedup (#1113–#1117) — plus typed heartbeat kwargs and hardened DI diagnostics (#1105, #1111). No user-facing behavior change.

---

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.2.4...v2.3.0)

## v2.3.0 (2026-05-23)

Lifecycle facades across the polyglot trilogy + unified dependency-injection contract.

v2.2 introduced the MeshJob substrate; v2.3 completes the lifecycle surface so callers that hold only a `job_id` can drive cancel / status / wait through DDDI-clean module-level facades — the same shape `post_event` and `subscribe_events` already had. The DI rules for `McpMeshTool` and `MeshJob` parameters are unified under a single positional contract, eliminating a silent wrong-proxy footgun when both types appeared in the same tool.

### 🪢 Lifecycle facades by `job_id` (#1074, #1077, #1078, #1079, #1080, #1081)

Three new facades on every runtime's `mesh.jobs` / `MeshJobs` surface. The underlying `JobProxy.cancel/status/wait` instance methods were already exposed in v2.2; this release adds the DDDI-clean module-level wrappers that resolve the registry URL internally — no more `JobProxy(jobId, registryUrl)` plumbing in user code.

| Operation                | Python                                             | TypeScript                                       | Java                                          |
| ------------------------ | -------------------------------------------------- | ------------------------------------------------ | --------------------------------------------- |
| Cancel a running job     | `await mesh.jobs.cancel(job_id, reason=None)`      | `await mesh.jobs.cancel(jobId, reason?)`         | `MeshJobs.cancel(jobId[, reason])`            |
| Read latest job state    | `await mesh.jobs.status(job_id)`                   | `await mesh.jobs.status(jobId)`                  | `MeshJobs.status(jobId)`                      |
| Wait for terminal state  | `await mesh.jobs.wait(job_id, timeout_secs=None)`  | `await mesh.jobs.wait(jobId, timeoutSecs?)`      | `MeshJobs.await(jobId[, timeoutSecs])`        |

- **Java naming nuance**: the static facade is `MeshJobs.await` (not `wait`) to avoid readability confusion with the inherited `Object.wait()` overload family, and to match the existing `JobProxy.await(double)` instance method precedent.
- **TS adds** a typed `JobStatus` interface alongside `JobEvent` / `JobEventReceipt`, exported from `mesh.jobs`. Fields mirror `job_to_json` in `jobs_napi.rs`: required fields typed `T`, `Option<T>` fields emitted as `T | null` — every key always present, no key-presence checks needed.
- **Typed errors** (`JobNotFoundError`, `JobTerminalError`) translate consistently across all three runtimes via substring-based dispatch from the underlying runtime exception.

### ⚙️ Unified positional dependency injection (#1075, #1082, **Python only**)

`McpMeshTool` and `MeshJob` parameters now share a **single positional `dep_index` namespace** in parameter declaration order. Each `dependencies[i]` strictly pairs with one parameter position; the slot's type determines what gets constructed (`MeshJobSubmitter` vs `McpMeshTool` proxy). Previously, the two types had inconsistent injection rules (positional for `McpMeshTool`, by-name for `MeshJob`), which produced wrong-proxy injection when both appeared in the same tool with `MeshJob` listed first in `dependencies[]`.

- **Free-form parameter names work**: a `MeshJob` parameter named `workflow` with `dependencies=[{"capability": "run_my_thing"}]` now resolves to `MeshJobSubmitter(capability="run_my_thing")`. Param names no longer need to match capability names byte-for-byte.
- **Unresolved-dependency invariant**: if `dependencies[i]` cannot be resolved at injection time, the corresponding parameter slot stays `None` — positions do NOT shift to fill the gap.
- **Behavior change to be aware of**: users who deliberately wrote `MeshJob` parameters out-of-order with their `dependencies[]` array (relying on the previous by-name resolution) now need to put params in the same order as deps. The natural same-order case continues to work unchanged.

The contract is documented end-to-end in `MESHJOB_DDDI_CONTRACT.md`. TypeScript and Java SDK DI paths still follow the orthogonal injection contract; their port to the unified positional rule is tracked separately.

### 🩺 `health_check_ttl` refresh on the user loop (#1072, #1073)

`@mesh.agent(health_check=fn, health_check_ttl=N)` now actually refreshes every N seconds. Previously, `update_health_result()` fired exactly once at startup and the stored result was served forever — a failed check during the startup window (e.g., racing with `lifespan`) cached as unhealthy and permanently failed the k8s readiness probe.

The refresh loop runs on the user loop (same loop as `lifespan` and tools, per the v2.2.4 architecture) so health checks that touch loop-bound resources (`asyncpg.Pool`, `redis.asyncio.Redis`, etc.) work correctly without cross-loop errors. A lifespan-ready signal gates the refresh start so iterations don't fire while user `__aenter__` is still mid-flight.

### 📚 FastMCP lifespan documentation correction (#1071, #1073)

The v2.2.4 "Loop topology" docs showed a FastAPI-style `app.state.pool` example — but FastMCP's lifespan callable receives a FastMCP server instance, not a FastAPI app, and there is no `.state` attribute. Examples across `docs/concepts/stateful-agents.md`, `docs/python/dependency-injection.md`, and `meshctl man dependency-injection` are rewritten to use the canonical Python pattern: a module-level global initialized in the lifespan body. Matches the working pattern in our own test fixtures.

### Internals — `user_loop_hooks` shared utility

New `src/runtime/python/_mcp_mesh/shared/user_loop_hooks.py` exposes `schedule_on_user_loop(app, user_loop, coro_factory, name=...)`, `cancel_app_user_loop_futures(app)`, and `get_or_create_lifespan_ready_future(app)` / `signal_lifespan_ready(app)` helpers. Subsystem code (e.g. the health-refresh loop) owns when to schedule; `lifespan_factory.wrap_lifespan_for_user_loop` owns cancellation on both clean and exception paths. The lifespan-ready future is `concurrent.futures.Future` (loop-agnostic), avoiding the cross-loop trap that an `asyncio.Event` would have created.

### Tests

`tests/integration/suites/uc02_agent_lifecycle/` gains `tc20_health_check_ttl_refresh` (proves the refresh actually fires; observed 5 iterations on the user loop after the seed call) and `tc21_health_check_lifespan_ready_gate` (proves no premature refresh iterations fire before `lifespan` completes startup under aggressive `health_check_ttl=1`). `test_12_dependency_injector.py` gains a `TestUnifiedPositionalInjection` class covering the mixed-type ordering matrix, unresolved-middle without shift, free-form parameter names, and the missing-`MCP_MESH_REGISTRY_URL` graceful-None fallback. Python unit suite: 1010 passing. uc02: 23/23. uc21_meshjob: 21/21. uc22_meshjob_ts: 24/24. uc23_meshjob_java: 27/27.

---

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.2.0...v2.2.4)

## v2.2.4 (2026-05-21)

Cross-loop affinity fix for v2.2 adopters using FastAPI lifespan patterns. Apps that create loop-bound resources (`asyncpg.Pool`, `redis.asyncio.Redis`, `aiohttp.ClientSession`) in `lifespan` startup and use them from tool bodies hit "Future attached to a different loop" errors in v2.2.0 — the documented `MCP_MESH_TOOL_WORKERS=1` "escape hatch" did not actually solve it. v2.2.4 fixes the topology so standard FastAPI patterns work as expected.

### 🪢 Loop topology fix (#1061)

- **Lifespan, tools, and lifespan exit now share one user loop.** Previously, `lifespan` ran on uvicorn's main loop and tools dispatched to N worker loops with their own asyncio runtimes — any loop-bound resource created in `lifespan` failed when reused from a tool body. The SDK now hijacks the composed lifespan and dispatches it to the user loop via `asyncio.run_coroutine_threadsafe` + `asyncio.wrap_future`, mirroring the pattern already used internally for cross-loop httpx-client close in `unified_mcp_proxy.close_connection_pools`.
- **`/health` / `/ready` / `/livez` remain on the framework loop**, never blocked by user-tool execution. K8s probe responsiveness during long tool calls is preserved (verified by integration test: `/health` responded in 0.958ms during a 10-second `await asyncio.sleep(10)` tool).
- **Contextvar propagation across the loop boundary** (mesh trace IDs, propagated headers) honored in the lifespan body via the same `contextvars.copy_context()` + `loop.create_task(..., context=ctx)` pattern used for tool dispatch.
- **Exception forwarding through `__aexit__`** preserves `exc_type` / `exc_val` / `exc_tb` per PEP 343, so user lifespan `finally` / except blocks see the original error if uvicorn raises during the yield.
- **Single wrap site** (`wrap_lifespan_for_user_loop()` in `lifespan_factory.py`) replaces the previous duplicate-wrap-site shape — future lifespan-related changes have one place to edit.

### ⚙️ Default worker pool size: 1 (was `min(8, max(2, cpu_count()))`)

- **Default tool dispatch now runs on a single-user loop.** Async-correct tool bodies (LLM calls, `asyncio.gather` fan-out, async DB drivers) see no throughput regression — `asyncio.gather` over 3 outbound mesh calls completes in 2.04 seconds at N=1, identical to N=8 (integration-test measured).
- **Apps with sync-blocking calls in tool bodies** (`time.sleep`, `requests.get`, CPU-bound work) that relied on `cpu_count()` worker pool absorbing concurrent load **must either**:
    - Refactor the blocking call to `await asyncio.to_thread(blocking_call)` (recommended — Python idiom; user loop stays free).
    - Or set `MCP_MESH_TOOL_WORKERS=N` (N>1) in the agent's environment to restore N worker loops. The loop-affinity caveat applies — resources created in `lifespan` startup bind to worker-0 only.
- **Apps that set `MCP_MESH_TOOL_WORKERS=1` as the documented escape hatch in v2.0/v2.1** are source-compatible in v2.2.4 — no code edits are required. The setting was previously insufficient for FastAPI `lifespan` + loop-bound resource patterns: it collapsed worker loops but did not unify the lifespan loop with the tool loop, so cross-loop errors still surfaced. v2.2.4 fixes the underlying lifespan-loop topology, so those same apps now function correctly without any changes — the previous escape hatch becomes a no-op duplication of the new default.

### 📚 Documentation

- `docs/concepts/stateful-agents.md`, `docs/python/dependency-injection.md`, `meshctl man dependency-injection` rewritten with a "Loop topology" section reflecting the new default and the FastAPI standard pattern that just works.
- `docs/environment-variables.md` updated for the new `MCP_MESH_TOOL_WORKERS` default.

### 🧪 Tests

`uc02_agent_lifecycle` gains 10 new test files (`tc12`–`tc19`, with `tc18` split into three concurrency variants `tc18a`/`tc18b`/`tc18c`) covering 8 logical scenarios that pin the loop-affinity contract — the FastAPI lifespan pattern, parallel `asyncio.gather` fan-out, lazy pool reuse, sync-blocking serialization vs opt-in N>1 recovery, exception-propagation through hijack, and `/health` responsiveness during a 10-second tool.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.1.0...v2.2.0)

## v2.2.0 (2026-05-19)

The MeshJob substrate gains a second-direction primitive: a per-job, ordered, append-only event log every running job carries, with cross-runtime parity across Python, TypeScript, and Java. Closes the sub-iteration gap left by the v2.0 progress-only surface — handlers can now drain events inline instead of polling state agents at iteration boundaries — and adds an observer iterator so multiple subscribers can mirror the same job's events independently without disturbing the producer's drain.

### 📬 MeshJob event injection (#1041, #1043, #1045)

Point-to-point: caller writes, handler drains. Same wire shape across all three runtimes; differences are limited to native idiom (async generator vs blocking `Closeable`, exception class hierarchy).

- **Static helpers for fire-and-forget posting**: `mesh.jobs.post_event(job_id, event_type, payload)` (Python), `mesh.jobs.postEvent(jobId, eventType, payload)` (TypeScript), `MeshJobs.postEvent(jobId, eventType, payload)` (Java). Each helper resolves `MCP_MESH_REGISTRY_URL` and constructs (or reuses, via the new LRU) a `JobProxy` — MCP tool bodies that hold a `job_id` no longer need a controller reference in scope to push an event into a running job.
- **In-handler drain**: producer-side `await controller.recv_event(types=[...], timeout_secs=N)` (Python) / `await controller.recvEvent([...], N)` (TypeScript) / `controller.recvEvent(List.of(...), Duration.ofSeconds(N))` (Java). Long-poll backed; returns one event dict (or `None` / null on timeout). Cursor is per-controller-instance.
- **Per-proxy send**: `proxy.send_event` / `proxy.sendEvent` is the fire-and-forget on a `JobProxy` already in scope. Same wire shape as `post_event`; use whichever surface you have.
- **Typed errors**: `JobNotFoundError` / `JobTerminalError` (Python, both subclass `RuntimeError`), `JobNotFoundError` / `JobTerminalError` (TypeScript, both extend `Error`), `JobNotFoundException` / `JobTerminalException` (Java, both extend `MeshException`). All translated from the Rust core's `JobError` variants via stable message substrings emitted by the pyo3 / napi wrappers.
- **LRU `JobProxy` cache** (256 entries by default, override via `MCP_MESH_JOBPROXY_CACHE_MAX`): the SDK caches `JobProxy` instances keyed by `(registry_url, job_id)` so steady-state senders don't pay a TCP/TLS handshake on every call. Eviction closes the native handle.
- **Synthetic cancel event with grace window**: when a consumer calls `proxy.cancel(reason)`, the registry writes `{"type": "cancelled", "payload": {"reason": "..."}}` into the job's event log before forwarding the cancel signal to the owner replica. A handler parked on `recv_event(types=["cancelled", ...])` observes the event and can return cleanly instead of being interrupted by `CancelledError`. The registry waits `MCP_MESH_CANCEL_EVENT_GRACE_MS` (default 200ms, capped at 10s) before issuing the cancel-forward so the synthetic event lands first.

### 👁️ MeshJob stream subscription (#1047, #1049, #1051)

Observer counterpart to `recv_event`: non-destructive, per-call cursor, multi-subscriber.

- **Async-iterator surface**: `async for event in mesh.jobs.subscribe_events(job_id, types=[...], after=0, long_poll_secs=30.0)` (Python async generator), `for await (const event of mesh.jobs.subscribeEvents(jobId, { types, after, longPollSecs }))` (TypeScript async generator), `try (EventSubscription sub = MeshJobs.subscribeEvents(jobId, SubscribeOptions.builder()...build())) { while (sub.hasNext()) { ... } }` (Java blocking `Closeable` iterator with try-with-resources).
- **Per-call cursor, registry-supplied watermark**: each subscription manages its own cursor — multiple subscribers can mirror the same job's events independently without affecting the producer's `recv_event` consumption. The `next_after` watermark advances even on empty pages, so a server-side `types` filter doesn't force the client to re-scan filtered ranges.
- **No automatic terminal detection**: the iterator runs until the caller breaks out of the loop or the registry raises `JobNotFoundError` / `JobNotFoundException` (job reaped). Applications signal end via a sentinel event type (e.g. `{"type": "ended"}`). This is intentional — the registry's event log is append-only, and "the job is terminal" is not the same condition as "the subscriber wants to stop."
- **Shared LRU**: `subscribe_events` and `post_event` reuse the same `JobProxy` cache, so a subscriber and a poster targeting the same job share one underlying connection pool.

### 📚 Documentation

- New "Event injection" and "Stream subscription" sections in `docs/concepts/jobs.md` with cross-runtime tabbed code examples and the synthetic-cancel-event flow.
- `docs/concepts/stateful-agents.md` — replaces the v2.0 "Coming soon" pointer to issue #1032 with a brief paragraph linking to the new sections and noting the feature is now shipped.
- `docs/environment-variables.md` + `meshctl man environment` — adds the `MCP_MESH_JOBPROXY_CACHE_MAX` and `MCP_MESH_CANCEL_EVENT_GRACE_MS` entries under a new "MeshJob event channel" section.
- `meshctl man jobs` (Python / `--typescript` / `--java` variants) — adds the same two sections to each per-runtime man page.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.0.1...v2.1.0)

## v2.1.0 (2026-05-17)

Lifecycle correctness pass plus a documentation refresh that gives stateful agents a first-class home in the docs. Three runtime fixes close lifecycle holes that have caused silent footguns since v1.4 (SIGTERM bypassing the FastAPI `lifespan` exit phase, `meshctl stop` falsely reporting "not running" while orphan descendants leak, dual `__main__`/`<module>` tool registration silently double-wiring DI). Three Java SDK enhancements extend the v2.0 native-LLM contract surface (TS/Java `modelParams` escape-hatch, Java `streamGenerate()` builder, `@MeshLlm` annotation defaults wiring). The Concepts and Reference sections gain landing pages mirroring the Tutorial pattern.

### 🛠️ Runtime lifecycle fixes

- **SIGTERM honors uvicorn graceful shutdown** (#1034): the Python runtime's signal handler short-circuited uvicorn's graceful shutdown — the FastAPI `@asynccontextmanager lifespan` exit phase never ran. User-installed `finally` blocks (asyncpg pool close, background-task drain, in-flight httpx cancel) were silently bypassed. Refactored `_start_blocking_fastapi_server` to use `uvicorn.Server` directly and registers the Server instance with `SimpleShutdownCoordinator`. Signal handler now flips `server.should_exit = True` on SIGTERM/SIGINT; uvicorn runs its normal graceful shutdown (including the lifespan exit phase) before the server thread exits. `timeout_graceful_shutdown=30` matches the sibling immediate-uvicorn site. API/A2A flows that don't own uvicorn keep the previous flag-only behavior.
- **`meshctl stop` kills orphan descendants** (#1035): when an agent's tracked parent crashed but descendants survived in the same process group (uvicorn workers, asyncio child reactors), `meshctl stop <agent>` falsely reported "agent is not running" while pgrep still found the orphans — blocking restarts via port-bind conflicts. Adds a group-aware liveness probe (`IsAliveOrGroupAlive` using POSIX `kill(-pid, 0)` with `IsAlive` fallback and `EPERM`-as-alive defensiveness) at exactly three sites: agent .pid sweep, deps refcount walk (both move in lockstep so refcounts stay synced), and `KillVerifyAndCleanup` pre-check (now three-branch: parent alive → existing dance; parent dead + group empty → cleanup; parent dead + group alive → SIGTERM-to-group + `pollUntilGroupDead` + SIGKILL escalation). Wrapper/watcher markers explicitly stay single-PID. Verified end-to-end on darwin via a real-fork test that spawns a parent with `Setpgid`, kills only the parent, and asserts the group probe differentiates orphan-alive from group-dead. Plus pid<=1 guard against `kill(-1, ...)` broadcast on a corrupted PID file.
- **Dual `__main__`/`<module>` registration detection** (#1034): when a Python mesh agent's entry script (`main.py`) is run as `python main.py` AND a sibling module does `from main import X`, Python re-evaluates `main.py` as a separate module instance (`main`) distinct from `__main__`. The `@mesh.tool` decorator fires twice, registering the tool under two fully-qualified names with independent DI state — the wrong copy silently injects `None` for every dependency. New `DualModuleCheckStep` runs after `DecoratorCollectionStep` in the startup pipeline, scans the DI registry via a new public `iter_dependency_keys()` accessor on `DependencyInjector`, and emits a framed ERROR (single `logger.error("\n".join(...))` so JSON-structured loggers render correctly) + `os._exit(1)` if any tool is registered under both `__main__.X` and `<basename>.X`. Uses `os._exit` (not `sys.exit`) because the pipeline runs from a `threading.Timer` thread where `sys.exit` is a no-op.

### 📚 Documentation: stateful agents trilogy + navigation landing pages

- **Stateful agents docs trilogy** (#1036): three layered docs that together cover the cases authors hit when building agents that hold state across multiple tool calls.
  - `docs/concepts/stateful-agents.md` — the headline tutorial. Walks the canonical decomposition: stateless state agent (CRUD over Postgres/Redis) + orchestrator agent using `@mesh.tool(task=True)` MeshJob + thin client surface. Shows the asyncpg-pool-at-module-level temptation and its cross-loop error, explains the worker pool topology, covers external events via inbox-via-state-agent polling, and points at #1032 as the v2.2 primitive for sub-iteration events.
  - `docs/python/dependency-injection.md` — new "Single-worker mode for shared loop-bound resources" section. `MCP_MESH_TOOL_WORKERS=1` trade-off table, when-to-use guidance, deployment snippets.
  - `docs/concepts/in-process-state.md` — escape hatch for cases where neither MeshJob nor `WORKERS=1` fits. Three-question gate up front so aesthetics-driven adopters bounce off; only those with real constraints (sub-10ms latency, GPU contexts, constant background work) reach the cookbook. Engine-thread pattern with caveats.
  - `meshctl man dependency-injection` gains a new "Loop topology" section between Resolution Pipeline and Declaring Dependencies.
- **Navigation landing pages** (#1036): `docs/reference/index.md` and `docs/concepts/index.md` mirror the existing `docs/tutorial/index.md` pattern. Clicking "Reference" or "Concepts" in the top tabs lands on a clean grid-card overview instead of routing to a leaf page that auto-expands its TOC and buries siblings.
- **SSE gateway shapes** (#1038): new "Don't parse `request.json()` inside an async-generator body" section in `docs/concepts/streaming.md`. Documents the upstream Starlette body-parsing race that affects any `async-gen-returning-StreamingResponse` route with `await request.json()` inside the gen body (reproduced with plain FastAPI — not a mesh defect), and shows the two safe shapes (Pydantic body model preferred, coroutine-returns-generator with `Request` if raw body parsing is required). New test class in `test_route_sse_wrapping.py` adds 4 regression-guard tests including a deadlock probe via `threading.Thread`.

### ☕ Java SDK contract polish

- **TS/Java `modelParams` escape-hatch** (#1024): cross-runtime parity for vendor-specific LLM kwargs (Gemini `thinking_config`, Anthropic `output_config`, OpenAI `reasoning_effort`). Java `GenerateBuilder.modelParams(Map)`, TS `LlmCallOptions.modelParams`. Merges into wire `model_params` before typed setters so typed setters win on collision and remain authoritative.
- **Java `streamGenerate()` builder** (#1027): adds `Flow.Publisher<String> streamGenerate()` as a terminal on `GenerateBuilder` so the streaming path gains the full builder surface (messages, typed options, `modelParams`). Existing `stream(List<Message>)` refactored to delegate to `request().messages(messages).streamGenerate()`, consolidating the model_params merge logic into a single `buildMergedModelParams()` helper shared with the buffered `executeAgenticLoop` path. Plus `@MeshLlm(maxTokens, temperature)` annotation values are now actually wired from `MeshLlmRegistry.LlmConfig` through `MeshEventProcessor` into the proxy via a new 10-arg `configure(...)` overload — fixes a pre-existing latent bug where the hardcoded `defaultMaxTokens=4096` / `defaultTemperature=0.7` silently overrode every caller's annotation.
- **Java `parallel_tool_calls` precedence + streamGenerate ThreadLocal clear** (#1028): `buildMergedModelParams()` now honors `containsKey` guard for `parallel_tool_calls` so a caller's `.modelParams("parallel_tool_calls", false)` is respected. `streamGenerate()` wrapped in `try { ... } finally { clearInvocationContext(); }` so the ThreadLocal seeded by `MeshToolWrapper.setInvocationContext()` doesn't survive on the calling thread after the cold `Flow.Publisher` is returned.

### 🔁 Earlier in the v2.1.0 cycle

- **`thinking_config` passthrough + Reference nav restructure** (#1022): Gemini `thinking_config` kwarg now passes through the native Gemini adapter (with unsupported-type warning). Reference nav reorganized — single dropdown with API / CLI / Environment Variables / Kwargs. New Kwargs reference page (`docs/reference/kwargs.md`) with cross-vendor matrix and per-language examples. Hadolint pre-commit hook fix.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v2.0.0...v2.0.1)

## v2.0.1 (2026-05-16)

Native LLM dispatch follow-ups to v2.0.0. Adapter contract honoring across Anthropic / OpenAI / Gemini, Sonnet 4.5+/Opus 4.1+ routed through Anthropic's first-class `output_config` primitive, Gemini prompt-level safety detection, plus pre-emptive migration off Gemini 2.0 Flash ahead of its June 2026 deprecation.

- **Native adapter contract** (#1012): `response_format` / `request_timeout` no longer silently dropped on native retry paths; per-vendor translations (Anthropic `timeout`, Gemini `HttpOptions.timeout` ms); synthetic tool_call args lifted to `content` on native retry; vendor plumbed explicitly through recovery helpers so unprefixed model strings don't fall through to LiteLLM. Typed `LLMRefusedError` exception for vendor-level refusal signals (OpenAI `message.refusal`, Anthropic synthetic-tool absence, Gemini safety-blocks).
- **Anthropic `output_config` for newer Claude** (#1014): Sonnet 4.5+/Opus 4.1+ route through `output_config` (per-model allow-list + schema filter) instead of synthetic-tool injection. Streaming + structured output now routes to HINT mode (synthetic-tool was a poor fit for streams). Gemini prompt-level safety-block detection raises `LLMRefusedError(category="PROMPT_BLOCK")`.
- **Polish + Gemini 2.5 Flash migration** (#1016): DRY shared helpers across adapters (`warn_unsupported_kwarg_once`, `resolve_request_timeout`, `filter_anthropic_output_schema`); regex-anchored model allow-list (no more substring overmatch on hypothetical future versions); AST-based test assertions; pre-emptive `gemini-2.0-flash` → `gemini-2.5-flash` across docs/examples/tests.

**Env-var unification**: `MCP_MESH_HINT_FALLBACK_TIMEOUT` is the canonical name; `MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT` remains as a deprecated back-compat alias with a runtime warning.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v1.4.1...v2.0.0)

## v2.0.0 (2026-05-14)

The 2.x major release. Two new flagship surfaces — **MeshJob** (a registry-backed substrate for long-running tasks across the mesh) and **A2A v1.0** (cross-runtime Agent-to-Agent protocol bridge, both producer and consumer sides) — plus a **schema registry** that makes capability matching type-safe across Python, TypeScript, and Java with cross-runtime hash equality. The LLM provider stack moves from direct-mode SDK calls to mesh-delegated providers backed by native vendor SDKs (Anthropic, OpenAI, Gemini AI Studio + Vertex AI). The dashboard UI gains Jobs, Schemas, A2A signals, and an agent grid. The `meshctl scaffold` surface migrates from `--agent-type X` flags to subcommands (`basic`, `llm`, `llm-provider`, `a2a-consumer`, `api`). The 28-topic meshctl audit (PRs #1001-#1008) drove a comprehensive doc cleanup pass.

**Breaking changes**: direct LLM provider mode retired (mesh-delegated only — see #859); `meshctl scaffold --agent-type` deprecated in favor of subcommand form (back-compat shim with runtime warning until 3.x).

### 🧱 MeshJob — long-running task substrate (cross-runtime)

- **Registry-backed claim/lease substrate** (#878): new `@mesh.tool(task=True)` opts a tool into MeshJob — runs under a registry-managed lease with progress updates and explicit `complete()`/`fail()` terminal states. Consumer types a dependency parameter as `MeshJob`; DDDI swaps the usual `McpMeshTool` proxy for a `MeshJobSubmitter`. Submit via `proxy.submit(...)` returns a `JobProxy` bound to the new job ID; `proxy.wait(...)` polls until terminal.
- **Cross-runtime parity**: TypeScript implementation (#885), Java implementation (#891), polyglot integration suites (#883, #888, #892) covering Python ↔ TS ↔ Java combinations end-to-end.
- **`retry_on` per-tool exception whitelist** (#896, #897, #898): producers declare which exception classes are transient. Matching exceptions trigger `release_lease()` instead of `fail()` — the registry hands the job to a peer replica within ~5s. Anything not in `retry_on` surfaces to the consumer immediately as `JobFailedError`.
- **Cancel propagation** (#899, #901): consumer `proxy.cancel(reason)` fires the cancel token in the producer's running handler. Java cancel-registry binding + outbound HTTP cancel propagation (#899); Python handler observes `/jobs/:id/cancel` (#901); TS bundle for retry_on + outbound cancel + structuredContent (#897).
- **User-facing documentation** (#902, #241): `meshctl man jobs` covers the producer + consumer surface, MeshJobSubmitter / JobProxy / JobController, retry_on semantics, and the cheat sheet table that aligns producer + consumer surfaces side-by-side.

### 🔗 A2A v1.0 — cross-runtime Agent-to-Agent protocol bridge

- **Python A2A — producer + consumer**:
  - Producer (#904, #905): expose mesh tools as A2A v1.0 skills via `mesh.a2a.mount(app, ...)` on a Starlette/FastAPI app — auto-generates `/.well-known/agent.json` and the JSON-RPC entry route. Long-running A2A tasks bridge into the MeshJob substrate (Phase 3, #905) with SSE streaming for progress. Test coverage: 7 deferred integration tests bringing uc24_a2a_python to 12/12 (#907).
  - Consumer (#908, #913): `@mesh.a2a_consumer` + injected `mesh.A2AClient` bridge an external A2A skill into the mesh as a regular mesh capability. Long-running submit/subscribe bridges to MeshJob (#910, #914). Hardening pass for loop binding, lifecycle, multi-agent diagnostics (#912, #915).
- **TypeScript A2A — producer + consumer**:
  - Producer (#935): `mesh.a2a.mount()` on Express apps. Per-heartbeat surfaces parity with Python via napi push (#943).
  - Consumer (#917, #927): `addTool({ a2aConfig })` with `A2AClient` injection in the execute callback. structuredContent fix in #927.
- **Java A2A — producer + consumer**:
  - Producer (#934): `@MeshA2A` annotation for Spring Boot apps. Empty-`@MeshA2A`-registry hotfix (#947); synthetic-tools registration ordering hotfix (#949).
  - Consumer (#919, #922): `@A2AConsumer` annotation + `A2AClient` parameter injection on a `@MeshTool` method. Phase 3 long-running submit/subscribe bridge (#922). Framework-injection refactor (#923, #924). MeshJobSubmitter auto-injection + user-`@Component` cycle fix (#941).
- **`meshctl scaffold a2a-consumer`** (#909, #929): fetches an external A2A producer's card from `--url` and generates a runnable bridge consumer (Python / TS / Java). `--offline` mode for placeholder generation. SSRF/redirect bounding (#944).
- **Bearer authentication** (#931): wired automatically when the upstream card declares it. Per-runtime env-var conventions: Python `A2A_BEARER_TOKEN`, TS `a2aConfig.auth = { tokenEnv: ... }`, Java `@A2AConsumer(authBearerEnv = ...)`.
- **Documentation suite** (#931): full A2A guide at `meshctl man a2a` covering producer + consumer + bearer auth + cross-runtime convention; A2A decorator family added to the decorators reference page in all three languages (#1007).

### 🧬 Schema registry + DDDI maturity

- **Type-safe capability matching** (#547, #841): the registry stores canonical, content-addressed JSON Schemas for every tool's input and output, plus consumer "expected" schemas. The Rust canonical normalizer (embedded in every SDK) collapses Python Pydantic models, TypeScript Zod schemas, and Java POJOs to the same byte-equal canonical form by sha256 — making cross-language matching meaningful. Opt-in per dependency via `expected_type` (Python) / `expectedSchema` (TS) / `expectedType` (Java). Two modes: `subset` (consumer's required fields exist on producer) or `strict` (byte-equal hashes for cross-language pinning). Cluster-wide `MCP_MESH_SCHEMA_STRICT=true` promotes WARN→BLOCK; per-tool `output_schema_strict=False` demotes BLOCK→WARN.
- **Dependency resolution audit trail** (#839): `meshctl audit <agent>` reads back the registry's per-dependency resolution log. `--explain` renders a stage tree showing which candidates entered each filter stage (`health → capability_match → tags → version → schema → tiebreaker`), which were dropped (and why, with typed reasons), and the chosen producer. Emission is gated to multi-candidate decisions and producer flips so the audit table stays noise-free. Plus prefix-resolver fix.
- **Schema diff + canonical schema browser**: `meshctl schema diff <hashA> <hashB>` for content-addressed schema comparison; `meshctl list --schemas` for the registry inventory.
- **Sweep job** (#837, #842, #843): purges stale agents and old registry events on a configurable interval. Orphan `schema_entries` GC under SERIALIZABLE isolation.

### 🌊 Streaming

- **`mesh.Stream[str]` author API** (#645, #849): annotate a tool's return type as `mesh.Stream[str]` and `yield` chunks — the framework picks the streaming code path automatically. Rides standard MCP `notifications/progress` — no protocol extensions, no global config knob. Vanilla MCP clients (Cursor, Claude Desktop, Cline, `fastmcp.Client`) can subscribe via `progressToken` in `_meta`.
- **`proxy.stream()` consumer API** (#849): when a mesh agent depends on a streaming tool, calling `proxy.stream(...)` returns an async iterator of chunks. Multi-hop streaming composes by re-yielding chunks at each layer.
- **Browser via `@mesh.route` auto-SSE** (#849): a FastAPI route handler that returns `mesh.Stream[str]` is auto-wrapped as Server-Sent Events; chunks become `data: <chunk>\n\n` lines, terminating with `data: [DONE]\n\n`.
- **Cross-runtime streaming consumer parity** (#854, #855): TypeScript and Java consumers can also subscribe to streaming producers (per-chunk `proxy.stream()` parity is Python today; wire-level streaming works for all runtimes).
- **Mesh-delegate streaming + tutorial** (#853): bonus tutorial chapter walking through token-by-token streaming end-to-end.

### 🤖 LLM provider stack — native SDKs + delegated mode only

- **Native vendor SDKs for `@mesh.llm_provider`** (#834, partial #862, #864, #865): Anthropic SDK (#862), OpenAI SDK (#864), Gemini SDK with both AI Studio (`gemini/*`) and Vertex AI (`vertex_ai/*`) backends (#865). Replaces the LiteLLM-only path with provider-native SDKs that get vendor-specific features (e.g., Anthropic's HINT mode, OpenAI's structured outputs) without LiteLLM as a translation layer.
- **Direct mode retired — mesh-delegated only** (#859, #870): v2.0 breaking change. `@mesh.llm` no longer accepts an embedded API key or vendor SDK; consumers always go through a mesh-resolved `@mesh.llm_provider`. Cleaner separation: providers own the API keys + SDK; consumers declare the capability + tag selector.
- **Synthetic-tool retry on schema-validation failure** (#961, #962): `mesh.llm`'s synthetic tool calls (`__mesh_job_*`, framework-injected) retry on Pydantic shape mismatches in the LLM's reply — LiteLLM-parity safety net for the native Anthropic path.
- **LLM stack cleanups** (#860, #863, #866): kwarg collision fixes, per-loop httpx pool to avoid cross-loop binding errors, vendor-aware emitter.

### 📊 UI dashboard

- **Jobs page** (#978): read-only MeshJob observability — surfaces submitted/running/completed jobs with their progress, owner, and terminal state. Drives off the `/jobs` registry endpoint.
- **Schema registry browser** (#979): inspect canonical schemas in the registry, see which agents produce/consume each hash.
- **Agents grid view + `/agents/:id` detail route** (#980): card-based agent overview with detail drill-down for capabilities, dependencies, last-seen timing.
- **A2A producer/consumer signals on agent metadata** (#977): sidenav + agent detail surface A2A flags for cross-language A2A topology.
- **Agent description persistence + UI surfacing** (#975): `@mesh.agent(description=...)` now persists to the registry and surfaces in the UI detail view.
- **Trace activity counter from recent ring buffer** (#985): dashboard activity indicator now reflects recent (last-N-minute) trace events instead of cumulative counts.
- **UI polish bundle** (#965 #966 #967 #970 #974, in #983): cumulative quality-of-life improvements + agents-page alphabetical sort to stop card reshuffling on refresh.
- **Forward rotate events + poller reason enrichment** (#982 #984, in #986).

### 🛠️ meshctl + scaffold

- **Subcommand-based scaffold surface** (#960, #1004): `meshctl scaffold` migrates from the deprecated `--agent-type X` flag to subcommands — `basic`, `llm`, `llm-provider`, `a2a-consumer`, `api`. Each subcommand has a focused flag surface (e.g., `scaffold llm --vendor claude --response-format json`); the deprecated `--agent-type` form is retained behind a runtime deprecation warning for back-compat.
- **`meshctl scaffold api`** (#1005, in #1004): HTTP gateway scaffold for FastAPI / Express / Spring Boot agents that consume mesh capabilities via `@mesh.route` (Python), Express middleware (TypeScript), or the Spring Boot starter (Java). Templates existed since 1.x but the command path was severed during the subcommand migration; this restores a runnable starter.
- **Auto port-bumping on scaffold** (#958): `meshctl scaffold` detects existing agents in the workdir and increments `http_port` so multi-agent projects don't collide on 8080.
- **Drop unimplemented `mode llm` scaffold engine** (#1002): `--list-modes` advertised an LLM-driven generation mode that was never implemented. Cleaned up entirely (−497 lines).
- **Audit-driven doc cleanup** (#1001 #1003 #1006 #1007 #1008): 28-topic walk through every `meshctl man` page surfaced ~50 doc fixes — scaffold-example rewrites across 11 pages, registry endpoint table fix (`/capabilities` removed, `/schemas` added), heartbeat env var label corrections, content polish bundle (~20 small items).

### 🔒 Registry + trust hardening

- **Trust chain fail-fast on backend init failure** (#988, originally #989): registry refuses to start if a configured trust backend (filestore, k8s-secrets, SPIRE) fails to initialize — eliminates a class of silent-degradation bugs where the registry would come up healthy but reject every cert with "no backends configured." Surfaced via tc13_vault_typescript on K8s nodes with restrictive pod sandboxes (newer containerd).
- **filestore fsnotify watcher non-fatal**: filestore backend now degrades to "trust without hot reload" instead of failing the backend if `fsnotify.NewWatcher()` is rejected by a restrictive sandbox.
- **uc12 test suite hardening** (#988): replaces fragile `handler: wait, seconds: N` blocks with poll-until-healthy shell loops across 8 registration-trust tests. Closes the registration-race flake class.
- **Registry sweep job** (#837): purges stale agents and old registry events on a configurable interval. Tunable via `MCP_MESH_SWEEP_INTERVAL`.
- **Unhealthy agents must re-register via POST** (#955, #959): heartbeat `HEAD` now returns `410 Gone` for previously-evicted agents, forcing a clean POST registration instead of a stale-state silent re-add.

### 🎬 Media storage

- **Fail-fast S3 startup validation** (#945, 4 of 5 from #846): agent fails to start if `MCP_MESH_MEDIA_STORAGE=s3` is set without `boto3` installed or `MCP_MESH_MEDIA_STORAGE_BUCKET` configured. Optional `MCP_MESH_MEDIA_STORAGE_VALIDATE=true` adds a bucket-reachability probe before serving traffic.

### 📚 Documentation

- **A2A documentation suite** (#931): full guide at `meshctl man a2a` with cross-language convention table; A2A decorators added to `meshctl man decorators` in all three languages (#1007).
- **MeshJob user docs** (#902): `meshctl man jobs` covers producer + consumer surfaces.
- **Homepage / README / comparison cleanup** (#951): A2A coverage, positioning reframe, failover accuracy.
- **Doc convention added** (`.claude/CLAUDE.md` and project memory): user-facing docs show only canonical command forms; deprecated forms remain functional with runtime warnings but are not teach-documented. Drove the audit-cleanup pass.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v1.3.4...v1.4.1)

## v1.4.1 (2026-04-28)

Reliability + provider expansion. The marquee item is a clean-cutover redesign of meshctl's process lifecycle that eliminates a class of bugs around orphaned registry/UI servers, same-name agent re-starts, and watch-mode races. Vertex AI joins the LLM provider lineup across all three runtimes with IAM-based auth instead of API keys. Python and TypeScript agents no longer have their health endpoints blocked by long-running tool calls (k8s pod-restart fix). Claude structured output goes HINT-first to eliminate silent hangs.

### 🛠️ meshctl Process Lifecycle Redesign

- **Refcount-based service ownership** (#827): `meshctl stop <agent>` no longer orphans the registry or UI when other agents in different start groups still depend on them. New `lifecycle/` package introduces per-invocation group IDs, per-group dependency files under `~/.mcp-mesh/registry/deps/<group-id>` and `~/.mcp-mesh/ui/deps/<group-id>`, and a single `KillVerifyAndCleanup` helper that all stop paths funnel through (TERM-then-KILL with poll, treats zombie state as dead, 3s window)
- **Single-instance enforcement**: `meshctl start <agent>` exits non-zero if the same agent name is already running, with a helpful message including the live PID and remediation. Uniform across MCP agents and REST API apps. Eliminates the silent `<agent>.pid`/`<agent>.group` overwrites that previously corrupted refcount bookkeeping
- **Watch-mode wait-for-death**: File-change reload now waits for the old process to be confirmed dead (PID file removed) before respawning. Loud failure on timeout, no silent retry. The old `MCP_MESH_HTTP_PORT=0` random-port workaround is gone — agents respawn on the same configured port, and `@mesh.route` REST API apps can now use `-w` (previously forbidden)
- **Stop semantics**: `meshctl stop` (no args) shuts down everything (sentinels pruned first); `meshctl stop <agent>` only reaps registry/UI when their refcount truly hits zero (and `--keep-registry` / `--keep-ui` flags aren't set); `meshctl stop --registry` / `--ui` force-kill with stderr WARN listing dependent groups
- **Sentinel handling**: Standalone `meshctl start --ui` (no agents) is reliably tracked across stop operations via a `_ui_only_` sentinel that survives GC sweeps
- **Watch-mode bookkeeping unified**: The legacy `<name>.<ppid>.pid` namespacing was retired; group-id supersedes it. Watch wrappers tracked via `<agent>.watcher.pid` sidecar so stop kills them BEFORE the agent (closes the respawn race)
- **GC sweeps** stale PID files and dead deps entries on every start/stop, but never kills services. Concurrent meshctl invocations serialized via `flock` on the start path

### 🌟 Vertex AI (Gemini via IAM)

- **`vertex_ai/<model>` provider prefix across Python, TypeScript, Java** (#824): Use Gemini through Vertex AI with IAM authentication via Application Default Credentials — no AI Studio API key required. Routes through `@mesh.llm` decorator (Python), `mesh.addLlmProvider` (TypeScript), and `@MeshLlm(provider = "vertex_ai")` (Java)
- **Per-runtime integration**: Python uses LiteLLM's `vertex_ai/` path with `google-auth`; TypeScript uses `@ai-sdk/google-vertex`; Java uses `spring-ai-starter-model-vertex-ai-gemini` with reflection-based dep loading so AI-Studio-only consumers don't hit `NoClassDefFoundError`
- **Working examples** for all three runtimes under `examples/{python,typescript,java}/vertex-ai-agent/`, plus per-runtime env-var matrix in `docs/environment-variables.md`
- **Integration tests** (tc34/35/36) cover the Vertex path end-to-end for each language

### 🔁 Tool Execution Isolation (Python + TypeScript)

- **Python worker pool** (#819): Tool execution now runs in an isolated worker thread pool with proper contextvars propagation. Health endpoints no longer block during long-running MCP tool calls — fixes k8s pod restarts where the readiness probe couldn't get a response while a slow tool was executing. Concurrent calls to the same tool no longer serialize
- **TypeScript worker_threads** (#821): Equivalent isolation using Node's `worker_threads`, V8 isolate boundary, with tsx loader resolution. Same health-endpoint fix as Python
- **Per-loop httpx pool** in Python prevents the cross-loop binding errors that surfaced after worker isolation

### 💎 Claude HINT-First Structured Output

- **Faster + more reliable** (#822): The Claude provider tries HINT mode first (schema in the system prompt) and falls back to STRICT mode only if HINT fails. HINT mode is sufficient for most cases and is significantly faster than STRICT, eliminating the silent hangs that occasionally surfaced with STRICT-mode JSON enforcement

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v1.3.3...v1.3.4)

## v1.3.4 (2026-04-18)

Hardening + Spring AI M4. Closes an audit-derived security pass (registry agent_id validation, header-propagation allowlist tightened from prefix-by-default to exact match, TLS auto fail-fast, proxy error sanitization), error-visibility improvements across Python/Java SDKs, meshctl signal handler leak fix, and stale doc/version cleanups. Spring AI upgraded to 2.0.0-M4 — brings the Java integration suite to parity, 5 previously-disabled Java tests re-enabled.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v1.3.2...v1.3.3)

## v1.3.3 (2026-04-16)

Patch release. Documentation polish — TripPlanner hero example refreshed in README and Quick Start (#786).

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v1.3.1...v1.3.2)

## v1.3.2 (2026-04-15)

Patch release. Agent `name` and `agent_id` are now distinct fields across Python, TypeScript, and Java SDKs — previously all three collapsed `name == agent_id`, making replicas behind a K8s Service indistinguishable. The topology dashboard now groups replicas of the same base name into a single node with a ×N badge and an accordion drawer for per-replica details. meshctl `list` / `call` / `status` display and filter by full agent ID so replicas are individually addressable; registry `/proxy/{target}` matches by either ID or base name (#781).

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v1.3.0...v1.3.1)

## v1.3.1 (2026-04-14)

Patch release. Tutorial download artifacts (zips, tutorial-complete.html/txt) now generate and deploy in CI (#775). Version bump script refactored to a handler-based design — catches 363 files per bump vs 184 previously, eliminating the manual cleanup toil from #753.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v1.2.0...v1.3.0)

## v1.3.0 (2026-04-14)

Reliability and production-readiness release. meshctl stop works reliably across all scenarios, timeouts propagate through multi-hop agent chains, and the TripPlanner tutorial ships end-to-end from first agent to production deployment.

### 🔗 X-Mesh-Timeout Propagation

- **Header propagation across all SDKs** (#769): Python/TypeScript/Java SDKs set and propagate `X-Mesh-Timeout` header on outgoing mesh calls. Multi-hop LLM chains (gateway → planner → specialist → provider) now respect a single top-level timeout instead of hitting the hardcoded 60s proxy floor
- **Registry proxy**: Forwards `X-Mesh-Timeout` to target agents and matches `MCP_MESH_PROPAGATE_HEADERS` headers; `MCP_MESH_PROXY_TIMEOUT` env var replaces the hardcoded 60s default
- **Client-side timeout override**: SDKs use propagated `X-Mesh-Timeout` value for their own client timeouts (not just the registry's) — Java's OkHttpClient rebuilt per-call to avoid the hardcoded 60s readTimeout

### 🛠️ meshctl Reliability

- **meshctl stop finds and kills detached processes** (#767): Parent writes safety-net PID files in `forkToBackground()` so `meshctl stop` has something to kill even before the child finishes starting agents. Monitoring goroutines detect external kills so wrapper meshctl processes self-exit instead of orphaning
- **macOS zombie detection** (#767): New `utils_darwin.go` uses `ps -o state=` to properly detect zombie processes (was a no-op, causing "still alive after SIGKILL" errors)
- **Signal handler race fix**: Signal handler set up early in `startRegistryOnlyMode` so SIGTERM during startup doesn't orphan the registry subprocess
- **Setpgid on forked child**: Process group kills now work reliably for cleanup
- **meshctl stop cascade-kill across independent watchers** (#749)

### 🗄️ Database Centralization

- **Registry DB moved to `~/.mcp-mesh/mcp_mesh_registry.db`** (#768): No more DB files scattered across project directories. `stop --clean` deletes from the centralized location
- **Single-registry constraint**: Prevents accidentally starting multiple local registries on different ports. Guard runs after port check to avoid false positives on concurrent starts

### 📚 TripPlanner Tutorial

- **10-day progressive tutorial** (#764): From scaffold to Kubernetes — flight/hotel/POI agents, LLM delegation with `@mesh.llm`, multiple providers with tag-based routing, HTTP gateway, chat history, committee pattern with specialist fan-out
- **TripPlanner production app** (#760): Full production-ready app with UI, auth, real data sources, and SPIRE workload identity
- **Tutorial polish** (#752, #759): Typed Pydantic models, downloadable artifacts, `meshctl man tutorial` integration
- **meshctl home dir, scaffold, UI resilience** (#754-757)

### 🔧 Environment Variables

- **`MCP_MESH_PROXY_TIMEOUT`** (default 60s, capped at 600s): Registry proxy default timeout when no `X-Mesh-Timeout` header is present
- **`MCP_MESH_CALL_TIMEOUT`** (default 300s): SDK default for outgoing mesh calls, sent as `X-Mesh-Timeout` header

### 🐛 Bug Fixes

- **Fortuna usability quick wins** (#751): Scaffold improvements, stop UX fixes
- **meshctl scaffold compose files**: No longer generates with stale 0.8 version tags

### 📋 Follow-up

- **Version bump script gaps** (#753): Current release required manual cleanup of 158 additional files (man content, Go handlers, docs, example Dockerfiles, test artifacts, tutorial Dockerfiles) that the bump script missed. Script needs extension to catch `mcpmesh/*:<tag>` patterns across all directories

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v1.1.0...v1.2.0)

## v1.2.0 (2026-04-09)

Observability and dashboard reliability release. Distributed tracing now works end-to-end across all runtimes, the dashboard is faster and lighter, and SQLite stability is improved.

### Observability

- **Fix parent_span linkage** (#745): Python `ExecutionTracer` was publishing all spans as root spans, breaking cross-agent edge detection. Per-Edge Traffic and Total Calls now work correctly on the dashboard
- **Total Calls metric** (#745): Counts every finalized trace once (single-agent and cross-agent), replacing the edge-stats-only count
- **Trace context injection in Rust core** (#742): Consolidated `_trace_id`, `_parent_span`, and `_mesh_headers` injection from Python/TypeScript into a single Rust implementation for cross-runtime consistency
- **Deferred trace finalization** (#743): 3-second grace period after root span arrival allows in-flight spans from other agents to arrive before finalizing. UI server tracing enabled by default

### Dashboard

- **Vite + React Router migration** (#735): Replaced Next.js with Vite + React Router for faster builds and smaller bundle. CSR-only with `go:embed` for the UI server binary
- **UI server integration tests** (#740): Comprehensive test coverage for dashboard API endpoints (agents, traces, edge stats, model stats, trace search)

### Bug Fixes

- **SQLite connection pool PRAGMA loss** (#737): PRAGMAs set on initial connection were lost when the pool recycled connections, causing corruption under load with 7+ agents

---

## v1.1.0 (2026-04-05)

The dashboard release. Real-time monitoring, parallel tool execution, per-service TLS, and production-grade Kubernetes deployment with Helm charts.

### 🖥️ Web Dashboard

- **Dashboard UI** (#665, #668, #669, #673, #677, #695): Real-time agent monitoring with 5 pages — Dashboard overview (stats, traffic, events), Agents (table with capabilities), Topology (dependency graph), Traffic (per-edge metrics, token usage, latency), and Live (trace streaming)
- **Docker image** (`mcpmesh/ui`) (#722, #723, #727, #731): Published to Docker Hub and GHCR, serves at `/ops/dashboard` by default for Kubernetes ingress routing
- **basePath support** (#711, #717): Configurable path prefix for ingress routing. Custom paths via `ui-custom.Dockerfile`
- **`meshctl start --ui`**: Embedded UI server for local development with auto-open via `--dashboard`

### ⚡ Performance

- **Parallel tool execution** (#672, #715): Provider-side parallel tool calls across all 3 runtimes — Python (`asyncio.gather`), TypeScript (`Promise.all`), Java (`CompletableFuture.allOf`)
- **HTTP-first transport** (#697): orjson + simd-json for faster serialization across Python and Rust runtimes
- **Connection pooling** (#674, #676): Shared HTTP clients for inter-agent calls in Python and TypeScript SDKs

### 🔒 Security & TLS

- **Per-service TLS** (#704, #716): Independent TLS configuration for Redis, Tempo, OTLP, and UI-to-Registry connections via `{SERVICE}_TLS_CA/CERT/KEY` environment variables
- **CLI TLS hardening** (#719): Auto-detect TLS auto CA, `--insecure` flag wired up, MinVersion TLS 1.2
- **SPIRE in published wheel** (#719): `pip install mcp-mesh-core` now includes SPIRE workload identity support
- **Reproducible Rust builds** (#719): Cargo.lock tracked in git to prevent dependency drift

### 🏗️ Helm & Infrastructure

- **mcp-mesh-ui chart**: Optional dependency in mcp-mesh-core with basePath-aware health probes
- **Ingress chart**: UI + Grafana routing (host-based and path-based), ops NetworkPolicy template
- **Grafana sub-path**: `serve_from_sub_path` support for basePath-based ingress
- **Per-service TLS secrets**: Conditional cert/key env vars and volume mounts in registry and UI charts

### 🛠️ SDK & Runtime

- **Rust core extraction** (#679): Duplicated SDK logic (TLS, config, heartbeat) moved to shared Rust core
- **DependencyKwargs parity** (#689): Schema filtering fix across all runtimes
- **Pydantic serialization** (#700): Model serialization fix in HTTP direct path

### 🐛 Bug Fixes

- **Detach mode** (#719): StringArray/StringSlice flags and TLS env vars properly forwarded to forked processes
- **meshctl stability** (#714): SQLite locking, watch mode stop, process management fixes
- **meshctl call** (#686): Falls back to capability name for tool lookup
- **Ingress NOTES.txt**: Fixed nil pointer in `range` loop

### 📚 Documentation

- **Dashboard docs**: Production screenshots, deployment guide, architecture overview
- **Environment variables** (#705): 50+ missing vars added to docs page, man page updated with key vars and footer link
- **UI deployment** in `meshctl man deployment`: Local dev, Kubernetes, ingress routing, custom basePath, beta tag overrides

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v1.0.0...v1.0.1)

## v1.0.1 (2026-03-28)

### ✨ New Features

- **download_media API** (#660): Added `mesh.download_media(uri)` / `downloadMedia(uri)` / `MeshMedia.downloadMedia(uri, store)` across all three SDKs for reading media back from MediaStore

### 🐛 Bug Fixes

- **Registry proxy timeout** (#657): `meshctl call --timeout` now propagates to the registry proxy via `X-Mesh-Timeout` header (was hardcoded 60s, capped at 600s)
- **Helm scaffold env/secrets override** (#660): Commented out `env: []` and `secrets: []` in scaffold helm-values templates to prevent silently wiping base values during multi-file `helm install`

### 📚 Documentation

- Various documentation fixes and improvements (#657)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.9...v1.0.0)

## v1.0.0 (2026-03-25)

The first stable release of MCP Mesh. This milestone brings production-grade security with mutual TLS everywhere, first-class multimodal/media support across all three SDKs, and provider-side tool execution for single-round-trip agentic workflows.

### 🔒 Security & Trust

- **Registration Trust — Phase 1** (#599): Registry validates agent identity via X.509 certificates before allowing registration. Entity-level trust model with pluggable trust backends (LocalCA, FileStore, K8s Secrets, SPIRE) and credential providers (File, Vault, SPIRE) for agent cert sourcing.
- **Agent-to-Agent mTLS — Phase 2** (#601): Every inter-agent call is mutually authenticated. The same cert used for registry registration is reused for peer auth, with SPIFFE-aware TLS verification.
- **Vault credential provider** (#605): Agents fetch TLS certs from HashiCorp Vault PKI at startup with in-memory fetch, secure temp files, and cleanup on shutdown.
- **SPIRE credential provider** (#607): X.509-SVID fetching from SPIRE Workload API via Unix domain socket for full workload identity support.
- **Helm TLS support + security docs** (#609): Helm charts support TLS configuration with full security documentation covering registration trust, agent-to-agent mTLS, and authorization.
- **litellm supply chain mitigation** (#644): Excluded compromised litellm versions 1.82.7 and 1.82.8.

### 🖼️ Multimodal / Media

- **Phase 1 — MediaStore + resource_link** (#616): Local and S3 storage backends with `upload_media()` and `media_result()` APIs. Resource link format for passing media references between agents.
- **Phase 2 — LLM handler media resolution** (#617): LLM providers auto-resolve resource_link URIs to native format (Claude image blocks, OpenAI image_url, Gemini inline_data) with no manual fetching needed.
- **Phase 3 — Developer convenience APIs** (#618): `MediaResult` one-step upload+link, `save_upload()` for web frameworks, `media=` parameter for LLM calls, and `MediaParam` type hints across all three SDKs.

### ✨ New Features

- **Provider-side tool execution + Gemini** (#603): LLM providers execute tool calls internally (full agentic loop on provider side), returning final structured responses in one round-trip. Gemini re-enabled for Python.
- **FastMCP/MCP SDK upgrade** (#611): Upgraded to FastMCP 3.x and latest MCP SDK across all runtimes with Streamable HTTP transport.

### 🔧 Improvements

- **OTLP exporter reconnection** (#644): Background connection manager with exponential backoff retry (5s-60s). Registry no longer fails to start when Tempo is unavailable, with auto-reconnection on connection loss and HTTP health check probe.
- **Go codebase optimization** (#634): Decomposition and optimization of Go registry code.
- **Rust core optimization** (#636): Deduplication and optimization of Rust FFI core.
- **Python SDK optimization** (#638): Handler deduplication across provider handlers.
- **Java SDK optimization** (#640): Handler deduplication and optimization.
- **TypeScript SDK optimization** (#642): Handler deduplication and optimization.

### 📚 Documentation

- **Multimodal docs + DDDI branding** (#628): MkDocs multimodal guide, DDDI concept page, and Sky chatbot widget.
- **Man page improvements** (#632): Distributed deployment and security man pages.
- **Media/multimodal restructure** (#651): Story-driven getting-started guide (receipt upload + chart generation), nav reorder, and man page condensing (52% reduction) with security mermaid diagram.
- **Man page fixes** (#651): Stale version refs, duplicate model, HA documentation, and decorator comments.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.8...v0.9.9)

## v0.9.9 (2026-03-05)

### 🐛 Bug Fixes

- **Java SDK — Flat trace spans in Grafana** (#595): Java agent traces appeared flat — all downstream agent spans at the same level under the handler span — while Python and TypeScript showed proper nested hierarchy. Added `proxy_call_wrapper` intermediate spans around outgoing tool/proxy calls in `McpMeshToolProxy.call()` and `ToolInvoker.invokeLocal()`, matching the span nesting behavior of Python and TypeScript SDKs. Also added `TraceContext.wrapSupplier()` for async trace context propagation via `CompletableFuture.supplyAsync()`, and wired `ExecutionTracer` to `McpMeshToolProxyFactory` and `ToolInvoker` via auto-configuration

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.7...v0.9.8)

## v0.9.8 (2026-02-22)

### 🐛 Bug Fixes

- **Java SDK — Orphan spans in trace graph** (#589): `TraceInfo.forPropagation()` generated a phantom spanId when no parent span was provided (e.g., `meshctl call --trace`), creating a span reference that was never published — downstream spans appeared as orphans with no root. Removed phantom generation so the first tool span is correctly a root span
- **Java SDK — Header propagation returning empty `{}`** (#589): `MeshMcpServerConfiguration` used default `immediateExecution=false`, causing MCP tool handlers to run on Reactor's `boundedElastic` thread pool instead of the servlet thread where `TracingFilter` sets ThreadLocal context. Set `immediateExecution(true)` so tool handlers execute on the servlet thread and can access propagated headers
- **Java SDK — Null guards on spanId** (#589): Added null checks on `getSpanId()` in `McpHttpClient` (argument injection and HTTP header injection) and `TracingFilter` (response header) to prevent NPE when parent span is legitimately null

All three bugs were regressions introduced in v0.9.7 by PR #585.

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.6...v0.9.7)

## v0.9.7 (2026-02-22)

### ✨ New Features

- **Language-agnostic Helm chart** (#580): `mcp-mesh-agent` chart now supports Python, TypeScript, and Java agents natively — added `agent.runtime` field and `isPython` helper for conditional Python env var injection; removed dead `agent.script` and `agent.python` fields; rewrote README with multi-language examples
- **Arbitrary namespace support** (#579): Helm charts deploy into any namespace — replaced hardcoded FQDN hostnames with short names, added `networkPolicy.allowedNamespace` with `| default .Release.Namespace` fallback, documented custom namespace, multi-tenant, and cross-namespace deployment patterns

### 🔧 Improvements

- **ENTRYPOINT/CMD alignment** (#586): TypeScript runtime ENTRYPOINT changed from `node` to `npx tsx`; all scaffold Dockerfiles now set CMD to just the script/jar path (ENTRYPOINT provides the runtime command)
- **NetworkPolicy** (#586): Registry ingress rule now filters by namespace only (not pod label), allowing both agents and APIs to reach the registry

### 🐛 Bug Fixes

- **Distributed tracing** (#585): Fixed `InheritableThreadLocal` trace context leak across Java thread pool reuse; added route handler span publishing to TypeScript `mesh.route()` and Java `@MeshRoute`; added `runtime` field to trace span metadata in all SDKs; fixed NPE in Java `TraceInfo.forPropagation()` when parent span is null
- **Scaffold registry URL** (#586): Fixed `mesh.registryUrl` in scaffold helm-values templates and deployment docs — the chart reads `registry.host`/`registry.port` but docs and templates were using a key the chart ignores, causing cross-namespace registry overrides to silently fail
- **TypeScript runtime tsx availability** (#586): Pinned `tsx@4` as global install in TypeScript runtime Dockerfile — previously relied on `npx` runtime download which fails in airgapped clusters
- **Registry NetworkPolicy port** (#586): Fixed default `ingressPorts` from 8080 to 8000 to match actual registry service port
- **Registry NetworkPolicy namespace label** (#586): Changed from `name:` to `kubernetes.io/metadata.name:` (auto-applied by K8s 1.21+)
- **Image tag consistency** (#586): Bumped all Go handler, scaffold template, and Dockerfile image tags from 0.8 to 0.9

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.5...v0.9.6)

## v0.9.6 (2026-02-19)

### ✨ New Features

- **Per-call custom headers** (#575): Inject headers like `x-audit-id` on individual tool invocations across all three SDKs — `tool(headers={"x-audit-id": "abc"})` (Python), `tool({}, { headers })` (TypeScript), `tool.call(args, headers)` (Java). Per-call headers merge with session-propagated headers (per-call wins)

### 🔧 Improvements

- **Header allowlist prefix matching** (#575): `MCP_MESH_PROPAGATE_HEADERS` now uses case-insensitive prefix matching — `x-audit` matches `x-audit-id`, `x-audit-source`, etc.

### 🐛 Bug Fixes

- **Registry dep_index alignment** (#574): Fixed dependency index positional alignment when dependencies can't be resolved — registry now preserves unresolved placeholder entries instead of empty arrays, ensuring Rust core assigns correct dep_index values
- **Pin fastmcp<3.0.0** (#574): Pinned across all Python source and examples to prevent breakage from FastMCP 3.0.0 breaking API changes
- **Watch mode detach logs** (#576): `meshctl start -w --detach` now writes agent stdout/stderr to per-agent log files (`~/.mcp-mesh/logs/<agent>.log`) instead of mixing everything into `meshctl.log`
- **Python header propagation** (#575): Fixed `decorators.py` middleware to use prefix matching for header allowlist (was exact-only, silently dropping prefixed headers)
- **Stale config warning removed** (#576): Removed noisy `cli_config.json` warning printed on every meshctl invocation since v0.9.5

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.4...v0.9.5)

## v0.9.5 (2026-02-17)

### ✨ New Features

- **Java SDK — `/health` endpoint** (#561): Added `GET` and `HEAD` `/health` endpoint to Java SDK for parity with Python and TypeScript runtimes

### 🔧 Improvements

- **Header propagation decoupled from distributed tracing** (#564): `MCP_MESH_PROPAGATE_HEADERS` now works across all SDKs (Python, Java, TypeScript) even when tracing is disabled — previously gated behind `MCP_MESH_DISTRIBUTED_TRACING_ENABLED`, silently dropping custom headers (auth tokens, tenant IDs)
- **Simplified tracing setup** (#554): Single `MCP_MESH_TRACING=true` env var enables end-to-end distributed tracing
- **Watch mode random port** (#552): Uses `MCP_MESH_HTTP_PORT=0` to eliminate "Address already in use" errors on restarts
- **Compile-before-restart in watch mode** (#556): Java runs `mvn compile` and Python runs `py_compile` before restarting, catching build errors early
- **Built-in retry for `meshctl trace`** (#555): Handles Tempo propagation delay automatically instead of requiring manual retries
- **Removed user-level config file** (#553): Eliminated `~/.mcp-mesh/config.yaml` to prevent cross-project conflicts

### 🐛 Bug Fixes

- **Java SDK** — `MeshEnvironmentPostProcessor` no longer overrides `server.port` for non-mesh Spring Boot apps (#558)
- **TypeScript SDK** — HTTP headers now propagate through `mesh.route()` Express middleware (#559)
- **meshctl** — `--env` flag uses `StringArray` instead of `StringSlice` so comma-separated values are not split (#564)
- **bump_version.py** — Added coverage for Docker image tags in `scaffold/compose.go` and Java pom.xml files in integration test artifacts (#560)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.3...v0.9.4)

## v0.9.4 (2026-02-10)

### 🐛 Bug Fixes

- **Java SDK — `List<Record>` @Param deserialization** (#548)
  - `@MeshTool` methods accepting `List<Record>` parameters (e.g., `List<TeamMember>`) received `List<LinkedHashMap>` at runtime due to Java type erasure — `MeshToolWrapper.ParamInfo` stored erased `Class<?>` instead of the full generic `Type` from `Method.getGenericParameterTypes()`; switched to `Type` and used Jackson `TypeFactory.constructType()` for proper parameterized type deserialization

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.2...v0.9.3)

## v0.9.3 (2026-02-10)

### 🐛 Bug Fixes

- **Java SDK — JavaTimeModule and isError guard in McpHttpClient** (#544)
  - `MeshMcpServerConfiguration` lacked `JavaTimeModule` — `@MeshTool` methods returning `java.time` types (`LocalDate`, `LocalTime`, `LocalDateTime`) threw `InvalidDefinitionException`; registered `JavaTimeModule` with `WRITE_DATES_AS_TIMESTAMPS=false` so java.time types serialize as ISO-8601 strings
  - `McpHttpClient.deserializeResult()` didn't check the MCP `isError` flag before attempting typed deserialization — upstream tool errors (returned as error text) caused `StreamReadException` instead of a proper `MeshToolCallException`; added `isError` check before `deserializeResult()` to convert upstream errors into `MeshToolCallException`

### 🔧 Improvements

- **meshctl man — cross-language links at top of pages**
  - Language variant links ("Also available: --typescript | --java") now appear near the top of man pages instead of at the bottom, making it easier to discover language-specific documentation

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.1...v0.9.2)

## v0.9.2 (2026-02-09)

### 🐛 Bug Fixes

- **meshctl start -w — Go fsnotify watch mode** (#533)
  - Replaced buggy bash-based watch mode with Go-native `AgentWatcher` using fsnotify, eliminating infinite restart cycles for Java agents and removing `watchfiles` pip dependency for Python
  - Event-driven file watching with debounce, process group termination, and automatic subdirectory watching — compiled into meshctl with zero runtime dependencies
  - TypeScript unchanged (`tsx --watch` works natively)

- **Java SDK — @MeshRoute generic type, consumer-only mode, and ObjectMapper centralization** (#532, #535, #536, #537)
  - `@MeshRoute` consumer-only mode: Spring Boot apps with `@MeshRoute` but no `@MeshAgent` now auto-start in consumer-only mode, registering as `agent_type=api`
  - `McpMeshTool<T>` generic type propagation: the full chain (BeanPostProcessor → DependencySpec → Interceptor → Proxy) now extracts and propagates the generic type, enabling typed deserialization instead of raw String
  - ObjectMapper centralization: replaced 8 bare `new ObjectMapper()` instances with `MeshObjectMappers.create()` factory; fixed silent deserialization fallback in `McpHttpClient`

### 🔧 Improvements

- **Version bump automation** — new `scripts/bump_version.py` handles 19 categories of version references across ~120 files with PEP 440 beta support and third-party dependency safety

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.9.0...v0.9.1)

## v0.9.1 (2026-02-08)

### 🐛 Bug Fixes

- **Release pipeline — PyPI indexing wait** (#526)
  - Docker builds could fail due to a race condition where `mcp-mesh-core` or `mcp-mesh` packages weren't indexed on PyPI yet when `pip install` ran
  - Added PyPI indexing wait steps to `publish-rust-core` and `publish-python` jobs, completing registry wait coverage for all 5 published packages (PyPI, npm, Maven Central)

- **meshctl scaffold — missing Java FreeMarker template** (#528)
  - `meshctl scaffold --lang java --agent-type llm-agent` generated code referencing a `.ftl` prompt template that was never created
  - Root cause: `.gitignore` blanket `prompts/` rule silently prevented the template from being tracked
  - Added gitignore exception and committed the missing template

- **Maven Central — incorrect external resource URLs**
  - Child module POMs inherited the parent `<url>` and Maven appended the `artifactId`, producing broken links on Maven Central
  - Added explicit `<url>` and `<scm>` to all child modules

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.8.1...v0.9.0)

## v0.9.0 (2026-02-07)

### ✨ New Features

- **Java SDK — Full Runtime Support** (#491)
  - New `mcp-mesh-spring-boot-starter` built on Spring Boot 4.0.2 + Spring AI 2.0.0-M2
  - Java agents participate as tool agents, LLM consumers, and LLM providers
  - Full cross-runtime interoperability (Java ↔ Python ↔ TypeScript)
  - Spring Boot auto-configuration for mesh registration, heartbeat, and discovery
  - MCP protocol support (tool listing, invocation, prompt handling)
  - Mesh delegation with `@MeshLlmProvider` and `@MeshRoute`
  - Distributed tracing support
  - 6 Maven modules: core, sdk, native, spring-boot-starter, spring-ai, bom

- **Java SDK — Auto-Port Detection** (#518)
  - Added `mesh_update_port` FFI binding to Rust core, enabling `MCP_MESH_HTTP_PORT=0` for Java agents
  - Java agents can now auto-detect their assigned port and report it to the registry

- **Java SDK — victools JSON Schema Generation** (#514)
  - Replaced manual schema building with victools `SchemaGenerator`
  - Structural parity with Python (Pydantic) and TypeScript (Zod) — produces `$defs`, `anyOf` for nullables, `required` arrays

- **meshctl scaffold — Java Support** (#497)
  - `meshctl scaffold --lang java` generates Spring Boot agent projects
  - 3 agent types: basic tool, LLM agent, LLM provider
  - Full template set: pom.xml, Application.java, application.yml, Dockerfile, helm-values

- **meshctl man — Java Documentation** (#495)
  - `meshctl man` now includes Java-specific guides: prerequisites, quickstart, deployment, capabilities

- **Java SDK on Maven Central** (#499)
  - Published under `io.mcp-mesh` namespace
  - Release pipeline: Rust FFI cross-compilation → fat JAR with native libs → GPG signing → Sonatype Central Portal
  - `mcpmesh/java-runtime` Docker image published to Docker Hub + GHCR

- **Custom Domain** — Documentation site moved from `dhyansraj.github.io/mcp-mesh` to [mcp-mesh.ai](https://mcp-mesh.ai/)

### 🔧 Improvements

- **LLM Provider Handler Refactoring** (all runtimes, #491)
  - Claude handler: TEXT + HINT only (removed unreliable STRICT mode)
  - OpenAI handler: STRICT mode with `response_format` for structured output
  - New base provider handler abstraction in Python and TypeScript

- **OTLP Tracing Flush Latency** (#514)
  - Buffer timeout reduced from 3s → 1s, flush ticker from 1s → 500ms
  - Residual spans now flush within ~1.5s instead of ~4-5s

- **Scaffold Cleanup** (#523)
  - Removed `--add-tool` feature (Python-only, complex, least-used)
  - Default port changed from 9000 to 8080
  - Enhanced basic tool templates with commented dependency injection and parameter examples

### 🐛 Bug Fixes

- **TypeScript SDK — Schema Injection** (#493): Fixed double-injection when provider delegates through mesh
- **meshctl start — Java Agent Name Detection** (#523): `isAgentFile()` now detects directory-based agents; `extractJavaAgentName()` parses `@MeshAgent` annotation instead of pom.xml artifactId
- **Java Native Library** (#511): `mcp-mesh-native` added as transitive dependency — users no longer need to manually manage native libs

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.8.0...v0.8.1)

## v0.8.1 (2026-01-29)

### 🔧 Improvements

- **TypeScript SDK - MESH*LLM*\* environment variables** (#484)
  - `MESH_LLM_PROVIDER`: Override LLM provider (direct mode only)
  - `MESH_LLM_MODEL`: Override model at runtime
  - `MESH_LLM_MAX_ITERATIONS`: Override max iterations
  - `MESH_LLM_FILTER_MODE`: Override tool filter mode

- **Python 3.13/3.14 support** (#485)
  - Updated pyproject.toml classifiers
  - Release workflow now builds wheels for Python 3.14

- Added scaffold test matrix (tc04-tc07) for llm-agent and llm-provider types
- New examples: context-self-dep-ts-direct, context-self-dep-ts-mesh
- Added 12 UC08 LLM prompt template tests

### 🐛 Bug Fixes

- **Scaffold TypeScript templates** (#482): Fixed templates to use `httpPort` instead of `port`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.21...v0.8.0)

## v0.8.0 (2026-01-27)

### ✨ New Features

- **Full TypeScript SDK** with `@mcpmesh/sdk` npm package (#391, #398, #400, #403, #406)
  - Express integration via `mesh.route()` for dependency injection (#396)
  - LLM agent support with `mesh.llm()` and provider plugin architecture (#398, #400)
  - Vercel AI SDK v6 compatibility (#412)
  - meshctl TypeScript support - start, watch, and manage TS agents (#406)

### 🔧 Improvements

- **Rust core runtime** for multi-language FFI support (#388, #394)
- **Agent name prefix matching** (#417) - `meshctl call calc` matches `calculator-agent`
- **AGE and LAST SEEN columns** (#452) - `meshctl list` now shows time since registration/heartbeat, following kubectl conventions
- **Rename McpMeshAgent to McpMeshTool** (#431) - Dependency injection type renamed for clarity
  - `McpMeshTool` is now the primary type for injected tool proxies
  - `McpMeshAgent` remains as deprecated alias for backward compatibility
  - Python: Shows runtime `DeprecationWarning` when `McpMeshAgent` is used
  - TypeScript: `@deprecated` JSDoc annotation for IDE warnings
- **Pre-flight checks before forking** (#444) - Validation errors now shown to user instead of hidden in log files when using `--detach`
- **Shutdown order fix** (#442) - Agents now stop first (in parallel), then registry. Added retry logic with exponential backoff for SQLite lock errors
- **Startup cleanup for stale agents** (#443) - Registry marks agents as unhealthy if no heartbeat within threshold (default 30s). Safe for multi-replica K8s deployments

### 🐛 Bug Fixes

- **Python SDK race condition** (#448) - Fixed `provider_proxy` being wiped by tools update. Now uses field-level updates to preserve data
- **TypeScript SDK template paths** (#449) - `file://` templates now resolve relative to package.json location, not `process.cwd()`
- **Scaffold template cleanup** (#446, #450) - Removed redundant transitive dependencies (`@ai-sdk/*`, `zod`) from TypeScript templates
- **addLlmProviderTool** now respects the `name` parameter (#407)
- **http_port=0 auto-assignment** (#430) - Fixed port auto-assignment in both Python and TypeScript SDKs
  - Python: Port detection now works correctly with uvicorn auto-assigned ports
  - TypeScript: Fixed port=0 being overridden to 8080

### 📚 Documentation

- README refresh with Python/TypeScript dual-language examples (#410)
- Feature comparison table and proxy/LLM documentation updates (#410)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.21...v0.8.0)

## v0.7.21 (2026-01-07)

### 🐛 Bug Fixes

- **Reduce API heartbeat pipeline logging verbosity** (#379): Downgrade routine logs from INFO/DEBUG to TRACE
  - API heartbeat pipeline now consistent with MCP pipeline logging
  - DEBUG mode shows only one summary line per heartbeat
  - INFO mode shows every 10th heartbeat, topology changes, and errors

- **Use parent directory name for main.py log files** (#382): Better log file naming for scaffolded agents
  - When filename is `main`, uses parent directory name for logs
  - `my-api/main.py` → `my-api.log` instead of `main.log`
  - Helps pure FastAPI apps with `@mesh.route` that don't have `@mesh.agent`

### 📚 Documentation

- **Add FAQ section** (#380, #381): New FAQ page in documentation
  - How to use `@mesh.tool` for background tasks (Redis consumers, cron jobs)
  - How to organize `@mesh.tool` functions across multiple files
  - Logging levels and heartbeat verbosity
  - Log file naming conventions

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.19...v0.7.20)

## v0.7.20 (2026-01-05)

### 🐛 Bug Fixes

- **Fix log/PID naming for scaffolded agents** (#376): Extract agent name from `@mesh.agent` decorator
  - Scaffolded agents (which use `main.py`) now correctly use decorator name for logs
  - Log files named by agent: `hello-world.log` instead of `main.log`
  - Uses Python AST for reliable parsing of all decorator syntax variations
  - Thread-safe caching with `sync.Map` for concurrent agent starts
  - Cross-platform support (Windows `.venv\Scripts\python.exe`)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.18...v0.7.19)

## v0.7.19 (2026-01-05)

### ✨ New Features

- **meshctl stop command** (#367): Stop detached agents and registry
  - `meshctl stop [name]` to stop specific agent or all processes
  - Per-agent PID files in `~/.mcp-mesh/pids/` (replaces single global PID)
  - Parallel agent shutdown with configurable timeout (default 10s)
  - Flags: `--registry`, `--agents`, `--keep-registry`, `--force`, `--timeout`, `--quiet`
  - Deprecates `--pid-file` flag (now managed automatically)

- **meshctl logs command** (#368): View agent logs in detached mode
  - Log files stored in `~/.mcp-mesh/logs/` with automatic rotation (5 files per agent)
  - Filtering: `-f` (follow), `-p` (previous), `--tail`, `--since`, `--until`
  - Standardized log format across Go/Python: `2026-01-05 14:24:38 INFO message`

- **meshctl stop --clean flag** (#372): Complete cleanup after stopping
  - Deletes registry database, log files, and PID files
  - Enables fresh start for development/testing

- **Observability documentation** (#370): New `meshctl man observability` page
  - CLI tracing with `meshctl call --trace` and `meshctl trace <id>`
  - Grafana/Tempo setup for Docker Compose and Kubernetes

### 🐛 Bug Fixes

- **Fix --env-file flag** (#369): Fixed completely non-functional `--env-file` flag in `meshctl start`
  - Env vars are now properly loaded and passed to agents

### 🔧 Improvements

- **Full LLM request/response logging** (#370): Enable debug logging at provider level
- **Remove default log truncation** (#370): `format_log_value()` no longer truncates by default
- **Better trace error messages** (#370): Helpful hints when trace not found

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.17...v0.7.18)

## v0.7.18 (2026-01-04)

### 🐛 Bug Fixes

- **Fix trace context propagation** (#326): Fixed flat trace hierarchy in distributed tracing
- **Fix registry URL in Helm values** (#357): Use correct `mcp-core-mcp-mesh-registry:8000` service name
- **Fix scaffold --compose --observability without agents** (#353): Generate infrastructure-only stack
- **Add missing watchfiles dependency** (#351): Added to pyproject.toml

### 📚 Documentation

- **Reorganize man pages** (#354): Improved `meshctl man llm`, `tags`, and `scaffold` documentation
- **Clarify meshctl call syntax** (#355): Use `[agent-ID:]tool_name` with realistic examples
- **Remove deprecated --healthy-only flag** (#352): Cleaned up stale documentation

### 🧹 Cleanup

- **Remove legacy examples/k8s directory** (#358): Replaced by Helm charts and scaffold
- **Consolidate logo files**: Moved to `docs/assets/images/`
- **Remove unused scripts**: Deleted `run-tests.sh`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.16...v0.7.17)

## v0.7.17 (2026-01-03)

### ✨ New Features

- **Add file watch mode for meshctl start** (#347): Auto-restart agents on file changes
  - Add `--watch/-w` flag for development workflows
  - Uses `watchfiles` library for reliable file monitoring
  - Each agent watches its own directory independently
  - Supports both `meshctl start` and direct Python execution

- **Add TRACE log level for SQL query logging** (#347): Separate SQL logging from DEBUG mode
  - `--debug` no longer shows Ent SQL queries
  - Use `MCP_MESH_LOG_LEVEL=TRACE` for SQL debugging

### 🐛 Bug Fixes

- **Fix scaffold llm-agent template issues** (#348):
  - Remove `response_format` parameter (causes LiteLLM TypeError)
  - Use `file://prompts/<name>.jinja2` for system_prompt (makes context_param work)
  - Dynamic file listing shows all generated files including prompts/ directory

- **Fix websockets deprecation warnings** (#347): Add `ws="websockets-sansio"` to uvicorn configs

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.15...v0.7.16)

## v0.7.16 (2026-01-03)

### ✨ New Features

- **Add pre-flight validation to meshctl start** (#338): Validates environment before running agents
  - Requires `.venv` in current directory (no fallback to system Python)
  - Validates Python version >= 3.11

- **Improve scaffold output** (#341): Better feedback after scaffolding
  - Display file tree of generated files
  - Show clear next steps for running the agent

### 🐛 Bug Fixes

- **Fix scaffold --observability missing Grafana provisioning** (#335): Added missing Grafana datasource/dashboard provisioning
- **Fix invalid agent.port in scaffold helm-values.yaml** (#339): Changed to `agent.http.port` with correct default
- **Fix Helm chart image tags to use minor version** (#340): Use `0.7` instead of `0.7.x` to track latest patch automatically

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.14...v0.7.15)

## v0.7.15 (2026-01-02)

### 🐛 Bug Fixes

- **Fix trace context propagation causing flat trace hierarchy** (#326): Fixed distributed tracing bug where all downstream calls incorrectly had the external span as parent
  - Use httpx `event_hooks` to inject trace headers at request time instead of transport construction
  - Ensures correct parent span is propagated to downstream agents
  - Added `examples/observability-test/` with 4-agent setup for trace hierarchy testing

- **Remove redundant mcp-mesh from scaffolded requirements.txt** (#325): Removed duplicate dependency from scaffold templates
  - `mcp-mesh` is already provided by runtime environment (Docker image or local install)
  - Prevents version conflicts and reduces confusion

### ⬆️ Dependencies

- **Update Grafana to 12.3.1 and Tempo to 2.9.0** (#329): Update observability stack versions
  - Grafana: 11.4.0 → 12.3.1
  - Tempo: 2.8.1 → 2.9.0
  - Updated in scaffold templates, Helm charts, k8s deployments, and docker-compose examples

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.13...v0.7.14)

## v0.7.14 (2026-01-02)

### 🐛 Bug Fixes

- **Fix scaffold --compose --observability tracing config** (#320): Fixed incomplete tracing configuration
  - Add missing registry tracing env vars (`TRACE_EXPORTER_TYPE`, `TELEMETRY_ENDPOINT`, `TELEMETRY_PROTOCOL`, `TEMPO_URL`)
  - Generate `tempo.yaml` config file when `--observability` is set
  - Update Tempo version from 2.3.1 to 2.8.1
  - Add `tempo-data` volume for trace persistence

- **Fix registry port default docs** (#322): Corrected `--registry-port` help text from 8080 to 8000

### ✨ New Features

- **Add observability to existing compose** (#320): Support running `--observability` on existing docker-compose files
  - Merge tracing env vars into existing registry and agent services
  - Preserve user-added environment variables when merging

### 📚 Documentation

- **Capability Selector Syntax** (#322): Add unified documentation for dependency selection
  - New "Capability Selector Syntax" section in `meshctl man capabilities`
  - Document AND/OR semantics for tag matching
  - Add cross-references from `di`, `llm`, `tags`, and `scaffold` man pages
  - Add `--filter` flag documentation to `meshctl man scaffold`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.12...v0.7.13)

## v0.7.13 (2026-01-01)

### ✨ New Features

- **LLM response metadata** (#314): Add `_mesh_meta` to LLM results with provider, model, token counts, and latency for cost tracking

  ```python
  result = await llm(question)
  print(result._mesh_meta.model)          # "openai/gpt-4o"
  print(result._mesh_meta.input_tokens)   # 100
  print(result._mesh_meta.output_tokens)  # 50
  print(result._mesh_meta.latency_ms)     # 125.5
  ```

- **Distributed tracing** (#313): Add `meshctl trace <id>` command and `--trace` flag for call tree visualization

  ```bash
  meshctl call smart_analyze '{"query": "test"}' --trace
  meshctl trace abc123  # View call tree
  ```

- **Model override in @mesh.llm** (#312): Allow consumers to specify model override with mesh delegation
  - Request specific model variant from provider (e.g., use haiku instead of default sonnet)
  - Vendor mismatch validation with automatic fallback

- **meshctl UX improvements** (#309):
  - `meshctl list` shows healthy agents by default, use `--all` for all
  - `meshctl status [agent-id]` shows details for specific agent
  - `meshctl list --tools=<name>` displays full input schema via registry proxy

- **Registry proxy** (#307): Add reverse proxy endpoint for external meshctl access
  - Call agents from outside Docker/K8s without exposing individual ports
  - Routes calls through registry by default (`--use-proxy=true`)

- **Decorator-level LLM params** (#305): Pass `max_tokens`, `temperature`, etc. from `@mesh.llm` decorator to provider
  ```python
  @mesh.llm(max_tokens=16000, temperature=0.7)
  def my_tool(llm=None):
      return llm(messages)  # params now respected
  ```

### 🐛 Bug Fixes

- **Normalize HTTP fallback response** (#304): Consistent response format between FastMCP and HTTP transport
- **Connection error hints** (#303): Helpful guidance when `meshctl call` fails from outside Docker/K8s
- **Code review improvements** (#301): Fix connection pooling, session cleanup, thread safety race condition
  - ~3000 lines of duplicate/dead code removed
  - Consolidated MCP proxies, health check logic, and heartbeat setup

### 🗑️ Removed

- **Remove auto-restart/watch-files** (#316): Remove unreliable `--auto-restart` and `--watch-files` flags
  - Features were unreliable due to subprocess/venv management issues
  - Users can reliably use Ctrl+C or kill signals to stop and manually restart agents

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.11...v0.7.12)

## v0.7.12 (2025-12-22)

### 🐛 Bug Fixes

- **scaffold --compose**: Preserve existing service configurations (#281)
  - Merges new agents without overwriting user modifications
  - Added `--force` flag to regenerate all configurations when needed
  - Infrastructure services never overwritten unless `--force` used

- **scaffold --compose**: Install requirements.txt dependencies at container startup (#283)
  - Third-party packages now work in dev mode (beautifulsoup4, pandas, etc.)
  - Packages cached in named volumes for fast subsequent starts

- **Logging cleanup**: Allowlist approach + remove noisy logs (#284)
  - Python: Root logger stays INFO, only mcp-mesh loggers get DEBUG
  - Go: Removed excessive troubleshooting logs from registry

### 📚 Documentation

- Update Helm chart version references to 0.7.11 (#287)
- Add ENTRYPOINT comments to Dockerfile templates for AI assistants
- Clarify FastAPI integration is for existing apps
- Update meshctl --help to emphasize framework over ops tool
- Add port strategy section for local vs Kubernetes
- Improve meshctl call docs for Docker Compose and Kubernetes

### ✨ Branding

- Add cyan logo to README with dark mode support (#285)
- Add YouTube channel link to README and mkdocs (#286)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.10...v0.7.11)

## v0.7.11 (2025-12-16)

### 🐛 Bug Fixes

- **SSE read timeout**: Fixed MCP SDK 1.24.0+ compatibility issue (#268)
  - MCP SDK deprecated `sse_read_timeout` parameter on `StreamableHttpTransport`
  - Now uses `httpx_client_factory` to configure httpx client with custom timeouts
  - Fixes connection timeout errors when agents take longer than default timeout

### 📚 Documentation

- **meshctl man prerequisites**: Clarified that meshctl auto-detects `.venv` (#270)
  - meshctl is a Go binary that auto-detects `.venv` in the current directory
  - Users only need to activate venv for `pip` commands
  - meshctl uses `.venv/bin/python` automatically when running agents

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.9...v0.7.10)

## v0.7.10 (2025-12-16)

### 🐛 Bug Fixes

- **LLM tool resolutions**: Fixed tags-only filters not being stored in registry database (#257)
  - Previously, `filter=[{"tags": ["tools"]}]` was skipped during storage
  - Now all resolved tools are properly stored for tags-only filters

### ✨ Enhancements

- **meshctl status --insecure**: Added `--insecure` flag for self-signed TLS certificates (#259)
  - Consistent with `meshctl list` and `meshctl call` commands
- **Cleaner DEBUG logs**: Suppressed noisy docket task queue logs (#261)
  - Removed spam like "Scheduling due tasks", "Getting redeliveries" in tight loops
  - MCP Mesh DEBUG logs remain visible
- **Anthropic health check**: Use GET /v1/models instead of HEAD /v1/messages (#263)
  - Returns proper 200 status (not hacky 405 workaround)
  - Free endpoint, no tokens consumed
  - Validates API key and confirms API reachability

### 📚 Documentation

- **@mesh.llm response_format**: Clarified that format is determined by return type annotation (#264)
  - `-> str` for text output, `-> PydanticModel` for structured JSON
  - Removed misleading `response_format` parameter from examples
- **Virtual environment**: Clarified venv should be at project root, shared by all agents (#264)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.8...v0.7.9)

## v0.7.9 (2025-12-15)

### 🐛 Bug Fixes

- **meshctl start**: Fixed Ctrl+C to properly stop registry in file watching mode (#251)
  - Previously, pressing Ctrl+C only stopped the agent but left the registry running
  - Now both agent and registry stop cleanly with a single Ctrl+C

### 📚 Documentation

- **meshctl man prerequisites**: New man topic covering system requirements (#249)
  - Local development setup with Python 3.11+ and virtual environments
  - Docker deployment prerequisites
  - Kubernetes deployment with Helm charts
  - Windows WSL2/Git Bash requirement note
- **Python 3.11+**: Updated minimum Python version from 3.9 to 3.11+ across all documentation (#249)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.7...v0.7.8)

## v0.7.8 (2025-12-15)

### 🐛 Bug Fixes

- **meshctl start**: Fixed `mcp-mesh-registry` not found when installed via npm (#245)
  - Registry binary lookup now properly searches the system PATH using `exec.LookPath()`
  - Previously only checked local directories with `os.Stat()`, which doesn't search PATH

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.6...v0.7.7)

## v0.7.7 (2025-12-15)

### 🐛 Bug Fixes

- **@mesh.llm with text mode**: Fixed `AttributeError: type object 'str' has no attribute 'model_json_schema'` when using `response_format="text"` (#239)

### ✨ Features

- **meshctl list --id**: New LLM resolution display sections (#241)
  - LLM Tool Filters - Shows filter configuration from `@mesh.llm` decorator
  - LLM Tool Resolutions - Shows resolved tools with endpoints
  - LLM Providers - Shows provider requirements with preference tags
  - LLM Provider Resolutions - Shows which provider agent was selected
- **Example LLM providers**: Added `claude-provider` and `openai-provider` example agents (#241)
- **Example agent**: Added `llm_with_deps_agent.py` demonstrating both LLM and static dependencies (#241)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.5...v0.7.6)

## v0.7.6 (2025-12-14)

### 🐛 Bug Fixes

- **@mesh.llm_provider**: Preserves original function name to avoid conflicts when multiple providers are used (#227)
- **meshctl scaffold --compose**: Generates correct command without redundant python prefix (#222)
- **Dockerfile templates**: Fixed non-root user permissions in scaffolded Dockerfiles (#226)
- **Registry version**: Fixed double 'v' in version output and updated description (#235)
- **Helm docs**: Removed redundant python from command examples (#225)

### ✨ Features

- **Configurable core release name**: Added `global.coreReleaseName` for flexible Helm service hostnames (#224)

### 📚 Documentation

- **meshctl man scaffold**: New topic for agent scaffolding command (#223)
- **meshctl man cli**: New topic covering call, list, status commands (#234)
- **Deployment docs**: Added Apple Silicon buildx hint and use `--create-namespace` (#236)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.4...v0.7.5)

## v0.7.5 (2025-12-12)

### 📚 Documentation

- **Installation simplification**: npm is now the primary installation method across all docs
- **Component-based organization**: Installation docs reorganized by component (meshctl, Registry, Python Runtime, Docker, Helm)
- **New tagline**: "Production-grade distributed mesh for intelligent agents"
- **Philosophy update**: Added "Why MCP Mesh?" section explaining agent autonomy philosophy
- **Core principles**: Added "LLMs are first-class capabilities" to documentation

### 🧹 Cleanup

- Removed accidentally committed `prompts/` folder
- Updated troubleshooting sections for npm-based installation

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.3...v0.7.4)

## v0.7.4 (2025-12-12)

### 🐛 Bug Fixes

- **npm packages**: Fixed `mcp-mesh-registry` missing from macOS npm packages
  - Now downloads pre-built binaries from GitHub releases instead of cross-compiling
  - All platforms (Linux x64/arm64, macOS x64/arm64) include both `meshctl` and `mcp-mesh-registry`

### 📦 Infrastructure

- Simplified npm build process by reusing release assets
- Removed CGO cross-compilation dependency from npm publish workflow

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.2...v0.7.3)

## v0.7.3 (2025-12-11)

### 📦 npm Package Enhancement

- **mcp-mesh-registry in npm**: Both `meshctl` and `mcp-mesh-registry` binaries are now bundled in the `@mcpmesh/cli` npm package
  - `npm install -g @mcpmesh/cli` installs both tools
  - `meshctl` - CLI for managing MCP Mesh agents and tools
  - `mcp-mesh-registry` - Registry service for service discovery
  - Supported platforms: Linux (x64, arm64), macOS (x64, arm64)

### 📦 Infrastructure

- Added CGO cross-compilation support for registry binary in npm build
- Simplified platform support to Linux and macOS (Windows users should use WSL2 or Docker)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.1...v0.7.2)

## v0.7.2 (2025-12-11)

### 🎯 CLI Tool Invocation & Discovery

- **meshctl call**: New command to invoke MCP tools directly from the CLI
  - `meshctl call <tool_name> '{"arg": "value"}'` - invoke any tool
  - Automatic agent discovery - finds which agent provides the tool
  - Support for `agent:tool` syntax to target specific agents
  - Pretty-printed JSON output

- **meshctl list --tools**: Enhanced tool discovery across all agents
  - `meshctl list --tools` - list all tools from all connected agents
  - `meshctl list --tools=<tool>` - show tool details with input schema
  - Great for LLM discoverability

### 📦 npm Package Distribution

- **@mcpmesh/cli**: Install meshctl via npm for easy LLM integration
  - `npm install -g @mcpmesh/cli`
  - Platform-specific binary packages (linux, darwin, win32 × x64, arm64)
  - Automatic platform detection and binary setup
  - Enables LLMs like Claude to install and use meshctl directly

### 📚 Documentation

- Updated all documentation examples to use `meshctl call` instead of curl
- Improved getting started guides with CLI-first approach

### 📦 Infrastructure

- GitHub Actions workflow for automated npm publishing on release
- Makefile targets: `npm-build`, `npm-publish`, `npm-clean`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.7.0...v0.7.1)

## v0.7.1 (2025-12-10)

### 📚 Documentation

- Simplified observability documentation with troubleshooting pipeline focus
- Updated Helm documentation to correctly explain mcp-mesh-core umbrella chart
- Streamlined Kubernetes deployment docs to focus on Helm
- Removed broken mike versioning configuration

### 🐛 Bug Fixes

- Fixed documentation version display in header

### 📦 Infrastructure

- Updated all Helm charts to version `0.7.1`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.4...v0.7.0)

## v0.7.0 (2025-12-04)

### 🎯 Agent Scaffolding & Developer Experience

- **Agent Scaffolding**: New `meshctl scaffold` command for generating agent boilerplate code from templates
  - Multiple template types: basic, tool, llm, advanced
  - Interactive prompts or CLI flags for configuration
  - Generates ready-to-run agent code with proper structure

- **Embedded Documentation**: New `meshctl man` command for viewing documentation without leaving the terminal
  - Browse documentation by topic
  - Search functionality for finding specific content
  - Offline-friendly - no network required

### 📊 Features

- **Runtime Context Injection for MeshLlmAgent**: LLM agents can now receive runtime context for dynamic behavior (#186)
  - Pass context at invocation time for agent customization
  - Supports dynamic prompt construction based on runtime state

- **FastAPI Route Dependency Injection**: Fixed `@mesh.route` decorator to properly inject dependencies in FastAPI routes (#188)
  - Uses `METHOD:path` format as unique route identifier (e.g., "GET:/api/v1/time")
  - Works with both direct `@mesh.route` and `APIRouter` patterns
  - Proper function signature preservation

### 🐛 Bug Fixes

- Fixed dependency injection for FastAPI routes when using `@mesh.route` decorator
- Fixed route wrapper registration to use full `METHOD:path` identifier

### 📦 Infrastructure

- Updated all Docker images to use `0.7` tag
- Updated all Helm charts to version `0.7.0`
- Updated Kubernetes manifests and CRDs with new image tags
- Updated Homebrew formula and Scoop manifest

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.3...v0.6.4)

## v0.6.4 (2025-11-30)

### 🐛 Bug Fixes

- **Missing PyPI Dependencies**: Added missing `litellm`, `jinja2`, and `cachetools` dependencies to PyPI package configuration
  - Fixes `jinja2 is required for template rendering` error
  - Fixes `litellm is required for MeshLlmAgent` error
  - Root cause: `packaging/pypi/pyproject.toml` was out of sync with `src/runtime/python/pyproject.toml`

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.2...v0.6.3)

## v0.6.3 (2025-11-30)

### 🎯 LLM Provider Handler Enhancements

- **Enhanced Model Name Handling**: Improved model name extraction and validation for direct LiteLLM provider calls
- **Response Format Injection**: Better response format configuration for Claude and OpenAI handlers
- **Provider Handler Support**: Enhanced provider handler selection and configuration
- **LLM Config Improvements**: Refactored LLM configuration handling for cleaner provider integration

### 📊 Features

- Enhanced `ClaudeHandler` and `OpenAIHandler` for more robust response processing
- Improved `MeshLLMAgentInjector` for better dependency injection
- Cleaner `ResponseParser` implementation for LLM responses

### 🐛 Bug Fixes

- Fixed response format injection for various LLM provider configurations
- Improved error handling in provider handlers

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.1...v0.6.2)

## v0.6.2 (2025-11-25)

### 🎯 LLM Provider Handler Fix

- **Vendor Extraction from Model Name**: Extract vendor from LiteLLM model strings (e.g., `anthropic/claude-sonnet-4-5` → `anthropic`) for proper provider handler selection in direct LiteLLM calls
- **Self-Dependency with @mesh.llm**: Fixed self-dependency injection to use wrapper function instead of original, ensuring LLM agent is properly injected

### 📊 Features

- Automatic vendor detection from model name for correct response format injection
- ClaudeHandler now properly used for `anthropic/*` models even with direct `provider="claude"` calls
- Added self-dependency test for `@mesh.llm` decorated functions

### 🐛 Bug Fixes

- Fixed curl syntax in documentation to include proper MCP headers (`Accept: application/json, text/event-stream`)
- Fixed self-dependency injection to use wrapper instead of original function (#169)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.6.0...v0.6.1)

## v0.6.1 (2025-11-24)

### 🎯 Health Check Support

- **Custom Health Check Decorator**: New `@mesh.health_check()` decorator for defining agent health logic
- **Kubernetes-Compatible Endpoints**: Added `/health`, `/ready`, `/live`, `/startup`, and `/metrics` endpoints
- **TTL-Based Caching**: Per-key TTL support (default 15s) for health check results to reduce overhead
- **Flexible Return Types**: Support for bool, dict, and HealthStatus return types from health check functions

### 📊 Features

- K8s-compatible health endpoints with automatic health status aggregation
- Automatic DEGRADED status on health check exceptions for resilience
- DecoratorRegistry integration for efficient health status storage
- Comprehensive test coverage with 239 new test lines

### 🐛 Bug Fixes

- Fixed TTL cache expiration behavior by implementing manual per-key expiry tracking
- Updated test assertions for DEBUG level logging (was INFO)
- Removed IDE-specific files from version control (.emigo_repomap, .windsurf, .windsurfrules)

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.7...v0.6.0)

## v0.6.0 (2025-11-20)

### 🎯 Dependency Resolution Tracking

- **Persistent Dependency Tracking**: Track and persist both resolved and unresolved dependencies in database
- **Enhanced Visibility**: Display dependency status in `meshctl list agents` with clear visual indicators
- **Topology Awareness**: Automatically update dependency status when provider agents go offline
- **Comprehensive Testing**: Full test coverage for dependency persistence and topology changes

### 📊 Features

- New `dependency_resolutions` table storing consumer/provider relationships
- Visual dependency table in meshctl showing: DEPENDENCY | MCP TOOL | ENDPOINT
- Color-coded status indicators (red for unresolved, green for resolved)
- Registry connection flags for meshctl (--registry-host, --registry-port, --registry-url)
- Support for both `[]interface{}` and `[]map[string]interface{}` dependency types

### 🐛 Bug Fixes

- Fixed health check port configuration in Docker Compose
- Updated health checks to use Python urllib instead of wget
- Corrected registry Dockerfile path references

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.6...v0.5.7)

## v0.5.7 (2025-11-06)

### 🎯 Dependency Injection Enhancements

- **Array-based Dependency Injection**: Support for multiple dependencies with the same capability name but different tags/versions
- **Improved Type Support**: Updated warning messages to reflect support for both `McpAgent` and `McpMeshAgent` types

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.5...v0.5.6)

## v0.5.6 (2025-09-21)

### 🔧 Graceful Shutdown and Registry Cleanup

- Implemented clean shutdown architecture with FastAPI lifespan integration
- Added proper DELETE /agents/{agent_id} registry cleanup when agents terminate
- Fixed race conditions between heartbeat and shutdown threads
- Enhanced agent lifecycle management with graceful signal handling
- Improved DNS atexit threading reliability for Kubernetes environments

### 🚀 System Improvements

- Updated environment variable configuration: MCP_MESH_REGISTRY_URL for Docker/K8s compatibility
- Fixed CI test hanging issues with MCP_MESH_AUTO_RUN=false configuration
- Enhanced error handling and logging for production debugging
- Streamlined agent startup and shutdown processes

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.3...v0.5.5)

## v0.5.3 (2025-08-16)

### GitHub Pipeline Fixes

- Fixed Docker registry binary path resolution
- Fixed release artifact checksum generation
- Improved release workflow reliability

[Full Changelog](https://github.com/dhyansraj/mcp-mesh/compare/v0.5.2...v0.5.3)

## v0.5.2 (2025-08-16)

### 🍎 macOS Support & Platform Improvements

**Native macOS Binary Distribution**

- Added native macOS builds for both Intel (`darwin/amd64`) and Apple Silicon (`darwin/arm64`) architectures
- Implemented automated Homebrew tap distribution via `dhyansraj/homebrew-mcp-mesh`
- Fixed binary naming consistency: standardized on `mcp-mesh-registry` across all platforms
- Enhanced GitHub Actions pipeline with cross-platform build support and automated package manager updates

**Enhanced Installation Experience**

- **Homebrew Support**: `brew tap dhyansraj/mcp-mesh && brew install mcp-mesh`
- **PATH Resolution**: Improved binary discovery for both development and system installations using `exec.LookPath()`
- **Cross-Platform Install Script**: Updated `install.sh` to handle macOS/Linux differences seamlessly

**Distributed Tracing Reliability**

- Fixed silent tracing failures that were preventing proper observability data collection
- Enhanced FastAPI middleware integration for more robust trace capture
- Improved context handling and metadata publishing to Redis streams
- Updated Grafana dashboards with better trace visualization

### 🏷️ Migration Guide

**Upgrading from v0.5.1:**

- **Python Package**: Update to `pip install "mcp-mesh>=0.5.2,<0.6"`
- **macOS Users**: Install via Homebrew: `brew tap dhyansraj/mcp-mesh && brew install mcp-mesh`
- **Docker Images**: Use `mcpmesh/registry:0.5.2` and `mcpmesh/python-runtime:0.5.2`
- **Helm Charts**: All charts now use v0.5.2 for consistent dependency management

**Breaking Changes:**

- None - this release maintains full backward compatibility with v0.5.1
- Binary names are now consistent (`mcp-mesh-registry`) but old references will continue to work

### 📦 Distribution Improvements

- **GitHub Actions**: Native macOS builds with proper Gatekeeper signing preparation
- **Homebrew Automation**: Automatic formula updates with cross-platform checksum verification
- **Enhanced CI/CD**: Improved reliability with disabled Go cache and proper dependency management

---

## v0.5.1 (2025-08-14)

### 🔧 Major Enhancement Release - Unified Telemetry Architecture

**FastMCP Client Integration**

- Replaced custom MCP client with official FastMCP client library for better protocol compliance
- Enhanced error handling and timeout management with official client optimizations

**Unified Telemetry Architecture**

- Moved telemetry from HTTP middleware to dependency injection wrapper for complete coverage
- Added distributed tracing support for FastAPI routes with `@mesh.route()` decorators
- Unified agent ID generation across MCP agents and API services
- Redis stream storage for all telemetry data in `mesh:trace`

**Agent Context Enhancement**

- 3-step agent ID resolution: cached → @mesh.agent config → synthetic defaults
- Environment variable priority: `MCP_MESH_API_NAME` → `MCP_MESH_AGENT_NAME` → `api-{uuid8}`
- Comprehensive metadata collection with performance metrics

### 🏷️ Migration Guide

**Upgrading from v0.5.0:**

- **Python Package**: Update to `pip install "mcp-mesh>=0.5.1,<0.6"`
- **Docker Images**: Use `mcpmesh/registry:0.5.1` and `mcpmesh/python-runtime:0.5.1`
- **Helm Charts**: All charts now use v0.5.1 for consistent dependency management

**Breaking Changes:**

- None - this release maintains full backward compatibility with v0.5.0

---

## v0.5.0 (2025-08-13)

### 🚀 Major Release - FastAPI Dependency Injection Integration

**FastAPI Native Support**

- Complete FastAPI dependency injection system integration with MCP Mesh decorators
- Seamless interoperability between FastAPI's `Depends()` and mesh dependency resolution
- Type-safe dependency injection with automatic provider discovery and lifecycle management
- Introduced new `@mesh.route` decorator exclusively for FastAPI apps to inject MCP Mesh agents

**Advanced Dependency Resolution**

- Added +/- operator support in tags: + means preferred, - means exclude

### 🐛 Bug Fixes & Stability

- Enhanced support for large payload and response handling

### 🏷️ Migration Guide

**Upgrading from v0.4.x**

- **Python Package**: Update to `pip install "mcp-mesh>=0.5,<0.6"`
- **Docker Images**: Use `mcpmesh/registry:0.5` and `mcpmesh/python-runtime:0.5`
- **Helm Charts**: All charts now use v0.5.0 for consistent dependency management
- **Configuration**: Update any hardcoded version references in deployment manifests

**Breaking Changes**

- None - this release maintains full backward compatibility with v0.4.x
- Enhanced FastAPI integration is additive and does not affect existing code
- All existing decorators and patterns continue to work unchanged

---

## v0.4.2 (2025-08-11)

### 🔧 Critical Bug Fixes

**SSE Parsing Reliability**

- Fixed sporadic JSON parsing errors during large file processing (>15KB files)
- Consolidated duplicate SSE parsing logic across 3 proxy classes for improved maintainability
- Enhanced error handling with context-aware debugging for better troubleshooting
- Added shared `SSEParser` utility class with proper JSON accumulation logic

**FastMCP Discovery Stability**

- Fixed `RuntimeError: dictionary changed size during iteration` crashes during agent startup
- Applied thread-safe dictionary iteration patterns to prevent concurrent modification errors
- Improved startup reliability for complex multi-agent environments

**Code Consolidation**

- Eliminated duplicate SSE parsing code across `MCPClientProxy`, `AsyncMCPClient`, and `FullMCPProxy`
- Added `SSEStreamProcessor` for consistent streaming support
- Enhanced debugging capabilities with contextual logging

### 📁 New Files Added

- `src/runtime/python/_mcp_mesh/shared/sse_parser.py` - Consolidated SSE parsing utilities

### 🧪 Enhanced Examples

- Updated LLM chat agent with real Claude API integration and tool calling support
- New comprehensive chat client agent demonstrating advanced dependency injection patterns
- Improved large file processing examples with 100% reliability testing

### 📈 Validation Results

- ✅ **Large file processing**: 100% reliability with 23KB+ files generating 6K+ token responses
- ✅ **Agent startup**: Eliminated intermittent crashes during FastMCP server discovery
- ✅ **Code quality**: Consolidated duplicate logic improving maintainability and reducing technical debt
- ✅ **Testing**: Verified with real-world scenarios including rapid startup/shutdown cycles

---

## v0.4.1 (2025-08-10)

### 🏷️ Enhanced Tag Matching

**Smart Service Discovery**

- Enhanced tag matching with `+` (preferred) and `-` (excluded) operators
- Priority scoring system for intelligent provider selection
- Industry-standard syntax similar to Kubernetes label selectors

**Migration & Compatibility**

- Complete backward compatibility with existing exact tag matching
- Comprehensive migration guide and documentation updates
- Test-driven development with extensive unit test coverage

### 📚 Documentation

- Updated mesh decorators documentation with enhanced tag examples
- Migration guide for upgrading from exact matching to enhanced matching
- Smart LLM provider selection patterns with cost control examples

---

## v0.4.0 (2025-07-31)

### 🔍 Observability & Monitoring

**Complete Observability Stack**

- Full Grafana + Tempo integration for Kubernetes and Helm deployments
- Pre-configured dashboards with MCP Mesh branding and metrics
- Production-ready monitoring with persistent storage support

**Real-Time Trace Streaming**

- Live trace streaming API (`/traces/{trace_id}/stream`) with Server-Sent Events
- Watch multi-agent workflows execute in real-time through web dashboards
- Redis consumer groups for scalable trace data processing

**Distributed Tracing System**

- Redis streams integration for trace data storage (`mesh:trace` stream)
- OTLP export with direct protobuf generation for Tempo/Jaeger compatibility
- Cross-agent context propagation maintaining parent-child span relationships
- Complete observability directory structure with organized assets

### 🏗️ Architecture & Deployment

**Enhanced Kubernetes Support**

- New observability components in `k8s/base/observability/` and `examples/k8s/base/observability/`
- Distributed tracing environment variables for all agent deployments
- Complete Helm chart ecosystem with dedicated observability charts

**Multi-Agent Dependency Injection**

- Complex data processor example with modular tools and utilities
- Advanced agent architecture with parsing, transformation, analysis capabilities
- Comprehensive Docker containerization and development workflows

### ⚙️ Infrastructure Improvements

**Helm Chart Enhancements**

- New `mcp-mesh-grafana` and `mcp-mesh-tempo` charts
- Enhanced agent code deployment methods with improved configuration
- Comprehensive chart ecosystem for full-stack deployments

## v0.3.0 (2025-07-04)

### 🚀 Major Features

**Enhanced Proxy System**

- Automatic proxy configuration from decorator kwargs (timeout, retry_count, custom_headers)
- Smart proxy selection based on capability requirements
- Authentication and streaming auto-configuration

**Redis-Backed Session Management**

- Distributed session storage with graceful in-memory fallback
- Session stickiness for stateful applications
- Automatic routing to same pod instances

**Advanced Agent Types**

- `McpMeshAgent`: Lightweight proxies for simple tool calls
- `McpAgent`: Full MCP protocol support with streaming and session management
- Backward compatibility maintained

**Streaming Support**

- `call_tool_streaming()` for real-time data processing
- FastMCP integration with text/event-stream
- Multihop streaming capabilities

### ⚡ Performance & Infrastructure

**Fast Heartbeat Optimization**

- 5-second heartbeat intervals with HEAD request optimization
- Sub-20 second topology change detection
- Improved fault tolerance and recovery

**Kubernetes Native**

- Comprehensive ingress support eliminates port forwarding
- Agent status management with graceful shutdown
- Enhanced health check endpoints

**Architecture Improvements**

- Registry as facilitator pattern
- Direct agent-to-agent communication
- Background orchestration with minimal overhead

### 📚 Developer Experience

**Enhanced Documentation**

- Comprehensive mesh decorator examples
- Clear distinction between agent types
- Advanced usage patterns and best practices

**Improved CLI**

- Better startup performance
- Enhanced error messages
- Environment variable consistency

### 🔧 Technical Improvements

- Ent migration completion (removed GORM/SQL remnants)
- Dependency resolution optimization
- Tag handling consistency fixes
- Python runtime cleanup

---

## v0.2.1 (2025-07-01)

### 🐛 Bug Fixes

- Fix Python packaging source paths in release workflow
- Resolve version update path issues
- Address DecoratorRegistry gaps and environment variable consistency

### 📦 Infrastructure

- Complete MCP Mesh 0.2.0 release preparation
- Add HEAD method support for efficient health checks
- Optimize CLI startup and FastAPI termination performance

---

## v0.1.0 (2025-06-19)

### 🎯 Initial Release

- Core dependency injection system
- Kubernetes deployment support
- Basic agent discovery and communication
- FastMCP integration
- Docker and Helm chart support
