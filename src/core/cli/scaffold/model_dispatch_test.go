package scaffold

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// Issue #1383: the generated requirements.txt pins mcp-mesh[litellm] only for
// models that actually take the LiteLLM long-tail path. Getting this wrong in
// either direction is a real cost — a needless 30MB pip layer, or an agent
// that ImportErrors on its first request.
func TestRequiresLiteLLM(t *testing.T) {
	tests := []struct {
		name     string
		model    string
		expected bool
	}{
		// --- big-3, explicit vendor/ prefix ------------------------------
		{"anthropic prefixed", "anthropic/claude-sonnet-5", false},
		{"openai prefixed", "openai/gpt-4o", false},
		{"gemini prefixed", "gemini/gemini-2.5-flash", false},

		// vertex_ai looks long-tail but ProviderHandlerRegistry maps it to
		// GeminiHandler and gemini_native.supports_model() matches the
		// prefix — it dispatches through the bundled google-genai SDK.
		{"vertex_ai prefixed", "vertex_ai/gemini-2.5-flash", false},

		// --- big-3, bare names -------------------------------------------
		{"bare claude", "claude-sonnet-5", false},
		{"bare claude 3 haiku", "claude-3-haiku", false},
		{"bare gpt", "gpt-4o", false},
		{"bare chatgpt", "chatgpt-4o-latest", false},
		{"bare o1", "o1", false},
		{"bare o3", "o3", false},
		{"bare o3-mini", "o3-mini", false},
		{"bare o4-mini", "o4-mini", false},
		{"bare gemini", "gemini-3-pro-preview", false},

		// --- long-tail vendors -------------------------------------------
		{"bedrock", "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0", true},
		{"databricks", "databricks/anthropic.claude-3-7-sonnet", true},
		{"cohere", "cohere/command-r-plus", true},
		{"unknown vendor", "acme-llm/frobnicator-9", true},
		{"ollama", "ollama/llama3", true},
		{"groq", "groq/llama-3.1-70b-versatile", true},

		// --- bare names that are NOT big-3 -------------------------------
		{"bare llama", "llama-3-70b", true},
		{"bare mistral", "mistral-large-latest", true},
		// Discipline mirrored from Python: the o-series prefixes match only
		// as a whole name or followed by "-".
		{"o3-lookalike", "o3xyz", true},

		// --- empty / unset ------------------------------------------------
		// Nothing is known about the model; never add an install line on a
		// guess. Every non-LLM template renders with an empty Model.
		{"empty", "", false},
		{"whitespace only", "   ", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, RequiresLiteLLM(tt.model),
				"RequiresLiteLLM(%q)", tt.model)
			assert.Equal(t, !tt.expected, IsNativeDispatchModel(tt.model),
				"IsNativeDispatchModel(%q)", tt.model)
		})
	}
}

func TestRequiresLiteLLMIsCaseInsensitive(t *testing.T) {
	assert.False(t, RequiresLiteLLM("Anthropic/Claude-Sonnet-5"))
	assert.False(t, RequiresLiteLLM("OpenAI/GPT-4o"))
	assert.False(t, RequiresLiteLLM("VERTEX_AI/gemini-2.5-flash"))
	assert.True(t, RequiresLiteLLM("Bedrock/Anthropic.Claude-3"))
}

func TestInferBig3VendorFromBareName(t *testing.T) {
	// Mirrors mesh.helpers._infer_big3_vendor_from_bare_name — a prefixed
	// model is never second-guessed.
	assert.Equal(t, "", inferBig3VendorFromBareName("anthropic/claude-sonnet-5"))
	assert.Equal(t, "openai", inferBig3VendorFromBareName("gpt-4o"))
	assert.Equal(t, "anthropic", inferBig3VendorFromBareName("claude-opus-4-8"))
	assert.Equal(t, "gemini", inferBig3VendorFromBareName("gemini-2.5-flash"))
	assert.Equal(t, "", inferBig3VendorFromBareName("command-r-plus"))
	assert.Equal(t, "", inferBig3VendorFromBareName(""))
}

