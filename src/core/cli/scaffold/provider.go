// Package scaffold provides the scaffolding functionality for meshctl.
// It implements a plugin-style architecture where different providers
// (static templates, LLM-based) can generate MCP Mesh agents.
package scaffold

import (
	"fmt"
	"regexp"

	"github.com/spf13/cobra"
)

// supportedLanguages defines the languages supported for scaffold generation
// Currently only Python is supported; TypeScript and Rust coming soon
var supportedLanguages = []string{"python"}

// supportedAgentTypes defines the agent types that can be scaffolded
var supportedAgentTypes = []string{"tool", "llm-agent", "llm-provider"}

// validNamePattern defines the regex for valid agent names
// Must start with a letter, can contain letters, numbers, hyphens, and underscores
var validNamePattern = regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9_-]*$`)

// ScaffoldProvider defines the interface for scaffold generation providers.
// Implementations handle different generation strategies (static templates, LLM, etc.)
type ScaffoldProvider interface {
	// Name returns the provider's unique identifier (e.g., "static", "llm")
	Name() string

	// Description returns a human-readable description of the provider
	Description() string

	// RegisterFlags adds provider-specific flags to the command
	RegisterFlags(cmd *cobra.Command)

	// Validate checks if the provided context is valid for this provider
	Validate(ctx *ScaffoldContext) error

	// Execute performs the scaffold generation
	Execute(ctx *ScaffoldContext) error
}

// ScaffoldContext contains all information needed for scaffold generation
type ScaffoldContext struct {
	// Common fields
	Name        string // Agent name
	Description string // Agent description
	Language    string // Target language (python, typescript, rust)
	OutputDir   string // Output directory
	Port        int    // HTTP port

	// Agent type: "tool", "llm-agent", "llm-provider"
	AgentType string

	// Provider-specific (static)
	Template    string // Template name (basic, llm-agent, multi-tool)
	TemplateDir string // Custom template directory
	ConfigFile  string // Config file path

	// Tool-specific (for basic tool agents)
	Capabilities []string // Capability names
	Tags         []string // Discovery tags
	Dependencies []string // Dependency capabilities

	// LLM-agent specific (for @mesh.llm decorator)
	LLMProviderSelector string   // "claude" or "openai" for provider selection
	ProviderTags        []string // Tags to filter LLM provider
	MaxIterations       int      // Max agentic loop iterations
	SystemPrompt        string   // System prompt (inline or file:// path)
	ContextParam        string   // Context parameter name
	ResponseFormat      string   // "text" or "json"

	// Tool filter for @mesh.llm (which tools the LLM can access)
	// Filter can be:
	// - nil/empty: No tools (use with FilterMode="*" for all tools)
	// - Single filter: {"capability": "x", "tags": ["a", "b"]}
	// - Multiple filters: [{"capability": "x"}, {"tags": ["y"]}]
	ToolFilter []map[string]interface{}
	FilterMode string // "all", "best_match", "*" (default: "all")

	// LLM-provider specific (for @mesh.llm_provider decorator)
	Model string // LiteLLM model string (e.g., "anthropic/claude-sonnet-4-5")

	// Provider-specific (llm scaffold mode)
	FromDoc      string // Requirements document path
	Prompt       string // Natural language prompt
	APIKey       string // LLM API key
	LLMProvider  string // LLM provider (claude, openai)
	ValidateCode bool   // Validate generated code

	// Runtime
	Cmd *cobra.Command // Reference to command for flag access
}

// NewScaffoldContext creates a new ScaffoldContext with default values
func NewScaffoldContext() *ScaffoldContext {
	return &ScaffoldContext{
		Language:            "python",
		OutputDir:           ".",
		Port:                9000,
		Template:            "basic",
		AgentType:           "tool",
		MaxIterations:       1,
		ContextParam:        "ctx",
		ResponseFormat:      "text",
		LLMProviderSelector: "claude",
		LLMProvider:         "claude",
		FilterMode:          "all",
	}
}

// Validate checks if the context has valid common fields
func (ctx *ScaffoldContext) Validate() error {
	// Validate name
	if ctx.Name == "" {
		return fmt.Errorf("name is required")
	}

	if !validNamePattern.MatchString(ctx.Name) {
		return fmt.Errorf("invalid agent name: must start with a letter and contain only letters, numbers, hyphens, and underscores")
	}

	// Validate language
	if !IsValidLanguage(ctx.Language) {
		if ctx.Language == "typescript" || ctx.Language == "rust" {
			return fmt.Errorf("language '%s' support coming soon; currently only 'python' is supported", ctx.Language)
		}
		return fmt.Errorf("unsupported language: %s (supported: %v)", ctx.Language, supportedLanguages)
	}

	// Validate agent type
	if ctx.AgentType != "" && !IsValidAgentType(ctx.AgentType) {
		return fmt.Errorf("unsupported agent type: %s (supported: %v)", ctx.AgentType, supportedAgentTypes)
	}

	// Validate LLM-provider specific fields
	if ctx.AgentType == "llm-provider" && ctx.Model == "" {
		return fmt.Errorf("model is required for llm-provider agent type")
	}

	return nil
}

// SupportedLanguages returns the list of supported languages
func SupportedLanguages() []string {
	return supportedLanguages
}

// IsValidLanguage checks if a language is supported
func IsValidLanguage(lang string) bool {
	for _, l := range supportedLanguages {
		if l == lang {
			return true
		}
	}
	return false
}

// SupportedAgentTypes returns the list of supported agent types
func SupportedAgentTypes() []string {
	return supportedAgentTypes
}

// IsValidAgentType checks if an agent type is supported
func IsValidAgentType(agentType string) bool {
	for _, t := range supportedAgentTypes {
		if t == agentType {
			return true
		}
	}
	return false
}
