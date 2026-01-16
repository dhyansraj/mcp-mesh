package scaffold

import (
	"os"
	"testing"

	"github.com/spf13/cobra"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestLLMProvider_ImplementsInterface(t *testing.T) {
	var _ ScaffoldProvider = (*LLMProvider)(nil)
}

func TestNewLLMProvider(t *testing.T) {
	provider := NewLLMProvider()

	assert.NotNil(t, provider)
}

func TestLLMProvider_Name(t *testing.T) {
	provider := NewLLMProvider()

	assert.Equal(t, "llm", provider.Name())
}

func TestLLMProvider_Description(t *testing.T) {
	provider := NewLLMProvider()

	desc := provider.Description()
	assert.NotEmpty(t, desc)
	assert.Contains(t, desc, "LLM")
}

func TestLLMProvider_RegisterFlags(t *testing.T) {
	provider := NewLLMProvider()
	cmd := &cobra.Command{}

	provider.RegisterFlags(cmd)

	// Check LLM-specific flags are registered
	assert.NotNil(t, cmd.Flags().Lookup("from-doc"))
	assert.NotNil(t, cmd.Flags().Lookup("prompt"))
	assert.NotNil(t, cmd.Flags().Lookup("provider"))
	assert.NotNil(t, cmd.Flags().Lookup("validate"))

	// api-key flag should NOT exist anymore
	assert.Nil(t, cmd.Flags().Lookup("api-key"))

	// Check default values
	llmProvider, _ := cmd.Flags().GetString("provider")
	assert.Equal(t, "claude", llmProvider)
}

func TestLLMProvider_Validate_WithClaudeEnvVar(t *testing.T) {
	// Set Claude API key
	os.Setenv("ANTHROPIC_API_KEY", "test-claude-key")
	defer os.Unsetenv("ANTHROPIC_API_KEY")

	provider := NewLLMProvider()
	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Language:    "python",
		FromDoc:     "requirements.md",
		LLMProvider: "claude",
	}

	err := provider.Validate(ctx)
	require.NoError(t, err)
	assert.Equal(t, "test-claude-key", ctx.APIKey)
}

func TestLLMProvider_Validate_WithOpenAIEnvVar(t *testing.T) {
	// Set OpenAI API key
	os.Setenv("OPENAI_API_KEY", "test-openai-key")
	defer os.Unsetenv("OPENAI_API_KEY")

	provider := NewLLMProvider()
	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Language:    "python",
		Prompt:      "Create a weather agent",
		LLMProvider: "openai",
	}

	err := provider.Validate(ctx)
	require.NoError(t, err)
	assert.Equal(t, "test-openai-key", ctx.APIKey)
}

func TestLLMProvider_Validate_MissingEnvVar(t *testing.T) {
	// Ensure env var is NOT set
	os.Unsetenv("ANTHROPIC_API_KEY")

	provider := NewLLMProvider()
	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Language:    "python",
		FromDoc:     "requirements.md",
		LLMProvider: "claude",
	}

	err := provider.Validate(ctx)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "ANTHROPIC_API_KEY")
	assert.Contains(t, err.Error(), "claude")
}

func TestLLMProvider_Validate_MissingOpenAIEnvVar(t *testing.T) {
	// Ensure env var is NOT set
	os.Unsetenv("OPENAI_API_KEY")

	provider := NewLLMProvider()
	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Language:    "python",
		FromDoc:     "requirements.md",
		LLMProvider: "openai",
	}

	err := provider.Validate(ctx)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "OPENAI_API_KEY")
	assert.Contains(t, err.Error(), "openai")
}

func TestLLMProvider_Validate(t *testing.T) {
	// Set API key for tests that need it
	os.Setenv("ANTHROPIC_API_KEY", "test-key")
	os.Setenv("OPENAI_API_KEY", "test-key")
	defer func() {
		os.Unsetenv("ANTHROPIC_API_KEY")
		os.Unsetenv("OPENAI_API_KEY")
	}()

	provider := NewLLMProvider()

	tests := []struct {
		name    string
		ctx     *ScaffoldContext
		wantErr bool
		errMsg  string
	}{
		{
			name: "valid with from-doc and claude",
			ctx: &ScaffoldContext{
				Name:        "my-agent",
				Language:    "python",
				FromDoc:     "requirements.md",
				LLMProvider: "claude",
			},
			wantErr: false,
		},
		{
			name: "valid with prompt and openai",
			ctx: &ScaffoldContext{
				Name:        "my-agent",
				Language:    "python",
				Prompt:      "Create a weather agent",
				LLMProvider: "openai",
			},
			wantErr: false,
		},
		{
			name: "valid with both from-doc and prompt",
			ctx: &ScaffoldContext{
				Name:        "my-agent",
				Language:    "python",
				FromDoc:     "requirements.md",
				Prompt:      "Create a weather agent",
				LLMProvider: "claude",
			},
			wantErr: false,
		},
		{
			name: "missing from-doc and prompt",
			ctx: &ScaffoldContext{
				Name:        "my-agent",
				Language:    "python",
				LLMProvider: "claude",
			},
			wantErr: true,
			errMsg:  "either --from-doc or --prompt required",
		},
		{
			name: "missing name still fails",
			ctx: &ScaffoldContext{
				Language:    "python",
				FromDoc:     "requirements.md",
				LLMProvider: "claude",
			},
			wantErr: true,
			errMsg:  "name is required",
		},
		{
			name: "invalid llm provider",
			ctx: &ScaffoldContext{
				Name:        "my-agent",
				Language:    "python",
				Prompt:      "Create agent",
				LLMProvider: "invalid",
			},
			wantErr: true,
			errMsg:  "unsupported LLM provider",
		},
		{
			name: "empty provider defaults to claude",
			ctx: &ScaffoldContext{
				Name:        "my-agent",
				Language:    "python",
				Prompt:      "Create agent",
				LLMProvider: "", // empty, should default to claude
			},
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := provider.Validate(tt.ctx)
			if tt.wantErr {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.errMsg)
			} else {
				require.NoError(t, err)
			}
		})
	}
}

func TestLLMProvider_Execute_NotImplemented(t *testing.T) {
	provider := NewLLMProvider()
	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Language:    "python",
		FromDoc:     "requirements.md",
		LLMProvider: "claude",
		APIKey:      "test-key",
	}

	err := provider.Execute(ctx)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "not implemented")
}

func TestLLMProvider_SupportedProviders(t *testing.T) {
	providers := SupportedLLMProviders()

	assert.Contains(t, providers, "claude")
	assert.Contains(t, providers, "openai")
	assert.Contains(t, providers, "gemini")
	assert.Len(t, providers, 3)
}

func TestLLMProvider_IsValidLLMProvider(t *testing.T) {
	assert.True(t, IsValidLLMProvider("claude"))
	assert.True(t, IsValidLLMProvider("openai"))
	assert.True(t, IsValidLLMProvider("gemini"))
	assert.False(t, IsValidLLMProvider("invalid"))
	assert.False(t, IsValidLLMProvider(""))
}

func TestLLMProvider_GetAPIKeyEnvVar(t *testing.T) {
	assert.Equal(t, "ANTHROPIC_API_KEY", GetAPIKeyEnvVar("claude"))
	assert.Equal(t, "OPENAI_API_KEY", GetAPIKeyEnvVar("openai"))
	assert.Equal(t, "GOOGLE_API_KEY", GetAPIKeyEnvVar("gemini"))
	assert.Equal(t, "", GetAPIKeyEnvVar("invalid"))
	assert.Equal(t, "", GetAPIKeyEnvVar(""))
}
