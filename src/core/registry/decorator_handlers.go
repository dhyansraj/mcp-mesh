package registry

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// Decorator-based request/response types (from our test file)
type DecoratorAgentRequest struct {
	AgentID   string                    `json:"agent_id"`
	Timestamp string                    `json:"timestamp"`
	Metadata  DecoratorAgentMetadata    `json:"metadata"`
}

type DecoratorAgentMetadata struct {
	Name        string          `json:"name"`
	AgentType   string          `json:"agent_type"`
	Namespace   string          `json:"namespace"`
	Endpoint    string          `json:"endpoint"`
	Version     string          `json:"version"`
	Decorators  []DecoratorInfo `json:"decorators"`
}

type DecoratorInfo struct {
	FunctionName string                   `json:"function_name"`
	Capability   string                   `json:"capability"`
	Dependencies []StandardizedDependency `json:"dependencies"`
	Description  string                   `json:"description,omitempty"`
	Version      string                   `json:"version,omitempty"`
	Tags         []string                 `json:"tags,omitempty"`
}

type StandardizedDependency struct {
	Capability string   `json:"capability"`
	Tags       []string `json:"tags,omitempty"`
	Version    string   `json:"version,omitempty"`
	Namespace  string   `json:"namespace,omitempty"`
}

type DecoratorAgentResponse struct {
	AgentID              string              `json:"agent_id"`
	Status               string              `json:"status"`
	Message              string              `json:"message"`
	Timestamp            string              `json:"timestamp"`
	DependenciesResolved []ResolvedDecorator `json:"dependencies_resolved,omitempty"`
}

type ResolvedDecorator struct {
	FunctionName string               `json:"function_name"`
	Capability   string               `json:"capability"`
	Dependencies []ResolvedDependency `json:"dependencies"`
}

type ResolvedDependency struct {
	Capability  string                 `json:"capability"`
	MCPToolInfo map[string]interface{} `json:"mcp_tool_info,omitempty"`
	Status      string                 `json:"status"`
}

