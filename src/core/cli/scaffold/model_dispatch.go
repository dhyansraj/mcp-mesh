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

// directProbeVendorPrefixes are the `vendor/` prefixes a scaffolded health
// check can probe by calling the vendor's own public API with the vendor's own
// API key.
//
// This is deliberately NOT nativeVendorPrefixes, and the difference is the
// whole point of issue #1479: "which native adapter dispatches this model" and
// "which direct API can a health check probe for it" are different questions.
//
// `vertex_ai` is native dispatch — it routes through the bundled google-genai
// SDK exactly like `gemini/*` — but it authenticates with ADC / Workload
// Identity against a Google Cloud project endpoint, not with an AI Studio
// GOOGLE_API_KEY against generativelanguage.googleapis.com. Probing the AI
// Studio endpoint for a Vertex deployment tests an API the agent does not use,
// with a key it does not have, so it is omitted here and falls through to the
// generic skeleton.
var directProbeVendorPrefixes = map[string]string{
	"anthropic": "anthropic",
	"openai":    "openai",
	"gemini":    "gemini",
}

// DirectProbeVendor resolves model to the vendor whose direct public API a
// scaffolded health check may probe: "anthropic", "openai", "gemini", or "" if
// no direct probe is valid.
//
// "" means the scaffolder must emit the generic skeleton rather than guess.
// That covers gateway-prefixed models (`bedrock/*`, `vertex_ai/*`,
// `databricks/*`, ...), which reach the model through a gateway that
// authenticates with its own credentials, every other long-tail vendor, any
// unrecognized bare name, and the empty model.
//
// The matching is prefix-based and case-insensitive, NOT a substring test.
// `bedrock/anthropic.claude-3-5-sonnet-...` contains "anthropic" but is served
// by AWS: api.anthropic.com being reachable says nothing about that agent's
// health, and ANTHROPIC_API_KEY is never set for it. A health check gated on
// that key returns unhealthy on the first tick, which suppresses the heartbeat
// and makes the registry withdraw a provider that is working fine — and since
// the key never appears, it never comes back (issue #1479).
func DirectProbeVendor(model string) string {
	m := strings.ToLower(strings.TrimSpace(model))
	if m == "" {
		return ""
	}
	if idx := strings.Index(m, "/"); idx >= 0 {
		return directProbeVendorPrefixes[m[:idx]]
	}
	return inferBig3VendorFromBareName(m)
}

// big3FamilyNames are the names a big-3 model FAMILY goes by when it appears as
// a segment of a model id — the vendor that built the model, regardless of who
// serves it.
//
// Deliberately separate from directProbeVendorPrefixes even though the three
// names coincide today: that map answers "may a health check call this vendor's
// own API", this one answers "whose model is this". They are allowed to
// diverge, and TestModelFamilyAndProbeVendorDivergeOnGateways pins the models
// where they already do.
var big3FamilyNames = map[string]string{
	"anthropic": "anthropic",
	"openai":    "openai",
	"gemini":    "gemini",
}

// ModelFamily resolves model to the big-3 family that built it — "anthropic",
// "openai", "gemini" — or "" for anything else.
//
// This is NOT DirectProbeVendor, and conflating the two is the mistake this
// function exists to prevent. `bedrock/anthropic.claude-3-5-sonnet-...` IS a
// Claude model: it must register the claude/anthropic discovery tags, or a
// consumer scaffolded with `--vendor claude` (which pins `+claude`) stops
// resolving it. What it must NOT get is a probe of api.anthropic.com gated on
// ANTHROPIC_API_KEY, because AWS serves it with AWS credentials — that is
// DirectProbeVendor's answer, and it is "" (issue #1479).
//
// Matching is case-insensitive and segment-based, never a substring test. A
// gateway carries the family in the segment AFTER its own prefix, separated by
// either "/" or "." depending on the gateway:
//
//	bedrock/anthropic.claude-3-5-sonnet-...  -> anthropic
//	bedrock/us.anthropic.claude-3-5-sonnet   -> anthropic (cross-region profile)
//	vertex_ai/gemini-2.5-flash               -> gemini    (bare-name inference)
//	azure/openai/gpt-4o                      -> openai
//	bedrock/meta.llama3-70b-instruct-v1:0    -> ""        (not a big-3 family)
func ModelFamily(model string) string {
	return big3Family(strings.ToLower(strings.TrimSpace(model)))
}

// big3Family resolves an already-lowercased, already-trimmed model id.
func big3Family(m string) string {
	if m == "" {
		return ""
	}

	// `vendor/rest`: the prefix names the family for a native vendor
	// (anthropic/, openai/, gemini/). For everything else the prefix is a
	// gateway, and the family — if any — lives in the remainder.
	if idx := strings.Index(m, "/"); idx >= 0 {
		if family := big3FamilyNames[m[:idx]]; family != "" {
			return family
		}
		return big3Family(m[idx+1:])
	}

	// Gateway model ids namespace with "." rather than "/": `anthropic.claude-*`
	// on Bedrock, `us.anthropic.claude-*` for a cross-region inference profile.
	// Each dot-delimited segment is matched WHOLE, so "meta.llama3" stays "" and
	// a hypothetical "openai-clone" never matches "openai".
	if strings.Contains(m, ".") {
		for _, segment := range strings.Split(m, ".") {
			if family := big3FamilyNames[segment]; family != "" {
				return family
			}
		}
	}

	// No vendor segment to go on: fall back to the same conservative bare-name
	// rules the Python runtime uses, so `claude-sonnet-5`, `gpt-4o` and
	// `gemini-2.5-flash` resolve whether they arrived bare or as a gateway
	// remainder. Note this also covers dotted names with no vendor segment
	// (e.g. "gpt-4.1"), which the loop above deliberately leaves alone.
	return inferBig3VendorFromBareName(m)
}

// providerTagsByFamily are the discovery tags a scaffolded provider registers
// for each big-3 family. The templates emit the same lists in their own syntax;
// this copy serves the Go-side callers (the interactive wizard).
var providerTagsByFamily = map[string][]string{
	"anthropic": {"llm", "claude", "anthropic", "provider"},
	"openai":    {"llm", "openai", "gpt", "provider"},
	"gemini":    {"llm", "gemini", "google", "provider"},
}

// ProviderTagsForModel returns the discovery tags an llm-provider should
// register for model: the family tags when the model belongs to a big-3 family,
// otherwise the generic ["llm", "provider"].
//
// Keyed on ModelFamily, never on a substring of the model string: a
// case-sensitive `strings.Contains(model, "anthropic")` both misses
// `Claude-Sonnet-5` and has no gemini answer at all.
func ProviderTagsForModel(model string) []string {
	if tags, ok := providerTagsByFamily[ModelFamily(model)]; ok {
		return append([]string{}, tags...)
	}
	return []string{"llm", "provider"}
}
