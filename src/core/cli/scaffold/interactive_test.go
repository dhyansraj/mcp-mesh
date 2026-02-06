package scaffold

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestSplitAndTrim(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected []string
	}{
		{
			name:     "simple comma separated",
			input:    "a,b,c",
			expected: []string{"a", "b", "c"},
		},
		{
			name:     "with spaces",
			input:    "a, b, c",
			expected: []string{"a", "b", "c"},
		},
		{
			name:     "with extra spaces",
			input:    "  a  ,  b  ,  c  ",
			expected: []string{"a", "b", "c"},
		},
		{
			name:     "empty parts",
			input:    "a,,b,",
			expected: []string{"a", "b"},
		},
		{
			name:     "single value",
			input:    "single",
			expected: []string{"single"},
		},
		{
			name:     "empty string",
			input:    "",
			expected: []string{},
		},
		{
			name:     "only spaces",
			input:    "   ,   ,   ",
			expected: []string{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := splitAndTrim(tt.input)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestContextFromInteractive_ToolAgent(t *testing.T) {
	ic := &InteractiveConfig{
		AgentType:   "tool",
		Name:        "my-tool",
		Description: "A test tool agent",
		Port:        9100,
		Tags:        []string{"tools", "test"},
	}

	ctx := ContextFromInteractive(ic)

	assert.Equal(t, "my-tool", ctx.Name)
	assert.Equal(t, "A test tool agent", ctx.Description)
	assert.Equal(t, 9100, ctx.Port)
	assert.Equal(t, "tool", ctx.AgentType)
	assert.Equal(t, "basic", ctx.Template)
	assert.Equal(t, []string{"tools", "test"}, ctx.Tags)
}

func TestContextFromInteractive_LLMAgent(t *testing.T) {
	ic := &InteractiveConfig{
		AgentType:           "llm-agent",
		Name:                "emotion-analyzer",
		Description:         "Analyzes emotional state",
		Port:                9200,
		LLMProviderSelector: "openai",
		ProviderTags:        []string{"llm", "+gpt"},
		MaxIterations:       3,
		UsePromptFile:       true,
		ContextParam:        "emotion_ctx",
		ResponseFormat:      "json",
		Tags:                []string{"llm", "analysis"},
	}

	ctx := ContextFromInteractive(ic)

	assert.Equal(t, "emotion-analyzer", ctx.Name)
	assert.Equal(t, "llm-agent", ctx.AgentType)
	assert.Equal(t, "llm-agent", ctx.Template)
	assert.Equal(t, "openai", ctx.LLMProviderSelector)
	assert.Equal(t, []string{"llm", "+gpt"}, ctx.ProviderTags)
	assert.Equal(t, 3, ctx.MaxIterations)
	assert.Equal(t, "file://prompts/emotion-analyzer.jinja2", ctx.SystemPrompt)
	assert.Equal(t, "emotion_ctx", ctx.ContextParam)
	assert.Equal(t, "json", ctx.ResponseFormat)
}

func TestContextFromInteractive_LLMAgentInlinePrompt(t *testing.T) {
	ic := &InteractiveConfig{
		AgentType:           "llm-agent",
		Name:                "simple-agent",
		Description:         "Simple agent",
		Port:                8080,
		LLMProviderSelector: "claude",
		ProviderTags:        []string{"llm", "+claude"},
		MaxIterations:       1,
		UsePromptFile:       false,
		SystemPrompt:        "You are a helpful assistant.",
		ContextParam:        "ctx",
		ResponseFormat:      "text",
	}

	ctx := ContextFromInteractive(ic)

	assert.Equal(t, "You are a helpful assistant.", ctx.SystemPrompt)
	assert.Equal(t, "text", ctx.ResponseFormat)
}

func TestContextFromInteractive_LLMProvider(t *testing.T) {
	ic := &InteractiveConfig{
		AgentType:   "llm-provider",
		Name:        "claude-provider",
		Description: "Claude LLM provider",
		Port:        9110,
		Model:       "anthropic/claude-sonnet-4-5",
		Tags:        []string{"llm", "claude", "anthropic", "provider"},
	}

	ctx := ContextFromInteractive(ic)

	assert.Equal(t, "claude-provider", ctx.Name)
	assert.Equal(t, "llm-provider", ctx.AgentType)
	assert.Equal(t, "llm-provider", ctx.Template)
	assert.Equal(t, "anthropic/claude-sonnet-4-5", ctx.Model)
	assert.Equal(t, []string{"llm", "claude", "anthropic", "provider"}, ctx.Tags)
}

func TestContextFromInteractive_DefaultValues(t *testing.T) {
	ic := &InteractiveConfig{
		AgentType: "tool",
		Name:      "test-agent",
		Port:      8080,
	}

	ctx := ContextFromInteractive(ic)

	// Should inherit defaults from NewScaffoldContext
	assert.Equal(t, "python", ctx.Language)
	assert.Equal(t, ".", ctx.OutputDir)
}

func TestInteractiveConfig_Defaults(t *testing.T) {
	ic := &InteractiveConfig{}

	// Verify zero values for InteractiveConfig
	assert.Equal(t, "", ic.AgentType)
	assert.Equal(t, "", ic.Name)
	assert.Equal(t, 0, ic.Port)
	assert.Equal(t, 0, ic.MaxIterations)
	assert.Nil(t, ic.Tags)
}