// Issue #1479: the llm-provider templates pick a health-check probe from the
// model string. Picking the wrong one is not cosmetic — the probe reports
// unhealthy on the first tick, the heartbeat stops, the registry withdraws the
// agent, and because the credential it asks for is one that deployment never
// sets, the verdict never flips back. A working provider disappears for good.
//
// So this is deliberately NOT IsNativeDispatchModel. `vertex_ai/*` IS native
// dispatch (bundled google-genai SDK) but authenticates with ADC / Workload
// Identity, so the AI Studio probe is wrong for it.
func TestDirectProbeVendor(t *testing.T) {
	tests := []struct {
		name     string
		model    string
		expected string
	}{
		// --- big-3, explicit vendor/ prefix ------------------------------
		{"anthropic prefixed", "anthropic/claude-sonnet-5", "anthropic"},
		{"openai prefixed", "openai/gpt-4o", "openai"},
		{"gemini prefixed", "gemini/gemini-2.5-flash", "gemini"},

		// --- big-3, bare names -------------------------------------------
		{"bare claude", "claude-sonnet-5", "anthropic"},
		{"bare gpt", "gpt-4o", "openai"},
		{"bare chatgpt", "chatgpt-4o-latest", "openai"},
		{"bare o1", "o1", "openai"},
		{"bare o3-mini", "o3-mini", "openai"},
		{"bare o4-mini", "o4-mini", "openai"},
		{"bare gemini", "gemini-3-pro-preview", "gemini"},
		{"o3-lookalike", "o3xyz", ""},
		{"bare llama", "llama-3-70b", ""},

		// --- native dispatch, but NOT directly probeable ------------------
		// vertex_ai routes through the same google-genai SDK as gemini/*,
		// so IsNativeDispatchModel says true — but it authenticates with
		// ADC / Workload Identity against a Google Cloud project endpoint.
		// Probing AI Studio with a GOOGLE_API_KEY tests an API this agent
		// never calls, with a key it does not have.
		{"vertex_ai prefixed", "vertex_ai/gemini-2.5-flash", ""},

		// --- gateways whose model id embeds a big-3 vendor name -----------
		// The exact strings that made the old substring gate misfire.
		{"bedrock claude", "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0", ""},
		{"databricks claude", "databricks/anthropic.claude-3-7-sonnet", ""},
		{"azure openai", "azure/gpt-4o", ""},
		{"openrouter openai", "openrouter/openai/gpt-4o", ""},

		// --- long-tail vendors -------------------------------------------
		{"cohere", "cohere/command-r-plus", ""},
		{"ollama", "ollama/llama3", ""},
		{"unknown vendor", "acme-llm/frobnicator-9", ""},

		// --- empty / unset ------------------------------------------------
		// Nothing is known about the model; emit the skeleton, never a probe
		// chosen on a guess.
		{"empty", "", ""},
		{"whitespace only", "   ", ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, DirectProbeVendor(tt.model),
				"DirectProbeVendor(%q)", tt.model)
		})
	}
}

// --model is free-form, so casing is the user's, not ours.
func TestDirectProbeVendorIsCaseInsensitive(t *testing.T) {
	assert.Equal(t, "anthropic", DirectProbeVendor("Anthropic/Claude-Sonnet-5"))
	assert.Equal(t, "openai", DirectProbeVendor("OpenAI/GPT-4o"))
	assert.Equal(t, "gemini", DirectProbeVendor("GEMINI/gemini-2.5-flash"))
	assert.Equal(t, "anthropic", DirectProbeVendor("Claude-Opus-4-8"))
	assert.Equal(t, "", DirectProbeVendor("VERTEX_AI/gemini-2.5-flash"))
	assert.Equal(t, "", DirectProbeVendor("Bedrock/Anthropic.Claude-3"))
}

