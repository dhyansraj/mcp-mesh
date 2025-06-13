package registry

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"mcp-mesh/src/core/database"
)

// Service provides registry operations matching Python RegistryService exactly
type Service struct {
	db     *database.Database
	config *RegistryConfig
	cache  *ResponseCache
	// healthMonitor *HealthMonitor  // Temporarily disabled
	validator *AgentRegistrationValidator
}

// RegistryConfig holds registry-specific configuration
type RegistryConfig struct {
	CacheTTL                 int
	DefaultTimeoutThreshold  int
	DefaultEvictionThreshold int
	EnableResponseCache      bool
}

// ResponseCache provides caching functionality matching Python implementation
type ResponseCache struct {
	cache   map[string]CacheEntry
	ttl     time.Duration
	enabled bool
}

type CacheEntry struct {
	Data      interface{}
	Timestamp time.Time
}

// NewService creates a new registry service instance
func NewService(db *database.Database, config *RegistryConfig) *Service {
	if config == nil {
		config = &RegistryConfig{
			CacheTTL:                 30,
			DefaultTimeoutThreshold:  60,
			DefaultEvictionThreshold: 120,
			EnableResponseCache:      true,
		}
	}

	cache := &ResponseCache{
		cache:   make(map[string]CacheEntry),
		ttl:     time.Duration(config.CacheTTL) * time.Second,
		enabled: config.EnableResponseCache,
	}

	service := &Service{
		db:        db,
		config:    config,
		cache:     cache,
		validator: NewAgentRegistrationValidator(),
	}

	// Initialize health monitor (temporarily disabled due to field conflicts)
	// service.healthMonitor = NewHealthMonitor(service, db)

	return service
}

// AgentRegistrationRequest matches Python RegisterAgentRequest exactly
type AgentRegistrationRequest struct {
	AgentID   string                 `json:"agent_id" binding:"required"`
	Metadata  map[string]interface{} `json:"metadata" binding:"required"`
	Timestamp string                 `json:"timestamp" binding:"required"`
}

// AgentRegistrationResponse matches Python response format exactly
type AgentRegistrationResponse struct {
	Status               string                           `json:"status"`
	AgentID              string                           `json:"agent_id"`
	ResourceVersion      string                           `json:"resource_version"`
	Timestamp            string                           `json:"timestamp"`
	Message              string                           `json:"message"`
	DependenciesResolved map[string]*DependencyResolution `json:"dependencies_resolved,omitempty"`
	Metadata             map[string]interface{}           `json:"metadata,omitempty"`
}

// DependencyResolution represents a resolved dependency
type DependencyResolution struct {
	AgentID  string `json:"agent_id"`
	Endpoint string `json:"endpoint"`
	Status   string `json:"status"`
}

