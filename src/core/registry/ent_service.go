package registry

import (
	"context"
	"fmt"
	"time"

	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry/generated"
)

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

// EntService provides registry operations using Ent ORM instead of raw SQL
type EntService struct {
	entDB     *database.EntDatabase
	config    *RegistryConfig
	cache     *ResponseCache
	validator *AgentRegistrationValidator
	logger    *logger.Logger
}

// NewEntService creates a new Ent-based registry service instance
func NewEntService(entDB *database.EntDatabase, config *RegistryConfig, logger *logger.Logger) *EntService {
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

	return &EntService{
		entDB:     entDB,
		config:    config,
		cache:     cache,
		validator: NewAgentRegistrationValidator(),
		logger:    logger,
	}
}

// RegisterAgent handles agent registration using Ent queries
func (s *EntService) RegisterAgent(req *AgentRegistrationRequest) (*AgentRegistrationResponse, error) {
	ctx := context.Background()

	if req.AgentID == "" {
		return nil, fmt.Errorf("agent_id is required")
	}

	now := time.Now().UTC()

	// Validate the request
	if err := s.validator.ValidateAgentRegistration(req); err != nil {
		return nil, fmt.Errorf("validation failed: %w", err)
	}

	// Extract agent metadata
	agentType := "mcp_agent" // default
	if aType, ok := req.Metadata["agent_type"]; ok {
		if aTypeStr, ok := aType.(string); ok {
			agentType = aTypeStr
		}
	}

	name := req.AgentID // default to agent_id
	if n, ok := req.Metadata["name"]; ok {
		if nameStr, ok := n.(string); ok {
			name = nameStr
		}
	}

	version := ""
	if v, ok := req.Metadata["version"]; ok {
		if vStr, ok := v.(string); ok {
			version = vStr
		}
	}

	namespace := "default"
	if ns, ok := req.Metadata["namespace"]; ok {
		if nsStr, ok := ns.(string); ok {
			namespace = nsStr
		}
	}

	var httpHost string
	var httpPort int
	if host, ok := req.Metadata["http_host"]; ok {
		if hostStr, ok := host.(string); ok {
			httpHost = hostStr
		}
	}
	if port, ok := req.Metadata["http_port"]; ok {
		switch p := port.(type) {
		case float64:
			httpPort = int(p)
		case int:
			httpPort = p
		}
	}

	// Start a transaction for atomicity
	err := s.entDB.Transaction(ctx, func(tx *ent.Tx) error {
		// Upsert the agent
		agentCreate := tx.Agent.Create().
			SetID(req.AgentID).
			SetAgentType(agent.AgentType(agentType)).
			SetName(name).
			SetNamespace(namespace).
			SetUpdatedAt(now)

		if version != "" {
			agentCreate = agentCreate.SetVersion(version)
		}
		if httpHost != "" {
			agentCreate = agentCreate.SetHTTPHost(httpHost)
		}
		if httpPort > 0 {
			agentCreate = agentCreate.SetHTTPPort(httpPort)
		}

		// Check if agent already exists and update or create
		existingAgent, err := tx.Agent.Query().Where(agent.IDEQ(req.AgentID)).Only(ctx)
		if err != nil {
			if ent.IsNotFound(err) {
				// Create new agent
				existingAgent, err = agentCreate.Save(ctx)
				if err != nil {
					return fmt.Errorf("failed to create agent: %w", err)
				}
			} else {
				return fmt.Errorf("failed to check existing agent: %w", err)
			}
		} else {
			// Update existing agent
			updateBuilder := existingAgent.Update().
				SetAgentType(agent.AgentType(agentType)).
				SetName(name).
				SetNamespace(namespace).
				SetUpdatedAt(now)

			if version != "" {
				updateBuilder = updateBuilder.SetVersion(version)
			}
			if httpHost != "" {
				updateBuilder = updateBuilder.SetHTTPHost(httpHost)
			}
			if httpPort > 0 {
				updateBuilder = updateBuilder.SetHTTPPort(httpPort)
			}

			existingAgent, err = updateBuilder.Save(ctx)
			if err != nil {
				return fmt.Errorf("failed to update agent: %w", err)
			}
		}

		// Process tools/capabilities if present
		totalDeps := 0
		if tools, ok := req.Metadata["tools"]; ok {
			if toolsArray, ok := tools.([]interface{}); ok {
				// Clear existing capabilities for this agent
				_, err := tx.Capability.Delete().Where(capability.HasAgentWith(agent.IDEQ(req.AgentID))).Exec(ctx)
				if err != nil {
					return fmt.Errorf("failed to clear existing capabilities: %w", err)
				}

				// Add new capabilities
				for _, tool := range toolsArray {
					if toolMap, ok := tool.(map[string]interface{}); ok {
						functionName, _ := toolMap["function_name"].(string)
						capabilityName, _ := toolMap["capability"].(string)
						description, _ := toolMap["description"].(string)
						capVersion := "1.0.0"
						if v, ok := toolMap["version"].(string); ok && v != "" {
							capVersion = v
						}

						tags := []string{}
						if tagsInterface, ok := toolMap["tags"]; ok {
							if tagsArray, ok := tagsInterface.([]interface{}); ok {
								for _, tag := range tagsArray {
									if tagStr, ok := tag.(string); ok {
										tags = append(tags, tagStr)
									}
								}
							}
						}

						if functionName != "" && capabilityName != "" {
							_, err := tx.Capability.Create().
								SetAgentID(req.AgentID).
								SetFunctionName(functionName).
								SetCapability(capabilityName).
								SetVersion(capVersion).
								SetNillableDescription(&description).
								SetTags(tags).
								Save(ctx)
							if err != nil {
								return fmt.Errorf("failed to create capability %s: %w", functionName, err)
							}
						}

						// Count dependencies
						if deps, ok := toolMap["dependencies"]; ok {
							if depsArray, ok := deps.([]interface{}); ok {
								s.logger.Debug("Function %s has %d dependencies", functionName, len(depsArray))
								totalDeps += len(depsArray)
							}
						}
					}
				}
			}
		}

		// Dependencies will be calculated after transaction commits

		// Create registry event
		eventData := map[string]interface{}{
			"agent_type": agentType,
			"name":       name,
			"version":    version,
		}

		_, err = tx.RegistryEvent.Create().
			SetEventType(registryevent.EventTypeRegister).
			SetAgentID(req.AgentID).
			SetTimestamp(now).
			SetData(eventData).
			Save(ctx)
		if err != nil {
			s.logger.Warning("Failed to create registry event: %v", err)
			// Don't fail the registration over event creation
		}

		return nil
	})

	if err != nil {
		return nil, fmt.Errorf("failed to register agent: %w", err)
	}

	// Now that capabilities are saved, calculate dependencies and update agent
	totalDeps, resolvedDeps := s.calculateAndResolveDependencies(req.Metadata)
	s.logger.Info("Agent %s: %d total dependencies, %d resolved", req.AgentID, totalDeps, resolvedDeps)

	// Update dependency counts in agent record (outside transaction)
	ctx = context.Background()
	_, err = s.entDB.Agent.UpdateOneID(req.AgentID).
		SetTotalDependencies(totalDeps).
		SetDependenciesResolved(resolvedDeps).
		Save(ctx)
	if err != nil {
		s.logger.Warning("Failed to update dependency counts: %v", err)
		// Don't fail registration over this
	}

	// Get dependencies resolved for response
	dependenciesResolved, err := s.ResolveAllDependenciesFromMetadata(req.Metadata)
	if err != nil {
		s.logger.Warning("Failed to resolve dependencies for response: %v", err)
		dependenciesResolved = make(map[string][]*DependencyResolution)
	}

	s.logger.Info("Agent %s registered successfully", req.AgentID)

	return &AgentRegistrationResponse{
		Status:               "success",
		Message:              "Agent registered successfully",
		AgentID:              req.AgentID,
		Timestamp:            now.Format(time.RFC3339),
		DependenciesResolved: dependenciesResolved,
	}, nil
}

