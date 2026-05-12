# What MCP Mesh Does

> A capability catalog organized by lifecycle phase: develop, build, test, run, observe, secure, deploy.

This page enumerates what mesh ships with, out of the box. For a side-by-side comparison against managed cloud agent platforms (AWS Bedrock, Vertex AI, Azure AI) where the managed-vs-self-hosted trade-off matters, jump to [Cloud Agent Platforms](#vs-cloud-agent-platforms) below.

---

## Develop

- **Scaffold agents** — `meshctl scaffold` creates new agents per runtime (Python / Java / TypeScript) with idiomatic project layouts
- **Local dev server** — `meshctl start` brings up the registry plus your agents in one command — no Docker required
- **List agents** — `meshctl list` shows live mesh topology including capabilities and tags
- **Status check** — `meshctl status` gives instant health view across the mesh
- **Built-in docs** — `meshctl man` covers every feature offline; works as a primer for AI coding assistants
- **Hot reload** — code changes pick up without restart
- **Local tracing** — `meshctl trace <id>` walks the full call tree across languages and agents

---

## Build

- **Zero-config dependency injection** — declare capabilities + dependencies on the function; mesh handles wiring
- **Distributed Dynamic DI ([DDDI](concepts/dddi.md))** — dependencies resolved at runtime across processes, machines, and clouds
- **Capability-based discovery** — agents declare capabilities, not URLs; resolution is by intent
- **Tag-based filtering** — `+claude`, `+gpt`, `+v2`, and arbitrary tags refine selection at runtime
- **Cross-language support** — Python, Java, and TypeScript agents call each other natively via shared Rust FFI core
- **Multi-protocol bridging** — MCP, A2A v1.0, and REST — consume external A2A producers or expose mesh tools to A2A / REST clients without rewriting business logic
- **Same code local / Docker / Kubernetes** — environment differences live in config, not code
- **Monolith mode** — run all agents in one process for fast local iteration
- **Distributed mode** — scale to many processes with the same code
- **Structured output** — Pydantic (Python), Zod (TypeScript), Java records — native typed returns from LLMs

---

## Test

- **Zero-config mocking** — start the topology you want to test; mesh resolves what's running
- **Mock by presence** — bring up a stub agent that declares the dependency capability; consumers find it
- **No code change for tests** — production code IS the test code
- **No config change for tests** — test environment differences live in agent-start choices, not config files
- **Integration test support** — tsuite framework ships with mesh for end-to-end suites

---

## Multi-LLM

- **Multi-LLM support** — Claude, GPT, Gemini, plus any provider supported by LiteLLM / Vercel AI SDK / Spring AI
- **Dynamic LLM discovery** — LLM agents are mesh agents; discovered the same way as any tool
- **LLM auto-failover** — provider goes down, mesh rewires to a peer (e.g., `+claude` falls back to `+gpt` when tagged)
- **Dynamic tool calls** — LLM picks a tool, mesh dispatches to the right agent — no agentic loop to write
- **LLM provider hot-swap** — change the active provider without restart
- **Zero-code LLM providers** — `meshctl scaffold llm-provider` creates a new provider in seconds

---

## Agents

- **Agent-to-agent calls** — native, typed, with auto-retry and trace propagation
- **Dynamic agent discovery** — new agents register and become callable without consumer-side changes
- **Agent hot join** — new agent starts mid-flight, becomes discoverable on next heartbeat tick
- **Agent hot leave** — graceful shutdown drains in-flight work; orphan-reset handles unclean kills
- **Agent health checks** — registry tracks per-agent health and drops unhealthy peers from resolution
- **N-way agent communication** — `filter_mode="all"` calls every consumer of a capability and aggregates results

---

## Deploy

- **Docker images** — official runtimes published per release
- **Helm charts** — umbrella + per-agent charts on OCI registry
- **Kubernetes-native** — declarative deployment with HPA, health probes, and service discovery
- **Auto-scaling** — Kubernetes-native horizontal pod autoscaling
- **Service discovery** — built into the registry; no external coordination needed
- **Zero-downtime deploy** — rolling updates with heartbeat-driven cutover
- **Environment parity** — same code runs locally, in Docker, and in Kubernetes

---

## Observe

- **Distributed tracing** — every cross-agent call carries a trace context
- **Cross-language tracing** — Python → Java → TypeScript spans land in the same trace tree
- **Local tracing** — `meshctl trace <id>` renders the call tree in the terminal
- **Production tracing** — Grafana + Tempo deployment included in the Helm umbrella chart
- **OpenTelemetry support** — native, no glue code
- **Trace propagation** — automatic across mesh calls, no manual context wiring
- **Span visualization** — Grafana dashboards ship with the platform

---

## Resilience

- **Auto-failover** — capability+tag mechanism rewires consumers transparently when an agent dies
- **Graceful degradation** — partial mesh failures don't cascade; degraded calls return useful errors
- **Circuit breaker** — repeated failures from a downstream agent trip the circuit; recovery is automatic
- **Retry logic** — built into the resolver with configurable policy
- **Dead agent removal** — orphan-reset sweep drops agents whose heartbeats stop

---

## Security

- **Registration trust** — X.509 identity verification at agent registration
- **Agent-to-agent mTLS** — every call authenticated; optional auto-rotation
- **Fine-grained authorization** — header propagation lets agents enforce caller-context rules
- **Zero-config TLS (dev)** — `--tls-auto` mints self-signed certs for local dev
- **Vault integration** — HashiCorp Vault as a PKI provider
- **SPIRE / workload identity** — X.509-SVID rotation via heartbeat
- **Cert rotation via heartbeat** — automatic, no restarts

---

## Architecture

- **Monolith → distributed without rewrite** — same decorators, same code, different topology
- **No central orchestrator required** — peer-to-peer mesh, registry is for discovery only
- **Topology-based wiring** — what's running IS what's connected
- **Standard protocol** — MCP (Anthropic's open protocol), not custom RPC

---

## Developer experience

- **Lines of code per agent** — ~10 lines for a typical agent
- **Low framework lock-in** — your code stays regular Python / Java / TypeScript with two mesh decorators
- **Low learning curve** — if you know FastAPI / Spring / Express, you know mesh
- **No framework classes** — `@mesh.tool`, `@mesh.agent`, `@mesh.llm` — plain decorators on plain functions

---

## Enterprise

- **Mature** — actively developed, production-ready
- **Enterprise observability** — Grafana + Tempo + Prometheus stack ships with the platform
- **Non-blocking team development** — capability boundaries let teams build agents independently
- **Multi-team support** — capability namespaces + tags let teams ship without coordination

---

## vs Cloud Agent Platforms

How MCP Mesh compares to managed cloud agent services — AWS Bedrock Agents, Google Vertex AI Agent Builder, and Azure AI Agent Service. This is a genuine trade-off (managed vs self-hosted, vendor-tied vs portable) rather than a feature gap, so a side-by-side comparison is useful here.

| Feature                            | Bedrock Agents              | Vertex AI Agent Builder     | Azure AI Agent Service      | MCP Mesh                                        |
| ---------------------------------- | --------------------------- | --------------------------- | --------------------------- | ----------------------------------------------- |
| **Run anywhere**                   | :x: AWS only                | :x: GCP only                | :x: Azure only              | :white_check_mark: Any infra                    |
| **Self-hosted**                    | :x:                         | :x:                         | :x:                         | :white_check_mark: Your data stays yours        |
| **Multi-language agents**          | :x: Python only             | :x: Python only             | :x: Python only             | :white_check_mark: Python + TypeScript + Java   |
| **Multi-LLM provider**             | :x: AWS models              | :x: Google models           | :x: Azure models            | :white_check_mark: Claude + GPT + Gemini + any  |
| **Switch LLM without code change** | :x:                         | :x:                         | :x:                         | :white_check_mark: Tag-based provider selection |
| **Agent-to-agent communication**   | :x: Limited                 | :x: Limited                 | :x: Limited                 | :white_check_mark: Native mTLS mesh             |
| **Dynamic agent discovery**        | :x:                         | :x:                         | :x:                         | :white_check_mark: DDDI                         |
| **Open protocol**                  | :x: Proprietary API         | :x: Proprietary API         | :x: Proprietary API         | :white_check_mark: MCP (open standard)          |
| **Own your security**              | :x: Their IAM               | :x: Their IAM               | :x: Their IAM               | :white_check_mark: Your PKI, Vault, SPIRE       |
| **Own your observability**         | :x: CloudWatch              | :x: Cloud Monitoring        | :x: App Insights            | :white_check_mark: Your Grafana, your Tempo     |
| **Cost model**                     | Per-invocation              | Per-invocation              | Per-invocation              | :white_check_mark: Open source, free            |
| **Kubernetes native**              | :x:                         | :x:                         | :x:                         | :white_check_mark: Helm charts, HPA             |
| **Structured output**              | :warning: Limited           | :warning: Limited           | :warning: Limited           | :white_check_mark: Native (Pydantic/Zod/record) |
| **Multimodal**                     | :warning: Provider-specific | :warning: Provider-specific | :warning: Provider-specific | :white_check_mark: Unified across providers     |

Cloud platforms give you a managed environment — but lock you into one vendor's LLMs, one cloud, and their pricing model. MCP Mesh gives you the same capabilities with full control over where it runs, which LLMs it uses, and how it scales.

---

## Summary

MCP Mesh is designed for **production AI systems** where you need:

- **Zero infrastructure code** — just decorators, no boilerplate
- **Dynamic discovery** — agents find each other automatically
- **Multi-protocol** — MCP, A2A, and REST agents in one framework
- **Multi-language** — Python, Java, TypeScript agents calling each other natively
- **Enterprise operations** — tracing, failover, and scaling built-in
- **Low lock-in** — your code stays clean Python / Java / TypeScript

[Get Started](python/getting-started/index.md){ .md-button .md-button--primary }
[View Architecture](concepts/architecture.md){ .md-button }
