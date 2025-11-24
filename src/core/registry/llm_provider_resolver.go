package registry

import (
	"context"
	"fmt"
	"sort"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
	"mcp-mesh/src/core/registry/generated"
)

// ResolveProvider finds a matching LLM provider agent based on provider specification
// Returns the best match based on tag scoring (supports +/- operators for preference/exclusion)
// Returns nil if no match is found
func ResolveProvider(ctx context.Context, client *ent.Client, providerSpec map[string]interface{}) (*generated.ResolvedLLMProvider, error) {
	// Extract capability (required)
	capabilityName, ok := providerSpec["capability"].(string)
	if !ok || capabilityName == "" {
		return nil, fmt.Errorf("provider spec must include 'capability' field")
	}

	// Query for matching capabilities
	query := client.Capability.Query().
		Where(capability.CapabilityEQ(capabilityName)).
		Where(capability.InputSchemaNotNil()). // Providers must have input schema
		Where(capability.HasAgentWith(agent.StatusEQ(agent.StatusHealthy))). // Only healthy agents
		WithAgent()

	caps, err := query.All(ctx)
	if err != nil {
		return nil, err
	}

	// Apply version constraints first if specified (uses matchesVersion from ent_service.go)
	if version, ok := providerSpec["version"].(string); ok && version != "" {
		var filtered []*ent.Capability
		for _, cap := range caps {
			if matchesVersion(cap.Version, version) {
				filtered = append(filtered, cap)
			}
		}
		caps = filtered
	}

	// Apply enhanced tag filtering with scoring if specified
	if tags, ok := providerSpec["tags"]; ok {
		caps = filterProviderByEnhancedTags(caps, tags)
	}

	// Return best match (highest scoring match wins)
	if len(caps) == 0 {
		return nil, nil // No match found
	}

	// Convert best match to ResolvedLLMProvider
	provider := convertToResolvedProvider(caps[0])
	if provider == nil {
		return nil, fmt.Errorf("failed to convert capability to provider (agent edge missing)")
	}
	return provider, nil
}

// filterProviderByEnhancedTags filters and scores capabilities using enhanced tag matching
// Supports +/- operators: + for preference (bonus points), - for exclusion (hard filter)
// Returns capabilities sorted by score (highest first)
// Uses matchesEnhancedTags() from ent_service.go for consistency with mesh.tool dependency resolution
func filterProviderByEnhancedTags(caps []*ent.Capability, requestedTags interface{}) []*ent.Capability {
	// Convert requested tags to string slice
	var reqTags []string
	switch t := requestedTags.(type) {
	case []string:
		reqTags = t
	case []interface{}:
		for _, tag := range t {
			if s, ok := tag.(string); ok {
				reqTags = append(reqTags, s)
			}
		}
	default:
		return caps // If tags format is unexpected, don't filter
	}

	if len(reqTags) == 0 {
		return caps
	}

	// Score each capability using enhanced tag matching (same logic as mesh.tool)
	type scoredCap struct {
		cap   *ent.Capability
		score int
	}
	var scored []scoredCap

	for _, cap := range caps {
		// Use the same matchesEnhancedTags() function from ent_service.go
		matches, score := matchesEnhancedTags(cap.Tags, reqTags)
		if matches {
			scored = append(scored, scoredCap{cap: cap, score: score})
		}
	}

	// Sort by score descending (highest score first)
	sort.Slice(scored, func(i, j int) bool {
		return scored[i].score > scored[j].score
	})

	// Extract capabilities in score order
	var filtered []*ent.Capability
	for _, s := range scored {
		filtered = append(filtered, s.cap)
	}
	return filtered
}

// convertToResolvedProvider converts an ent.Capability to generated.ResolvedLLMProvider
func convertToResolvedProvider(cap *ent.Capability) *generated.ResolvedLLMProvider {
	if cap.Edges.Agent == nil {
		return nil
	}

	endpoint := buildProviderEndpoint(cap)
	status := generated.Available

	// Extract vendor from kwargs (stored by @mesh.llm_provider decorator)
	vendor := "unknown"
	if cap.Kwargs != nil {
		if vendorVal, ok := cap.Kwargs["vendor"]; ok {
			if vendorStr, ok := vendorVal.(string); ok {
				vendor = vendorStr
			}
		}
	}

	// Create provider
	provider := &generated.ResolvedLLMProvider{
		AgentId:    cap.Edges.Agent.ID,
		Name:       cap.FunctionName,
		Endpoint:   endpoint,
		Capability: cap.Capability,
		Status:     status,
		Vendor:     vendor, // Include vendor for provider handler selection
	}

	// Add optional fields
	if len(cap.Tags) > 0 {
		tags := cap.Tags
		provider.Tags = &tags
	}

	if cap.Version != "" {
		version := cap.Version
		provider.Version = &version
	}

	// Add kwargs if present
	if cap.Kwargs != nil && len(cap.Kwargs) > 0 {
		provider.Kwargs = &cap.Kwargs
	}

	return provider
}

