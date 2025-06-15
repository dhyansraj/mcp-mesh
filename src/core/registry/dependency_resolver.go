package registry

import (
	"encoding/json"
	"fmt"
	"log"
	"strings"

	"github.com/Masterminds/semver/v3"
	"mcp-mesh/src/core/database"
)

// ResolveAllDependencies resolves dependencies for all capabilities of an agent using new schema
// This function takes a tools metadata map (from registration) and resolves dependencies
func (s *Service) ResolveAllDependencies(agentID string) (map[string][]*DependencyResolution, error) {
	resolved := make(map[string][]*DependencyResolution)

	// Get agent capabilities to know what functions exist
	capabilities, err := s.GetAgentCapabilities(agentID)
	if err != nil {
		return resolved, nil // Return empty if agent not found
	}

	// Since dependencies aren't stored in DB, we need to get them from the current registration context
	// For now, return empty arrays for each function (dependencies will be provided during registration)
	for _, cap := range capabilities {
		functionName := cap["function_name"].(string)
		resolved[functionName] = []*DependencyResolution{} // Empty array for now
	}

	return resolved, nil
}

// ResolveAllDependenciesFromMetadata resolves dependencies using the tools metadata from registration
// Implements strict dependency resolution: ALL dependencies must resolve or function fails
func (s *Service) ResolveAllDependenciesFromMetadata(metadata map[string]interface{}) (map[string][]*DependencyResolution, error) {
	resolved := make(map[string][]*DependencyResolution)

	// Extract tools from metadata
	toolsData, exists := metadata["tools"]
	if !exists {
		return resolved, nil
	}

	toolsList, ok := toolsData.([]interface{})
	if !ok {
		return resolved, nil
	}

	// Process each tool and resolve its dependencies
	for _, toolData := range toolsList {
		toolMap, ok := toolData.(map[string]interface{})
		if !ok {
			continue
		}

		functionName := getStringFromMap(toolMap, "function_name", "")
		if functionName == "" {
			continue
		}


		// Get dependencies for this function
		var resolvedDeps []*DependencyResolution
		var allDependenciesResolved = true

		if deps, exists := toolMap["dependencies"]; exists {

			// Handle both []interface{} and []map[string]interface{} types
			var depsList []map[string]interface{}

			if depsSlice, ok := deps.([]interface{}); ok {
				depsList = make([]map[string]interface{}, len(depsSlice))
				for i, item := range depsSlice {
					if depMap, ok := item.(map[string]interface{}); ok {
						depsList[i] = depMap
					}
				}
			} else if depsMapSlice, ok := deps.([]map[string]interface{}); ok {
				depsList = depsMapSlice
			} else {
				depsList = nil
			}

			if depsList != nil {
				for _, depMap := range depsList {
					// Extract dependency info
					requiredCapability, _ := depMap["capability"].(string)
					if requiredCapability == "" {
						continue
					}

					// Create dependency object
					dep := database.Dependency{
						Capability: requiredCapability,
					}

					if version, exists := depMap["version"]; exists {
						if vStr, ok := version.(string); ok {
							dep.Version = vStr
						}
					}

					if tags, exists := depMap["tags"]; exists {
						if tagsList, ok := tags.([]interface{}); ok {
							dep.Tags = make([]string, len(tagsList))
							for i, tag := range tagsList {
								if tagStr, ok := tag.(string); ok {
									dep.Tags[i] = tagStr
								}
							}
						}
					}

					// Find provider with TTL and strict matching
					provider := s.findHealthyProviderWithTTL(dep)
					if provider != nil {
						resolvedDeps = append(resolvedDeps, provider)
					} else {
						// Dependency cannot be resolved - mark as failed
						allDependenciesResolved = false
						log.Printf("Failed to resolve dependency %s for function %s", dep.Capability, functionName)
						break // No point continuing if any dependency fails
					}
				}
			}
		}

		// Only include function if ALL dependencies resolved (or no dependencies)
		if allDependenciesResolved {
			resolved[functionName] = resolvedDeps
		} else {
			// Function excluded from resolved map due to unresolvable dependencies
			log.Printf("Function %s excluded due to unresolvable dependencies", functionName)
		}
	}

	return resolved, nil
}

