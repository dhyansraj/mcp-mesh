package registry

import (
	"fmt"
	"net/url"
	"regexp"
	"strings"
)

// ValidationError represents validation errors
type ValidationError struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

func (e ValidationError) Error() string {
	return fmt.Sprintf("%s: %s", e.Field, e.Message)
}

// AgentRegistrationValidator provides validation for agent registration
// MUST match Python validation logic exactly
type AgentRegistrationValidator struct {
	// Regex patterns matching Python validation
	agentNamePattern       *regexp.Regexp
	capabilityNamePattern  *regexp.Regexp
	semanticVersionPattern *regexp.Regexp
}

// NewAgentRegistrationValidator creates a new validator instance
// Patterns MUST match Python validator regex exactly
func NewAgentRegistrationValidator() *AgentRegistrationValidator {
	return &AgentRegistrationValidator{
		// Kubernetes-style name validation (matches Python)
		agentNamePattern: regexp.MustCompile(`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`),
		// Capability name validation (matches Python)
		capabilityNamePattern: regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9_-]*$`),
		// Semantic version validation (matches Python)
		semanticVersionPattern: regexp.MustCompile(`^\d+\.\d+\.\d+(-[a-zA-Z0-9-]+)?$`),
	}
}

// ValidateAgentRegistration validates an agent registration request
// MUST match Python validate_agent_registration behavior exactly
func (v *AgentRegistrationValidator) ValidateAgentRegistration(req *AgentRegistrationRequest) error {
	if req == nil {
		return ValidationError{Field: "request", Message: "request cannot be nil"}
	}

	// Validate agent ID (matches Python validation)
	if err := v.validateAgentID(req.AgentID); err != nil {
		return err
	}

	// Validate metadata exists
	if req.Metadata == nil {
		return ValidationError{Field: "metadata", Message: "metadata is required"}
	}

	// Validate agent name
	if name, exists := req.Metadata["name"]; exists {
		if nameStr, ok := name.(string); ok {
			if err := v.validateAgentName(nameStr); err != nil {
				return err
			}
		}
	}

	// Validate namespace (if provided)
	if namespace, exists := req.Metadata["namespace"]; exists {
		if nsStr, ok := namespace.(string); ok {
			if err := v.validateNamespace(nsStr); err != nil {
				return err
			}
		}
	}

	// Validate endpoint (if provided)
	if endpoint, exists := req.Metadata["endpoint"]; exists {
		if epStr, ok := endpoint.(string); ok && epStr != "" {
			if err := v.validateEndpoint(epStr); err != nil {
				return err
			}
		}
	}

	// Validate capabilities
	if capabilities, exists := req.Metadata["capabilities"]; exists {
		if err := v.validateCapabilities(capabilities); err != nil {
			return err
		}
	}

	// Validate health configuration
	if err := v.validateHealthConfig(req.Metadata); err != nil {
		return err
	}

	return nil
}

// validateAgentID validates agent ID format
// MUST match Python agent ID validation exactly
func (v *AgentRegistrationValidator) validateAgentID(agentID string) error {
	if agentID == "" {
		return ValidationError{Field: "agent_id", Message: "agent_id is required"}
	}

	// Check length (matches Python max length)
	if len(agentID) > 253 {
		return ValidationError{Field: "agent_id", Message: "agent_id cannot exceed 253 characters"}
	}

	// Normalize and validate the agent ID
	normalized := normalizeName(agentID)
	if !v.agentNamePattern.MatchString(normalized) {
		return ValidationError{
			Field:   "agent_id",
			Message: "agent_id must contain only lowercase alphanumeric characters and hyphens",
		}
	}

	return nil
}

// validateAgentName validates agent name format
// MUST match Python agent name validation exactly
func (v *AgentRegistrationValidator) validateAgentName(name string) error {
	if name == "" {
		return ValidationError{Field: "name", Message: "name cannot be empty"}
	}

	// Check length (matches Python max length)
	if len(name) > 63 {
		return ValidationError{Field: "name", Message: "name cannot exceed 63 characters"}
	}

	// Normalize and validate
	normalized := normalizeName(name)
	if !v.agentNamePattern.MatchString(normalized) {
		return ValidationError{
			Field:   "name",
			Message: "name must contain only lowercase alphanumeric characters and hyphens",
		}
	}

	return nil
}

// validateNamespace validates namespace format
// MUST match Python namespace validation exactly
func (v *AgentRegistrationValidator) validateNamespace(namespace string) error {
	if namespace == "" {
		return ValidationError{Field: "namespace", Message: "namespace cannot be empty"}
	}

	// Check length (matches Python max length)
	if len(namespace) > 63 {
		return ValidationError{Field: "namespace", Message: "namespace cannot exceed 63 characters"}
	}

	// Validate namespace format (Kubernetes DNS label format)
	if !v.agentNamePattern.MatchString(namespace) {
		return ValidationError{
			Field:   "namespace",
			Message: "namespace must contain only lowercase alphanumeric characters and hyphens",
		}
	}

	return nil
}

// validateEndpoint validates endpoint URL format
// MUST match Python endpoint validation exactly
func (v *AgentRegistrationValidator) validateEndpoint(endpoint string) error {
	if endpoint == "" {
		return nil // Empty endpoint is allowed, will be auto-generated
	}

	// Check for stdio:// protocol (matches Python stdio agent detection)
	if strings.HasPrefix(endpoint, "stdio://") {
		// stdio endpoints are always valid
		return nil
	}

	// Validate HTTP/HTTPS URLs
	if !strings.HasPrefix(endpoint, "http://") && !strings.HasPrefix(endpoint, "https://") {
		return ValidationError{
			Field:   "endpoint",
			Message: "endpoint must be a valid HTTP/HTTPS URL or stdio:// protocol",
		}
	}

	// Parse and validate URL structure
	parsedURL, err := url.Parse(endpoint)
	if err != nil {
		return ValidationError{
			Field:   "endpoint",
			Message: fmt.Sprintf("endpoint must be a valid URL: %s", err.Error()),
		}
	}

	// Validate scheme
	if parsedURL.Scheme != "http" && parsedURL.Scheme != "https" {
		return ValidationError{
			Field:   "endpoint",
			Message: "endpoint must use http or https scheme",
		}
	}

	// Validate host is present
	if parsedURL.Host == "" {
		return ValidationError{
			Field:   "endpoint",
			Message: "endpoint must include a valid host",
		}
	}

	return nil
}

// validateCapabilities validates capability definitions
// Supports both simple string arrays and complex capability objects for backward compatibility
func (v *AgentRegistrationValidator) validateCapabilities(capabilities interface{}) error {
	capList, ok := capabilities.([]interface{})
	if !ok {
		// Try to handle []string type as well
		if strSlice, ok := capabilities.([]string); ok {
			// Convert []string to []interface{}
			capList = make([]interface{}, len(strSlice))
			for i, s := range strSlice {
				capList[i] = s
			}
		} else {
			return ValidationError{Field: "capabilities", Message: fmt.Sprintf("capabilities must be an array, got %T", capabilities)}
		}
	}

	for i, capItem := range capList {
		// Support both string and object formats
		switch cap := capItem.(type) {
		case string:
			// Simple string format: ["greeting", "farewell"]
			if err := v.validateCapabilityName(cap); err != nil {
				return ValidationError{
					Field:   fmt.Sprintf("capabilities[%d]", i),
					Message: err.Error(),
				}
			}
		case map[string]interface{}:
			// Complex object format: [{"name": "greeting", "version": "1.0.0"}]
			// Validate capability name (required)
			name, exists := cap["name"]
			if !exists {
				return ValidationError{
					Field:   fmt.Sprintf("capabilities[%d].name", i),
					Message: "capability name is required",
				}
			}

			nameStr, ok := name.(string)
			if !ok {
				return ValidationError{
					Field:   fmt.Sprintf("capabilities[%d].name", i),
					Message: "capability name must be a string",
				}
			}

			if err := v.validateCapabilityName(nameStr); err != nil {
				return ValidationError{
					Field:   fmt.Sprintf("capabilities[%d].name", i),
					Message: err.Error(),
				}
			}

			// Validate version (if provided)
			if version, exists := cap["version"]; exists {
				versionStr, ok := version.(string)
				if !ok {
					return ValidationError{
						Field:   fmt.Sprintf("capabilities[%d].version", i),
						Message: "capability version must be a string",
					}
				}

				if err := v.validateSemanticVersion(versionStr); err != nil {
					return ValidationError{
						Field:   fmt.Sprintf("capabilities[%d].version", i),
						Message: err.Error(),
					}
				}
			}

			// Validate description (if provided)
			if description, exists := cap["description"]; exists {
				if _, ok := description.(string); !ok {
					return ValidationError{
						Field:   fmt.Sprintf("capabilities[%d].description", i),
						Message: "capability description must be a string",
					}
				}
			}
		default:
			return ValidationError{
				Field:   fmt.Sprintf("capabilities[%d]", i),
				Message: "capability must be a string or an object with 'name' property",
			}
		}
	}

	return nil
}

// validateCapabilityName validates capability name format
// MUST match Python capability name validation exactly
func (v *AgentRegistrationValidator) validateCapabilityName(name string) error {
	if name == "" {
		return fmt.Errorf("capability name cannot be empty")
	}

	if len(name) > 100 {
		return fmt.Errorf("capability name cannot exceed 100 characters")
	}

	if !v.capabilityNamePattern.MatchString(name) {
		return fmt.Errorf("capability name must start with a letter and contain only letters, numbers, underscores, and hyphens")
	}

	return nil
}

// validateSemanticVersion validates semantic version format
// MUST match Python semantic version validation exactly
func (v *AgentRegistrationValidator) validateSemanticVersion(version string) error {
	if version == "" {
		return fmt.Errorf("version cannot be empty")
	}

	if !v.semanticVersionPattern.MatchString(version) {
		return fmt.Errorf("version must follow semantic versioning format (e.g., '1.0.0' or '1.0.0-alpha')")
	}

	return nil
}

// validateHealthConfig validates health monitoring configuration
// MUST match Python health config validation exactly
func (v *AgentRegistrationValidator) validateHealthConfig(metadata map[string]interface{}) error {
	// Validate health_interval (if provided)
	if healthInterval, exists := metadata["health_interval"]; exists {
		switch hi := healthInterval.(type) {
		case float64:
			if hi < 1 || hi > 3600 {
				return ValidationError{
					Field:   "health_interval",
					Message: "health_interval must be between 1 and 3600 seconds",
				}
			}
		case int:
			if hi < 1 || hi > 3600 {
				return ValidationError{
					Field:   "health_interval",
					Message: "health_interval must be between 1 and 3600 seconds",
				}
			}
		default:
			return ValidationError{
				Field:   "health_interval",
				Message: "health_interval must be a number",
			}
		}
	}

	// Validate timeout_threshold (if provided)
	if timeoutThreshold, exists := metadata["timeout_threshold"]; exists {
		switch tt := timeoutThreshold.(type) {
		case float64:
			if tt < 1 || tt > 7200 {
				return ValidationError{
					Field:   "timeout_threshold",
					Message: "timeout_threshold must be between 1 and 7200 seconds",
				}
			}
		case int:
			if tt < 1 || tt > 7200 {
				return ValidationError{
					Field:   "timeout_threshold",
					Message: "timeout_threshold must be between 1 and 7200 seconds",
				}
			}
		default:
			return ValidationError{
				Field:   "timeout_threshold",
				Message: "timeout_threshold must be a number",
			}
		}
	}

	// Validate eviction_threshold (if provided)
	if evictionThreshold, exists := metadata["eviction_threshold"]; exists {
		switch et := evictionThreshold.(type) {
		case float64:
			if et < 1 || et > 14400 {
				return ValidationError{
					Field:   "eviction_threshold",
					Message: "eviction_threshold must be between 1 and 14400 seconds",
				}
			}
		case int:
			if et < 1 || et > 14400 {
				return ValidationError{
					Field:   "eviction_threshold",
					Message: "eviction_threshold must be between 1 and 14400 seconds",
				}
			}
		default:
			return ValidationError{
				Field:   "eviction_threshold",
				Message: "eviction_threshold must be a number",
			}
		}
	}

	return nil
}