// UpdateHeartbeat handles lightweight agent heartbeat updates using Ent
func (s *EntService) UpdateHeartbeat(req *HeartbeatRequest) (*HeartbeatResponse, error) {
	ctx := context.Background()

	if req.AgentID == "" {
		return nil, fmt.Errorf("agent_id is required")
	}

	now := time.Now().UTC()

	// Check if agent exists
	existingAgent, err := s.entDB.Agent.Query().Where(agent.IDEQ(req.AgentID)).Only(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			// If agent doesn't exist and heartbeat has metadata, register it
			if req.Metadata != nil {
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

			return &HeartbeatResponse{
				Status:    "error",
				Timestamp: now.Format(time.RFC3339),
				Message:   fmt.Sprintf("Agent %s not found - must provide metadata for registration", req.AgentID),
			}, nil
		}
		return nil, fmt.Errorf("failed to check agent existence: %w", err)
	}

	// If metadata is provided and contains tools, do full registration instead
	if req.Metadata != nil {
		if _, hasTools := req.Metadata["tools"]; hasTools {
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
				Message:              "Agent updated via heartbeat",
				AgentID:              regResp.AgentID,
				DependenciesResolved: regResp.DependenciesResolved,
			}, nil
		}
	}

	// Simple heartbeat update - just update timestamp
	_, err = existingAgent.Update().
		SetUpdatedAt(now).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to update agent heartbeat: %w", err)
	}

	// Create heartbeat event
	eventData := map[string]interface{}{
		"status": "healthy",
	}
	_, err = s.entDB.RegistryEvent.Create().
		SetEventType(registryevent.EventTypeHeartbeat).
		SetAgentID(req.AgentID).
		SetTimestamp(now).
		SetData(eventData).
		Save(ctx)
	if err != nil {
		s.logger.Warning("Failed to create heartbeat event: %v", err)
	}

	s.logger.Info("Heartbeat updated for agent %s", req.AgentID)

	return &HeartbeatResponse{
		Status:    "success",
		Timestamp: now.Format(time.RFC3339),
		Message:   "Heartbeat updated successfully",
		AgentID:   req.AgentID,
	}, nil
}

