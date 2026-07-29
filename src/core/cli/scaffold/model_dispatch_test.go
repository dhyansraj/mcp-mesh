package scaffold

import (
	"testing"

	"github.com/stretchr/testify/assert"
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