// HeartbeatRequest matches Python HeartbeatRequest exactly
type HeartbeatRequest struct {
	AgentID  string                 `json:"agent_id" binding:"required"`
	Status   string                 `json:"status,omitempty"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// HeartbeatResponse matches Python response format exactly
type HeartbeatResponse struct {
	Status               string                           `json:"status"`
	Timestamp            string                           `json:"timestamp"`
	Message              string                           `json:"message"`
	AgentID              string                           `json:"agent_id,omitempty"`
	ResourceVersion      string                           `json:"resource_version,omitempty"`
	DependenciesResolved map[string]*DependencyResolution `json:"dependencies_resolved,omitempty"`
}

// AgentsResponse matches Python AgentsResponse exactly
type AgentsResponse struct {
	Agents    []map[string]interface{} `json:"agents"`
	Count     int                      `json:"count"`
	Timestamp string                   `json:"timestamp"`
}

// CapabilitiesResponse matches Python CapabilitiesResponse exactly
type CapabilitiesResponse struct {
	Capabilities []map[string]interface{} `json:"capabilities"`
	Count        int                      `json:"count"`
	Timestamp    string                   `json:"timestamp"`
}

// RegisterAgent handles agent registration with metadata
// MUST match Python register_agent_with_metadata behavior exactly
func (s *Service) RegisterAgent(req *AgentRegistrationRequest) (*AgentRegistrationResponse, error) {
	// Validate registration request (matches Python validation)
	if err := s.validator.ValidateAgentRegistration(req); err != nil {
		return nil, fmt.Errorf("validation failed: %w", err)
	}

	// Extract metadata similar to Python implementation
	metadata := req.Metadata

	// Skip legacy capabilities processing - we'll focus on new tools format

	// Normalize names (matches Python normalize_name function)
	agentName := normalizeName(getStringFromMap(metadata, "name", req.AgentID))
	agentType := normalizeName(getStringFromMap(metadata, "agent_type", "mesh-agent"))

	// Set type-specific thresholds (matches Python logic)
	timeoutThreshold := getIntFromMap(metadata, "timeout_threshold", s.config.DefaultTimeoutThreshold)
	evictionThreshold := getIntFromMap(metadata, "eviction_threshold", s.config.DefaultEvictionThreshold)

	// Apply type-specific defaults if not specified
	switch agentType {
	case "file-agent":
		if timeoutThreshold == s.config.DefaultTimeoutThreshold {
			timeoutThreshold = 90
		}
		if evictionThreshold == s.config.DefaultEvictionThreshold {
			evictionThreshold = 180
		}
	case "worker":
		if timeoutThreshold == s.config.DefaultTimeoutThreshold {
			timeoutThreshold = 45
		}
		if evictionThreshold == s.config.DefaultEvictionThreshold {
			evictionThreshold = 90
		}
	case "critical":
		if timeoutThreshold == s.config.DefaultTimeoutThreshold {
			timeoutThreshold = 30
		}
		if evictionThreshold == s.config.DefaultEvictionThreshold {
			evictionThreshold = 60
		}
	}

	// Create endpoint (matches Python logic for stdio agents)
	endpoint := getStringFromMap(metadata, "endpoint", "")

	// Handle HTTP endpoint if provided
	httpEndpoint := ""
	if ep, ok := metadata["endpoint"].(string); ok && (strings.HasPrefix(ep, "http://") || strings.HasPrefix(ep, "https://")) {
		httpEndpoint = ep
	}

	// Store transport type information
	transports := []string{"stdio"}
	if httpEndpoint != "" {
		transports = append(transports, "http")
	}

	// Store transport info in metadata
	if _, exists := metadata["transport"]; !exists {
		metadata["transport"] = transports
	}
	// Keep stdio:// endpoints as-is, they will be updated when HTTP wrapper starts
	if endpoint == "" {
		endpoint = fmt.Sprintf("stdio://%s", agentName)
	} else if strings.HasPrefix(endpoint, "stdio://") {
		// Keep stdio:// prefix as-is
		endpoint = endpoint
	} else if !strings.HasPrefix(endpoint, "http://") && !strings.HasPrefix(endpoint, "https://") {
		// For backward compatibility, convert other formats to stdio://
		endpoint = fmt.Sprintf("stdio://%s", agentName)
	}

	// Convert labels to JSON strings (matches Python storage format)
	labelsJSON := "{}"
	if labels, exists := metadata["tags"]; exists {
		if labelsBytes, err := json.Marshal(labels); err == nil {
			labelsJSON = string(labelsBytes)
		}
	}

	// Convert config and dependencies to JSON strings
	configJSON := "{}"
	if config, exists := metadata["metadata"]; exists {
		if configBytes, err := json.Marshal(config); err == nil {
			configJSON = string(configBytes)
		}
	}

	dependenciesJSON := "[]"
	if deps, exists := metadata["dependencies"]; exists {
		if depsBytes, err := json.Marshal(deps); err == nil {
			dependenciesJSON = string(depsBytes)
		}
	}

	// Create agent record (matching actual database.Agent model)
	now := time.Now().UTC()
	agent := database.Agent{
		ID:                req.AgentID,
		Name:              agentName,
		Namespace:         getStringFromMap(metadata, "namespace", "default"),
		BaseEndpoint:      endpoint, // Changed from Endpoint to BaseEndpoint
		Status:            "healthy",
		Labels:            labelsJSON,
		Metadata:          configJSON, // Changed from Config to Metadata
		CreatedAt:         now,
		UpdatedAt:         now,
		LastHeartbeat:     &now,
		TimeoutThreshold:  timeoutThreshold,
		EvictionThreshold: evictionThreshold,
		Transport:         `["stdio"]`, // Default transport
	}

	// Save to database using transaction (matches Python behavior)
	tx, err := s.db.DB.Begin()
	if err != nil {
		return nil, fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer tx.Rollback()

	// Delete existing tools for this agent (tools replace the old capabilities table)
	_, err = tx.Exec("DELETE FROM tools WHERE agent_id = ?", req.AgentID)
	if err != nil {
		return nil, fmt.Errorf("failed to delete existing tools: %w", err)
	}

	// Insert or update agent using direct SQL that matches database schema
	resourceVersion := fmt.Sprintf("%d", now.UnixMilli())
	_, err = tx.Exec(`
		INSERT OR REPLACE INTO agents (
			id, name, namespace, endpoint, status, labels, annotations,
			created_at, updated_at, resource_version, last_heartbeat,
			health_interval, timeout_threshold, eviction_threshold,
			agent_type, config, dependencies
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		agent.ID, agent.Name, agent.Namespace, agent.BaseEndpoint, agent.Status,
		agent.Labels, "{}", // annotations
		agent.CreatedAt, agent.UpdatedAt, resourceVersion, agent.LastHeartbeat,
		30, // health_interval
		agent.TimeoutThreshold, agent.EvictionThreshold,
		"mesh-agent", // agent_type
		agent.Metadata, // config
		"[]") // dependencies
	if err != nil {
		return nil, fmt.Errorf("failed to save agent: %w", err)
	}

	// Convert simple capabilities array to tools format for backward compatibility
	if capabilities, exists := metadata["capabilities"]; exists {
		if capSlice, ok := capabilities.([]string); ok {
			// Convert simple string capabilities to tools format
			tools := make([]interface{}, len(capSlice))
			for i, cap := range capSlice {
				tools[i] = map[string]interface{}{
					"function_name": cap,
					"capability":    cap,
					"version":       "1.0.0",
					"dependencies":  []interface{}{},
					"config":        map[string]interface{}{},
				}
			}
			metadata["tools"] = tools
		}
	}

	// Process tools (multi-tool format, including converted capabilities)
	if err := s.ProcessTools(req.AgentID, metadata, tx); err != nil {
		return nil, fmt.Errorf("failed to process tools: %w", err)
	}

	// Skip recording registry events for now

	// Skip registry events for now as the table may not exist
	// _, err = tx.Exec(`
	//	INSERT INTO registry_events (
	//		event_type, agent_id, timestamp, resource_version, data, source, metadata
	//	) VALUES (?, ?, ?, ?, ?, ?, ?)`,
	//	"MODIFIED", req.AgentID, now, fmt.Sprintf("%d", now.UnixMilli()), eventDataStr, "registry", "{}")
	// if err != nil {
	//	return nil, fmt.Errorf("failed to record registry event: %w", err)
	// }

	// Commit transaction
	err = tx.Commit()
	if err != nil {
		return nil, fmt.Errorf("failed to commit transaction: %w", err)
	}

	if err != nil {
		return nil, fmt.Errorf("failed to register agent: %w", err)
	}

	// Invalidate cache
	s.cache.invalidateAll()

	// Parse dependencies from JSON (legacy format)
	var dependencies []string
	if dependenciesJSON != "[]" && dependenciesJSON != "" {
		if err := json.Unmarshal([]byte(dependenciesJSON), &dependencies); err != nil {
			log.Printf("Warning: Failed to parse dependencies: %v", err)
		}
	}

	// Resolve dependencies (legacy format)
	dependenciesResolved, err := s.resolveDependencies(req.AgentID, dependencies)
	if err != nil {
		log.Printf("Warning: Failed to resolve dependencies: %v", err)
		// Continue without dependencies rather than failing registration
		dependenciesResolved = make(map[string]*DependencyResolution)
	}

	// Resolve per-tool dependencies (new multi-tool format)
	toolDependenciesResolved := s.resolveAllDependencies(req.AgentID)

	// Return response with both legacy and new dependency resolution
	response := &AgentRegistrationResponse{
		Status:               "success",
		AgentID:              req.AgentID,
		ResourceVersion:      fmt.Sprintf("%d", now.UnixMilli()),
		Timestamp:            now.Format(time.RFC3339),
		Message:              "Agent registered successfully",
		DependenciesResolved: dependenciesResolved,
		Metadata: map[string]interface{}{
			"dependencies_resolved": toolDependenciesResolved,
		},
	}

	return response, nil
}

