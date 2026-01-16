package scaffold

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestLoadConfig_ToolAgent(t *testing.T) {
	yaml := `
agent_type: tool
name: my-tool
description: A test tool agent
port: 9100
tags:
  - tools
  - test
tools:
  - capability: hello
    description: Say hello
    tags: ["greeting"]
  - capability: echo
    description: Echo message
`
	path := writeTestConfig(t, yaml)

	config, err := LoadConfig(path)
	require.NoError(t, err)

	assert.Equal(t, "tool", config.AgentType)
	assert.Equal(t, "my-tool", config.Name)
	assert.Equal(t, "A test tool agent", config.Description)
	assert.Equal(t, 9100, config.Port)
	assert.Equal(t, []string{"tools", "test"}, config.Tags)
	assert.Len(t, config.Tools, 2)
	assert.Equal(t, "hello", config.Tools[0].Capability)
}

func TestLoadConfig_LLMAgent(t *testing.T) {
	yaml := `
agent_type: llm-agent
name: emotion-analyzer
description: Analyzes emotional state
port: 9200

llm:
  provider: openai
  provider_tags: ["llm", "+gpt"]
  max_iterations: 3
  system_prompt: |
    You are an emotion analyzer.
    Analyze the emotional state of the user.
  context_param: emotion_ctx
  response_format: json

tags:
  - llm
  - analysis
`
	path := writeTestConfig(t, yaml)

	config, err := LoadConfig(path)
	require.NoError(t, err)

	assert.Equal(t, "llm-agent", config.AgentType)
	assert.Equal(t, "emotion-analyzer", config.Name)
	require.NotNil(t, config.LLM)
	assert.Equal(t, "openai", config.LLM.Provider)
	assert.Equal(t, []string{"llm", "+gpt"}, config.LLM.ProviderTags)
	assert.Equal(t, 3, config.LLM.MaxIterations)
	assert.Contains(t, config.LLM.SystemPrompt, "emotion analyzer")
	assert.Equal(t, "emotion_ctx", config.LLM.ContextParam)
	assert.Equal(t, "json", config.LLM.ResponseFormat)
}

func TestLoadConfig_LLMProvider(t *testing.T) {
	yaml := `
agent_type: llm-provider
name: claude-provider
description: Claude LLM provider
port: 9110

provider:
  model: anthropic/claude-sonnet-4-5
  tags:
    - llm
    - claude
    - anthropic
    - provider
`
	path := writeTestConfig(t, yaml)

	config, err := LoadConfig(path)
	require.NoError(t, err)

	assert.Equal(t, "llm-provider", config.AgentType)
	assert.Equal(t, "claude-provider", config.Name)
	require.NotNil(t, config.Provider)
	assert.Equal(t, "anthropic/claude-sonnet-4-5", config.Provider.Model)
	assert.Equal(t, []string{"llm", "claude", "anthropic", "provider"}, config.Provider.Tags)
}

func TestLoadConfig_Defaults(t *testing.T) {
	yaml := `
name: minimal-agent
`
	path := writeTestConfig(t, yaml)

	config, err := LoadConfig(path)
	require.NoError(t, err)

	assert.Equal(t, "tool", config.AgentType)
	assert.Equal(t, 9000, config.Port)
}

func TestLoadConfig_FileNotFound(t *testing.T) {
	_, err := LoadConfig("/nonexistent/path/config.yaml")
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "failed to read config file")
}

func TestLoadConfig_InvalidYAML(t *testing.T) {
	yaml := `
name: test
invalid: [unclosed bracket
`
	path := writeTestConfig(t, yaml)

	_, err := LoadConfig(path)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "failed to parse config file")
}

