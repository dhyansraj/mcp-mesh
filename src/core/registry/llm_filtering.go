package registry

import (
	"context"
	"fmt"
	"strings"

	"github.com/Masterminds/semver/v3"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
)

// LLMToolInfo represents a filtered tool for LLM consumption
// JSON field names match the OpenAPI spec exactly (camelCase)
type LLMToolInfo struct {
	FunctionName string                 `json:"name"` // OpenAPI spec uses "name"
	Capability   string                 `json:"capability"`
	Description  string                 `json:"description"`
	InputSchema  map[string]interface{} `json:"inputSchema,omitempty"` // OpenAPI spec uses "inputSchema" (camelCase)
	Tags         []string               `json:"tags,omitempty"`
	Version      string                 `json:"version"`
	Endpoint     string                 `json:"endpoint"`
}

// FilterToolsForLLM filters available tools based on LLM filter criteria
// excludeAgentID specifies which agent's tools to exclude from results (typically the requesting agent itself)
func FilterToolsForLLM(ctx context.Context, client *ent.Client, filter []interface{}, filterMode string, excludeAgentID string) ([]LLMToolInfo, error) {
	// Handle wildcard mode - return all tools (except the requesting agent's own tools)
	if filterMode == "*" {
		return getAllTools(ctx, client, excludeAgentID)
	}

	// Collect matching capabilities
	var matchedCaps []*ent.Capability

	for _, f := range filter {
		caps, err := matchFilter(ctx, client, f)
		if err != nil {
			return nil, err
		}
		matchedCaps = append(matchedCaps, caps...)
	}

	// Remove duplicates and apply filter mode
	uniqueCaps := deduplicateCapabilities(matchedCaps)

	if filterMode == "best_match" {
		uniqueCaps = applyBestMatch(uniqueCaps)
	}

	// Convert to LLMToolInfo
	return convertToLLMToolInfo(uniqueCaps), nil
}

// matchFilter matches a single filter (string or map)
func matchFilter(ctx context.Context, client *ent.Client, filter interface{}) ([]*ent.Capability, error) {
	switch f := filter.(type) {
	case string:
		// Simple capability name filter
		if f == "*" {
			return client.Capability.Query().
				Where(capability.InputSchemaNotNil()).
				Where(capability.HasAgentWith(agent.StatusEQ(agent.StatusHealthy))).
				WithAgent().
				All(ctx)
		}

		return client.Capability.Query().
			Where(capability.CapabilityEQ(f)).
			Where(capability.InputSchemaNotNil()).
			Where(capability.HasAgentWith(agent.StatusEQ(agent.StatusHealthy))).
			WithAgent().
			All(ctx)

	case map[string]interface{}:
		// Rich filter with capability, tags, version (with health check)
		query := client.Capability.Query().
			Where(capability.InputSchemaNotNil()).
			Where(capability.HasAgentWith(agent.StatusEQ(agent.StatusHealthy))).
			WithAgent()

		// Capability name
		if cap, ok := f["capability"].(string); ok {
			query = query.Where(capability.CapabilityEQ(cap))
		}

		caps, err := query.All(ctx)
		if err != nil {
			return nil, err
		}

		// Apply tag filtering (subset matching)
		if tags, ok := f["tags"]; ok {
			caps = filterByTags(caps, tags)
		}

		// Apply version constraints
		if version, ok := f["version"].(string); ok {
			caps = filterByVersion(caps, version)
		}

		return caps, nil

	default:
		return nil, fmt.Errorf("unsupported filter type: %T", filter)
	}
}

// filterByTags filters capabilities where requested tags are a subset of capability tags
func filterByTags(caps []*ent.Capability, requestedTags interface{}) []*ent.Capability {
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

	var filtered []*ent.Capability
	for _, cap := range caps {
		if isSubset(reqTags, cap.Tags) {
			filtered = append(filtered, cap)
		}
	}
	return filtered
}

// isSubset checks if all elements in 'subset' are present in 'set'
func isSubset(subset, set []string) bool {
	setMap := make(map[string]bool)
	for _, item := range set {
		setMap[item] = true
	}

	for _, item := range subset {
		if !setMap[item] {
			return false
		}
	}
	return true
}