// UpdateHeartbeat handles agent heartbeat updates
// MUST match Python update_heartbeat behavior exactly
func (s *Service) UpdateHeartbeat(req *HeartbeatRequest) (*HeartbeatResponse, error) {
	now := time.Now().UTC()
	resourceVersion := fmt.Sprintf("%d", now.UnixMilli())

	// Build update map (matches Python heartbeat update logic)
	updates := map[string]interface{}{
		"last_heartbeat":   now,
		"status":           "healthy",
		"updated_at":       now,
		"resource_version": resourceVersion,
	}

	// Override status if provided in request (matches Python behavior)
	if req.Status != "" {
		updates["status"] = req.Status
	}

	// Check if endpoint is provided in metadata and update it
	var endpointUpdate string
	var hasEndpointUpdate bool
	if req.Metadata != nil {
		if endpoint, ok := req.Metadata["endpoint"].(string); ok && endpoint != "" {
			endpointUpdate = endpoint
			hasEndpointUpdate = true
			log.Printf("Updating endpoint for agent %s to: %s", req.AgentID, endpoint)
		}
	}

	// Update agent heartbeat in database
	var result sql.Result
	var err error

	if hasEndpointUpdate {
		// Update including endpoint
		result, err = s.db.DB.Exec(`
			UPDATE agents SET
				last_heartbeat = ?,
				status = ?,
				updated_at = ?,
				resource_version = ?,
				endpoint = ?
			WHERE id = ?`,
			updates["last_heartbeat"], updates["status"], updates["updated_at"], updates["resource_version"], endpointUpdate, req.AgentID)
	} else {
		// Update without endpoint
		result, err = s.db.DB.Exec(`
			UPDATE agents SET
				last_heartbeat = ?,
				status = ?,
				updated_at = ?,
				resource_version = ?
			WHERE id = ?`,
			updates["last_heartbeat"], updates["status"], updates["updated_at"], updates["resource_version"], req.AgentID)
	}

	if err != nil {
		return nil, fmt.Errorf("failed to update heartbeat: %w", err)
	}

	rowsAffected, err := result.RowsAffected()
	if err != nil {
		return nil, fmt.Errorf("failed to get rows affected: %w", err)
	}

	if rowsAffected == 0 {
		return &HeartbeatResponse{
			Status:    "error",
			Timestamp: now.Format(time.RFC3339),
			Message:   fmt.Sprintf("Agent %s not found", req.AgentID),
		}, nil
	}

	// Record health event (matches Python behavior)
	_ = req.AgentID // avoid unused variable warning
	// Skip health event recording for now - table may not exist

	// _, err = s.db.DB.Exec(`
	//	INSERT INTO agent_health (
	//		agent_id, status, timestamp, metadata
	//	) VALUES (?, ?, ?, ?)`,
	//	req.AgentID, req.Status, now, metadata)
	// if err != nil {
	//	log.Printf("Warning: Failed to record health event: %v", err)
	// }

	// Invalidate cache when heartbeat updates occur (matches Python behavior)
	s.cache.invalidateAll()

	// Get agent's dependencies from database
	var dependenciesJSON string
	err = s.db.DB.QueryRow("SELECT dependencies FROM agents WHERE id = ?", req.AgentID).Scan(&dependenciesJSON)
	if err != nil {
		log.Printf("Warning: Failed to get agent dependencies: %v", err)
		dependenciesJSON = "[]"
	}

	// Parse dependencies
	var dependencies []string
	if dependenciesJSON != "[]" && dependenciesJSON != "" {
		if err := json.Unmarshal([]byte(dependenciesJSON), &dependencies); err != nil {
			log.Printf("Warning: Failed to parse dependencies: %v", err)
		}
	}

	// Resolve dependencies
	dependenciesResolved, err := s.resolveDependencies(req.AgentID, dependencies)
	if err != nil {
		log.Printf("Warning: Failed to resolve dependencies: %v", err)
		dependenciesResolved = make(map[string]*DependencyResolution)
	}

	return &HeartbeatResponse{
		Status:               "success",
		Timestamp:            now.Format(time.RFC3339),
		Message:              "Heartbeat recorded",
		AgentID:              req.AgentID,
		ResourceVersion:      resourceVersion,
		DependenciesResolved: dependenciesResolved,
	}, nil
}

