"""Native vendor SDK clients for the provider-side LLM dispatch path.

Each module in this package adapts a single vendor SDK (Anthropic, OpenAI,
Gemini, etc.) to the litellm.completion() / litellm.acompletion() shape that
the rest of the mesh provider code consumes. Native dispatch is enabled by
default whenever the relevant vendor SDK is importable. Set
``MCP_MESH_NATIVE_LLM=0`` to force the LiteLLM fallback path; if the SDK is
absent, the call sites also fall back to LiteLLM with a one-time INFO log.

This is part of issue #834 — the multi-PR migration off LiteLLM for the
provider-side path. PR 1 lands Anthropic only; OpenAI / Gemini follow.
"""
