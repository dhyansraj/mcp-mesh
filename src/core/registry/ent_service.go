package registry

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/Masterminds/semver/v3"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry/generated"
)

// Dependency represents a tool dependency with constraints
// Replaces the old database.Dependency from GORM models
type Dependency struct {
	Capability string   `json:"capability"`
	Version    string   `json:"version,omitempty"` // e.g., ">=1.0.0"
	Tags       []string `json:"tags,omitempty"`    // e.g., ["production", "US_EAST"]
}

// RegistryConfig holds registry-specific configuration
type RegistryConfig struct {
	CacheTTL                 int
	DefaultTimeoutThreshold  int
	DefaultEvictionThreshold int
	HealthCheckInterval      int
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
			SetStatus(agent.StatusHealthy).
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
		isNewAgent := false
		if err != nil {
			if ent.IsNotFound(err) {
				// Create new agent
				existingAgent, err = agentCreate.Save(ctx)
				if err != nil {
					return fmt.Errorf("failed to create agent: %w", err)
				}
				isNewAgent = true
			} else {
				return fmt.Errorf("failed to check existing agent: %w", err)
			}
		} else {
			// Update existing agent
			updateBuilder := existingAgent.Update().
				SetAgentType(agent.AgentType(agentType)).
				SetName(name).
				SetNamespace(namespace).
				SetStatus(agent.StatusHealthy).
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
							} else if stringSlice, ok := tagsInterface.([]string); ok {
								// Handle direct []string case
								tags = stringSlice
							}
						}

						if functionName != "" && capabilityName != "" {
							capCreate := tx.Capability.Create().
								SetAgentID(req.AgentID).
								SetFunctionName(functionName).
								SetCapability(capabilityName).
								SetVersion(capVersion).
								SetNillableDescription(&description).
								SetTags(tags)

							// Add kwargs if present
							if kwargsInterface, ok := toolMap["kwargs"]; ok {
								if kwargs, ok := kwargsInterface.(map[string]interface{}); ok {
									capCreate = capCreate.SetKwargs(kwargs)
								}
							}

							_, err := capCreate.Save(ctx)
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

		// Create registry event only for new agents
		if isNewAgent {
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
		}

		return nil
	})

	if err != nil {
		return nil, fmt.Errorf("failed to register agent: %w", err)
	}

	// Now that capabilities are saved, resolve dependencies for both response AND database counts
	dependenciesResolved, err := s.ResolveAllDependenciesFromMetadata(req.Metadata)
	if err != nil {
		s.logger.Warning("Failed to resolve dependencies for response: %v", err)
		dependenciesResolved = make(map[string][]*DependencyResolution)
	}

	// Calculate totals from the resolution map (single source of truth)
	totalDeps := countTotalDependenciesInMetadata(req.Metadata)
	resolvedDeps := 0
	for _, deps := range dependenciesResolved {
		resolvedDeps += len(deps)
	}

	s.logger.Info("Agent %s: %d total dependencies, %d resolved", req.AgentID, totalDeps, resolvedDeps)

	// Update dependency counts in agent record (outside transaction)
	ctx = context.Background()
	_, err = s.entDB.Agent.UpdateOneID(req.AgentID).
		SetTotalDependencies(totalDeps).
		SetDependenciesResolved(resolvedDeps).
		SetLastFullRefresh(now).
		Save(ctx)
	if err != nil {
		s.logger.Warning("Failed to update dependency counts: %v", err)
		// Don't fail registration over this
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

	// Check for status transitions and handle accordingly
	previousStatus := existingAgent.Status

	// If metadata is provided and contains tools, handle metadata updates directly
	var dependenciesResolved map[string][]*DependencyResolution
	if req.Metadata != nil {
		if _, hasTools := req.Metadata["tools"]; hasTools {
			// Update agent metadata and capabilities within transaction
			err := s.entDB.Transaction(ctx, func(tx *ent.Tx) error {
				// Extract agent metadata for updates
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

				// Update existing agent metadata and status using transaction client
				updateBuilder := tx.Agent.UpdateOneID(existingAgent.ID).
					SetAgentType(agent.AgentType(agentType)).
					SetName(name).
					SetNamespace(namespace).
					SetStatus(agent.StatusHealthy).
					SetUpdatedAt(now).
					SetLastFullRefresh(now)

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

				// Process tools/capabilities
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
									} else if stringSlice, ok := tagsInterface.([]string); ok {
										tags = stringSlice
									}
								}

								if functionName != "" && capabilityName != "" {
									capCreate := tx.Capability.Create().
										SetAgentID(req.AgentID).
										SetFunctionName(functionName).
										SetCapability(capabilityName).
										SetVersion(capVersion).
										SetNillableDescription(&description).
										SetTags(tags)

									// Add kwargs if present
									if kwargsInterface, ok := toolMap["kwargs"]; ok {
										if kwargs, ok := kwargsInterface.(map[string]interface{}); ok {
											capCreate = capCreate.SetKwargs(kwargs)
										}
									}

									_, err := capCreate.Save(ctx)
									if err != nil {
										return fmt.Errorf("failed to create capability %s: %w", functionName, err)
									}
								}
							}
						}
					}
				}

				return nil
			})

			if err != nil {
				return &HeartbeatResponse{
					Status:    "error",
					Timestamp: now.Format(time.RFC3339),
					Message:   err.Error(),
				}, nil
			}

			// Resolve dependencies after transaction commits
			dependenciesResolved, err = s.ResolveAllDependenciesFromMetadata(req.Metadata)
			if err != nil {
				s.logger.Warning("Failed to resolve dependencies for response: %v", err)
				dependenciesResolved = make(map[string][]*DependencyResolution)
			}

			// Calculate dependency counts and update agent record
			totalDeps := countTotalDependenciesInMetadata(req.Metadata)
			resolvedDeps := 0
			for _, deps := range dependenciesResolved {
				resolvedDeps += len(deps)
			}

			_, err = s.entDB.Agent.UpdateOneID(req.AgentID).
				SetTotalDependencies(totalDeps).
				SetDependenciesResolved(resolvedDeps).
				Save(ctx)
			if err != nil {
				s.logger.Warning("Failed to update dependency counts: %v", err)
			}

			// Only create register event if agent was unhealthy and is now recovering
			if previousStatus == agent.StatusUnhealthy {
				eventData := map[string]interface{}{
					"reason": "recovery",
					"previous_status": previousStatus.String(),
					"new_status": "healthy",
				}
				_, err = s.entDB.RegistryEvent.Create().
					SetEventType(registryevent.EventTypeRegister).
					SetAgentID(req.AgentID).
					SetTimestamp(now).
					SetData(eventData).
					Save(ctx)
				if err != nil {
					s.logger.Warning("Failed to create recovery register event: %v", err)
				} else {
					s.logger.Info("Agent %s recovered from unhealthy status", req.AgentID)
				}
			}

			return &HeartbeatResponse{
				Status:               "success",
				Timestamp:            now.Format(time.RFC3339),
				Message:              "Agent updated via heartbeat",
				AgentID:              req.AgentID,
				DependenciesResolved: dependenciesResolved,
			}, nil
		}
	}

	// Simple heartbeat update - update timestamps
	_, err = existingAgent.Update().
		SetUpdatedAt(now).
		SetLastFullRefresh(now).
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

	// Apply capability filtering after query (in-memory filtering)
	if params != nil && len(params.Capabilities) > 0 {
		var filteredAgents []*ent.Agent
		for _, a := range agents {
			agentMatches := false
			for _, requestedCap := range params.Capabilities {
				for _, agentCap := range a.Edges.Capabilities {
					if params.FuzzyMatch {
						// Fuzzy matching: check if requested capability is contained in agent capability
						if strings.Contains(strings.ToLower(agentCap.Capability), strings.ToLower(requestedCap)) {
							agentMatches = true
							break
						}
					} else {
						// Exact matching
						if agentCap.Capability == requestedCap {
							agentMatches = true
							break
						}
					}
				}
				if agentMatches {
					break
				}
			}
			if agentMatches {
				filteredAgents = append(filteredAgents, a)
			}
		}
		agents = filteredAgents
	}

	// Convert to response format
	var agentInfos []generated.AgentInfo
	for _, a := range agents {
		// Build endpoint
		endpoint := fmt.Sprintf("stdio://%s", a.ID) // Default to stdio
		if a.HTTPHost != "" && a.HTTPPort > 0 {
			endpoint = fmt.Sprintf("http://%s:%d", a.HTTPHost, a.HTTPPort)
		}

		// Use stored status column instead of calculating
		// This provides consistency with health monitor and prevents mismatches
		status := string(a.Status)

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
				Tags:         &cap.Tags,
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
		Timestamp: time.Now().UTC(),
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
					dep := Dependency{
						Capability: requiredCapability,
					}

					if version, exists := depMap["version"]; exists {
						if vStr, ok := version.(string); ok {
							dep.Version = vStr
						}
					}

					if tags, exists := depMap["tags"]; exists {
						s.logger.Debug("Found tags in dependency: %T = %v", tags, tags)
						if tagsList, ok := tags.([]interface{}); ok {
							dep.Tags = make([]string, len(tagsList))
							for i, tag := range tagsList {
								if tagStr, ok := tag.(string); ok {
									dep.Tags[i] = tagStr
								}
							}
							s.logger.Info("Parsed dependency tags: %v", dep.Tags)
						} else if stringSlice, ok := tags.([]string); ok {
							// Handle direct []string case
							dep.Tags = stringSlice
							s.logger.Debug("Direct string slice tags: %v", dep.Tags)
						} else {
							s.logger.Info("Tags not []interface{} or []string, type is: %T", tags)
						}
					} else {
						s.logger.Info("No tags field found in dependency")
					}

					// Find provider with TTL and strict matching using Ent
					s.logger.Debug("About to call findHealthyProviderWithTTL for %s with tags %v", dep.Capability, dep.Tags)
					provider := s.findHealthyProviderWithTTL(dep)
					if provider != nil {
						s.logger.Info("Found provider for %s: %+v", dep.Capability, provider)
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
			"kwargs":        cap.Kwargs,
		}
	}
	result["capabilities"] = capabilities

	return result, nil
}