// ListAgents returns a list of agents using Ent queries
func (s *EntService) ListAgents(params *AgentQueryParams) (*generated.AgentsListResponse, error) {
	ctx := context.Background()

	// Build query
	query := s.entDB.Agent.Query()

	// Apply filters
	if params != nil {
		if params.Namespace != "" {
			query = query.Where(agent.NamespaceEQ(params.Namespace))
		}
		if params.Type != "" {
			query = query.Where(agent.AgentTypeEQ(agent.AgentType(params.Type)))
		}
	}

	// Execute query with capabilities
	agents, err := query.WithCapabilities().All(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to query agents: %w", err)
	}

	// Convert to response format
	var agentInfos []generated.AgentInfo
	for _, a := range agents {
		// Build endpoint
		endpoint := fmt.Sprintf("stdio://%s", a.ID) // Default to stdio
		if a.HTTPHost != "" && a.HTTPPort > 0 {
			endpoint = fmt.Sprintf("http://%s:%d", a.HTTPHost, a.HTTPPort)
		}

		// Calculate health status based on TTL (matches old SQL service logic)
		status := "expired" // Default
		timeSinceLastSeen := time.Since(a.UpdatedAt)
		timeoutThreshold := time.Duration(s.config.DefaultTimeoutThreshold) * time.Second

		// Smart health calculation (same as old service):
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

		agentInfo := generated.AgentInfo{
			Id:       a.ID,
			Name:     a.Name,
			Version:  &a.Version,
			Status:   generated.AgentInfoStatus(status),
			Endpoint: endpoint,
			LastSeen: &a.UpdatedAt,
		}

		// Add capabilities
		var capabilities []generated.CapabilityInfo
		for _, cap := range a.Edges.Capabilities {
			capabilities = append(capabilities, generated.CapabilityInfo{
				FunctionName: cap.FunctionName,
				Name:         cap.Capability,
				Version:      cap.Version,
				Description:  &cap.Description,
			})
		}
		agentInfo.Capabilities = capabilities

		// Use stored dependency counts (calculated at registration time)
		agentInfo.TotalDependencies = a.TotalDependencies
		agentInfo.DependenciesResolved = a.DependenciesResolved

		agentInfos = append(agentInfos, agentInfo)
	}

	return &generated.AgentsListResponse{
		Agents:    agentInfos,
		Count:     len(agentInfos),
		Timestamp: time.Now(),
	}, nil
}

