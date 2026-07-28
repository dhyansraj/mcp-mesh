package scaffold

import "strings"

// Which LLM models need the optional LiteLLM provider path (issue #1383).
//
// mcp-mesh bundles native SDK adapters for three vendors — Anthropic, OpenAI
// and Gemini — and native dispatch is default-ON. Those models never import
// litellm. Every other vendor/model falls through to GenericHandler, which
// dispatches via LiteLLM.
//
// !! CROSS-LANGUAGE DUPLICATE !!
// The routing rules below mirror the Python runtime, which is the source of
// truth for dispatch at request time:
//
//	src/runtime/python/_mcp_mesh/engine/provider_handlers/provider_handler_registry.py
//	  -> _handlers: which vendor prefixes get a native handler
//	src/runtime/python/mesh/helpers.py
//	  -> _infer_big3_vendor_from_bare_name: which UNPREFIXED names are big-3
//
// This copy exists only so `meshctl scaffold` can decide what to write into a
// generated requirements.txt at scaffold time, with no Python available. It is
// intentionally NOT shared code. When a vendor gains (or loses) a native
// adapter, BOTH sides must be updated — the Python side changes behavior, this
// side changes what gets installed. Each Python site carries the reciprocal
// pointer back here.

// nativeVendorPrefixes are the explicit `vendor/` prefixes that route to a
// bundled native SDK adapter rather than to LiteLLM.
//
// `vertex_ai` is included deliberately: it looks like a long-tail vendor, but
// ProviderHandlerRegistry maps it to GeminiHandler and gemini_native's
// supports_model() matches the `vertex_ai/` prefix, so `vertex_ai/*` dispatches
// through the bundled google-genai SDK exactly like `gemini/*` (only the auth
// differs — ADC / Workload Identity vs. an AI Studio API key).
//
// `bedrock/*` and `databricks/*` are NOT included even though
// anthropic_native.supports_model() matches `bedrock/anthropic.claude-*`:
// handler selection happens by VENDOR, and those vendors resolve to
// GenericHandler, so they take the LiteLLM path.
var nativeVendorPrefixes = map[string]bool{
	"anthropic": true,
	"openai":    true,
	"gemini":    true,
	"vertex_ai": true,
}

// inferBig3VendorFromBareName mirrors Python's
// `_infer_big3_vendor_from_bare_name`: conservatively resolve an UNPREFIXED
// model name to one of the three native-adapter vendors, using only
// unambiguous name prefixes. Returns "" for anything else (including any
// string that already carries a `/` prefix).
func inferBig3VendorFromBareName(model string) string {
	name := strings.ToLower(strings.TrimSpace(model))
	if name == "" || strings.Contains(name, "/") {
		return ""
	}

	// o1/o3/o4 reasoning families: match only when the prefix is the whole
	// name or is followed by "-" (e.g. "o3", "o3-mini"), so an unrelated
	// "o3xyz" does not misroute. Mirrors the trailing-dash discipline of the
	// "gpt-"/"chatgpt-" prefixes.
	switch name {
	case "o1", "o3", "o4":
		return "openai"
	}
	if strings.HasPrefix(name, "gpt-") ||
		strings.HasPrefix(name, "chatgpt-") ||
		strings.HasPrefix(name, "o1-") ||
		strings.HasPrefix(name, "o3-") ||
		strings.HasPrefix(name, "o4-") {
		return "openai"
	}
	if strings.HasPrefix(name, "claude-") {
		return "anthropic"
	}
	if strings.HasPrefix(name, "gemini-") {
		return "gemini"
	}
	return ""
}

// IsNativeDispatchModel reports whether model dispatches through one of the
// bundled native SDK adapters (Anthropic / OpenAI / Gemini) rather than
// through LiteLLM.
//
// An empty model is reported as native: nothing is known about it, and the
// scaffolder must not add an install line on a guess.
func IsNativeDispatchModel(model string) bool {
	m := strings.ToLower(strings.TrimSpace(model))
	if m == "" {
		return true
	}
	if idx := strings.Index(m, "/"); idx >= 0 {
		return nativeVendorPrefixes[m[:idx]]
	}
	return inferBig3VendorFromBareName(m) != ""
}

// RequiresLiteLLM reports whether an agent using model needs the optional
// LiteLLM provider path, i.e. whether the generated requirements.txt should
// pin `mcp-mesh[litellm]`.
func RequiresLiteLLM(model string) bool {
	return !IsNativeDispatchModel(model)
}
