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
	assert.Equal(t, 9000, ctx.Port)
	assert.Equal(t, "basic", ctx.Template)
	assert.Equal(t, "claude", ctx.LLMProvider)
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
			name: "typescript coming soon",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "typescript",
			},
			wantErr: true,
			errMsg:  "coming soon",
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
			name: "empty language defaults to valid",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "",
			},
			wantErr: true,
			errMsg:  "unsupported language",
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
	// TypeScript and Rust coming soon
	assert.NotContains(t, languages, "typescript")
	assert.NotContains(t, languages, "rust")
	assert.Len(t, languages, 1)
}

func TestScaffoldContext_IsValidLanguage(t *testing.T) {
	assert.True(t, IsValidLanguage("python"))
	// TypeScript and Rust coming soon - not valid yet
	assert.False(t, IsValidLanguage("typescript"))
	assert.False(t, IsValidLanguage("rust"))
	assert.False(t, IsValidLanguage("cobol"))
	assert.False(t, IsValidLanguage(""))
	assert.False(t, IsValidLanguage("Python")) // case sensitive
}
