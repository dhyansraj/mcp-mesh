package scaffold

import (
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

// ScaffoldConfig represents a YAML configuration file for scaffolding
type ScaffoldConfig struct {
	// Common fields
	AgentType   string `yaml:"agent_type"`
	Name        string `yaml:"name"`
	Description string `yaml:"description"`
	Port        int    `yaml:"port"`

	// LLM agent configuration
	LLM *LLMConfig `yaml:"llm,omitempty"`

	// LLM provider configuration
	Provider *ProviderConfig `yaml:"provider,omitempty"`

	// Tool definitions (for basic tool agents)
	Tools []ToolConfig `yaml:"tools,omitempty"`

	// Tags for discovery
	Tags []string `yaml:"tags,omitempty"`
}

// LLMConfig contains configuration for @mesh.llm agents
type LLMConfig struct {
	// Provider selection (claude or openai)
	Provider string `yaml:"provider"`

	// Provider filter tags
	ProviderTags []string `yaml:"provider_tags,omitempty"`

	// Max agentic loop iterations
	MaxIterations int `yaml:"max_iterations"`

	// System prompt (inline or file:// path)
	SystemPrompt string `yaml:"system_prompt"`

	// Context parameter name
	ContextParam string `yaml:"context_param"`

	// Response format (text or json)
	ResponseFormat string `yaml:"response_format"`

	// Tool filter for which tools the LLM can access
	// Can be:
	// - Single filter: {capability: "x", tags: ["a"]}
	// - Multiple filters: [{capability: "x"}, {tags: ["y"]}]
	ToolFilter []map[string]interface{} `yaml:"filter,omitempty"`

	// Filter mode: "all", "best_match", or "*"
	FilterMode string `yaml:"filter_mode,omitempty"`
}

// ProviderConfig contains configuration for @mesh.llm_provider agents
type ProviderConfig struct {
	// LiteLLM model string
	Model string `yaml:"model"`

	// Tags for discovery
	Tags []string `yaml:"tags,omitempty"`
}

// ToolConfig contains configuration for individual tools
type ToolConfig struct {
	// Capability name
	Capability string `yaml:"capability"`

	// Tool description
	Description string `yaml:"description"`

	// Tags for the tool
	Tags []string `yaml:"tags,omitempty"`

	// Dependencies (capability names)
	Dependencies []string `yaml:"dependencies,omitempty"`
}

// LoadConfig loads a scaffold configuration from a YAML file
func LoadConfig(path string) (*ScaffoldConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var config ScaffoldConfig
	if err := yaml.Unmarshal(data, &config); err != nil {
		return nil, fmt.Errorf("failed to parse config file: %w", err)
	}

	// Set defaults
	if config.Port == 0 {
		config.Port = 9000
	}
	if config.AgentType == "" {
		config.AgentType = "tool"
	}

	return &config, nil
}

// Validate checks if the configuration is valid
func (c *ScaffoldConfig) Validate() error {
	if c.Name == "" {
		return fmt.Errorf("name is required in config")
	}

	if !IsValidAgentType(c.AgentType) {
		return fmt.Errorf("invalid agent_type: %s (supported: %v)", c.AgentType, supportedAgentTypes)
	}

	switch c.AgentType {
	case "llm-agent":
		if c.LLM == nil {
			return fmt.Errorf("llm section is required for llm-agent type")
		}
		if c.LLM.Provider == "" {
			return fmt.Errorf("llm.provider is required (claude or openai)")
		}
		if c.LLM.Provider != "claude" && c.LLM.Provider != "openai" {
			return fmt.Errorf("llm.provider must be 'claude' or 'openai'")
		}
	case "llm-provider":
		if c.Provider == nil {
			return fmt.Errorf("provider section is required for llm-provider type")
		}
		if c.Provider.Model == "" {
			return fmt.Errorf("provider.model is required")
		}
	}

	return nil
}

// ContextFromConfig creates a ScaffoldContext from a config file
func ContextFromConfig(config *ScaffoldConfig) *ScaffoldContext {
	ctx := NewScaffoldContext()
	ctx.Name = config.Name
	ctx.Description = config.Description
	ctx.Port = config.Port
	ctx.AgentType = config.AgentType
	ctx.Tags = config.Tags

	// Map agent type to template
	switch config.AgentType {
	case "tool":
		ctx.Template = "basic"
	case "llm-agent":
		ctx.Template = "llm-agent"
	case "llm-provider":
		ctx.Template = "llm-provider"
	}

	// LLM agent configuration
	if config.LLM != nil {
		ctx.LLMProviderSelector = config.LLM.Provider
		ctx.ProviderTags = config.LLM.ProviderTags
		ctx.MaxIterations = config.LLM.MaxIterations
		ctx.SystemPrompt = config.LLM.SystemPrompt
		ctx.ContextParam = config.LLM.ContextParam
		ctx.ResponseFormat = config.LLM.ResponseFormat
		ctx.ToolFilter = config.LLM.ToolFilter
		ctx.FilterMode = config.LLM.FilterMode

		// Set default provider tags if not specified
		if len(ctx.ProviderTags) == 0 {
			switch config.LLM.Provider {
			case "claude":
				ctx.ProviderTags = []string{"llm", "+claude"}
			case "openai":
				ctx.ProviderTags = []string{"llm", "+gpt"}
			}
		}

		// Set defaults
		if ctx.MaxIterations == 0 {
			ctx.MaxIterations = 1
		}
		if ctx.ContextParam == "" {
			ctx.ContextParam = "ctx"
		}
		if ctx.ResponseFormat == "" {
			ctx.ResponseFormat = "text"
		}
		if ctx.FilterMode == "" {
			ctx.FilterMode = "all"
		}
	}

	// LLM provider configuration
	if config.Provider != nil {
		ctx.Model = config.Provider.Model
		if len(config.Provider.Tags) > 0 {
			ctx.Tags = config.Provider.Tags
		}
	}

	// Tool configuration (for basic agents)
	if len(config.Tools) > 0 {
		for _, tool := range config.Tools {
			ctx.Capabilities = append(ctx.Capabilities, tool.Capability)
			ctx.Dependencies = append(ctx.Dependencies, tool.Dependencies...)
		}
	}

	return ctx
}