// ListAgents handles agent discovery with filtering
// MUST match Python get_agents behavior exactly
func (s *Service) ListAgents(params *AgentQueryParams) (*AgentsResponse, error) {
	// Check cache first
	cacheKey := s.cache.generateCacheKey("agents_list", params)
	if cached := s.cache.get(cacheKey); cached != nil {
		if response, ok := cached.(*AgentsResponse); ok {
			return response, nil
		}
	}

	// Build query conditions and arguments
	conditions := []string{}
	args := []interface{}{}

	// Apply basic filters (matches Python filtering logic)
	if params.Namespace != "" {
		conditions = append(conditions, "namespace = ?")
		args = append(args, params.Namespace)
	}

	if params.Status != "" {
		conditions = append(conditions, "status = ?")
		args = append(args, params.Status)
	}

	// Capability filtering via subquery (matches Python logic exactly)
	if len(params.Capabilities) > 0 {
		// Build capability filter with fuzzy matching support
		capabilityConditions := make([]string, 0, len(params.Capabilities))
		capabilityArgs := make([]interface{}, 0, len(params.Capabilities))

		for _, cap := range params.Capabilities {
			if params.FuzzyMatch {
				// Fuzzy matching using LIKE (matches Python Levenshtein logic approximation)
				capabilityConditions = append(capabilityConditions, "LOWER(name) LIKE ?")
				capabilityArgs = append(capabilityArgs, "%"+strings.ToLower(cap)+"%")
			} else {
				// Exact matching
				capabilityConditions = append(capabilityConditions, "name = ?")
				capabilityArgs = append(capabilityArgs, cap)
			}
		}

		capabilitySubquery := fmt.Sprintf("id IN (SELECT DISTINCT agent_id FROM tools WHERE %s)", strings.Join(capabilityConditions, " OR "))
		conditions = append(conditions, capabilitySubquery)
		args = append(args, capabilityArgs...)
	}

	// Capability category filtering (matches Python logic)
	if params.CapabilityCategory != "" {
		// Note: In simplified model, category is not stored, but preserving API compatibility
		conditions = append(conditions, "1=0") // No results for category filter in simplified model
	}

	// Capability stability filtering (matches Python logic)
	if params.CapabilityStability != "" {
		// Note: In simplified model, stability is not stored, but preserving API compatibility
		conditions = append(conditions, "1=0") // No results for stability filter in simplified model
	}

	// Capability tags filtering (matches Python logic)
	if len(params.CapabilityTags) > 0 {
		// Note: In simplified model, tags are not stored separately, but preserving API compatibility
		conditions = append(conditions, "1=0") // No results for tags filter in simplified model
	}

	// Build final query
	querySQL := "SELECT * FROM agents"
	if len(conditions) > 0 {
		querySQL += " WHERE " + strings.Join(conditions, " AND ")
	}
	querySQL += " ORDER BY updated_at DESC"

	// Execute query
	rows, err := s.db.Query(querySQL, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to list agents: %w", err)
	}
	defer rows.Close()

	var agents []database.Agent
	for rows.Next() {
		var agent database.Agent
		var lastHeartbeat sql.NullTime
		var securityContext sql.NullString

		// Simplified scan to match actual database.Agent fields
		var annotations, resourceVersion, agentType, config, dependencies string
		var healthInterval int
		err := rows.Scan(
			&agent.ID, &agent.Name, &agent.Namespace, &agent.BaseEndpoint, &agent.Status,
			&agent.Labels, &annotations, &agent.CreatedAt, &agent.UpdatedAt,
			&resourceVersion, &lastHeartbeat, &healthInterval,
			&agent.TimeoutThreshold, &agent.EvictionThreshold, &agentType,
			&config, &securityContext, &dependencies)
		if err != nil {
			return nil, fmt.Errorf("failed to scan agent: %w", err)
		}

		if lastHeartbeat.Valid {
			agent.LastHeartbeat = &lastHeartbeat.Time
		}
		// Note: securityContext is scanned but not used in current Agent model

		agents = append(agents, agent)
	}

	// Post-process filtering (matches Python post-query filtering)
	filteredAgents := make([]database.Agent, 0, len(agents))
	for _, agent := range agents {
		include := true

		// TODO: Add label selector filtering when AgentQueryParams includes LabelSelector field
		// Currently AgentQueryParams doesn't have LabelSelector field

		// TODO: Add version constraint filtering when needed
		// if params.VersionConstraint != "" {
		//     include = include && s.matchesVersionConstraint(agent, params.VersionConstraint)
		// }

		if include {
			filteredAgents = append(filteredAgents, agent)
		}
	}

	// Convert to response format (matches Python agent.model_dump())
	agentMaps := make([]map[string]interface{}, len(filteredAgents))
	for i, agent := range filteredAgents {
		agentMaps[i] = s.agentToMap(agent)
	}

	response := &AgentsResponse{
		Agents:    agentMaps,
		Count:     len(agentMaps),
		Timestamp: time.Now().UTC().Format(time.RFC3339),
	}

	// Cache the result
	s.cache.set(cacheKey, response)

	return response, nil
}

