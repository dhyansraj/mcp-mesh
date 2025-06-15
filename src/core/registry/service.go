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
	Status               string                             `json:"status"`
	AgentID              string                             `json:"agent_id"`
	ResourceVersion      string                             `json:"resource_version"`
	Timestamp            string                             `json:"timestamp"`
	Message              string                             `json:"message"`
	DependenciesResolved map[string][]*DependencyResolution `json:"dependencies_resolved,omitempty"`
	Metadata             map[string]interface{}             `json:"metadata,omitempty"`
}

// DependencyResolution represents a resolved dependency in the new format
type DependencyResolution struct {
	AgentID      string `json:"agent_id"`
	FunctionName string `json:"function_name"`
	Endpoint     string `json:"endpoint"`
	Capability   string `json:"capability"`
	Status       string `json:"status"`
}

// HeartbeatRequest matches Python HeartbeatRequest exactly
type HeartbeatRequest struct {
	AgentID  string                 `json:"agent_id" binding:"required"`
	Status   string                 `json:"status,omitempty"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// HeartbeatResponse matches Python response format exactly
type HeartbeatResponse struct {
	Status               string                             `json:"status"`
	Timestamp            string                             `json:"timestamp"`
	Message              string                             `json:"message"`
	AgentID              string                             `json:"agent_id,omitempty"`
	ResourceVersion      string                             `json:"resource_version,omitempty"`
	DependenciesResolved map[string][]*DependencyResolution `json:"dependencies_resolved,omitempty"`
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
	if req.AgentID == "" {
		return nil, fmt.Errorf("agent_id is required")
	}

	// Begin transaction
	tx, err := s.db.DB.Begin()
	if err != nil {
		return nil, fmt.Errorf("failed to begin transaction: %w", err)
	}
	defer func() {
		if err != nil {
			tx.Rollback()
		}
	}()

	// Check if agent exists
	var existingID string
	err = tx.QueryRow("SELECT agent_id FROM agents WHERE agent_id = ?", req.AgentID).Scan(&existingID)
	if err != nil && err != sql.ErrNoRows {
		return nil, fmt.Errorf("failed to check existing agent: %w", err)
	}

	// Extract agent metadata from request
	agentName := req.AgentID
	if name, exists := req.Metadata["name"]; exists {
		if nameStr, ok := name.(string); ok {
			agentName = nameStr
		}
	}

	agentType := "mcp_agent"
	if aType, exists := req.Metadata["agent_type"]; exists {
		if typeStr, ok := aType.(string); ok {
			agentType = typeStr
		}
	}

	namespace := "default"
	if ns, exists := req.Metadata["namespace"]; exists {
		if nsStr, ok := ns.(string); ok {
			namespace = nsStr
		}
	}

	version := ""
	if v, exists := req.Metadata["version"]; exists {
		if vStr, ok := v.(string); ok {
			version = vStr
		}
	}

	httpHost := ""
	if host, exists := req.Metadata["http_host"]; exists {
		if hostStr, ok := host.(string); ok {
			httpHost = hostStr
		}
	}

	var httpPort *int
	if port, exists := req.Metadata["http_port"]; exists {
		switch p := port.(type) {
		case float64:
			portInt := int(p)
			httpPort = &portInt
		case int:
			httpPort = &p
		case int64:
			portInt := int(p)
			httpPort = &portInt
		}
	}

	// Note: timestamp field removed - registry controls all timestamps via created_at/updated_at

	// Count total dependencies from tools
	totalDeps := 0
	if toolsData, exists := req.Metadata["tools"]; exists {
		if toolsList, ok := toolsData.([]interface{}); ok {
			for _, toolData := range toolsList {
				if toolMap, ok := toolData.(map[string]interface{}); ok {
					if deps, exists := toolMap["dependencies"]; exists {
						// Handle both []interface{} and []map[string]interface{} types
						var depCount int
						if depsList, ok := deps.([]interface{}); ok {
							depCount = len(depsList)
						} else if depsMapList, ok := deps.([]map[string]interface{}); ok {
							depCount = len(depsMapList)
						} else {
							continue
						}
						totalDeps += depCount
					}
				}
			}
		}
	}

	// Prepare SQL for agent upsert
	now := time.Now().UTC()
	if existingID != "" {
		// Update existing agent
		_, err = tx.Exec(`
			UPDATE agents
			SET agent_type = ?, name = ?, version = ?, http_host = ?, http_port = ?,
			    namespace = ?, total_dependencies = ?, updated_at = ?
			WHERE agent_id = ?`,
			agentType, agentName, version, httpHost, httpPort, namespace, totalDeps, now, req.AgentID)
	} else {
		// Insert new agent
		_, err = tx.Exec(`
			INSERT INTO agents (agent_id, agent_type, name, version, http_host, http_port,
			                   namespace, total_dependencies, dependencies_resolved,
			                   created_at, updated_at)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)`,
			req.AgentID, agentType, agentName, version, httpHost, httpPort, namespace, totalDeps, now, now)
	}

	if err != nil {
		return nil, fmt.Errorf("failed to upsert agent: %w", err)
	}

	// Process capabilities using the new ProcessCapabilities method
	err = s.ProcessCapabilities(req.AgentID, req.Metadata, tx)
	if err != nil {
		return nil, fmt.Errorf("failed to process capabilities: %w", err)
	}

	// Commit transaction
	err = tx.Commit()
	if err != nil {
		return nil, fmt.Errorf("failed to commit transaction: %w", err)
	}

	// Resolve dependencies from metadata during registration
	dependenciesResolved, err := s.ResolveAllDependenciesFromMetadata(req.Metadata)
	if err != nil {
		log.Printf("Warning: Failed to resolve dependencies: %v", err)
		// Continue without dependencies rather than failing registration
		dependenciesResolved = make(map[string][]*DependencyResolution)
	}

	// Count total resolved dependencies across all functions
	resolvedCount := 0
	for _, deps := range dependenciesResolved {
		resolvedCount += len(deps)
	}

	// Update dependencies_resolved count in database
	_, err = s.db.DB.Exec(`
		UPDATE agents SET dependencies_resolved = ? WHERE agent_id = ?`,
		resolvedCount, req.AgentID)
	if err != nil {
		log.Printf("Warning: Failed to update dependencies_resolved count: %v", err)
		// Don't fail registration over this
	}

	log.Printf("Agent %s: %d total dependencies, %d resolved", req.AgentID, totalDeps, resolvedCount)

	return &AgentRegistrationResponse{
		Status:               "success",
		Message:              "Agent registered successfully",
		AgentID:              req.AgentID,
		Timestamp:            now.Format(time.RFC3339),
		DependenciesResolved: dependenciesResolved,
	}, nil
}

// UpdateHeartbeat handles lightweight agent heartbeat updates
func (s *Service) UpdateHeartbeat(req *HeartbeatRequest) (*HeartbeatResponse, error) {
	if req.AgentID == "" {
		return nil, fmt.Errorf("agent_id is required")
	}

	now := time.Now().UTC()

	// Check if agent exists
	var existingID string
	err := s.db.DB.QueryRow("SELECT agent_id FROM agents WHERE agent_id = ?", req.AgentID).Scan(&existingID)
	agentExists := err == nil

	if err != nil && err != sql.ErrNoRows {
		return nil, fmt.Errorf("failed to check agent existence: %w", err)
	}

	// If agent doesn't exist and heartbeat has tools/metadata, register it
	if !agentExists && req.Metadata != nil {
		fullReq := &AgentRegistrationRequest{
			AgentID:   req.AgentID,
			Metadata:  req.Metadata,
			Timestamp: now.Format(time.RFC3339),
		}
		regResp, err := s.RegisterAgent(fullReq)
		if err != nil {
			return &HeartbeatResponse{
				Status:    "error",
				Timestamp: now.Format(time.RFC3339),
				Message:   err.Error(),
			}, nil
		}
		return &HeartbeatResponse{
			Status:               regResp.Status,
			Timestamp:            now.Format(time.RFC3339),
			Message:              "Agent registered via heartbeat",
			AgentID:              regResp.AgentID,
			DependenciesResolved: regResp.DependenciesResolved,
		}, nil
	}

	// If agent doesn't exist and no metadata, return error
	if !agentExists {
		return &HeartbeatResponse{
			Status:    "error",
			Timestamp: now.Format(time.RFC3339),
			Message:   fmt.Sprintf("Agent %s not found - must provide metadata for registration", req.AgentID),
		}, nil
	}

	// Note: Status is implicit in heartbeat (assumes healthy unless agent sends error)

	// If metadata is provided and contains tools, do full registration instead
	if req.Metadata != nil {
		if _, hasTools := req.Metadata["tools"]; hasTools {
			// Fall back to full registration for tool updates
			fullReq := &AgentRegistrationRequest{
				AgentID:   req.AgentID,
				Metadata:  req.Metadata,
				Timestamp: now.Format(time.RFC3339),
			}
			regResp, err := s.RegisterAgent(fullReq)
			if err != nil {
				return &HeartbeatResponse{
					Status:    "error",
					Timestamp: now.Format(time.RFC3339),
					Message:   err.Error(),
				}, nil
			}
			return &HeartbeatResponse{
				Status:               regResp.Status,
				Timestamp:            now.Format(time.RFC3339),
				Message:              "Heartbeat with tools update received",
				AgentID:              regResp.AgentID,
				DependenciesResolved: regResp.DependenciesResolved,
			}, nil
		}
	}

	// Lightweight heartbeat - just update timestamp and basic metadata
	updateSQL := `UPDATE agents SET updated_at = ?`
	args := []interface{}{now}

	// Optionally update basic metadata fields
	if req.Metadata != nil {
		if version, exists := req.Metadata["version"]; exists {
			if vStr, ok := version.(string); ok {
				updateSQL += ", version = ?"
				args = append(args, vStr)
			}
		}
		if namespace, exists := req.Metadata["namespace"]; exists {
			if nsStr, ok := namespace.(string); ok {
				updateSQL += ", namespace = ?"
				args = append(args, nsStr)
			}
		}
		if httpHost, exists := req.Metadata["http_host"]; exists {
			if hostStr, ok := httpHost.(string); ok {
				updateSQL += ", http_host = ?"
				args = append(args, hostStr)
			}
		}
		if httpPort, exists := req.Metadata["http_port"]; exists {
			switch p := httpPort.(type) {
			case float64:
				updateSQL += ", http_port = ?"
				args = append(args, int(p))
			case int:
				updateSQL += ", http_port = ?"
				args = append(args, p)
			case int64:
				updateSQL += ", http_port = ?"
				args = append(args, int(p))
			}
		}
	}

	updateSQL += " WHERE agent_id = ?"
	args = append(args, req.AgentID)

	// Execute update
	result, err := s.db.DB.Exec(updateSQL, args...)
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

	return &HeartbeatResponse{
		Status:    "success",
		Timestamp: now.Format(time.RFC3339),
		Message:   "Heartbeat received",
		AgentID:   req.AgentID,
	}, nil
}

// UpdateHeartbeatLegacy handles agent heartbeat updates (legacy implementation)
// MUST match Python update_heartbeat behavior exactly
func (s *Service) UpdateHeartbeatLegacy(req *HeartbeatRequest) (*HeartbeatResponse, error) {
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

	// Resolve dependencies using new dependency resolution system
	dependenciesResolved, err := s.ResolveAllDependencies(req.AgentID)
	if err != nil {
		log.Printf("Warning: Failed to resolve dependencies: %v", err)
		dependenciesResolved = make(map[string][]*DependencyResolution)
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

	// Capability filtering via subquery (updated for new schema)
	if len(params.Capabilities) > 0 {
		// Build capability filter with fuzzy matching support
		capabilityConditions := make([]string, 0, len(params.Capabilities))
		capabilityArgs := make([]interface{}, 0, len(params.Capabilities))

		for _, cap := range params.Capabilities {
			if params.FuzzyMatch {
				// Fuzzy matching using LIKE (matches Python Levenshtein logic approximation)
				capabilityConditions = append(capabilityConditions, "LOWER(capability) LIKE ?")
				capabilityArgs = append(capabilityArgs, "%"+strings.ToLower(cap)+"%")
			} else {
				// Exact matching
				capabilityConditions = append(capabilityConditions, "capability = ?")
				capabilityArgs = append(capabilityArgs, cap)
			}
		}

		// Updated to use capabilities table instead of tools table
		capabilitySubquery := fmt.Sprintf("agent_id IN (SELECT DISTINCT agent_id FROM capabilities WHERE %s)", strings.Join(capabilityConditions, " OR "))
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

	// Use map to represent agents for new schema
	var agents []map[string]interface{}
	for rows.Next() {
		var agentID, agentType, name string
		var version, httpHost, namespace sql.NullString
		var httpPort, totalDeps, resolvedDeps sql.NullInt64
		var createdAt, updatedAt sql.NullString

		// Scan using new schema columns (timestamp column removed)
		err := rows.Scan(
			&agentID, &agentType, &name, &version, &httpHost, &httpPort,
			&namespace, &totalDeps, &resolvedDeps,
			&createdAt, &updatedAt)
		if err != nil {
			return nil, fmt.Errorf("failed to scan agent: %w", err)
		}

		// Calculate health status based on last_seen with smart thresholds
		status := "expired" // Default for unparseable timestamps
		if updatedAt.Valid {
			// Try multiple timestamp formats
			var lastSeen time.Time
			var parseErr error

			// Try RFC3339 format first (what we store)
			lastSeen, parseErr = time.Parse(time.RFC3339, updatedAt.String)
			if parseErr != nil {
				// Try SQLite default format
				lastSeen, parseErr = time.Parse("2006-01-02 15:04:05", updatedAt.String)
			}
			if parseErr != nil {
				// Try another common format
				lastSeen, parseErr = time.Parse("2006-01-02T15:04:05Z", updatedAt.String)
			}

			if parseErr == nil {
				timeSinceLastSeen := time.Since(lastSeen)
				timeoutThreshold := time.Duration(s.config.DefaultTimeoutThreshold) * time.Second

				// Smart health calculation:
				// < timeout = healthy
				// timeout to timeout*2 = degraded
				// > timeout*2 = expired
				if timeSinceLastSeen < timeoutThreshold {
					status = "healthy"
				} else if timeSinceLastSeen < timeoutThreshold*2 {
					status = "degraded"
				} else {
					status = "expired"
				}
			} else {
				log.Printf("Warning: Could not parse updated_at timestamp '%s': %v", updatedAt.String, parseErr)
			}
		}

		// Build agent map for API response
		agent := map[string]interface{}{
			"id":     agentID,
			"name":   name,
			"status": status,
		}

		// Add optional fields
		if version.Valid {
			agent["version"] = version.String
		}
		if namespace.Valid {
			agent["namespace"] = namespace.String
		} else {
			agent["namespace"] = "default"
		}

		// Build endpoint
		endpoint := "stdio://" + agentID // Default
		if httpHost.Valid && httpPort.Valid && httpPort.Int64 > 0 {
			endpoint = fmt.Sprintf("http://%s:%d", httpHost.String, httpPort.Int64)
		}
		agent["endpoint"] = endpoint

		// Add dependency counts (for debugging/display)
		if totalDeps.Valid {
			agent["total_dependencies"] = totalDeps.Int64
		}
		if resolvedDeps.Valid {
			agent["dependencies_resolved"] = resolvedDeps.Int64
		}

		// Parse last seen from updated_at (reuse the parsed value from health calculation)
		if updatedAt.Valid {
			// Try multiple timestamp formats (same as health calculation)
			var lastSeenTime time.Time
			var parseErr error

			lastSeenTime, parseErr = time.Parse(time.RFC3339, updatedAt.String)
			if parseErr != nil {
				lastSeenTime, parseErr = time.Parse("2006-01-02 15:04:05", updatedAt.String)
			}
			if parseErr != nil {
				lastSeenTime, parseErr = time.Parse("2006-01-02T15:04:05Z", updatedAt.String)
			}

			if parseErr == nil {
				agent["last_seen"] = lastSeenTime.Format(time.RFC3339)
			}
		}

		agents = append(agents, agent)
	}

	// Now we need to add capabilities to each agent
	agentMaps := make([]map[string]interface{}, 0, len(agents))
	for _, agent := range agents {
		// Get capabilities for this agent
		agentID := agent["id"].(string)
		capabilities, err := s.GetAgentCapabilities(agentID)
		if err != nil {
			log.Printf("Warning: Failed to get capabilities for agent %s: %v", agentID, err)
			capabilities = []map[string]interface{}{} // Empty capabilities on error
		}

		// Extract capability names for the required "capabilities" field
		capabilityNames := make([]string, len(capabilities))
		for i, cap := range capabilities {
			if capName, ok := cap["capability"].(string); ok {
				capabilityNames[i] = capName
			}
		}
		agent["capabilities"] = capabilityNames

		// Note: Dependencies field removed from API spec - we use real-time resolution instead

		agentMaps = append(agentMaps, agent)
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

	// Parse dependencies from agent data
	if agent.Dependencies != "" && agent.Dependencies != "[]" {
		var dependencies interface{}
		if err := json.Unmarshal([]byte(agent.Dependencies), &dependencies); err == nil {
			result["dependencies"] = dependencies
		} else {
			result["dependencies"] = []interface{}{} // Empty array on parse error
		}
	} else {
		result["dependencies"] = []interface{}{} // Default empty array
	}

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

// getMapKeys returns all keys from a map for debugging
func getMapKeys(m map[string]interface{}) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}
