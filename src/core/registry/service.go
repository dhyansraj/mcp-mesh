package registry

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/registry/generated"
)

// NotFoundError represents a resource not found error (should return 404)
type NotFoundError struct {
	Message string
}

func (e *NotFoundError) Error() string {
	return e.Message
}

// isTableNotExistError checks if the error is due to missing database table
func isTableNotExistError(err error) bool {
	if err == nil {
		return false
	}
	errMsg := strings.ToLower(err.Error())
	return strings.Contains(errMsg, "no such table") ||
		   strings.Contains(errMsg, "table doesn't exist") ||
		   strings.Contains(errMsg, "table not found")
}

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

// AgentsResponse is now defined in generated package

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
	placeholder := s.db.GetParameterPlaceholder(1)
	checkSQL := fmt.Sprintf("SELECT agent_id FROM agents WHERE agent_id = %s", placeholder)

	// DEBUG: PostgreSQL parameter debugging
	log.Printf("🐛 [PostgreSQL DEBUG] Database type: isPostgreSQL=%t", s.db.IsPostgreSQL())
	log.Printf("🐛 [PostgreSQL DEBUG] Parameter placeholder: '%s'", placeholder)
	log.Printf("🐛 [PostgreSQL DEBUG] Generated SQL: '%s'", checkSQL)
	log.Printf("🐛 [PostgreSQL DEBUG] Parameter value: '%s'", req.AgentID)

	err = tx.QueryRow(checkSQL, req.AgentID).Scan(&existingID)
	if err != nil && err != sql.ErrNoRows {
		log.Printf("🐛 [PostgreSQL DEBUG] Query error: %v", err)
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
		updateSQL := fmt.Sprintf(`
			UPDATE agents
			SET agent_type = %s, name = %s, version = %s, http_host = %s, http_port = %s,
			    namespace = %s, total_dependencies = %s, updated_at = %s
			WHERE agent_id = %s`,
			s.db.GetParameterPlaceholder(1), s.db.GetParameterPlaceholder(2), s.db.GetParameterPlaceholder(3),
			s.db.GetParameterPlaceholder(4), s.db.GetParameterPlaceholder(5), s.db.GetParameterPlaceholder(6),
			s.db.GetParameterPlaceholder(7), s.db.GetParameterPlaceholder(8), s.db.GetParameterPlaceholder(9))
		_, err = tx.Exec(updateSQL, agentType, agentName, version, httpHost, httpPort, namespace, totalDeps, now, req.AgentID)
	} else {
		// Insert new agent
		insertSQL := fmt.Sprintf(`
			INSERT INTO agents (agent_id, agent_type, name, version, http_host, http_port,
			                   namespace, total_dependencies, dependencies_resolved,
			                   created_at, updated_at)
			VALUES (%s)`,
			s.db.BuildParameterList(11))
		_, err = tx.Exec(insertSQL, req.AgentID, agentType, agentName, version, httpHost, httpPort, namespace, totalDeps, 0, now, now)
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
	updateDepsSQL := fmt.Sprintf(`
		UPDATE agents SET dependencies_resolved = %s WHERE agent_id = %s`,
		s.db.GetParameterPlaceholder(1), s.db.GetParameterPlaceholder(2))
	_, err = s.db.DB.Exec(updateDepsSQL, resolvedCount, req.AgentID)
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
	placeholder := s.db.GetParameterPlaceholder(1)
	checkSQL := fmt.Sprintf("SELECT agent_id FROM agents WHERE agent_id = %s", placeholder)

	// DEBUG: PostgreSQL parameter debugging (heartbeat)
	log.Printf("🐛 [PostgreSQL DEBUG - Heartbeat] Database type: isPostgreSQL=%t", s.db.IsPostgreSQL())
	log.Printf("🐛 [PostgreSQL DEBUG - Heartbeat] Parameter placeholder: '%s'", placeholder)
	log.Printf("🐛 [PostgreSQL DEBUG - Heartbeat] Generated SQL: '%s'", checkSQL)
	log.Printf("🐛 [PostgreSQL DEBUG - Heartbeat] Parameter value: '%s'", req.AgentID)

	err := s.db.DB.QueryRow(checkSQL, req.AgentID).Scan(&existingID)
	agentExists := err == nil

	if err != nil && err != sql.ErrNoRows {
		log.Printf("🐛 [PostgreSQL DEBUG - Heartbeat] Query error: %v", err)
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
	updateSQL := fmt.Sprintf(`UPDATE agents SET updated_at = %s`, s.db.GetParameterPlaceholder(1))
	args := []interface{}{now}
	paramCount := 1

	// Optionally update basic metadata fields
	if req.Metadata != nil {
		if version, exists := req.Metadata["version"]; exists {
			if vStr, ok := version.(string); ok {
				paramCount++
				updateSQL += fmt.Sprintf(", version = %s", s.db.GetParameterPlaceholder(paramCount))
				args = append(args, vStr)
			}
		}
		if namespace, exists := req.Metadata["namespace"]; exists {
			if nsStr, ok := namespace.(string); ok {
				paramCount++
				updateSQL += fmt.Sprintf(", namespace = %s", s.db.GetParameterPlaceholder(paramCount))
				args = append(args, nsStr)
			}
		}
		if httpHost, exists := req.Metadata["http_host"]; exists {
			if hostStr, ok := httpHost.(string); ok {
				paramCount++
				updateSQL += fmt.Sprintf(", http_host = %s", s.db.GetParameterPlaceholder(paramCount))
				args = append(args, hostStr)
			}
		}
		if httpPort, exists := req.Metadata["http_port"]; exists {
			switch p := httpPort.(type) {
			case float64:
				paramCount++
				updateSQL += fmt.Sprintf(", http_port = %s", s.db.GetParameterPlaceholder(paramCount))
				args = append(args, int(p))
			case int:
				paramCount++
				updateSQL += fmt.Sprintf(", http_port = %s", s.db.GetParameterPlaceholder(paramCount))
				args = append(args, p)
			case int64:
				paramCount++
				updateSQL += fmt.Sprintf(", http_port = %s", s.db.GetParameterPlaceholder(paramCount))
				args = append(args, int(p))
			}
		}
	}

	paramCount++
	updateSQL += fmt.Sprintf(" WHERE agent_id = %s", s.db.GetParameterPlaceholder(paramCount))
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
		updateWithEndpointSQL := fmt.Sprintf(`
			UPDATE agents SET
				last_heartbeat = %s,
				status = %s,
				updated_at = %s,
				resource_version = %s,
				endpoint = %s
			WHERE id = %s`,
			s.db.GetParameterPlaceholder(1), s.db.GetParameterPlaceholder(2), s.db.GetParameterPlaceholder(3),
			s.db.GetParameterPlaceholder(4), s.db.GetParameterPlaceholder(5), s.db.GetParameterPlaceholder(6))
		result, err = s.db.DB.Exec(updateWithEndpointSQL,
			updates["last_heartbeat"], updates["status"], updates["updated_at"], updates["resource_version"], endpointUpdate, req.AgentID)
	} else {
		// Update without endpoint
		updateWithoutEndpointSQL := fmt.Sprintf(`
			UPDATE agents SET
				last_heartbeat = %s,
				status = %s,
				updated_at = %s,
				resource_version = %s
			WHERE id = %s`,
			s.db.GetParameterPlaceholder(1), s.db.GetParameterPlaceholder(2), s.db.GetParameterPlaceholder(3),
			s.db.GetParameterPlaceholder(4), s.db.GetParameterPlaceholder(5))
		result, err = s.db.DB.Exec(updateWithoutEndpointSQL,
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
func (s *Service) ListAgents(params *AgentQueryParams) (*generated.AgentsListResponse, error) {
	// Check cache first
	cacheKey := s.cache.generateCacheKey("agents_list", params)
	if cached := s.cache.get(cacheKey); cached != nil {
		if response, ok := cached.(*generated.AgentsListResponse); ok {
			return response, nil
		}
	}

	// Build query conditions and arguments with database-specific placeholders
	conditions := []string{}
	args := []interface{}{}
	paramCount := 0

	// Apply basic filters (matches Python filtering logic)
	if params.Namespace != "" {
		paramCount++
		conditions = append(conditions, fmt.Sprintf("namespace = %s", s.db.GetParameterPlaceholder(paramCount)))
		args = append(args, params.Namespace)
	}

	if params.Status != "" {
		paramCount++
		conditions = append(conditions, fmt.Sprintf("status = %s", s.db.GetParameterPlaceholder(paramCount)))
		args = append(args, params.Status)
	}

	// Capability filtering via subquery (updated for new schema)
	if len(params.Capabilities) > 0 {
		// Build capability filter with fuzzy matching support
		capabilityConditions := make([]string, 0, len(params.Capabilities))
		capabilityArgs := make([]interface{}, 0, len(params.Capabilities))

		for _, cap := range params.Capabilities {
			paramCount++
			if params.FuzzyMatch {
				// Fuzzy matching using LIKE (matches Python Levenshtein logic approximation)
				capabilityConditions = append(capabilityConditions, fmt.Sprintf("LOWER(capability) LIKE %s", s.db.GetParameterPlaceholder(paramCount)))
				capabilityArgs = append(capabilityArgs, "%"+strings.ToLower(cap)+"%")
			} else {
				// Exact matching
				capabilityConditions = append(capabilityConditions, fmt.Sprintf("capability = %s", s.db.GetParameterPlaceholder(paramCount)))
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
		// Check if error is due to missing database table (no agents registered yet)
		if isTableNotExistError(err) {
			// Return empty list instead of error when table doesn't exist
			return &generated.AgentsListResponse{
				Agents:    []generated.AgentInfo{},
				Count:     0,
				Timestamp: time.Now(),
			}, nil
		}
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

	// Now we need to add capabilities to each agent and build proper AgentInfo structs
	agentInfos := make([]generated.AgentInfo, 0, len(agents))
	for _, agent := range agents {
		// Get capabilities for this agent
		agentID := agent["id"].(string)
		capabilities, err := s.GetAgentCapabilities(agentID)
		if err != nil {
			log.Printf("Warning: Failed to get capabilities for agent %s: %v", agentID, err)
			capabilities = []map[string]interface{}{} // Empty capabilities on error
		}

		// Build enhanced capabilities array with CapabilityInfo objects
		capabilityInfos := make([]generated.CapabilityInfo, len(capabilities))
		for i, cap := range capabilities {
			capInfo := generated.CapabilityInfo{
				Name:         cap["capability"].(string),
				Version:      cap["version"].(string),
				FunctionName: cap["function_name"].(string),
			}

			// Add optional description if present
			if description, ok := cap["description"].(string); ok && description != "" {
				capInfo.Description = &description
			}

			// Add tags if present and non-empty
			if tags, ok := cap["tags"].([]interface{}); ok && len(tags) > 0 {
				tagStrings := make([]string, len(tags))
				for j, tag := range tags {
					if tagStr, ok := tag.(string); ok {
						tagStrings[j] = tagStr
					}
				}
				capInfo.Tags = &tagStrings
			}

			capabilityInfos[i] = capInfo
		}

		// Build AgentInfo struct
		agentInfo := generated.AgentInfo{
			Id:                   agent["id"].(string),
			Name:                 agent["name"].(string),
			Status:               generated.AgentInfoStatus(agent["status"].(string)),
			Endpoint:             agent["endpoint"].(string),
			Capabilities:         capabilityInfos,
			TotalDependencies:    int(agent["total_dependencies"].(int64)),
			DependenciesResolved: int(agent["dependencies_resolved"].(int64)),
		}

		// Add optional fields
		if version, ok := agent["version"].(string); ok {
			agentInfo.Version = &version
		}
		if lastSeen, ok := agent["last_seen"].(string); ok {
			if lastSeenTime, err := time.Parse(time.RFC3339, lastSeen); err == nil {
				agentInfo.LastSeen = &lastSeenTime
			}
		}

		agentInfos = append(agentInfos, agentInfo)
	}

	response := &generated.AgentsListResponse{
		Agents:    agentInfos,
		Count:     len(agentInfos),
		Timestamp: time.Now().UTC(),
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

	// Build capability query conditions and arguments with database-specific placeholders
	conditions := []string{}
	args := []interface{}{}
	paramCount := 0

	// Apply agent-level filters first (matches Python agent filtering)
	if params.AgentStatus != "" {
		paramCount++
		conditions = append(conditions, fmt.Sprintf("a.status = %s", s.db.GetParameterPlaceholder(paramCount)))
		args = append(args, params.AgentStatus)
	} else {
		// Default to healthy agents only (matches Python default behavior)
		paramCount++
		param1 := s.db.GetParameterPlaceholder(paramCount)
		paramCount++
		param2 := s.db.GetParameterPlaceholder(paramCount)
		conditions = append(conditions, fmt.Sprintf("a.status IN (%s, %s)", param1, param2))
		args = append(args, "healthy", "degraded")
	}

	if params.Namespace != "" {
		paramCount++
		conditions = append(conditions, fmt.Sprintf("a.namespace = %s", s.db.GetParameterPlaceholder(paramCount)))
		args = append(args, params.Namespace)
	}

	// Apply capability filters (matches Python capability filtering logic)
	if params.Name != "" {
		paramCount++
		if params.FuzzyMatch {
			// Fuzzy matching using LIKE (matches Python Levenshtein distance approximation)
			conditions = append(conditions, fmt.Sprintf("LOWER(t.name) LIKE %s", s.db.GetParameterPlaceholder(paramCount)))
			args = append(args, "%"+strings.ToLower(params.Name)+"%")
		} else {
			// Exact matching (case insensitive)
			conditions = append(conditions, fmt.Sprintf("LOWER(t.name) = %s", s.db.GetParameterPlaceholder(paramCount)))
			args = append(args, strings.ToLower(params.Name))
		}
	}

	// TODO: Add description filtering when CapabilityQueryParams includes DescriptionContains field

	// Version constraint filtering (implement semantic version matching when needed)
	if params.Version != "" {
		paramCount++
		// For now, simple exact match - would need semantic version parsing for full compatibility
		conditions = append(conditions, fmt.Sprintf("t.version = %s", s.db.GetParameterPlaceholder(paramCount)))
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
	toolsQuerySQL := fmt.Sprintf("SELECT id, agent_id, name, capability, version, created_at, updated_at FROM tools WHERE agent_id = %s", s.db.GetParameterPlaceholder(1))
	rows, err := s.db.DB.Query(toolsQuerySQL, agent.ID)
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
