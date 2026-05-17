# LLM Kwargs Reference

> Per-call generation parameters forwarded from `@mesh.llm` consumers to the underlying vendor SDK.

## Overview

`model_params` is the per-call kwarg surface that flows from a `@mesh.llm`
consumer, through the mesh proxy, to the resolved provider, and finally into the
vendor's native SDK (Anthropic, OpenAI, Gemini). Mesh does not invent its own
parameter names — common knobs (`max_tokens`, `temperature`, ...) work across
all three vendors; vendor-specific knobs (`thinking_config`, `reasoning_effort`,
`top_k`, ...) unlock per-vendor features.

The exact passthrough surface for each Python adapter lives in
`_<VENDOR>_PASSTHROUGH_KWARGS` (see
[Source pointers](#source-pointers) below). Anything outside that set is logged
as a once-per-key WARN by the adapter so a typo or a newer litellm-only knob
surfaces immediately instead of being silently dropped.

## Common kwargs (cross-vendor)

These work across Anthropic, OpenAI, and Gemini:

| Kwarg | Type | Purpose |
| --- | --- | --- |
| `max_tokens` | int | Maximum tokens to generate in the response. |
| `temperature` | float (0.0 - 2.0) | Sampling temperature. Lower = more deterministic. |
| `top_p` | float (0.0 - 1.0) | Nucleus sampling cutoff. Alternative to `temperature`. |
| `stop` | list[str] | Stop sequences that halt generation when produced. (Anthropic: `stop_sequences`.) |
| `seed` | int | Best-effort determinism seed. Honored by OpenAI and Gemini; ignored by Anthropic. |

Mesh forwards these unchanged for OpenAI and Gemini. For Anthropic, mesh
translates `stop` → `stop_sequences` to match the native SDK.

## Vendor-specific kwargs

### Anthropic-only

| Kwarg | Purpose |
| --- | --- |
| `top_k` | Top-k sampling cutoff. (Also supported by Gemini.) |
| `metadata` | Caller-supplied metadata dict (e.g. `{"user_id": "..."}`) attached to the Anthropic request for billing/audit grouping. |
| `output_config` | Native structured-output primitive on Claude Sonnet 4.5+ / Opus 4.1+. Wire shape: `{"format": {"type": "json_schema", "schema": {...}}}`. Older models fall through to mesh's synthetic-tool path. |
| `extra_headers` / `extra_query` / `extra_body` | SDK-level escape hatches forwarded verbatim to the Anthropic client. |

### OpenAI-only

| Kwarg | Purpose |
| --- | --- |
| `n` | Number of completions (note: mesh's response/stream adapters only consume the first candidate; use with care). |
| `presence_penalty` | Penalty for repeated topics. (Also Gemini.) |
| `frequency_penalty` | Penalty for repeated tokens. (Also Gemini.) |
| `logit_bias` | Per-token bias dict. |
| `logprobs` / `top_logprobs` | Return log-probabilities for sampled / top-k tokens. |
| `parallel_tool_calls` | Allow the model to emit multiple tool calls in a single turn. |
| `user` | End-user identifier for OpenAI abuse-monitoring. |
| `reasoning_effort` | `o1` / `o3` reasoning-model effort knob (`"low"`, `"medium"`, `"high"`). |
| `max_completion_tokens` | Newer name for `max_tokens` on reasoning models — both accepted. |
| `stream_options` | OpenAI streaming options dict (mesh sets `include_usage` itself but a caller-provided override is merged). |

### Gemini-only

| Kwarg | Purpose |
| --- | --- |
| `top_k` | Top-k sampling cutoff. (Also Anthropic.) |
| `presence_penalty` / `frequency_penalty` | Repetition penalties. (Also OpenAI.) |
| `thinking_config` | Gemini 2.5+ thinking-budget control. Accepts a dict (e.g. `{"thinking_budget": 0}` to disable thinking) or a pre-built `google.genai.types.ThinkingConfig` instance. |
| `response_mime_type` | Response MIME type — set to `"application/json"` together with `response_schema` for JSON output. |
| `response_schema` | JSON schema for structured output. Mesh's HINT-mode workaround strips this when tools are present (Gemini API loop bug). |
| `extra_headers` / `extra_body` | Translated into per-call `google.genai.types.HttpOptions` overrides. |

## Per-language usage

### Python

`model_params={...}` is a parameter on `@mesh.llm`. Values are merged into the
`MeshLlmRequest.model_params` dict at runtime and forwarded to the resolved
provider.

```python
import mesh

@mesh.llm(
    provider={"capability": "llm", "tags": ["+gemini"]},
    model_params={
        "max_tokens": 4096,
        "temperature": 0.3,
        "thinking_config": {"thinking_budget": 0},  # disable thinking for fast Gemini 2.5
    },
)
async def my_tool(prompt: str, llm: mesh.MeshLlmAgent = None) -> str:
    return await llm(prompt)
```

See [`MeshLlmRequest`](../python/llm/index.md) for the underlying request shape.

### TypeScript

The TS SDK exposes a typed options surface on `MeshLlmAgentConfig`. Options are
mapped to `model_params` keys on the wire (e.g. `maxOutputTokens` →
`max_tokens`, `topP` → `top_p`).

```typescript
import { MeshLlmAgent } from "@mcpmesh/sdk";

const agent = new MeshLlmAgent({
  functionId: "my_tool",
  provider: { capability: "llm", tags: ["+claude"] },
  model: "anthropic/claude-sonnet-4-5",
  maxIterations: 5,
  maxOutputTokens: 4096,
  temperature: 0.3,
  topP: 0.95,
  stop: ["\n\n---"],
  parallelToolCalls: true,
});

const result = await agent.run("Help me draft a release note", {
  tools: resolvedToolProxies,
  meshProvider: { endpoint: "http://provider:9000", functionName: "process_chat" },
});
```

For vendor-specific kwargs the typed surface doesn't expose (e.g. Gemini
`thinking_config`, Anthropic `output_config`, OpenAI `reasoning_effort`), use
the `modelParams` escape hatch on `LlmCallOptions`. The dict is merged into the
wire `model_params` **before** typed fields, so typed options (`maxOutputTokens`,
`temperature`, ...) win on collision and remain authoritative:

```typescript
const reply = await llm.call(prompt, {
  maxOutputTokens: 4096,
  temperature: 0.3,
  modelParams: {
    thinking_config: { thinking_budget: 0 }, // escape hatch for vendor-specific kwargs
  },
});
```

Source: [`src/runtime/typescript/src/llm-agent.ts`](https://github.com/dhyansraj/mcp-mesh/blob/main/src/runtime/typescript/src/llm-agent.ts).

### Java

The Java SDK uses the `@MeshLlm` annotation for tool-call defaults and a fluent
builder on `MeshLlmAgent` for per-call overrides. Builder values are translated
into `model_params` keys on the wire (`maxTokens` → `max_tokens`, `topP` →
`top_p`).

```java
import io.mcpmesh.types.MeshLlmAgent;
import io.mcpmesh.types.annotations.MeshLlm;
import io.mcpmesh.types.annotations.MeshTool;

@MeshLlm(
    providerSelector = "capability=llm,tags=+claude",
    maxTokens = 4096,
    temperature = 0.3
)
@MeshTool(capability = "summarizer")
public String summarize(@Param("text") String text, MeshLlmAgent llm) {
    return llm.request()
        .system("Summarize the following text in 2 sentences.")
        .user(text)
        .maxTokens(1024)        // override the annotation default for this call
        .temperature(0.5)
        .topP(0.95)
        .stop("END")
        .generate();
}
```

For vendor-specific kwargs the typed builder doesn't expose (e.g. Gemini
`thinking_config`, Anthropic `output_config`, OpenAI `reasoning_effort`), use
the `.modelParams(...)` escape hatch on the builder. The map is merged into the
wire `model_params` **before** typed setters, so typed setters (`maxTokens`,
`temperature`, ...) win on collision and remain authoritative:

```java
String response = llm.request()
    .user(prompt)
    .maxTokens(4096)
    .temperature(0.3)
    .modelParams(Map.of(
        "thinking_config", Map.of("thinking_budget", 0)
    ))
    .generate();
```

The same builder surface — including `.modelParams(...)` — is available on the
streaming path via `.streamGenerate()`. The merge semantics (escape hatch
first, typed setters win, annotation defaults only when unset) are shared with
the buffered `.generate()` path:

```java
Flow.Publisher<String> chunks = llm.request()
    .system("You are helpful")
    .user(prompt)
    .maxTokens(4096)
    .temperature(0.7)
    .modelParams(Map.of(
        "thinking_config", Map.of("thinking_budget", 0)
    ))
    .streamGenerate();
```

Streaming requires the consumer to opt in via the `ai.mcpmesh.stream` tag on
`@MeshLlm(providerSelector = ...)` — see
[Java LLM Integration](../java/llm/index.md).

Source: [`MeshLlmAgentProxy.java`](https://github.com/dhyansraj/mcp-mesh/blob/main/src/runtime/java/mcp-mesh-spring-boot-starter/src/main/java/io/mcpmesh/spring/MeshLlmAgentProxy.java).

## Reference matrix

| Kwarg | Anthropic | OpenAI | Gemini | Notes |
| --- | :---: | :---: | :---: | --- |
| `max_tokens` | yes | yes | yes | Anthropic requires it; OpenAI/Gemini optional. |
| `temperature` | yes | yes | yes | |
| `top_p` | yes | yes | yes | |
| `top_k` | yes | no | yes | OpenAI has no equivalent. |
| `stop` | yes (`stop_sequences`) | yes | yes | Anthropic SDK renames; mesh translates. |
| `seed` | no | yes | yes | Anthropic ignores. |
| `presence_penalty` | no | yes | yes | |
| `frequency_penalty` | no | yes | yes | |
| `logit_bias` | no | yes | no | |
| `logprobs` / `top_logprobs` | no | yes | no | |
| `n` | no | yes | no | Mesh assumes single-completion; multi-candidate output is dropped. |
| `parallel_tool_calls` | no | yes | no | Mesh's loop honors it for sequencing on Anthropic too. |
| `user` | no | yes | no | |
| `reasoning_effort` | no | yes (o1/o3) | no | |
| `metadata` | yes | no | no | Anthropic billing/audit grouping. |
| `output_config` | yes (Sonnet 4.5+/Opus 4.1+) | no | no | Native structured output. |
| `thinking_config` | no | no | yes (2.5+) | Budget control for Gemini thinking models. |
| `response_mime_type` | no | no | yes | Pair with `response_schema`. |
| `response_schema` | no | no | yes | JSON schema for structured output. |
| `extra_headers` | yes | yes | yes | Vendor SDK escape hatch. |
| `extra_body` | yes | yes | yes | |
| `extra_query` | yes | yes | no | Gemini's `HttpOptions` has no per-call query override. |
| `timeout` / `request_timeout` | yes | yes | yes | Per-call timeout override in seconds. |

## Source pointers

For the precise passthrough surface per adapter, see the
`_<VENDOR>_PASSTHROUGH_KWARGS` frozenset at the top of each native client:

- Anthropic: `src/runtime/python/_mcp_mesh/engine/native_clients/anthropic_native.py`
- OpenAI: `src/runtime/python/_mcp_mesh/engine/native_clients/openai_native.py`
- Gemini: `src/runtime/python/_mcp_mesh/engine/native_clients/gemini_native.py`

Any kwarg outside the passthrough + handled sets emits a once-per-key WARN —
useful diagnostic surface for callers debugging cross-vendor passthrough.

## See also

- [Environment Variables](../environment-variables.md) - configure provider API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`) and runtime overrides (`MESH_LLM_MODEL`, `MESH_LLM_MAX_ITERATIONS`).
- [Python LLM Integration](../python/llm/index.md) - `@mesh.llm` consumer guide.
- [Java LLM Integration](../java/llm/index.md) - `@MeshLlm` consumer guide.
- [TypeScript LLM Integration](../typescript/llm/index.md) - LLM agent consumer guide.