// buildProviderEndpoint constructs the endpoint URL from agent information
func buildProviderEndpoint(cap *ent.Capability) string {
	if cap.Edges.Agent == nil {
		return ""
	}

	agent := cap.Edges.Agent

	// Handle stdio:// endpoints
	if agent.HTTPPort == 0 {
		return fmt.Sprintf("stdio://%s", agent.ID)
	}

	// Handle HTTP endpoints
	host := agent.HTTPHost
	if host == "" || host == "0.0.0.0" {
		host = "localhost"
	}

	// Clean up host (remove http:// if present)
	if len(host) > 7 && host[:7] == "http://" {
		host = host[7:]
	}
	if len(host) > 8 && host[:8] == "https://" {
		host = host[8:]
	}

	return fmt.Sprintf("http://%s:%d", host, agent.HTTPPort)
}

// ResolveLLMProvidersFromMetadata resolves LLM providers from heartbeat metadata
// This is called during heartbeat processing to resolve llm_provider specs to actual providers
// Returns a map of function_name -> ResolvedLLMProvider
func (s *EntService) ResolveLLMProvidersFromMetadata(ctx context.Context, agentID string, metadata map[string]interface{}) (map[string]*generated.ResolvedLLMProvider, error) {
	llmProviders := make(map[string]*generated.ResolvedLLMProvider)

	// Extract tools from metadata
	toolsData, exists := metadata["tools"]
	if !exists {
		s.logger.Debug("No tools in metadata for agent %s", agentID)
		return llmProviders, nil
	}
	s.logger.Debug("ResolveLLMProviders: agent=%s has tools in metadata", agentID)

	toolsList, ok := toolsData.([]interface{})
	if !ok {
		return llmProviders, nil
	}

	// Process each tool and check for llm_provider
	for _, toolData := range toolsList {
		toolMap, ok := toolData.(map[string]interface{})
		if !ok {
			continue
		}

		functionName := getStringFromMap(toolMap, "function_name", "")
		if functionName == "" {
			continue
		}
		s.logger.Debug("ResolveLLMProviders: checking function '%s' for llm_provider", functionName)

		// Check if tool has llm_provider
		llmProviderData, exists := toolMap["llm_provider"]
		if !exists {
			s.logger.Debug("ResolveLLMProviders: function '%s' has NO llm_provider", functionName)
			continue
		}
		s.logger.Debug("ResolveLLMProviders: function '%s' HAS llm_provider", functionName)

		// Convert llmProviderData to map[string]interface{}
		// The data may come in as generated.LLMProvider struct or as map already
		var llmProviderMap map[string]interface{}

		switch v := llmProviderData.(type) {
		case generated.LLMProvider:
			// Convert struct to map
			llmProviderMap = make(map[string]interface{})
			llmProviderMap["capability"] = v.Capability
			if v.Namespace != nil {
				llmProviderMap["namespace"] = *v.Namespace
			}
			if v.Tags != nil {
				llmProviderMap["tags"] = *v.Tags
			}
			if v.Version != nil {
				llmProviderMap["version"] = *v.Version
			}
			s.logger.Debug("ResolveLLMProviders: converted generated.LLMProvider to map: %+v", llmProviderMap)
		case map[string]interface{}:
			// Already a map, use directly
			llmProviderMap = v
			s.logger.Debug("ResolveLLMProviders: llmProviderData already a map: %+v", llmProviderMap)
		default:
			s.logger.Warning("ResolveLLMProviders: unexpected type %T for llmProviderData", llmProviderData)
			continue
		}

		// Call ResolveProvider to find matching provider
		provider, err := ResolveProvider(ctx, s.entDB.Client, llmProviderMap)
		if err != nil {
			s.logger.Warning("Failed to resolve provider for %s: %v", functionName, err)
			continue
		}

		if provider == nil {
			s.logger.Warning("No matching provider found for %s with spec: %+v", functionName, llmProviderMap)
			continue
		}

		s.logger.Info("Resolved provider for %s: %s (agent: %s, endpoint: %s)",
			functionName, provider.Name, provider.AgentId, provider.Endpoint)

		// Add to result map
		llmProviders[functionName] = provider
	}

	return llmProviders, nil
}