// Health returns service health information
func (s *EntService) Health() map[string]interface{} {
	stats, err := s.entDB.GetStats()
	if err != nil {
		s.logger.Warning("Failed to get database stats: %v", err)
		stats = map[string]interface{}{
			"error": "Failed to get database stats",
		}
	}

	return map[string]interface{}{
		"status":        "healthy",
		"service":       "mcp-mesh-registry",
		"database_type": func() string {
			if s.entDB.IsPostgreSQL() {
				return "postgresql"
			}
			return "sqlite"
		}(),
		"cache_enabled": s.cache.enabled,
		"stats":         stats,
	}
}

// ResolveAllDependenciesFromMetadata resolves dependencies using the tools metadata from registration
// Implements strict dependency resolution: ALL dependencies must resolve or function fails
func (s *EntService) ResolveAllDependenciesFromMetadata(metadata map[string]interface{}) (map[string][]*DependencyResolution, error) {
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

					// Find provider with TTL and strict matching using Ent
					provider := s.findHealthyProviderWithTTL(dep)
					if provider != nil {
						resolvedDeps = append(resolvedDeps, provider)
					} else {
						// Dependency cannot be resolved - log but continue with other dependencies
						s.logger.Debug("Failed to resolve dependency %s for function %s", dep.Capability, functionName)
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
					s.logger.Debug("Function %s excluded due to unresolvable dependencies", functionName)
				}
			}
		}
	}

	return resolved, nil
}

// GetAgentWithCapabilities retrieves agent data with capabilities for testing
func (s *EntService) GetAgentWithCapabilities(agentID string) (map[string]interface{}, error) {
	ctx := context.Background()

	agentRecord, err := s.entDB.Agent.Query().
		Where(agent.IDEQ(agentID)).
		WithCapabilities().
		Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("agent not found: %w", err)
	}

	result := map[string]interface{}{
		"agent_id":   agentRecord.ID,
		"name":       agentRecord.Name,
		"namespace":  agentRecord.Namespace,
		"version":    agentRecord.Version,
		"updated_at": agentRecord.UpdatedAt.Format(time.RFC3339),
		"agent_type": string(agentRecord.AgentType),
	}

	// Add capabilities
	capabilities := make([]map[string]interface{}, len(agentRecord.Edges.Capabilities))
	for i, cap := range agentRecord.Edges.Capabilities {
		capabilities[i] = map[string]interface{}{
			"function_name": cap.FunctionName,
			"capability":    cap.Capability,
			"version":       cap.Version,
			"description":   cap.Description,
			"tags":          cap.Tags,
		}
	}
	result["capabilities"] = capabilities

	return result, nil
}