// SearchCapabilities handles capability discovery with filtering
// MUST match Python get_capabilities behavior exactly
func (s *Service) SearchCapabilities(params *CapabilityQueryParams) (*CapabilitiesResponse, error) {
	// Check cache first
	cacheKey := s.cache.generateCacheKey("capabilities_search", params)
	if cached := s.cache.get(cacheKey); cached != nil {
		if response, ok := cached.(*CapabilitiesResponse); ok {
			return response, nil
		}
	}

	// Execute query
	type CapabilityResult struct {
		ID                   uint      `json:"id"`
		Name                 string    `json:"name"`
		Description          *string   `json:"description"`
		Version              string    `json:"version"`
		ParametersSchema     *string   `json:"parameters_schema"`
		SecurityRequirements *string   `json:"security_requirements"`
		CreatedAt            time.Time `json:"created_at"`
		UpdatedAt            time.Time `json:"updated_at"`
		AgentID              string    `json:"agent_id"`
		AgentName            string    `json:"agent_name"`
		AgentNamespace       string    `json:"agent_namespace"`
		AgentStatus          string    `json:"agent_status"`
		AgentEndpoint        string    `json:"agent_endpoint"`
	}

	// Build capability query conditions and arguments
	conditions := []string{}
	args := []interface{}{}

	// Apply agent-level filters first (matches Python agent filtering)
	if params.AgentStatus != "" {
		conditions = append(conditions, "a.status = ?")
		args = append(args, params.AgentStatus)
	} else {
		// Default to healthy agents only (matches Python default behavior)
		conditions = append(conditions, "a.status IN (?, ?)")
		args = append(args, "healthy", "degraded")
	}

	if params.Namespace != "" {
		conditions = append(conditions, "a.namespace = ?")
		args = append(args, params.Namespace)
	}

	// Apply capability filters (matches Python capability filtering logic)
	if params.Name != "" {
		if params.FuzzyMatch {
			// Fuzzy matching using LIKE (matches Python Levenshtein distance approximation)
			conditions = append(conditions, "LOWER(t.name) LIKE ?")
			args = append(args, "%"+strings.ToLower(params.Name)+"%")
		} else {
			// Exact matching (case insensitive)
			conditions = append(conditions, "LOWER(t.name) = ?")
			args = append(args, strings.ToLower(params.Name))
		}
	}

	// TODO: Add description filtering when CapabilityQueryParams includes DescriptionContains field

	// Version constraint filtering (implement semantic version matching when needed)
	if params.Version != "" {
		// For now, simple exact match - would need semantic version parsing for full compatibility
		conditions = append(conditions, "t.version = ?")
		args = append(args, params.Version)
	}

	// Tags filtering using tools table
	if len(params.Tags) > 0 {
		// TODO: Implement tag filtering when tool configuration includes tags
	}

	// Build final query
	querySQL := `SELECT t.id, t.agent_id, t.name, t.capability as description, t.version,
					'{}' as parameters_schema, '{}' as security_requirements,
					t.created_at, t.updated_at,
					a.id as agent_id, a.name as agent_name, a.namespace as agent_namespace,
					a.status as agent_status, a.base_endpoint as agent_endpoint
			 FROM tools t
			 JOIN agents a ON t.agent_id = a.id`

	if len(conditions) > 0 {
		querySQL += " WHERE " + strings.Join(conditions, " AND ")
	}
	querySQL += " ORDER BY t.name ASC"

	rows, err := s.db.Query(querySQL, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to search capabilities: %w", err)
	}
	defer rows.Close()

	var results []CapabilityResult
	for rows.Next() {
		var result CapabilityResult
		var description sql.NullString
		var parametersSchema sql.NullString
		var securityRequirements sql.NullString

		err := rows.Scan(
			&result.ID, &result.AgentID, &result.Name, &description, &result.Version,
			&parametersSchema, &securityRequirements, &result.CreatedAt, &result.UpdatedAt,
			&result.AgentID, &result.AgentName, &result.AgentNamespace,
			&result.AgentStatus, &result.AgentEndpoint)
		if err != nil {
			return nil, fmt.Errorf("failed to scan capability: %w", err)
		}

		if description.Valid {
			result.Description = &description.String
		}
		if parametersSchema.Valid {
			result.ParametersSchema = &parametersSchema.String
		}
		if securityRequirements.Valid {
			result.SecurityRequirements = &securityRequirements.String
		}

		results = append(results, result)
	}

	// Convert to response format (matches Python capability serialization)
	capabilityMaps := make([]map[string]interface{}, len(results))
	for i, result := range results {
		capabilityMaps[i] = map[string]interface{}{
			"id":              result.ID,
			"name":            result.Name,
			"description":     result.Description,
			"version":         result.Version,
			"created_at":      result.CreatedAt.Format(time.RFC3339),
			"updated_at":      result.UpdatedAt.Format(time.RFC3339),
			"agent_id":        result.AgentID,
			"agent_name":      result.AgentName,
			"agent_namespace": result.AgentNamespace,
			"agent_status":    result.AgentStatus,
			"agent_endpoint":  result.AgentEndpoint,
		}

		// Add parameters_schema if present (matches Python JSON field handling)
		if result.ParametersSchema != nil {
			var paramSchema interface{}
			if err := json.Unmarshal([]byte(*result.ParametersSchema), &paramSchema); err == nil {
				capabilityMaps[i]["parameters_schema"] = paramSchema
			}
		}

		// Add security_requirements if present (matches Python JSON field handling)
		if result.SecurityRequirements != nil {
			var secReqs interface{}
			if err := json.Unmarshal([]byte(*result.SecurityRequirements), &secReqs); err == nil {
				capabilityMaps[i]["security_requirements"] = secReqs
			}
		}
	}

	response := &CapabilitiesResponse{
		Capabilities: capabilityMaps,
		Count:        len(capabilityMaps),
		Timestamp:    time.Now().UTC().Format(time.RFC3339),
	}

	// Cache the result
	s.cache.set(cacheKey, response)

	return response, nil
}

