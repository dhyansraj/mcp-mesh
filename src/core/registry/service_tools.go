package registry

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/Masterminds/semver/v3"
	"mcp-mesh/src/core/database"
)

// ProcessTools handles the new multi-tool registration format
func (s *Service) ProcessTools(agentID string, metadata map[string]interface{}, tx *sql.Tx) error {
	// Extract tools from metadata
	toolsData, exists := metadata["tools"]
	if !exists {
		return nil // No tools to process
	}

	toolsList, ok := toolsData.([]interface{})
	if !ok {
		return fmt.Errorf("tools must be an array")
	}

	// Delete existing tools for this agent
	deleteSQL := fmt.Sprintf("DELETE FROM tools WHERE agent_id = %s", s.db.GetParameterPlaceholder(1))
	_, err := tx.Exec(deleteSQL, agentID)
	if err != nil {
		return fmt.Errorf("failed to delete existing tools: %w", err)
	}

	// Insert new tools
	now := time.Now().UTC()
	for i, toolData := range toolsList {
		toolMap, ok := toolData.(map[string]interface{})
		if !ok {
			log.Printf("Skipping invalid tool at index %d", i)
			continue
		}

		// Extract tool fields
		name := getStringFromMap(toolMap, "function_name", "")
		if name == "" {
			log.Printf("Skipping tool with no function_name at index %d", i)
			continue
		}

		capability := getStringFromMap(toolMap, "capability", name)
		version := getStringFromMap(toolMap, "version", "1.0.0")

		// Process dependencies
		dependencies := "[]"
		if deps, exists := toolMap["dependencies"]; exists {
			if depsBytes, err := json.Marshal(deps); err == nil {
				dependencies = string(depsBytes)
			}
		}

		// Process config (including tags)
		config := make(map[string]interface{})
		if tags, exists := toolMap["tags"]; exists {
			config["tags"] = tags
		}
		if desc, exists := toolMap["description"]; exists {
			config["description"] = desc
		}
		if endpoint, exists := toolMap["endpoint"]; exists {
			config["endpoint"] = endpoint
		}

		configJSON := "{}"
		if configBytes, err := json.Marshal(config); err == nil {
			configJSON = string(configBytes)
		}

		// Insert tool
		insertSQL := fmt.Sprintf(`
			INSERT INTO tools (agent_id, name, capability, version, dependencies, config, created_at, updated_at)
			VALUES (%s)`,
			s.db.BuildParameterList(8))
		_, err := tx.Exec(insertSQL, agentID, name, capability, version, dependencies, configJSON, now, now)

		if err != nil {
			return fmt.Errorf("failed to insert tool %s: %w", name, err)
		}
	}

	return nil
}

// GetAgentWithTools returns agent details with all tools
func (s *Service) GetAgentWithTools(agentID string) (map[string]interface{}, error) {
	// Get agent details
	var agent struct {
		ID                string
		Name              string
		Namespace         string
		Endpoint          string
		Status            string
		LastHeartbeat     *time.Time
		TimeoutThreshold  int
		EvictionThreshold int
		CreatedAt         time.Time
		UpdatedAt         time.Time
	}

	agentQuerySQL := fmt.Sprintf(`
		SELECT id, name, namespace, endpoint, status, last_heartbeat,
			   timeout_threshold, eviction_threshold, created_at, updated_at
		FROM agents WHERE id = %s`, s.db.GetParameterPlaceholder(1))
	err := s.db.QueryRow(agentQuerySQL, agentID).Scan(
		&agent.ID, &agent.Name, &agent.Namespace, &agent.Endpoint, &agent.Status,
		&agent.LastHeartbeat, &agent.TimeoutThreshold, &agent.EvictionThreshold,
		&agent.CreatedAt, &agent.UpdatedAt)

	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("agent not found")
		}
		return nil, err
	}

	// Get tools
	tools, err := s.GetAgentTools(agentID)
	if err != nil {
		return nil, err
	}

	// Build response
	result := map[string]interface{}{
		"id":                 agent.ID,
		"name":               agent.Name,
		"namespace":          agent.Namespace,
		"endpoint":           agent.Endpoint,
		"status":             agent.Status,
		"timeout_threshold":  agent.TimeoutThreshold,
		"eviction_threshold": agent.EvictionThreshold,
		"created_at":         agent.CreatedAt.Format(time.RFC3339),
		"updated_at":         agent.UpdatedAt.Format(time.RFC3339),
		"tools":              tools,
	}

	if agent.LastHeartbeat != nil {
		result["last_heartbeat"] = agent.LastHeartbeat.Format(time.RFC3339)
	}

	return result, nil
}

