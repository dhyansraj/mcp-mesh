package scaffold

import (
	"testing"

	"github.com/spf13/cobra"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// MockProvider for testing
type MockProvider struct {
	name        string
	description string
	validateErr error
	executeErr  error
	executed    bool
}

func (m *MockProvider) Name() string                     { return m.name }
func (m *MockProvider) Description() string              { return m.description }
func (m *MockProvider) RegisterFlags(cmd *cobra.Command) {}
func (m *MockProvider) Validate(ctx *ScaffoldContext) error {
	return m.validateErr
}
func (m *MockProvider) Execute(ctx *ScaffoldContext) error {
	m.executed = true
	return m.executeErr
}

func TestScaffoldProvider_Interface(t *testing.T) {
	// Ensure MockProvider implements ScaffoldProvider
	var _ ScaffoldProvider = (*MockProvider)(nil)
}

func TestNewScaffoldContext(t *testing.T) {
	ctx := NewScaffoldContext()

	assert.Equal(t, "python", ctx.Language)
	assert.Equal(t, ".", ctx.OutputDir)
	assert.Equal(t, 8080, ctx.Port)
	assert.Equal(t, "basic", ctx.Template)
}

func TestScaffoldContext_Validate(t *testing.T) {
	tests := []struct {
		name    string
		ctx     *ScaffoldContext
		wantErr bool
		errMsg  string
	}{
		{
			name: "valid context",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "python",
			},
			wantErr: false,
		},
		{
			name: "typescript is now supported",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "typescript",
			},
			wantErr: false,
		},
		{
			name: "rust coming soon",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "rust",
			},
			wantErr: true,
			errMsg:  "coming soon",
		},
		{
			name: "missing name",
			ctx: &ScaffoldContext{
				Language: "python",
			},
			wantErr: true,
			errMsg:  "name is required",
		},
		{
			name: "empty name",
			ctx: &ScaffoldContext{
				Name:     "",
				Language: "python",
			},
			wantErr: true,
			errMsg:  "name is required",
		},
		{
			name: "invalid language",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "cobol",
			},
			wantErr: true,
			errMsg:  "unsupported language",
		},
		{
			name: "empty language defaults to python",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "",
			},
			wantErr: false,
		},
		{
			name: "invalid name with spaces",
			ctx: &ScaffoldContext{
				Name:     "my agent",
				Language: "python",
			},
			wantErr: true,
			errMsg:  "invalid agent name",
		},
		{
			name: "invalid name starting with number",
			ctx: &ScaffoldContext{
				Name:     "123agent",
				Language: "python",
			},
			wantErr: true,
			errMsg:  "invalid agent name",
		},
		{
			name: "valid name with hyphen",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "python",
			},
			wantErr: false,
		},
		{
			name: "valid name with underscore",
			ctx: &ScaffoldContext{
				Name:     "my_agent",
				Language: "python",
			},
			wantErr: false,
		},

		// --- llm-provider needs a model, whichever way it was selected ----
		//
		// Issue #1479. `meshctl scaffold --template llm-provider` never sets
		// AgentType (the flag was dropped in #957), so an agent-type-only
		// check let a modelless provider render. There is no correct
		// rendering of one: the Java template defaults the model for its code
		// while the README describes the raw, empty one, so the operator is
		// told to configure gateway credentials while the generated probe
		// demands ANTHROPIC_API_KEY — and the agent withdraws itself for good.
		{
			name: "llm-provider agent type without model",
			ctx: &ScaffoldContext{
				Name:      "my-provider",
				Language:  "python",
				AgentType: "llm-provider",
			},
			wantErr: true,
			errMsg:  "model is required",
		},
		{
			name: "llm-provider template without model",
			ctx: &ScaffoldContext{
				Name:     "my-provider",
				Language: "java",
				Template: "llm-provider",
			},
			wantErr: true,
			errMsg:  "model is required",
		},
		{
			// A whitespace-only --model is the same "no model" case wearing a
			// disguise: ModelFamily and DirectProbeVendor both trim before
			// resolving, so it answers "" for every question the templates ask
			// and renders the skeleton — with the blank string embedded in the
			// decorator as the model id.
			name: "llm-provider template with whitespace-only model",
			ctx: &ScaffoldContext{
				Name:     "my-provider",
				Language: "java",
				Template: "llm-provider",
				Model:    "   ",
			},
			wantErr: true,
			errMsg:  "model is required",
		},
		{
			name: "llm-provider template with model",
			ctx: &ScaffoldContext{
				Name:     "my-provider",
				Language: "java",
				Template: "llm-provider",
				Model:    "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
			},
			wantErr: false,
		},
		{
			// The requirement is scoped to the provider template: every other
			// template renders with an empty Model and must keep working.
			name: "basic template without model",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "python",
				Template: "basic",
			},
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.ctx.Validate()
			if tt.wantErr {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.errMsg)
			} else {
				require.NoError(t, err)
			}
		})
	}
}

func TestScaffoldContext_SupportedLanguages(t *testing.T) {
	languages := SupportedLanguages()

	assert.Contains(t, languages, "python")
	assert.Contains(t, languages, "typescript")
	assert.Contains(t, languages, "java")
	// Rust coming soon
	assert.NotContains(t, languages, "rust")
	assert.Len(t, languages, 3)
}

func TestScaffoldContext_IsValidLanguage(t *testing.T) {
	assert.True(t, IsValidLanguage("python"))
	assert.True(t, IsValidLanguage("typescript"))
	assert.True(t, IsValidLanguage("java"))
	// Rust coming soon - not valid yet
	assert.False(t, IsValidLanguage("rust"))
	assert.False(t, IsValidLanguage("cobol"))
	assert.False(t, IsValidLanguage(""))
	assert.False(t, IsValidLanguage("Python")) // case sensitive
}

func TestNormalizeLanguage(t *testing.T) {
	// Python variations
	assert.Equal(t, "python", NormalizeLanguage("python"))
	assert.Equal(t, "python", NormalizeLanguage("py"))
	assert.Equal(t, "python", NormalizeLanguage(""))

	// TypeScript variations
	assert.Equal(t, "typescript", NormalizeLanguage("typescript"))
	assert.Equal(t, "typescript", NormalizeLanguage("ts"))

	// Java variations
	assert.Equal(t, "java", NormalizeLanguage("java"))
	assert.Equal(t, "java", NormalizeLanguage("jv"))

	// Unknown returns as-is
	assert.Equal(t, "rust", NormalizeLanguage("rust"))
	assert.Equal(t, "cobol", NormalizeLanguage("cobol"))
}