// DecoratorRegistrationHandler handles decorator-based agent registration
func (s *Service) DecoratorRegistrationHandler(c *gin.Context) {
	var request DecoratorAgentRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		log.Printf("Invalid decorator registration request: %v", err)
		c.JSON(http.StatusBadRequest, gin.H{
			"error":     "Invalid request format",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	log.Printf("Processing decorator registration for agent: %s", request.AgentID)

	// Process the decorator-based registration
	response, err := s.processDecoratorRegistration(&request)
	if err != nil {
		log.Printf("Failed to process decorator registration: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":     err.Error(),
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	// Return appropriate status code
	statusCode := http.StatusCreated
	if response.Status == "error" {
		statusCode = http.StatusInternalServerError
	}

	c.JSON(statusCode, response)
}

// DecoratorHeartbeatHandler handles decorator-based heartbeat requests
func (s *Service) DecoratorHeartbeatHandler(c *gin.Context) {
	var request DecoratorAgentRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		log.Printf("Invalid decorator heartbeat request: %v", err)
		c.JSON(http.StatusBadRequest, gin.H{
			"error":     "Invalid request format",
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	log.Printf("Processing decorator heartbeat for agent: %s", request.AgentID)

	// Process the decorator-based heartbeat (same logic as registration)
	response, err := s.processDecoratorHeartbeat(&request)
	if err != nil {
		log.Printf("Failed to process decorator heartbeat: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":     err.Error(),
			"timestamp": time.Now().Format(time.RFC3339),
		})
		return
	}

	c.JSON(http.StatusOK, response)
}

// processDecoratorRegistration handles the business logic for decorator-based registration
func (s *Service) processDecoratorRegistration(request *DecoratorAgentRequest) (*DecoratorAgentResponse, error) {
	// Start transaction for atomic operations
	tx, err := s.db.Begin()
	if err != nil {
		return nil, fmt.Errorf("failed to start transaction: %w", err)
	}
	defer tx.Rollback()

	// Insert or update agent
	err = s.upsertDecoratorAgent(tx, request)
	if err != nil {
		return nil, fmt.Errorf("failed to upsert agent: %w", err)
	}

	// Insert or update tools for each decorator
	err = s.upsertDecoratorTools(tx, request)
	if err != nil {
		return nil, fmt.Errorf("failed to upsert tools: %w", err)
	}

	// Resolve dependencies for all decorators
	resolvedDecorators, err := s.resolveDecoratorDependencies(request)
	if err != nil {
		log.Printf("Warning: Failed to resolve dependencies: %v", err)
		// Don't fail registration if dependency resolution fails
	}

	// Commit transaction
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("failed to commit transaction: %w", err)
	}

	return &DecoratorAgentResponse{
		AgentID:              request.AgentID,
		Status:               "success",
		Message:              "Agent registered successfully",
		Timestamp:            time.Now().Format(time.RFC3339),
		DependenciesResolved: resolvedDecorators,
	}, nil
}

// processDecoratorHeartbeat handles the business logic for decorator-based heartbeat
func (s *Service) processDecoratorHeartbeat(request *DecoratorAgentRequest) (*DecoratorAgentResponse, error) {
	// Update last heartbeat
	_, err := s.db.Exec(`
		UPDATE agents 
		SET last_heartbeat = ?, updated_at = ?
		WHERE id = ?
	`, time.Now(), time.Now(), request.AgentID)
	
	if err != nil {
		return nil, fmt.Errorf("failed to update heartbeat: %w", err)
	}

	// Resolve dependencies (same as registration)
	resolvedDecorators, err := s.resolveDecoratorDependencies(request)
	if err != nil {
		log.Printf("Warning: Failed to resolve dependencies: %v", err)
		// Don't fail heartbeat if dependency resolution fails
	}

	return &DecoratorAgentResponse{
		AgentID:              request.AgentID,
		Status:               "success",
		Message:              "Heartbeat received",
		Timestamp:            time.Now().Format(time.RFC3339),
		DependenciesResolved: resolvedDecorators,
	}, nil
}

// upsertDecoratorAgent inserts or updates agent record
func (s *Service) upsertDecoratorAgent(tx *sql.Tx, request *DecoratorAgentRequest) error {
	// Prepare dependencies JSON
	allDependencies := []StandardizedDependency{}
	for _, decorator := range request.Metadata.Decorators {
		allDependencies = append(allDependencies, decorator.Dependencies...)
	}
	dependenciesJSON, _ := json.Marshal(allDependencies)

	// Prepare decorators JSON  
	decoratorsJSON, _ := json.Marshal(request.Metadata.Decorators)

	// Use INSERT OR REPLACE for SQLite / UPSERT pattern
	_, err := tx.Exec(`
		INSERT OR REPLACE INTO agents (
			id, name, namespace, endpoint, status, 
			created_at, updated_at, resource_version, 
			dependencies, config, agent_type, last_heartbeat
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`,
		request.AgentID,
		request.Metadata.Name,
		request.Metadata.Namespace,
		request.Metadata.Endpoint,
		"healthy",
		time.Now(),
		time.Now(),
		"1", // resource version
		string(dependenciesJSON),
		string(decoratorsJSON), // Store decorators in config field
		request.Metadata.AgentType,
		time.Now(),
	)

	return err
}

// upsertDecoratorTools inserts or updates tool records for each decorator
func (s *Service) upsertDecoratorTools(tx *sql.Tx, request *DecoratorAgentRequest) error {
	// Delete existing tools for this agent
	_, err := tx.Exec("DELETE FROM tools WHERE agent_id = ?", request.AgentID)
	if err != nil {
		return fmt.Errorf("failed to delete existing tools: %w", err)
	}

	// Insert new tools for each decorator
	for _, decorator := range request.Metadata.Decorators {
		dependenciesJSON, _ := json.Marshal(decorator.Dependencies)
		configJSON, _ := json.Marshal(map[string]interface{}{
			"function_name": decorator.FunctionName,
			"description":   decorator.Description,
			"tags":          decorator.Tags,
		})

		_, err := tx.Exec(`
			INSERT INTO tools (
				agent_id, name, capability, version, 
				dependencies, config, created_at, updated_at
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		`,
			request.AgentID,
			decorator.FunctionName,
			decorator.Capability,
			decorator.Version,
			string(dependenciesJSON),
			string(configJSON),
			time.Now(),
			time.Now(),
		)

		if err != nil {
			return fmt.Errorf("failed to insert tool %s: %w", decorator.FunctionName, err)
		}
	}

	return nil
}

// resolveDecoratorDependencies resolves dependencies for all decorators
func (s *Service) resolveDecoratorDependencies(request *DecoratorAgentRequest) ([]ResolvedDecorator, error) {
	var resolvedDecorators []ResolvedDecorator

	for _, decorator := range request.Metadata.Decorators {
		resolvedDeps, err := s.resolveDependenciesForDecorator(decorator)
		if err != nil {
			log.Printf("Warning: Failed to resolve dependencies for %s: %v", decorator.FunctionName, err)
			// Continue with empty resolution
			resolvedDeps = []ResolvedDependency{}
		}

		resolvedDecorators = append(resolvedDecorators, ResolvedDecorator{
			FunctionName: decorator.FunctionName,
			Capability:   decorator.Capability,
			Dependencies: resolvedDeps,
		})
	}

	return resolvedDecorators, nil
}

// resolveDependenciesForDecorator resolves dependencies for a single decorator
func (s *Service) resolveDependenciesForDecorator(decorator DecoratorInfo) ([]ResolvedDependency, error) {
	var resolved []ResolvedDependency

	for _, dep := range decorator.Dependencies {
		resolvedDep, err := s.resolveSingleDependency(dep)
		if err != nil {
			log.Printf("Warning: Failed to resolve dependency %s: %v", dep.Capability, err)
			// Add failed resolution
			resolved = append(resolved, ResolvedDependency{
				Capability: dep.Capability,
				Status:     "failed",
			})
			continue
		}

		resolved = append(resolved, *resolvedDep)
	}

	return resolved, nil
}

// resolveSingleDependency resolves a single dependency using complex tag/version matching
func (s *Service) resolveSingleDependency(dep StandardizedDependency) (*ResolvedDependency, error) {
	// Build query for capability matching
	baseQuery := `
		SELECT t.agent_id, a.endpoint, t.name, t.capability, t.config, a.status
		FROM tools t
		JOIN agents a ON t.agent_id = a.id
		WHERE t.capability = ? AND a.status = 'healthy'
	`
	args := []interface{}{dep.Capability}

	// Add namespace filtering if specified
	if dep.Namespace != "" && dep.Namespace != "default" {
		baseQuery += " AND a.namespace = ?"
		args = append(args, dep.Namespace)
	}

	rows, err := s.db.Query(baseQuery, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to query providers: %w", err)
	}
	defer rows.Close()

	// Collect all potential providers
	type provider struct {
		AgentID    string
		Endpoint   string
		ToolName   string
		Capability string
		ConfigJSON string
		Status     string
	}

	var providers []provider
	for rows.Next() {
		var p provider
		err := rows.Scan(&p.AgentID, &p.Endpoint, &p.ToolName, &p.Capability, &p.ConfigJSON, &p.Status)
		if err != nil {
			continue
		}
		providers = append(providers, p)
	}

	if len(providers) == 0 {
		return &ResolvedDependency{
			Capability: dep.Capability,
			Status:     "failed",
		}, nil
	}

	// Apply tag filtering if required
	if len(dep.Tags) > 0 {
		var filteredProviders []provider
		for _, p := range providers {
			// Parse config to check tags
			var config map[string]interface{}
			if err := json.Unmarshal([]byte(p.ConfigJSON), &config); err != nil {
				continue
			}

			// Check if provider has matching tags
			providerTags, ok := config["tags"].([]interface{})
			if !ok {
				continue
			}

			hasMatchingTag := false
			for _, reqTag := range dep.Tags {
				for _, providerTag := range providerTags {
					if tagStr, ok := providerTag.(string); ok && tagStr == reqTag {
						hasMatchingTag = true
						break
					}
				}
				if hasMatchingTag {
					break
				}
			}

			if hasMatchingTag {
				filteredProviders = append(filteredProviders, p)
			}
		}

		if len(filteredProviders) == 0 {
			return &ResolvedDependency{
				Capability: dep.Capability,
				Status:     "failed",
			}, nil
		}

		providers = filteredProviders
	}

	// TODO: Implement version constraint matching here
	// For now, just take the first available provider

	selectedProvider := providers[0]

	// Build MCP tool info
	mcpToolInfo := map[string]interface{}{
		"name":     selectedProvider.ToolName,
		"agent_id": selectedProvider.AgentID,
	}

	// Convert endpoint for HTTP-capable proxy
	endpoint := selectedProvider.Endpoint
	if strings.HasPrefix(endpoint, "stdio://") {
		// Convert stdio to HTTP endpoint for proxy
		// This is a placeholder - in reality, we'd need to know the actual HTTP port
		endpoint = fmt.Sprintf("http://%s:8000", strings.TrimPrefix(endpoint, "stdio://"))
	}
	mcpToolInfo["endpoint"] = endpoint

	return &ResolvedDependency{
		Capability:  dep.Capability,
		MCPToolInfo: mcpToolInfo,
		Status:      "resolved",
	}, nil
}