---
title: Reference
description: API signatures, CLI flags, env vars, and model-parameter cheatsheets you look up while writing code
---

# Reference

The Reference section covers the surfaces you look up *while writing code* —
exact API signatures, CLI flags, environment-variable names, and vendor-specific
model-parameter cheatsheets. It is deliberately compact and lookup-shaped.

Use it alongside the other sections:

- [**Concepts**](../concepts/architecture.md) explains the architecture and the
  design rationale behind features like DDDI, tag matching, and the registry.
- [**Tutorial**](../tutorial/index.md) walks you through building a real
  multi-agent application from scratch.
- The **Python SDK**, **Java SDK**, and **TypeScript SDK** sections in the top
  nav are the language-specific deep references — decorators, annotations,
  per-language idioms.

Reference is what you reach for *after* you know the shape of the thing and just
need the exact spelling.

## Sections

<div class="grid cards" markdown>

- :material-api:{ .lg .middle } **API**

  ***

  Symbol references for the multimodal media surfaces — return types, parameter
  annotations, upload helpers, and storage configuration.

  - [MediaResult](../api/media-result.md)
  - [MediaParam](../api/media-param.md)
  - [save_upload](../api/save-upload.md)
  - [MediaStore](../api/media-store.md)

- :material-console:{ .lg .middle } **CLI**

  ***

  `meshctl` command reference — every subcommand, flag, and environment
  variable that the CLI honors, generated from the embedded man pages.

  [:octicons-arrow-right-24: meshctl Overview](../cli/index.md)

- :material-cog:{ .lg .middle } **Environment Variables**

  ***

  Exhaustive list of runtime environment variables read by the registry,
  agents, and SDKs — TLS, observability, retries, transport, and more.

  [:octicons-arrow-right-24: Environment Variables](../environment-variables.md)

- :material-tune:{ .lg .middle } **Kwargs**

  ***

  Vendor-specific `model_params` cheatsheet for `@mesh.llm` consumers —
  `thinking_config` (Gemini), `output_config` (Anthropic), `reasoning_effort`
  (OpenAI), and the cross-vendor common kwargs.

  [:octicons-arrow-right-24: LLM Kwargs](kwargs.md)

</div>

## See also

- [Python SDK](../python/index.md) — decorators, dependency injection, LLM
  integration, FastAPI wiring.
- [Java SDK](../java/index.md) — Spring Boot annotations and integration.
- [TypeScript SDK](../typescript/index.md) — mesh functions and Express wiring.
- [Concepts](../concepts/architecture.md) — architecture and design rationale.
- [Tutorial](../tutorial/index.md) — guided build of a multi-agent application.