// GetAgentTools returns all tools for an agent
func (s *Service) GetAgentTools(agentID string) ([]map[string]interface{}, error) {
	toolsQuerySQL := fmt.Sprintf(`
		SELECT name, capability, version, dependencies, config, created_at, updated_at
		FROM tools WHERE agent_id = %s ORDER BY name`, s.db.GetParameterPlaceholder(1))
	rows, err := s.db.Query(toolsQuerySQL, agentID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var tools []map[string]interface{}
	for rows.Next() {
		var name, capability, version, dependencies, config string
		var createdAt, updatedAt time.Time

		err := rows.Scan(&name, &capability, &version, &dependencies, &config, &createdAt, &updatedAt)
		if err != nil {
			return nil, err
		}

		tool := map[string]interface{}{
			"function_name": name,
			"capability":    capability,
			"version":       version,
			"created_at":    createdAt.Format(time.RFC3339),
			"updated_at":    updatedAt.Format(time.RFC3339),
		}

		// Parse dependencies
		var deps []interface{}
		if err := json.Unmarshal([]byte(dependencies), &deps); err == nil && len(deps) > 0 {
			tool["dependencies"] = deps
		}

		// Parse config for tags and other metadata
		var configMap map[string]interface{}
		if err := json.Unmarshal([]byte(config), &configMap); err == nil {
			if tags, exists := configMap["tags"]; exists {
				tool["tags"] = tags
			}
			if desc, exists := configMap["description"]; exists {
				tool["description"] = desc
			}
		}

		tools = append(tools, tool)
	}

	return tools, nil
}

// resolveAllDependencies resolves dependencies for all tools of an agent
func (s *Service) resolveAllDependencies(agentID string) map[string]interface{} {
	resolved := make(map[string]interface{})

	// Get all tools for this agent
	depsQuerySQL := fmt.Sprintf("SELECT name, dependencies FROM tools WHERE agent_id = %s", s.db.GetParameterPlaceholder(1))
	rows, err := s.db.Query(depsQuerySQL, agentID)
	if err != nil {
		log.Printf("Error fetching tools for dependency resolution: %v", err)
		return resolved
	}
	defer rows.Close()

	for rows.Next() {
		var toolName, dependenciesJSON string
		if err := rows.Scan(&toolName, &dependenciesJSON); err != nil {
			continue
		}

		// Parse dependencies
		var dependencies []database.Dependency
		if err := json.Unmarshal([]byte(dependenciesJSON), &dependencies); err != nil {
			continue
		}

		// Resolve dependencies for this tool
		toolDeps := make(map[string]interface{})
		for _, dep := range dependencies {
			provider := s.findBestProvider(dep)
			if provider != nil {
				toolDeps[dep.Capability] = provider
			}
		}

		resolved[toolName] = toolDeps
	}

	return resolved
}

// findBestProvider finds the best provider for a dependency
func (s *Service) findBestProvider(dep database.Dependency) map[string]interface{} {
	// Build query for healthy providers
	query := fmt.Sprintf(`
		SELECT t.agent_id, t.name, t.version, t.config, a.endpoint
		FROM tools t
		JOIN agents a ON t.agent_id = a.id
		WHERE t.capability = %s AND a.status = 'healthy'`, s.db.GetParameterPlaceholder(1))

	rows, err := s.db.Query(query, dep.Capability)
	if err != nil {
		log.Printf("Error finding providers for %s: %v", dep.Capability, err)
		return nil
	}
	defer rows.Close()

	var candidates []struct {
		AgentID  string
		ToolName string
		Version  string
		Config   string
		Endpoint string
	}

	for rows.Next() {
		var c struct {
			AgentID  string
			ToolName string
			Version  string
			Config   string
			Endpoint string
		}
		if err := rows.Scan(&c.AgentID, &c.ToolName, &c.Version, &c.Config, &c.Endpoint); err != nil {
			continue
		}
		candidates = append(candidates, c)
	}

	// Filter by version constraint
	if dep.Version != "" && len(candidates) > 0 {
		filtered := make([]struct {
			AgentID  string
			ToolName string
			Version  string
			Config   string
			Endpoint string
		}, 0)

		constraint, err := parseVersionConstraint(dep.Version)
		if err == nil {
			for _, c := range candidates {
				if matchesVersion(c.Version, constraint) {
					filtered = append(filtered, c)
				}
			}
			candidates = filtered
		}
	}

	// Filter by tags
	if len(dep.Tags) > 0 && len(candidates) > 0 {
		filtered := make([]struct {
			AgentID  string
			ToolName string
			Version  string
			Config   string
			Endpoint string
		}, 0)

		for _, c := range candidates {
			var config map[string]interface{}
			if err := json.Unmarshal([]byte(c.Config), &config); err == nil {
				if tags, ok := config["tags"].([]interface{}); ok {
					tagStrs := make([]string, len(tags))
					for i, tag := range tags {
						tagStrs[i] = fmt.Sprintf("%v", tag)
					}
					if hasAllTags(tagStrs, dep.Tags) {
						filtered = append(filtered, c)
					}
				}
			}
		}
		candidates = filtered
	}

	// Return first match (TODO: implement selection strategy)
	if len(candidates) > 0 {
		c := candidates[0]
		return map[string]interface{}{
			"agent_id":   c.AgentID,
			"tool_name":  c.ToolName,
			"capability": dep.Capability,
			"version":    c.Version,
			"endpoint":   c.Endpoint,
		}
	}

	return nil
}

// parseVersionConstraint parses version constraint string
func parseVersionConstraint(constraint string) (*semver.Constraints, error) {
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

// matchesVersion checks if version matches constraint
func matchesVersion(version string, constraint *semver.Constraints) bool {
	v, err := semver.NewVersion(version)
	if err != nil {
		return false
	}
	return constraint.Check(v)
}

// hasAllTags checks if all required tags are present
func hasAllTags(available, required []string) bool {
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