// StartHealthMonitoring starts the passive health monitoring system
// MUST match Python start_health_monitoring behavior exactly
func (s *Service) StartHealthMonitoring() error {
	// Health monitor temporarily disabled
	return fmt.Errorf("health monitor not implemented yet")
}

// StopHealthMonitoring stops the health monitoring system
func (s *Service) StopHealthMonitoring() error {
	// Health monitor temporarily disabled
	return nil
}

// GetHealthMonitoringStats returns health monitoring statistics
func (s *Service) GetHealthMonitoringStats() (map[string]interface{}, error) {
	// Health monitor temporarily disabled
	return map[string]interface{}{
		"status": "disabled",
	}, nil
}

// Health returns service health status
func (s *Service) Health() map[string]interface{} {
	// Check database connectivity
	sqlDB := s.db.DB
	if err := sqlDB.Ping(); err != nil {
		return map[string]interface{}{
			"status":  "unhealthy",
			"service": "mcp-mesh-registry",
			"error":   err.Error(),
		}
	}

	// Include health monitoring status
	health := map[string]interface{}{
		"status":  "healthy",
		"service": "mcp-mesh-registry",
	}

	// Add health monitoring info (temporarily disabled)
	health["health_monitoring_active"] = false
	health["monitoring_stats"] = map[string]interface{}{
		"status": "disabled",
	}

	return health
}