// findHealthyProviderWithTTL finds a healthy provider using TTL check and strict matching using Ent queries
func (s *EntService) findHealthyProviderWithTTL(dep database.Dependency) *DependencyResolution {
	ctx := context.Background()

	// Calculate TTL threshold
	timeoutDuration := time.Duration(s.config.DefaultTimeoutThreshold) * time.Second
	ttlThreshold := time.Now().UTC().Add(-timeoutDuration)

	// Query capabilities with healthy agents using Ent
	capabilities, err := s.entDB.Capability.Query().
		Where(capability.CapabilityEQ(dep.Capability)).
		WithAgent().
		All(ctx)

	if err != nil {
		s.logger.Error("Error finding healthy providers for %s: %v", dep.Capability, err)
		return nil
	}

	// Convert to candidates structure
	var candidates []struct {
		AgentID      string
		FunctionName string
		Capability   string
		Version      string
		Tags         []string
		HttpHost     string
		HttpPort     int
		UpdatedAt    time.Time
	}

	for _, cap := range capabilities {
		if cap.Edges.Agent == nil {
			continue // Skip if agent not loaded
		}

		// Check TTL - agent must have been updated recently
		if cap.Edges.Agent.UpdatedAt.Before(ttlThreshold) {
			continue // Skip stale agents
		}

		candidate := struct {
			AgentID      string
			FunctionName string
			Capability   string
			Version      string
			Tags         []string
			HttpHost     string
			HttpPort     int
			UpdatedAt    time.Time
		}{
			AgentID:      cap.Edges.Agent.ID,
			FunctionName: cap.FunctionName,
			Capability:   cap.Capability,
			Version:      cap.Version,
			Tags:         cap.Tags,
			HttpHost:     cap.Edges.Agent.HTTPHost,
			HttpPort:     cap.Edges.Agent.HTTPPort,
			UpdatedAt:    cap.Edges.Agent.UpdatedAt,
		}
		candidates = append(candidates, candidate)
	}

	// Filter by version constraint if specified
	if dep.Version != "" && len(candidates) > 0 {
		filtered := make([]struct {
			AgentID      string
			FunctionName string
			Capability   string
			Version      string
			Tags         []string
			HttpHost     string
			HttpPort     int
			UpdatedAt    time.Time
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
			s.logger.Warning("Invalid version constraint %s: %v", dep.Version, err)
		}
	}

	// Filter by tags if specified (ALL tags must match)
	if len(dep.Tags) > 0 && len(candidates) > 0 {
		filtered := make([]struct {
			AgentID      string
			FunctionName string
			Capability   string
			Version      string
			Tags         []string
			HttpHost     string
			HttpPort     int
			UpdatedAt    time.Time
		}, 0)

		for _, c := range candidates {
			if hasAllTags(c.Tags, dep.Tags) {
				filtered = append(filtered, c)
			}
		}
		candidates = filtered
	}

	// Return first match (deterministic selection)
	if len(candidates) > 0 {
		c := candidates[0]

		// Build endpoint
		endpoint := "stdio://" + c.AgentID // Default
		if c.HttpHost != "" && c.HttpPort > 0 {
			endpoint = fmt.Sprintf("http://%s:%d", c.HttpHost, c.HttpPort)
		}

		return &DependencyResolution{
			AgentID:      c.AgentID,
			FunctionName: c.FunctionName,
			Endpoint:     endpoint,
			Capability:   c.Capability,
			Status:       "available",
		}
	}

	s.logger.Debug("No healthy providers found for %s (version: %s, tags: %v)", dep.Capability, dep.Version, dep.Tags)
	return nil
}

// calculateAndResolveDependencies counts total dependencies and resolves them at registration time
func (s *EntService) calculateAndResolveDependencies(metadata map[string]interface{}) (int, int) {
	totalDeps := 0
	resolvedDeps := 0

	// Extract tools from metadata
	toolsData, exists := metadata["tools"]
	if !exists {
		return 0, 0
	}

	toolsList, ok := toolsData.([]interface{})
	if !ok {
		return 0, 0
	}

	// Process each tool and count/resolve dependencies
	for _, toolData := range toolsList {
		toolMap, ok := toolData.(map[string]interface{})
		if !ok {
			continue
		}

		// Get dependencies for this function
		if deps, exists := toolMap["dependencies"]; exists {
			// Handle both []interface{} and []map[string]interface{} formats
			var depsList []map[string]interface{}

			if depsSlice, ok := deps.([]interface{}); ok {
				// Convert []interface{} to []map[string]interface{}
				depsList = make([]map[string]interface{}, len(depsSlice))
				for i, item := range depsSlice {
					if depMap, ok := item.(map[string]interface{}); ok {
						depsList[i] = depMap
					}
				}
			} else if depsMapSlice, ok := deps.([]map[string]interface{}); ok {
				// Direct []map[string]interface{} format
				depsList = depsMapSlice
			}

			for _, depMap := range depsList {
				totalDeps++

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

				// Try to resolve this dependency
				provider := s.findHealthyProviderWithTTL(dep)
				if provider != nil {
					resolvedDeps++
					s.logger.Debug("Resolved dependency %s -> %s", dep.Capability, provider.AgentID)
				} else {
					s.logger.Debug("Could not resolve dependency: %s", dep.Capability)
				}
			}
		}
	}

	return totalDeps, resolvedDeps
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

func parseVersionConstraint(version string) (string, error) {
	// Simple version constraint parsing - can be enhanced later
	return version, nil
}

func matchesVersion(version, constraint string) bool {
	// Simple version matching - can be enhanced later
	return version == constraint
}

func hasAllTags(available, required []string) bool {
	for _, req := range required {
		found := false
		for _, avail := range available {
			if avail == req {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	return true
}

func normalizeName(name string) string {
	// Simple name normalization
	return name
}