// filterByVersion filters capabilities by semantic version constraint
func filterByVersion(caps []*ent.Capability, versionConstraint string) []*ent.Capability {
	constraint, err := semver.NewConstraint(versionConstraint)
	if err != nil {
		// If constraint is invalid, return all
		return caps
	}

	var filtered []*ent.Capability
	for _, cap := range caps {
		v, err := semver.NewVersion(cap.Version)
		if err != nil {
			continue // Skip capabilities with invalid versions
		}

		if constraint.Check(v) {
			filtered = append(filtered, cap)
		}
	}
	return filtered
}

// getAllTools returns all capabilities that have input schemas (excluding specified agent)
func getAllTools(ctx context.Context, client *ent.Client, excludeAgentID string) ([]LLMToolInfo, error) {
	caps, err := client.Capability.Query().
		Where(capability.InputSchemaNotNil()).
		Where(capability.HasAgentWith(agent.StatusEQ(agent.StatusHealthy))).
		WithAgent().
		All(ctx)
	if err != nil {
		return nil, err
	}

	// Filter out capabilities from the excluded agent
	if excludeAgentID != "" {
		var filtered []*ent.Capability
		for _, cap := range caps {
			if cap.Edges.Agent == nil || cap.Edges.Agent.ID != excludeAgentID {
				filtered = append(filtered, cap)
			}
		}
		caps = filtered
	}

	// Deduplicate by function name (LLM APIs require unique function names)
	caps = deduplicateCapabilities(caps)

	return convertToLLMToolInfo(caps), nil
}

// deduplicateCapabilities removes duplicate capabilities by function name
// This ensures that if multiple agents provide functions with the same name, only one is returned.
// Follows the same pattern as dependency resolution: return first healthy match.
//
// IMPORTANT: LLM APIs (like Anthropic Claude) require unique function names in the tools array.
// We deduplicate by function_name (not capability+function_name) to ensure compliance.
func deduplicateCapabilities(caps []*ent.Capability) []*ent.Capability {
	// Use function_name as key to detect duplicates
	// This matches the behavior of mesh.tool dependency resolution: first match wins
	seen := make(map[string]bool)
	var unique []*ent.Capability

	for _, cap := range caps {
		// Deduplicate by function name only (LLM APIs require unique function names)
		if !seen[cap.FunctionName] {
			seen[cap.FunctionName] = true
			unique = append(unique, cap)
		}
	}
	return unique
}

// applyBestMatch selects the best capability per capability name
// Preference: latest version, then most tags
func applyBestMatch(caps []*ent.Capability) []*ent.Capability {
	// Group by capability name
	groups := make(map[string][]*ent.Capability)
	for _, cap := range caps {
		groups[cap.Capability] = append(groups[cap.Capability], cap)
	}

	var best []*ent.Capability
	for _, group := range groups {
		if len(group) == 0 {
			continue
		}

		// Find best in group
		bestCap := group[0]
		for _, cap := range group[1:] {
			if isBetter(cap, bestCap) {
				bestCap = cap
			}
		}
		best = append(best, bestCap)
	}
	return best
}

// isBetter determines if cap1 is better than cap2 (higher version or more tags)
func isBetter(cap1, cap2 *ent.Capability) bool {
	v1, err1 := semver.NewVersion(cap1.Version)
	v2, err2 := semver.NewVersion(cap2.Version)

	// Compare versions if both are valid
	if err1 == nil && err2 == nil {
		if v1.GreaterThan(v2) {
			return true
		}
		if v2.GreaterThan(v1) {
			return false
		}
	}

	// If versions are equal or invalid, compare by tag count
	return len(cap1.Tags) > len(cap2.Tags)
}

// convertToLLMToolInfo converts ent Capabilities to LLMToolInfo structs
func convertToLLMToolInfo(caps []*ent.Capability) []LLMToolInfo {
	var tools []LLMToolInfo

	for _, cap := range caps {
		if cap.InputSchema == nil {
			continue // Skip tools without input schema
		}

		// Build endpoint from agent info
		endpoint := buildEndpoint(cap)

		tool := LLMToolInfo{
			FunctionName: cap.FunctionName,
			Capability:   cap.Capability,
			Description:  cap.Description,
			InputSchema:  cap.InputSchema,
			Tags:         cap.Tags,
			Version:      cap.Version,
			Endpoint:     endpoint,
		}
		tools = append(tools, tool)
	}

	return tools
}

// buildEndpoint constructs the endpoint URL from agent information
func buildEndpoint(cap *ent.Capability) string {
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
	host = strings.TrimPrefix(host, "http://")
	host = strings.TrimPrefix(host, "https://")

	return fmt.Sprintf("http://%s:%d", host, agent.HTTPPort)
}
