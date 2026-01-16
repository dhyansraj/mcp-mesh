package scaffold

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

// supportedLLMProviders defines the LLM providers available for generation
var supportedLLMProviders = []string{"claude", "openai", "gemini"}

// llmProviderEnvVars maps provider names to their API key environment variables
var llmProviderEnvVars = map[string]string{
	"claude": "ANTHROPIC_API_KEY",
	"openai": "OPENAI_API_KEY",
	"gemini": "GOOGLE_API_KEY",
}

// LLMProvider implements ScaffoldProvider for LLM-based generation.
// It uses LLM APIs to generate agents from requirements documents or prompts.
type LLMProvider struct{}

// NewLLMProvider creates a new LLM-based provider
func NewLLMProvider() *LLMProvider {
	return &LLMProvider{}
}

// Name returns the provider's unique identifier
func (p *LLMProvider) Name() string {
	return "llm"
}

// Description returns a human-readable description of the provider
func (p *LLMProvider) Description() string {
	return "Generate using LLM from requirements document or prompt"
}

// RegisterFlags adds LLM-specific flags to the command
func (p *LLMProvider) RegisterFlags(cmd *cobra.Command) {
	cmd.Flags().String("from-doc", "", "Requirements document path")
	cmd.Flags().String("prompt", "", "Natural language prompt")
	cmd.Flags().String("provider", "claude", "LLM provider: claude, openai, gemini (uses provider-specific env var for API key)")
	cmd.Flags().Bool("validate", false, "Validate generated code")
}

// Validate checks if the provided context is valid for LLM generation
func (p *LLMProvider) Validate(ctx *ScaffoldContext) error {
	// First validate common fields
	if err := ctx.Validate(); err != nil {
		return err
	}

	// Validate LLM provider
	if ctx.LLMProvider == "" {
		ctx.LLMProvider = "claude" // default
	}
	if !IsValidLLMProvider(ctx.LLMProvider) {
		return fmt.Errorf("unsupported LLM provider: %s (supported: %v)", ctx.LLMProvider, supportedLLMProviders)
	}

	// Get API key from provider-specific environment variable
	envVar := GetAPIKeyEnvVar(ctx.LLMProvider)
	ctx.APIKey = os.Getenv(envVar)
	if ctx.APIKey == "" {
		return fmt.Errorf("API key required: set %s environment variable for %s provider", envVar, ctx.LLMProvider)
	}

	// Check for requirements source
	if ctx.FromDoc == "" && ctx.Prompt == "" {
		return fmt.Errorf("either --from-doc or --prompt required for LLM mode")
	}

	return nil
}

// Execute performs the scaffold generation using LLM.
// This is a stub implementation for Phase 1.
func (p *LLMProvider) Execute(ctx *ScaffoldContext) error {
	return fmt.Errorf("llm provider not implemented yet (coming in Phase 3)")
}

// SupportedLLMProviders returns the list of available LLM providers
func SupportedLLMProviders() []string {
	return supportedLLMProviders
}

// IsValidLLMProvider checks if an LLM provider is supported
func IsValidLLMProvider(provider string) bool {
	for _, p := range supportedLLMProviders {
		if p == provider {
			return true
		}
	}
	return false
}

// GetAPIKeyEnvVar returns the environment variable name for a provider's API key
func GetAPIKeyEnvVar(provider string) string {
	if envVar, ok := llmProviderEnvVars[provider]; ok {
		return envVar
	}
	return ""
}

// init registers the LLM provider with the default registry
func init() {
	DefaultRegistry.Register(NewLLMProvider())
}