// resolveDependencies resolves the dependencies for an agent by finding healthy agents with the required capabilities
func (s *Service) resolveDependencies(agentID string, dependencies []string) (map[string]*DependencyResolution, error) {
	resolved := make(map[string]*DependencyResolution)

	// If no dependencies, return empty map
	if len(dependencies) == 0 {
		return resolved, nil
	}

	// For each dependency, find the first healthy agent with that capability
	for _, dep := range dependencies {
		// Query for healthy agents with the required capability
		rows, err := s.db.DB.Query(`
			SELECT DISTINCT a.id, a.base_endpoint, a.status
			FROM agents a
			JOIN tools t ON t.agent_id = a.id
			WHERE t.capability = ? AND a.status = 'healthy'
			ORDER BY a.updated_at DESC
			LIMIT 1`, dep)

		if err != nil {
			log.Printf("Error querying for dependency %s: %v", dep, err)
			resolved[dep] = nil
			continue
		}

		var found bool
		if rows.Next() {
			var depAgentID, endpoint, status string
			if err := rows.Scan(&depAgentID, &endpoint, &status); err == nil {
				resolved[dep] = &DependencyResolution{
					AgentID:  depAgentID,
					Endpoint: endpoint,
					Status:   status,
				}
				found = true
			}
		}
		rows.Close()

		if !found {
			// No healthy provider found
			resolved[dep] = nil
		}
	}

	return resolved, nil
}

// Helper methods

