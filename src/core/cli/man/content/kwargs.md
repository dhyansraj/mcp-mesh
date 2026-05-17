# LLM Kwargs

> Per-call generation parameters forwarded from `@mesh.llm` consumers to the underlying vendor SDK.

## Overview

`model_params={...}` on `@mesh.llm` (Python) — or the equivalent fluent builder
in TS/Java — is the surface that flows through mesh into the vendor's native
SDK (Anthropic, OpenAI, Gemini). Common knobs work across all three vendors;
vendor-specific knobs unlock per-vendor features.

## Common knobs (cross-vendor)

| Kwarg | Purpose |
| --- | --- |
| `max_tokens` | Maximum tokens to generate. Required by Anthropic; optional elsewhere. |
| `temperature` | Sampling temperature. Lower = more deterministic. |
| `top_p` | Nucleus sampling cutoff (alternative to `temperature`). |
| `stop` | Stop sequences. Translated to `stop_sequences` for Anthropic. |
| `seed` | Best-effort determinism seed. Honored by OpenAI + Gemini; Anthropic ignores. |

## Vendor-specific knobs

- **Anthropic**: `top_k`, `metadata` (billing/audit grouping), `output_config` (native structured output on Sonnet 4.5+ / Opus 4.1+).
- **OpenAI**: `presence_penalty`, `frequency_penalty`, `logit_bias`, `logprobs`, `parallel_tool_calls`, `reasoning_effort` (o1/o3), `user`.
- **Gemini**: `top_k`, `thinking_config` (2.5+ thinking-budget), `response_mime_type` + `response_schema` (structured output).

## Python example

```python
import mesh

@mesh.llm(
    provider={"capability": "llm", "tags": ["+gemini"]},
    model_params={
        "max_tokens": 4096,
        "temperature": 0.3,
        "thinking_config": {"thinking_budget": 0},  # fast path on Gemini 2.5
    },
)
async def my_tool(prompt: str, llm: mesh.MeshLlmAgent = None) -> str:
    return await llm(prompt)
```

Anything outside the per-vendor passthrough set emits a once-per-key WARN in
the adapter — useful when chasing a typo or a newer litellm-only knob.

## TypeScript / Java

TS uses the typed options surface on `MeshLlmAgent` (`maxOutputTokens`,
`temperature`, `topP`, `stop`, `parallelToolCalls`). Java uses the `@MeshLlm`
annotation defaults plus a fluent builder (`maxTokens()`, `temperature()`,
`topP()`, `stop()`). Both runtimes serialize to the same `model_params` wire
shape. See the full reference for typed examples per language.

## See also

- `meshctl man environment` - provider API keys + `MESH_LLM_*` runtime overrides
- `meshctl man llm` - `@mesh.llm` consumer guide

For the complete kwargs reference including TypeScript/Java examples and
vendor-by-vendor matrix, see <https://mcp-mesh.io/reference/kwargs>.