func TestDirectProbeVendorTrimsWhitespace(t *testing.T) {
	assert.Equal(t, "anthropic", DirectProbeVendor("  anthropic/claude-sonnet-5  "))
	assert.Equal(t, "openai", DirectProbeVendor("\tgpt-4o\n"))
	assert.Equal(t, "", DirectProbeVendor("  bedrock/anthropic.claude-3  "))
}

// A probeable model is always native dispatch; the converse does not hold, and
// vertex_ai is the whole reason the two questions need separate answers.
func TestDirectProbeVendorIsNarrowerThanNativeDispatch(t *testing.T) {
	for _, model := range []string{
		"anthropic/claude-sonnet-5", "openai/gpt-4o", "gemini/gemini-2.5-flash",
		"claude-sonnet-5", "gpt-4o", "gemini-2.5-flash",
	} {
		assert.NotEmpty(t, DirectProbeVendor(model), "probeable: %q", model)
		assert.True(t, IsNativeDispatchModel(model), "native: %q", model)
	}

	assert.True(t, IsNativeDispatchModel("vertex_ai/gemini-2.5-flash"))
	assert.Empty(t, DirectProbeVendor("vertex_ai/gemini-2.5-flash"))
}

// The template data map is what the requirements.txt template branches on.
func TestTemplateDataCarriesRequiresLiteLLM(t *testing.T) {
	native := TemplateDataFromContext(&ScaffoldContext{
		Name:  "claude-provider",
		Model: "anthropic/claude-sonnet-5",
	})
	assert.Equal(t, false, native["RequiresLiteLLM"])

	longTail := TemplateDataFromContext(&ScaffoldContext{
		Name:  "bedrock-provider",
		Model: "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
	})
	assert.Equal(t, true, longTail["RequiresLiteLLM"])

	none := TemplateDataFromContext(&ScaffoldContext{Name: "basic-agent"})
	assert.Equal(t, false, none["RequiresLiteLLM"])
}

// The llm-provider templates gate the health-check probe on this key, so it
// has to reach them (issue #1479).
func TestTemplateDataCarriesProbeVendor(t *testing.T) {
	probeable := TemplateDataFromContext(&ScaffoldContext{
		Name:  "claude-provider",
		Model: "anthropic/claude-sonnet-5",
	})
	assert.Equal(t, "anthropic", probeable["ProbeVendor"])

	gateway := TemplateDataFromContext(&ScaffoldContext{
		Name:  "bedrock-provider",
		Model: "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
	})
	assert.Equal(t, "", gateway["ProbeVendor"],
		"a Bedrock deployment has AWS credentials, not ANTHROPIC_API_KEY")

	vertex := TemplateDataFromContext(&ScaffoldContext{
		Name:  "vertex-provider",
		Model: "vertex_ai/gemini-2.5-flash",
	})
	assert.Equal(t, "", vertex["ProbeVendor"],
		"Vertex authenticates with ADC / Workload Identity, not an AI Studio key")

	none := TemplateDataFromContext(&ScaffoldContext{Name: "basic-agent"})
	assert.Equal(t, "", none["ProbeVendor"])
}

// Java's llm-provider computes its own $model (it defaults an empty .Model),
// so it resolves the vendor through this function rather than the data key.
func TestProbeVendorTemplateFunc(t *testing.T) {
	r := NewTemplateRenderer()
	render := func(tmpl string) string {
		out, err := r.RenderString(tmpl, map[string]interface{}{})
		require.NoError(t, err)
		return out
	}

	assert.Equal(t, "anthropic", render(`{{ probeVendor "anthropic/claude-sonnet-5" }}`))
	assert.Equal(t, "", render(`{{ probeVendor "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0" }}`))
	assert.Equal(t, "", render(`{{ probeVendor "vertex_ai/gemini-2.5-flash" }}`))
}