// findHealthyProviderWithTTL finds a healthy provider using TTL check and strict matching using Ent queries
func (s *EntService) findHealthyProviderWithTTL(dep Dependency) *DependencyResolution {
	ctx := context.Background()

	// Use Info level to ensure it gets logged
	s.logger.Debug("Looking for provider for capability: %s, version: %s, tags: %v", dep.Capability, dep.Version, dep.Tags)

	// Calculate TTL threshold
	// Health status checking is now handled by the health monitor
	// No need for TTL threshold calculations here

	// Query capabilities with healthy agents using Ent with retry logic for database locks
	var capabilities []*ent.Capability
	var err error
	maxRetries := 3
	for attempt := 0; attempt < maxRetries; attempt++ {
		capabilities, err = s.entDB.Capability.Query().
			Where(capability.CapabilityEQ(dep.Capability)).
			WithAgent().
			All(ctx)

		if err == nil {
			break // Success
		}

		// Check if it's a database lock error
		if strings.Contains(err.Error(), "database is locked") || strings.Contains(err.Error(), "SQLITE_BUSY") {
			s.logger.Warning("Database lock detected on attempt %d for capability %s, retrying...", attempt+1, dep.Capability)
			time.Sleep(time.Duration(50*(attempt+1)) * time.Millisecond) // Exponential backoff
			continue
		}

		// Non-lock error, don't retry
		break
	}

	if err != nil {
		s.logger.Error("Error finding healthy providers for %s after %d attempts: %v", dep.Capability, maxRetries, err)
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

		// Check agent health status - only return healthy agents as available
		// Health monitor is responsible for marking agents unhealthy based on timestamps
		if cap.Edges.Agent.Status != agent.StatusHealthy {
			s.logger.Debug("Skipping unhealthy agent %s: Status=%v",
				cap.Edges.Agent.ID, cap.Edges.Agent.Status)
			continue // Skip unhealthy agents
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
		s.logger.Info("Found candidate for %s: AgentID=%s, Version=%s, Tags=%v",
			dep.Capability, candidate.AgentID, candidate.Version, candidate.Tags)
	}

	s.logger.Debug("Total candidates found for %s: %d", dep.Capability, len(candidates))

	// Filter by version constraint if specified
	if dep.Version != "" && len(candidates) > 0 {
		s.logger.Info("Filtering candidates by version constraint: %s", dep.Version)
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
			if matchesVersion(c.Version, dep.Version) {
				filtered = append(filtered, c)
			}
		}
		candidates = filtered
		s.logger.Info("After version filtering: %d candidates remain", len(candidates))
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

// Helper functions

func getStringFromMap(m map[string]interface{}, key, defaultValue string) string {
	if value, exists := m[key]; exists {
		if str, ok := value.(string); ok {
			return str
		}
	}
	return defaultValue
}

func parseVersionConstraint(version string) (*semver.Constraints, error) {
	if version == "" {
		return nil, nil
	}
	return semver.NewConstraint(version)
}

func matchesVersion(version, constraint string) bool {
	// Handle empty cases
	if constraint == "" || version == "" {
		return version == constraint
	}

	// Parse the version
	v, err := semver.NewVersion(version)
	if err != nil {
		// If version parsing fails, fall back to string comparison
		return version == constraint
	}

	// Parse the constraint
	c, err := semver.NewConstraint(constraint)
	if err != nil {
		// If constraint parsing fails, fall back to string comparison
		return version == constraint
	}

	// Check if version satisfies constraint
	return c.Check(v)
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

// countTotalDependenciesInMetadata counts the total number of dependencies across all tools in metadata
func countTotalDependenciesInMetadata(metadata map[string]interface{}) int {
	totalDeps := 0

	// Extract tools from metadata
	toolsData, exists := metadata["tools"]
	if !exists {
		return 0
	}

	toolsList, ok := toolsData.([]interface{})
	if !ok {
		return 0
	}

	// Process each tool and count dependencies
	for _, toolData := range toolsList {
		toolMap, ok := toolData.(map[string]interface{})
		if !ok {
			continue
		}

		// Get dependencies for this function
		if deps, exists := toolMap["dependencies"]; exists {
			// Handle both []interface{} and []map[string]interface{} formats
			if depsSlice, ok := deps.([]interface{}); ok {
				totalDeps += len(depsSlice)
			} else if depsMapSlice, ok := deps.([]map[string]interface{}); ok {
				totalDeps += len(depsMapSlice)
			}
		}
	}

	return totalDeps
}

func normalizeName(name string) string {
	// Simple name normalization
	return name
}

// GetAgent retrieves an agent by ID for fast heartbeat check
func (s *EntService) GetAgent(ctx context.Context, agentID string) (*ent.Agent, error) {
	return s.entDB.Client.Agent.
		Query().
		Where(agent.IDEQ(agentID)).
		Only(ctx)
}

// HasTopologyChanges checks if topology has changed since last full refresh
func (s *EntService) HasTopologyChanges(ctx context.Context, agentID string, lastRefresh time.Time) (bool, error) {
	// Count registry events after last refresh that indicate topology changes
	count, err := s.entDB.Client.RegistryEvent.
		Query().
		Where(
			registryevent.TimestampGT(lastRefresh),
			registryevent.EventTypeIn("register", "unregister", "unhealthy"),
		).
		Count(ctx)

	if err != nil {
		return false, fmt.Errorf("failed to check topology changes: %w", err)
	}

	s.logger.Info("Topology changes check for agent %s: found %d events since %v", agentID, count, lastRefresh)
	return count > 0, nil
}

// UnregisterAgent gracefully unregisters an agent by marking it as unhealthy
func (s *EntService) UnregisterAgent(ctx context.Context, agentID string) error {
	// Start a transaction for atomic operation
	tx, err := s.entDB.Client.Tx(ctx)
	if err != nil {
		return fmt.Errorf("failed to start transaction: %w", err)
	}
	defer tx.Rollback()

	// Check if agent exists
	currentAgent, err := tx.Agent.Query().Where(agent.IDEQ(agentID)).Only(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			// Agent doesn't exist - idempotent operation, return success
			return nil
		}
		return fmt.Errorf("failed to query agent: %w", err)
	}

	// Update agent status to unhealthy while preserving original UpdatedAt timestamp
	agentUpdated, err := tx.Agent.
		Update().
		Where(agent.IDEQ(agentID)).
		SetStatus(agent.StatusUnhealthy).
		SetUpdatedAt(currentAgent.UpdatedAt). // Preserve original timestamp like health monitor does
		Save(ctx)

	if err != nil {
		return fmt.Errorf("failed to update agent %s status to unhealthy: %w", agentID, err)
	}

	if agentUpdated == 0 {
		// Agent doesn't exist, no need to create event
		return nil
	}

	// Create unregister event (similar to health monitor creating unhealthy events)
	eventData := map[string]interface{}{
		"reason":      "graceful_shutdown",
		"detected_at": time.Now().UTC().Format(time.RFC3339),
	}

	_, err = tx.RegistryEvent.Create().
		SetEventType("unregister").
		SetAgentID(agentID).
		SetTimestamp(time.Now().UTC()).
		SetData(eventData).
		Save(ctx)

	if err != nil {
		return fmt.Errorf("failed to create unregister event: %w", err)
	}

	// Commit transaction
	err = tx.Commit()
	if err != nil {
		return fmt.Errorf("failed to commit transaction: %w", err)
	}

	s.logger.Info("Marked agent %s as unhealthy and created unregister event (graceful shutdown)", agentID)
	return nil
}

// UpdateAgentHeartbeatTimestamp updates only the agent's timestamp for HEAD heartbeat requests
func (s *EntService) UpdateAgentHeartbeatTimestamp(ctx context.Context, agentID string) error {
	now := time.Now().UTC()

	// Find the existing agent
	existingAgent, err := s.entDB.Agent.Query().Where(agent.IDEQ(agentID)).Only(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			// Agent doesn't exist - return without error (idempotent behavior)
			return nil
		}
		return fmt.Errorf("failed to query agent: %w", err)
	}

	// Update timestamp and reset to healthy if agent was previously unhealthy
	// If agent can send HEAD requests, it's clearly responsive and should be marked healthy
	updateBuilder := existingAgent.Update().SetUpdatedAt(now)

	if existingAgent.Status == agent.StatusUnhealthy {
		s.logger.Info("Agent %s recovered: marking healthy (was %v)", agentID, existingAgent.Status)
		updateBuilder = updateBuilder.SetStatus(agent.StatusHealthy)

		// Create recovery event for audit trail
		eventData := map[string]interface{}{
			"reason":          "head_request_recovery",
			"detected_at":     now.Format(time.RFC3339),
			"previous_status": "unhealthy",
			"new_status":      "healthy",
		}

		_, err := s.entDB.RegistryEvent.Create().
			SetEventType("register").
			SetAgentID(agentID).
			SetTimestamp(now).
			SetData(eventData).
			Save(ctx)
		if err != nil {
			s.logger.Warning("Failed to create recovery event for agent %s: %v", agentID, err)
			// Don't fail the timestamp update due to event creation failure
		}
	}

	_, err = updateBuilder.Save(ctx)
	if err != nil {
		return fmt.Errorf("failed to update agent heartbeat timestamp: %w", err)
	}

	s.logger.Debug("Updated heartbeat timestamp for agent %s", agentID)
	return nil
}