func TestScaffoldConfig_Validate(t *testing.T) {
	tests := []struct {
		name    string
		config  ScaffoldConfig
		wantErr string
	}{
		{
			name:    "missing name",
			config:  ScaffoldConfig{AgentType: "tool"},
			wantErr: "name is required",
		},
		{
			name:    "invalid agent type",
			config:  ScaffoldConfig{Name: "test", AgentType: "invalid"},
			wantErr: "invalid agent_type",
		},
		{
			name: "llm-agent missing llm section",
			config: ScaffoldConfig{
				Name:      "test",
				AgentType: "llm-agent",
			},
			wantErr: "llm section is required",
		},
		{
			name: "llm-agent missing provider",
			config: ScaffoldConfig{
				Name:      "test",
				AgentType: "llm-agent",
				LLM:       &LLMConfig{},
			},
			wantErr: "llm.provider is required",
		},
		{
			name: "llm-agent invalid provider",
			config: ScaffoldConfig{
				Name:      "test",
				AgentType: "llm-agent",
				LLM:       &LLMConfig{Provider: "invalid"},
			},
			wantErr: "llm.provider must be 'claude', 'openai', or 'gemini'",
		},
		{
			name: "llm-provider missing provider section",
			config: ScaffoldConfig{
				Name:      "test",
				AgentType: "llm-provider",
			},
			wantErr: "provider section is required",
		},
		{
			name: "llm-provider missing model",
			config: ScaffoldConfig{
				Name:      "test",
				AgentType: "llm-provider",
				Provider:  &ProviderConfig{},
			},
			wantErr: "provider.model is required",
		},
		{
			name: "valid tool agent",
			config: ScaffoldConfig{
				Name:      "test",
				AgentType: "tool",
			},
			wantErr: "",
		},
		{
			name: "valid llm-agent",
			config: ScaffoldConfig{
				Name:      "test",
				AgentType: "llm-agent",
				LLM:       &LLMConfig{Provider: "claude"},
			},
			wantErr: "",
		},
		{
			name: "valid llm-provider",
			config: ScaffoldConfig{
				Name:      "test",
				AgentType: "llm-provider",
				Provider:  &ProviderConfig{Model: "anthropic/claude-3-opus"},
			},
			wantErr: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.config.Validate()
			if tt.wantErr != "" {
				assert.Error(t, err)
				assert.Contains(t, err.Error(), tt.wantErr)
			} else {
				assert.NoError(t, err)
			}
		})
	}
}

func TestContextFromConfig_ToolAgent(t *testing.T) {
	config := &ScaffoldConfig{
		AgentType:   "tool",
		Name:        "my-tool",
		Description: "Test tool",
		Port:        9100,
		Tags:        []string{"tools"},
		Tools: []ToolConfig{
			{Capability: "hello", Description: "Say hello"},
			{Capability: "echo", Description: "Echo"},
		},
	}

	ctx := ContextFromConfig(config)

	assert.Equal(t, "my-tool", ctx.Name)
	assert.Equal(t, "tool", ctx.AgentType)
	assert.Equal(t, "basic", ctx.Template)
	assert.Equal(t, 9100, ctx.Port)
	assert.Equal(t, []string{"hello", "echo"}, ctx.Capabilities)
}

func TestContextFromConfig_LLMAgent(t *testing.T) {
	config := &ScaffoldConfig{
		AgentType:   "llm-agent",
		Name:        "analyzer",
		Description: "Analyzer agent",
		Port:        9200,
		LLM: &LLMConfig{
			Provider:       "claude",
			MaxIterations:  5,
			SystemPrompt:   "You are an analyzer.",
			ContextParam:   "analysis_ctx",
			ResponseFormat: "json",
		},
	}

	ctx := ContextFromConfig(config)

	assert.Equal(t, "analyzer", ctx.Name)
	assert.Equal(t, "llm-agent", ctx.AgentType)
	assert.Equal(t, "llm-agent", ctx.Template)
	assert.Equal(t, "claude", ctx.LLMProviderSelector)
	assert.Equal(t, []string{"llm", "+claude"}, ctx.ProviderTags)
	assert.Equal(t, 5, ctx.MaxIterations)
	assert.Equal(t, "You are an analyzer.", ctx.SystemPrompt)
	assert.Equal(t, "analysis_ctx", ctx.ContextParam)
	assert.Equal(t, "json", ctx.ResponseFormat)
}

func TestContextFromConfig_LLMAgentDefaults(t *testing.T) {
	config := &ScaffoldConfig{
		AgentType: "llm-agent",
		Name:      "simple",
		Port:      9000,
		LLM: &LLMConfig{
			Provider: "openai",
		},
	}

	ctx := ContextFromConfig(config)

	// Check defaults are applied
	assert.Equal(t, 1, ctx.MaxIterations)
	assert.Equal(t, "ctx", ctx.ContextParam)
	assert.Equal(t, "text", ctx.ResponseFormat)
	assert.Equal(t, []string{"llm", "+gpt"}, ctx.ProviderTags)
}

func TestContextFromConfig_LLMProvider(t *testing.T) {
	config := &ScaffoldConfig{
		AgentType:   "llm-provider",
		Name:        "claude-provider",
		Description: "Claude provider",
		Port:        9110,
		Provider: &ProviderConfig{
			Model: "anthropic/claude-sonnet-4-5",
			Tags:  []string{"llm", "claude", "provider"},
		},
	}

	ctx := ContextFromConfig(config)

	assert.Equal(t, "claude-provider", ctx.Name)
	assert.Equal(t, "llm-provider", ctx.AgentType)
	assert.Equal(t, "llm-provider", ctx.Template)
	assert.Equal(t, "anthropic/claude-sonnet-4-5", ctx.Model)
	assert.Equal(t, []string{"llm", "claude", "provider"}, ctx.Tags)
}

// writeTestConfig writes a test config file and returns its path
func writeTestConfig(t *testing.T, content string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "scaffold.yaml")
	err := os.WriteFile(path, []byte(content), 0644)
	require.NoError(t, err)
	return path
}