// findHealthyProviderWithTTL finds a healthy provider using TTL check and strict matching
func (s *Service) findHealthyProviderWithTTL(dep database.Dependency) *DependencyResolution {
	// Build query with TTL check using config timeout: updated_at + DEFAULT_TIMEOUT > NOW()
	timeoutSeconds := s.config.DefaultTimeoutThreshold
	query := `
		SELECT c.agent_id, c.function_name, c.capability, c.version, c.tags,
		       a.http_host, a.http_port, a.updated_at
		FROM capabilities c
		JOIN agents a ON c.agent_id = a.agent_id
		WHERE c.capability = ?
		AND datetime(a.updated_at, '+' || ? || ' seconds') > datetime('now')
		ORDER BY a.updated_at DESC`


	rows, err := s.db.Query(query, dep.Capability, timeoutSeconds)
	if err != nil {
		log.Printf("Error finding healthy providers for %s: %v", dep.Capability, err)
		return nil
	}
	defer rows.Close()

	var candidates []struct {
		AgentID      string
		FunctionName string
		Capability   string
		Version      string
		Tags         string
		HttpHost     string
		HttpPort     *int
		UpdatedAt    string
	}

	for rows.Next() {
		var c struct {
			AgentID      string
			FunctionName string
			Capability   string
			Version      string
			Tags         string
			HttpHost     string
			HttpPort     *int
			UpdatedAt    string
		}
		err := rows.Scan(&c.AgentID, &c.FunctionName, &c.Capability, &c.Version, &c.Tags,
						&c.HttpHost, &c.HttpPort, &c.UpdatedAt)
		if err != nil {
			log.Printf("Error scanning provider: %v", err)
			continue
		}
		candidates = append(candidates, c)
	}


	// Filter by version constraint if specified
	if dep.Version != "" && len(candidates) > 0 {
		filtered := make([]struct {
			AgentID      string
			FunctionName string
			Capability   string
			Version      string
			Tags         string
			HttpHost     string
			HttpPort     *int
			UpdatedAt    string
		}, 0)

		constraint, err := parseVersionConstraintNew(dep.Version)
		if err == nil {
			for _, c := range candidates {
				if matchesVersionNew(c.Version, constraint) {
					filtered = append(filtered, c)
				}
			}
			candidates = filtered
		} else {
			log.Printf("Invalid version constraint %s: %v", dep.Version, err)
		}
	}

	// Filter by tags if specified (ALL tags must match)
	if len(dep.Tags) > 0 && len(candidates) > 0 {
		filtered := make([]struct {
			AgentID      string
			FunctionName string
			Capability   string
			Version      string
			Tags         string
			HttpHost     string
			HttpPort     *int
			UpdatedAt    string
		}, 0)

		for _, c := range candidates {
			var tags []interface{}
			if err := json.Unmarshal([]byte(c.Tags), &tags); err == nil {
				tagStrs := make([]string, len(tags))
				for i, tag := range tags {
					tagStrs[i] = fmt.Sprintf("%v", tag)
				}
				if hasAllTagsNew(tagStrs, dep.Tags) {
					filtered = append(filtered, c)
				}
			}
		}
		candidates = filtered
	}

	// Return first match (deterministic selection)
	if len(candidates) > 0 {
		c := candidates[0]

		// Build endpoint
		endpoint := "stdio://" + c.AgentID // Default
		if c.HttpHost != "" && c.HttpPort != nil && *c.HttpPort > 0 {
			endpoint = fmt.Sprintf("http://%s:%d", c.HttpHost, *c.HttpPort)
		}


		return &DependencyResolution{
			AgentID:      c.AgentID,
			FunctionName: c.FunctionName,
			Endpoint:     endpoint,
			Capability:   c.Capability,
			Status:       "available",
		}
	}

	log.Printf("No healthy providers found for %s (version: %s, tags: %v)", dep.Capability, dep.Version, dep.Tags)
	return nil
}

// parseVersionConstraintNew parses version constraint string
func parseVersionConstraintNew(constraint string) (*semver.Constraints, error) {
	// Handle special cases
	constraint = strings.TrimSpace(constraint)

	// Convert Python-style constraints to semver
	if strings.HasPrefix(constraint, "~") {
		// ~1.2 -> >=1.2.0, <1.3.0
		base := strings.TrimPrefix(constraint, "~")
		parts := strings.Split(base, ".")
		if len(parts) == 2 {
			minor, _ := fmt.Sscanf(parts[1], "%d", new(int))
			constraint = fmt.Sprintf(">=%s.0, <%s.%d.0", base, parts[0], minor+1)
		}
	}

	return semver.NewConstraint(constraint)
}

// matchesVersionNew checks if version matches constraint
func matchesVersionNew(version string, constraint *semver.Constraints) bool {
	v, err := semver.NewVersion(version)
	if err != nil {
		return false
	}
	return constraint.Check(v)
}

// hasAllTagsNew checks if all required tags are present
func hasAllTagsNew(available, required []string) bool {
	tagMap := make(map[string]bool)
	for _, tag := range available {
		tagMap[tag] = true
	}

	for _, tag := range required {
		if !tagMap[tag] {
			return false
		}
	}

	return true
}
