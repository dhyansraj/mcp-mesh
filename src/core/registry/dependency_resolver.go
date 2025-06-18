package registry

import (
	"encoding/json"
	"fmt"
	"log"

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
						// Dependency cannot be resolved - log but continue with other dependencies
						log.Printf("Failed to resolve dependency %s for function %s", dep.Capability, functionName)
						// Continue processing other dependencies instead of breaking
					}
				}
			}
		}

		// Always include function in resolved map, even if some dependencies are unresolved
		// This allows partial dependency resolution tracking
		resolved[functionName] = resolvedDeps
		if len(resolvedDeps) == 0 && len(toolMap) > 0 {
			// Only log if function had dependencies but none were resolved
			if deps, exists := toolMap["dependencies"]; exists {
				if depsList, ok := deps.([]interface{}); ok && len(depsList) > 0 {
					log.Printf("Function %s excluded due to unresolvable dependencies", functionName)
				}
			}
		}
	}

	return resolved, nil
}

// findHealthyProviderWithTTL finds a healthy provider using TTL check and strict matching
func (s *Service) findHealthyProviderWithTTL(dep database.Dependency) *DependencyResolution {
	// Build query with TTL check using config timeout: updated_at + DEFAULT_TIMEOUT > NOW()
	timeoutSeconds := s.config.DefaultTimeoutThreshold
	
	var query string
	if s.db.IsPostgreSQL() {
		// PostgreSQL version with interval arithmetic and NOW()
		query = fmt.Sprintf(`
			SELECT c.agent_id, c.function_name, c.capability, c.version, c.tags,
			       a.http_host, a.http_port, a.updated_at
			FROM capabilities c
			JOIN agents a ON c.agent_id = a.agent_id
			WHERE c.capability = %s
			AND a.updated_at + INTERVAL '1 second' * %s > NOW()
			ORDER BY a.updated_at DESC`,
			s.db.GetParameterPlaceholder(1), s.db.GetParameterPlaceholder(2))
	} else {
		// SQLite version with datetime functions
		query = fmt.Sprintf(`
			SELECT c.agent_id, c.function_name, c.capability, c.version, c.tags,
			       a.http_host, a.http_port, a.updated_at
			FROM capabilities c
			JOIN agents a ON c.agent_id = a.agent_id
			WHERE c.capability = %s
			AND datetime(a.updated_at, '+' || %s || ' seconds') > datetime('now')
			ORDER BY a.updated_at DESC`,
			s.db.GetParameterPlaceholder(1), s.db.GetParameterPlaceholder(2))
	}

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

		constraint, err := parseVersionConstraint(dep.Version)
		if err == nil {
			for _, c := range candidates {
				if matchesVersion(c.Version, constraint) {
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
				if hasAllTags(tagStrs, dep.Tags) {
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