func (s *Service) agentToMap(agent database.Agent) map[string]interface{} {
	// Start building result map
	result := map[string]interface{}{
		"id":                 agent.ID,
		"name":               agent.Name,
		"namespace":          agent.Namespace,
		"endpoint":           agent.BaseEndpoint,
		"status":             agent.Status,
		"created_at":         agent.CreatedAt.Format(time.RFC3339),
		"updated_at":         agent.UpdatedAt.Format(time.RFC3339),
		"resource_version":   fmt.Sprintf("%d", agent.UpdatedAt.UnixMilli()),
		"health_interval":    30, // Default value
		"timeout_threshold":  agent.TimeoutThreshold,
		"eviction_threshold": agent.EvictionThreshold,
		"agent_type":         "mesh-agent", // Default value
	}

	// Load tools separately using raw SQL
	rows, err := s.db.DB.Query("SELECT id, agent_id, name, capability, version, created_at, updated_at FROM tools WHERE agent_id = ?", agent.ID)
	if err != nil {
		log.Printf("Warning: Failed to load capabilities for agent %s: %v", agent.ID, err)
		// Return result with empty capabilities array
		result["capabilities"] = []map[string]interface{}{}
		return result
	}
	defer rows.Close()

	var tools []database.Tool
	for rows.Next() {
		var tool database.Tool
		var capability string

		err := rows.Scan(&tool.ID, &tool.AgentID, &tool.Name, &capability, &tool.Version, &tool.CreatedAt, &tool.UpdatedAt)
		if err != nil {
			log.Printf("Warning: Failed to scan tool: %v", err)
			continue
		}

		tool.Capability = capability
		tools = append(tools, tool)
	}

	// Include last_heartbeat if available (matches Python serialization)
	if agent.LastHeartbeat != nil {
		result["last_heartbeat"] = agent.LastHeartbeat.Format(time.RFC3339)
	} else {
		result["last_heartbeat"] = nil // Explicit null for API consistency
	}

	// Include security_context (not in current Agent model)
	result["security_context"] = nil // Explicit null for API consistency

	// Parse JSON fields (matches Python JSON field handling exactly)
	if agent.Labels != "" && agent.Labels != "{}" {
		var labels interface{}
		if err := json.Unmarshal([]byte(agent.Labels), &labels); err == nil {
			result["labels"] = labels
		} else {
			result["labels"] = map[string]interface{}{} // Empty object on parse error
		}
	} else {
		result["labels"] = map[string]interface{}{} // Default empty object
	}

	// Annotations not in current Agent model
	result["annotations"] = map[string]interface{}{} // Default empty object

	// Use Metadata field from current Agent model
	if agent.Metadata != "" && agent.Metadata != "{}" {
		var config interface{}
		if err := json.Unmarshal([]byte(agent.Metadata), &config); err == nil {
			result["config"] = config
		} else {
			result["config"] = map[string]interface{}{} // Empty object on parse error
		}
	} else {
		result["config"] = map[string]interface{}{} // Default empty object
	}

	// Dependencies not in current Agent model - would be in tools
	result["dependencies"] = []interface{}{} // Default empty array

	// Add capabilities with full details (using tools data, formatted as capabilities for compatibility)
	capabilityMaps := make([]map[string]interface{}, len(tools))
	for i, tool := range tools {
		capability := map[string]interface{}{
			"id":                    tool.ID,
			"name":                  tool.Name,
			"capability":            tool.Capability,
			"version":               tool.Version,
			"created_at":            tool.CreatedAt.Format(time.RFC3339),
			"updated_at":            tool.UpdatedAt.Format(time.RFC3339),
			"description":           tool.Capability, // Use capability as description
			"parameters_schema":     nil,             // TODO: Extract from tool config
			"security_requirements": nil,             // TODO: Extract from tool config
		}

		capabilityMaps[i] = capability
	}
	result["capabilities"] = capabilityMaps

	return result
}

// Cache methods

func (c *ResponseCache) get(key string) interface{} {
	if !c.enabled {
		return nil
	}

	entry, exists := c.cache[key]
	if !exists {
		return nil
	}

	// Check if entry is expired
	if time.Since(entry.Timestamp) > c.ttl {
		delete(c.cache, key)
		return nil
	}

	return entry.Data
}

func (c *ResponseCache) set(key string, data interface{}) {
	if !c.enabled {
		return
	}

	c.cache[key] = CacheEntry{
		Data:      data,
		Timestamp: time.Now(),
	}
}

func (c *ResponseCache) invalidateAll() {
	if !c.enabled {
		return
	}
	c.cache = make(map[string]CacheEntry)
}

func (c *ResponseCache) generateCacheKey(prefix string, params interface{}) string {
	if paramsBytes, err := json.Marshal(params); err == nil {
		return fmt.Sprintf("%s:%x", prefix, paramsBytes)
	}
	return prefix
}

// Helper functions

func getStringFromMap(m map[string]interface{}, key, defaultValue string) string {
	if value, exists := m[key]; exists {
		if str, ok := value.(string); ok {
			return str
		}
	}
	return defaultValue
}

func getStringPtrFromMap(m map[string]interface{}, key string) *string {
	if value, exists := m[key]; exists {
		if str, ok := value.(string); ok && str != "" {
			return &str
		}
	}
	return nil
}

func getIntFromMap(m map[string]interface{}, key string, defaultValue int) int {
	if value, exists := m[key]; exists {
		if intVal, ok := value.(int); ok {
			return intVal
		}
		if floatVal, ok := value.(float64); ok {
			return int(floatVal)
		}
	}
	return defaultValue
}

func normalizeName(name string) string {
	// Convert to lowercase and replace invalid characters with hyphens
	name = strings.ToLower(name)
	name = strings.ReplaceAll(name, "_", "-")
	name = strings.ReplaceAll(name, " ", "-")

	// Remove consecutive hyphens
	for strings.Contains(name, "--") {
		name = strings.ReplaceAll(name, "--", "-")
	}

	// Remove leading/trailing hyphens
	name = strings.Trim(name, "-")

	if name == "" {
		return "agent"
	}

	return name
}
