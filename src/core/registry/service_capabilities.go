package registry

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"time"
)

// ProcessCapabilities handles the new capabilities storage format
func (s *Service) ProcessCapabilities(agentID string, metadata map[string]interface{}, tx *sql.Tx) error {
	// Extract tools from metadata
	toolsData, exists := metadata["tools"]
	if !exists {
		return nil // No tools to process
	}

	toolsList, ok := toolsData.([]interface{})
	if !ok {
		return fmt.Errorf("tools must be an array")
	}

	// Delete existing capabilities for this agent
	deleteSQL := fmt.Sprintf("DELETE FROM capabilities WHERE agent_id = %s", s.db.GetParameterPlaceholder(1))
	_, err := tx.Exec(deleteSQL, agentID)
	if err != nil {
		return fmt.Errorf("failed to delete existing capabilities: %w", err)
	}

	// Insert new capabilities
	now := time.Now().UTC()
	for i, toolData := range toolsList {
		toolMap, ok := toolData.(map[string]interface{})
		if !ok {
			log.Printf("Skipping invalid tool at index %d", i)
			continue
		}

		// Extract capability fields
		functionName := getStringFromMap(toolMap, "function_name", "")
		if functionName == "" {
			log.Printf("Skipping tool with no function_name at index %d", i)
			continue
		}

		capability := getStringFromMap(toolMap, "capability", functionName)
		version := getStringFromMap(toolMap, "version", "1.0.0")
		description := getStringFromMap(toolMap, "description", "")

		// Process tags
		tags := "[]"
		if tagsData, exists := toolMap["tags"]; exists {
			if tagsBytes, err := json.Marshal(tagsData); err == nil {
				tags = string(tagsBytes)
			}
		}

		// Insert capability
		insertSQL := fmt.Sprintf(`
			INSERT INTO capabilities (agent_id, function_name, capability, version, description, tags, created_at, updated_at)
			VALUES (%s)`,
			s.db.BuildParameterList(8))
		_, err := tx.Exec(insertSQL, agentID, functionName, capability, version, description, tags, now, now)

		if err != nil {
			return fmt.Errorf("failed to insert capability %s: %w", functionName, err)
		}
	}

	return nil
}

// GetAgentCapabilities returns all capabilities for an agent
func (s *Service) GetAgentCapabilities(agentID string) ([]map[string]interface{}, error) {
	querySQL := fmt.Sprintf(`
		SELECT function_name, capability, version, description, tags, created_at, updated_at
		FROM capabilities WHERE agent_id = %s ORDER BY function_name`, s.db.GetParameterPlaceholder(1))
	rows, err := s.db.Query(querySQL, agentID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var capabilities []map[string]interface{}
	for rows.Next() {
		var functionName, capability, version, description, tags string
		var createdAt, updatedAt time.Time

		err := rows.Scan(&functionName, &capability, &version, &description, &tags, &createdAt, &updatedAt)
		if err != nil {
			return nil, err
		}

		cap := map[string]interface{}{
			"function_name": functionName,
			"capability":    capability,
			"version":       version,
			"description":   description,
			"created_at":    createdAt.Format(time.RFC3339),
			"updated_at":    updatedAt.Format(time.RFC3339),
		}

		// Parse tags
		var tagsArray []interface{}
		if err := json.Unmarshal([]byte(tags), &tagsArray); err == nil && len(tagsArray) > 0 {
			cap["tags"] = tagsArray
		}

		capabilities = append(capabilities, cap)
	}

	return capabilities, nil
}

// GetAgentWithCapabilities returns agent details with all capabilities
func (s *Service) GetAgentWithCapabilities(agentID string) (map[string]interface{}, error) {
	// Get agent details
	var agent struct {
		AgentID              string
		AgentType            string
		Name                 string
		Version              string
		HttpHost             string
		HttpPort             *int
		Namespace            string
		TotalDependencies    int
		DependenciesResolved int
		CreatedAt            time.Time
		UpdatedAt            time.Time
	}

	querySQL := fmt.Sprintf(`
		SELECT agent_id, agent_type, name, version, http_host, http_port,
		       namespace, total_dependencies, dependencies_resolved,
		       created_at, updated_at
		FROM agents WHERE agent_id = %s`, s.db.GetParameterPlaceholder(1))
	err := s.db.QueryRow(querySQL, agentID).Scan(
		&agent.AgentID, &agent.AgentType, &agent.Name, &agent.Version,
		&agent.HttpHost, &agent.HttpPort, &agent.Namespace,
		&agent.TotalDependencies, &agent.DependenciesResolved,
		&agent.CreatedAt, &agent.UpdatedAt)

	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("agent not found")
		}
		return nil, err
	}

	// Get capabilities
	capabilities, err := s.GetAgentCapabilities(agentID)
	if err != nil {
		return nil, err
	}

	// Build response
	result := map[string]interface{}{
		"agent_id":              agent.AgentID,
		"agent_type":            agent.AgentType,
		"name":                  agent.Name,
		"version":               agent.Version,
		"http_host":             agent.HttpHost,
		"http_port":             agent.HttpPort,
		"namespace":             agent.Namespace,
		"total_dependencies":    agent.TotalDependencies,
		"dependencies_resolved": agent.DependenciesResolved,
		"created_at":            agent.CreatedAt.Format(time.RFC3339),
		"updated_at":            agent.UpdatedAt.Format(time.RFC3339),
		"capabilities":          capabilities,
	}

	// Note: timestamp field removed - registry uses created_at/updated_at only

	return result, nil
}
