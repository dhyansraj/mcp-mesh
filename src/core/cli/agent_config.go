package cli

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

type AgentConfig struct {
	Script            string            `yaml:"script"`
	WorkingDirectory  string            `yaml:"working_directory,omitempty"`
	PythonInterpreter string            `yaml:"python_interpreter,omitempty"`
	Environment       map[string]string `yaml:"environment,omitempty"`
	Metadata          AgentMetadata     `yaml:"metadata,omitempty"`
	Resources         ResourceLimits    `yaml:"resources,omitempty"`
}

type AgentMetadata struct {
	Name        string   `yaml:"name,omitempty"`
	Version     string   `yaml:"version,omitempty"`
	Description string   `yaml:"description,omitempty"`
	Tags        []string `yaml:"tags,omitempty"`
}

type ResourceLimits struct {
	Timeout     int    `yaml:"timeout,omitempty"`
	MemoryLimit string `yaml:"memory_limit,omitempty"`
	CPULimit    string `yaml:"cpu_limit,omitempty"`
}

// LoadAgentConfig loads configuration from a YAML file
func LoadAgentConfig(configPath string) (*AgentConfig, error) {
	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var config AgentConfig
	if err := yaml.Unmarshal(data, &config); err != nil {
		return nil, fmt.Errorf("failed to parse config YAML: %w", err)
	}

	// Validate required fields
	if config.Script == "" {
		return nil, fmt.Errorf("config must specify 'script' field")
	}

	// Resolve relative paths
	if !filepath.IsAbs(config.Script) {
		configDir := filepath.Dir(configPath)
		config.Script = filepath.Join(configDir, config.Script)
	}

	if config.WorkingDirectory != "" && !filepath.IsAbs(config.WorkingDirectory) {
		configDir := filepath.Dir(configPath)
		config.WorkingDirectory = filepath.Join(configDir, config.WorkingDirectory)
	}

	return &config, nil
}

// SaveAgentConfig saves configuration to a YAML file
func SaveAgentConfig(config *AgentConfig, configPath string) error {
	data, err := yaml.Marshal(config)
	if err != nil {
		return fmt.Errorf("failed to marshal config to YAML: %w", err)
	}

	if err := os.WriteFile(configPath, data, 0644); err != nil {
		return fmt.Errorf("failed to write config file: %w", err)
	}

	return nil
}

// ValidateAgentConfig validates the configuration
func ValidateAgentConfig(config *AgentConfig) error {
	// Check if script file exists
	if !fileExists(config.Script) {
		return fmt.Errorf("script file does not exist: %s", config.Script)
	}

	// Check if working directory exists (if specified)
	if config.WorkingDirectory != "" && !dirExists(config.WorkingDirectory) {
		return fmt.Errorf("working directory does not exist: %s", config.WorkingDirectory)
	}

	// Check if Python interpreter exists (if specified)
	if config.PythonInterpreter != "" && !fileExists(config.PythonInterpreter) {
		return fmt.Errorf("Python interpreter does not exist: %s", config.PythonInterpreter)
	}

	// Validate timeout
	if config.Resources.Timeout < 0 {
		return fmt.Errorf("timeout must be non-negative")
	}

	return nil
}

// GetWorkingDirectory returns the working directory for the agent
func (ac *AgentConfig) GetWorkingDirectory() string {
	if ac.WorkingDirectory != "" {
		return ac.WorkingDirectory
	}
	// Default to script directory
	return filepath.Dir(ac.Script)
}

// GetEnvironmentVariables returns environment variables as a slice
func (ac *AgentConfig) GetEnvironmentVariables() []string {
	var envVars []string

	// Start with current environment
	envVars = append(envVars, os.Environ()...)

	// Add custom environment variables
	for key, value := range ac.Environment {
		// Support environment variable expansion
		expandedValue := os.ExpandEnv(value)
		envVars = append(envVars, fmt.Sprintf("%s=%s", key, expandedValue))
	}

	return envVars
}

// CreateSampleConfig creates a sample configuration file
func CreateSampleConfig(configPath string) error {
	sampleConfig := &AgentConfig{
		Script:           "agent.py",
		WorkingDirectory: ".",
		Environment: map[string]string{
			"MCP_MESH_LOG_LEVEL": "INFO",
			"CUSTOM_VAR":         "value",
		},
		Metadata: AgentMetadata{
			Name:        "sample-agent",
			Version:     "1.0.0",
			Description: "Sample MCP Mesh agent",
			Tags:        []string{"sample", "demo"},
		},
		Resources: ResourceLimits{
			Timeout:     300,
			MemoryLimit: "512MB",
			CPULimit:    "1",
		},
	}

	return SaveAgentConfig(sampleConfig, configPath)
}
