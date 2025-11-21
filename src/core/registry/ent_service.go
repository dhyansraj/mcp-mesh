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
	"mcp-mesh/src/core/ent/dependencyresolution"
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
	TracingEnabled           bool // Enable distributed tracing
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
	LLMTools             map[string][]LLMToolInfo           `json:"llm_tools,omitempty"`
}

// EntService provides registry operations using Ent ORM instead of raw SQL
type EntService struct {
	entDB       *database.EntDatabase
	config      *RegistryConfig
	cache       *ResponseCache
	validator   *AgentRegistrationValidator
	logger      *logger.Logger
	hookManager *AgentStatusChangeHookManager
}

// NewEntService creates a new Ent-based registry service instance
func NewEntService(entDB *database.EntDatabase, config *RegistryConfig, logger *logger.Logger) *EntService {
	if config == nil {
		config = &RegistryConfig{
			CacheTTL:                 30,
			DefaultTimeoutThreshold:  60,
			DefaultEvictionThreshold: 120,
			HealthCheckInterval:      30, // Health check every 30 seconds
			EnableResponseCache:      true,
		}
	}

	cache := &ResponseCache{
		cache:   make(map[string]CacheEntry),
		ttl:     time.Duration(config.CacheTTL) * time.Second,
		enabled: config.EnableResponseCache,
	}

	// Initialize status change hook manager
	hookManager := NewAgentStatusChangeHookManager(logger, true) // Enable hooks by default

	// Create EntService instance
	service := &EntService{
		entDB:       entDB,
		config:      config,
		cache:       cache,
		validator:   NewAgentRegistrationValidator(),
		logger:      logger,
		hookManager: hookManager,
	}

	// Register status change hooks with the database client
	for _, hook := range hookManager.GetHooks() {
		entDB.Client.Agent.Use(hook)
	}

	logger.Info("Status change hooks registered successfully")

	return service
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

							// Add input_schema if present
							if inputSchemaInterface, ok := toolMap["inputSchema"]; ok {
								if inputSchema, ok := inputSchemaInterface.(map[string]interface{}); ok {
									capCreate = capCreate.SetInputSchema(inputSchema)
								}
							}

							// Add llm_filter if present
							if llmFilterInterface, ok := toolMap["llm_filter"]; ok {
								if llmFilter, ok := llmFilterInterface.(map[string]interface{}); ok {
									capCreate = capCreate.SetLlmFilter(llmFilter)
								}
							}

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

		// Create registry event only for new agents (skip for API services)
		if isNewAgent && agentType != "api" {
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

	// Store dependency resolutions in database
	err = s.StoreDependencyResolutions(ctx, req.AgentID, req.Metadata, dependenciesResolved)
	if err != nil {
		s.logger.Warning("Failed to store dependency resolutions: %v", err)
		// Don't fail registration over this
	}

	return &AgentRegistrationResponse{
		Status:               "success",
		Message:              "Agent registered successfully",
		AgentID:              req.AgentID,
		Timestamp:            now.Format(time.RFC3339),
		DependenciesResolved: dependenciesResolved,
	}, nil
}

// StoreDependencyResolutions persists dependency resolution information to the database
func (s *EntService) StoreDependencyResolutions(
	ctx context.Context,
	agentID string,
	metadata map[string]interface{},
	dependenciesResolved map[string][]*DependencyResolution,
) error {
	s.logger.Info("StoreDependencyResolutions called for agent %s", agentID)

	// Extract tools from metadata to get requested dependencies
	toolsData, exists := metadata["tools"]
	if !exists {
		s.logger.Info("StoreDependencyResolutions: No tools in metadata for agent %s", agentID)
		return nil // No tools means no dependencies
	}

	toolsList, ok := toolsData.([]interface{})
	if !ok {
		return fmt.Errorf("tools is not an array")
	}

	s.logger.Info("StoreDependencyResolutions: Found %d tools for agent %s", len(toolsList), agentID)
	s.logger.Info("StoreDependencyResolutions: dependenciesResolved map has %d entries", len(dependenciesResolved))

	// Delete existing dependency resolutions for this agent
	_, err := s.entDB.DependencyResolution.Delete().
		Where(dependencyresolution.ConsumerAgentIDEQ(agentID)).
		Exec(ctx)
	if err != nil {
		return fmt.Errorf("failed to delete old dependency resolutions: %w", err)
	}

	// Process each tool and store its dependency resolutions
	for _, toolData := range toolsList {
		toolMap, ok := toolData.(map[string]interface{})
		if !ok {
			continue
		}

		functionName, ok := toolMap["function_name"].(string)
		if !ok {
			continue
		}

		// Get requested dependencies for this function
		deps, exists := toolMap["dependencies"]
		if !exists {
			continue // Tool has no dependencies
		}

		// Handle both []interface{} and []map[string]interface{} types
		var depsSlice []interface{}
		switch v := deps.(type) {
		case []interface{}:
			depsSlice = v
		case []map[string]interface{}:
			// Convert []map[string]interface{} to []interface{}
			depsSlice = make([]interface{}, len(v))
			for i, m := range v {
				depsSlice[i] = m
			}
		default:
			s.logger.Warning("  Tool %s dependencies has unexpected type: %T", functionName, deps)
			continue
		}

		if len(depsSlice) == 0 {
			continue // No dependencies
		}

		// Get resolved dependencies for this function
		resolved, hasResolved := dependenciesResolved[functionName]

		// Process each requested dependency
		for _, depData := range depsSlice {
			depMap, ok := depData.(map[string]interface{})
			if !ok {
				continue
			}

			capability := getString(depMap, "capability")
			if capability == "" {
				continue
			}

			tags := getStringSlice(depMap, "tags")
			version := getString(depMap, "version")
			namespace := getString(depMap, "namespace")
			if namespace == "" {
				namespace = "default"
			}

			// Find matching resolved dependency (if any)
			var matchedResolution *DependencyResolution
			if hasResolved {
				for _, res := range resolved {
					if res.Capability == capability {
						matchedResolution = res
						break
					}
				}
			}

			// Create dependency resolution record
			create := s.entDB.DependencyResolution.Create().
				SetConsumerAgentID(agentID).
				SetConsumerFunctionName(functionName).
				SetCapabilityRequired(capability).
				SetNamespaceRequired(namespace)

			if len(tags) > 0 {
				create = create.SetTagsRequired(tags)
			}
			if version != "" {
				create = create.SetVersionRequired(version)
			}

			if matchedResolution != nil {
				// Dependency was resolved
				create = create.
					SetNillableProviderAgentID(&matchedResolution.AgentID).
					SetNillableProviderFunctionName(&matchedResolution.FunctionName).
					SetNillableEndpoint(&matchedResolution.Endpoint).
					SetStatus(dependencyresolution.StatusAvailable).
					SetResolvedAt(time.Now().UTC())
			} else {
				// Dependency is unresolved
				create = create.SetStatus(dependencyresolution.StatusUnresolved)
			}

			savedResolution, err := create.Save(ctx)
			if err != nil {
				s.logger.Warning("Failed to save dependency resolution for %s/%s: %v",
					agentID, functionName, err)
				// Continue processing other dependencies
			} else {
				s.logger.Info("Saved dependency resolution: %s/%s -> %s (status: %s)",
					agentID, functionName, capability, savedResolution.Status)
			}
		}
	}

	s.logger.Info("StoreDependencyResolutions completed for agent %s", agentID)
	return nil
}

// UpdateDependencyStatusOnAgentOffline marks all dependencies provided by an agent as unavailable
func (s *EntService) UpdateDependencyStatusOnAgentOffline(ctx context.Context, agentID string) error {
	_, err := s.entDB.DependencyResolution.Update().
		Where(dependencyresolution.ProviderAgentIDEQ(agentID)).
		SetStatus(dependencyresolution.StatusUnavailable).
		ClearResolvedAt().
		Save(ctx)

	if err != nil {
		return fmt.Errorf("failed to update dependency status: %w", err)
	}

	s.logger.Info("Updated dependency status for offline agent %s", agentID)
	return nil
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
						Timestamp:    now.Format(time.RFC3339),
						Message:   err.Error(),
					}, nil
				}

				// Resolve LLM tools for newly registered agent
				llmTools, err := s.ResolveLLMToolsFromMetadata(ctx, req.AgentID, req.Metadata)
				if err != nil {
					llmTools = make(map[string][]LLMToolInfo)
				}

				return &HeartbeatResponse{
					Status:               regResp.Status,
					Timestamp:            now.Format(time.RFC3339),
					Message:              "Agent registered via heartbeat",
					AgentID:              regResp.AgentID,
					DependenciesResolved: regResp.DependenciesResolved,
					LLMTools:             llmTools,
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
		_, hasTools := req.Metadata["tools"]
		if hasTools {
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

									// Add input_schema if present
									if inputSchemaInterface, ok := toolMap["inputSchema"]; ok {
										if inputSchema, ok := inputSchemaInterface.(map[string]interface{}); ok {
											capCreate = capCreate.SetInputSchema(inputSchema)
										}
									}

									// Add llm_filter if present
									if llmFilterInterface, ok := toolMap["llm_filter"]; ok {
										if llmFilter, ok := llmFilterInterface.(map[string]interface{}); ok {
											capCreate = capCreate.SetLlmFilter(llmFilter)
										}
									}

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

			// Store dependency resolutions in database
			err = s.StoreDependencyResolutions(ctx, req.AgentID, req.Metadata, dependenciesResolved)
			if err != nil {
				s.logger.Warning("Failed to store dependency resolutions: %v", err)
				// Don't fail heartbeat over this
			}

			// Status change recovery events are now handled automatically by hooks
			if previousStatus == agent.StatusUnhealthy {
				if existingAgent.AgentType.String() == "api" {
					s.logger.Info("Agent %s recovered from unhealthy status - no event created (API service)", req.AgentID)
				} else {
					s.logger.Info("Agent %s recovered from unhealthy status - event created by hook", req.AgentID)
				}
			}

			// Resolve LLM tools for functions with llm_filter
			llmTools, err := s.ResolveLLMToolsFromMetadata(ctx, req.AgentID, req.Metadata)
			if err != nil {
				llmTools = make(map[string][]LLMToolInfo)
			}

			return &HeartbeatResponse{
				Status:               "success",
				Timestamp:            now.Format(time.RFC3339),
				Message:              "Agent updated via heartbeat",
				AgentID:              req.AgentID,
				DependenciesResolved: dependenciesResolved,
				LLMTools:             llmTools,
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

	// Execute query with capabilities and dependency resolutions
	agents, err := query.WithCapabilities().WithDependencyResolutions().All(ctx)
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
			Id:        a.ID,
			Name:      a.Name,
			AgentType: generated.AgentInfoAgentType(a.AgentType),
			Version:   &a.Version,
			Status:    generated.AgentInfoStatus(status),
			Endpoint:  endpoint,
			LastSeen:  &a.UpdatedAt,
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

		// Add dependency resolutions
		var depResolutions []generated.DependencyResolutionInfo
		for _, depRes := range a.Edges.DependencyResolutions {
			depInfo := generated.DependencyResolutionInfo{
				FunctionName: depRes.ConsumerFunctionName,
				Capability:   depRes.CapabilityRequired,
				Status:       generated.DependencyResolutionInfoStatus(depRes.Status),
			}

			// Add tags if present
			if depRes.TagsRequired != nil {
				depInfo.Tags = &depRes.TagsRequired
			}

			// Add resolved provider information (if available)
			if depRes.ProviderAgentID != nil {
				depInfo.ProviderAgentId = depRes.ProviderAgentID
			}
			if depRes.ProviderFunctionName != nil {
				depInfo.McpTool = depRes.ProviderFunctionName
			}
			if depRes.Endpoint != nil {
				depInfo.Endpoint = depRes.Endpoint
			}

			depResolutions = append(depResolutions, depInfo)
		}
		agentInfo.DependencyResolutions = &depResolutions

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

// ResolveLLMToolsFromMetadata resolves LLM tools for functions with llm_filter
func (s *EntService) ResolveLLMToolsFromMetadata(ctx context.Context, agentID string, metadata map[string]interface{}) (map[string][]LLMToolInfo, error) {
	llmTools := make(map[string][]LLMToolInfo)

	// Extract tools from metadata
	toolsData, exists := metadata["tools"]
	if !exists {
		s.logger.Debug("No tools in metadata for agent %s", agentID)
		return llmTools, nil
	}
	s.logger.Info("ResolveLLMTools: agent=%s has tools in metadata", agentID)

	toolsList, ok := toolsData.([]interface{})
	if !ok {
		return llmTools, nil
	}

	// Process each tool and check for llm_filter
	for _, toolData := range toolsList {
		toolMap, ok := toolData.(map[string]interface{})
		if !ok {
			continue
		}

		functionName := getStringFromMap(toolMap, "function_name", "")
		if functionName == "" {
			continue
		}
		s.logger.Info("ResolveLLMTools: checking function '%s' for llm_filter", functionName)

		// Check if tool has llm_filter
		llmFilterData, exists := toolMap["llm_filter"]
		if !exists {
			s.logger.Info("ResolveLLMTools: function '%s' has NO llm_filter", functionName)
			continue
		}
		s.logger.Info("ResolveLLMTools: function '%s' HAS llm_filter!", functionName)

		llmFilterMap, ok := llmFilterData.(map[string]interface{})
		if !ok {
			continue
		}

		// Extract filter array
		filterData, exists := llmFilterMap["filter"]
		if !exists {
			s.logger.Warning("No filter array in llm_filter for %s", functionName)
			continue
		}

		filterArray, ok := filterData.([]interface{})
		if !ok {
			s.logger.Warning("filter is not an array for %s: %T", functionName, filterData)
			continue
		}
		s.logger.Info("Filter array for %s: %+v", functionName, filterArray)

		// Extract filter_mode (default to "all")
		filterMode := "all"
		if filterModeData, exists := llmFilterMap["filter_mode"]; exists {
			if fm, ok := filterModeData.(string); ok {
				filterMode = fm
			}
		}
		s.logger.Info("Filter mode for %s: %s", functionName, filterMode)

		// Call FilterToolsForLLM to get filtered tools (excluding this agent's own tools)
		filteredTools, err := FilterToolsForLLM(ctx, s.entDB.Client, filterArray, filterMode, agentID)
		if err != nil {
			continue
		}

		// Add to result map
		// IMPORTANT: Always add function key, even if filteredTools is empty.
		// This supports standalone LLM agents that don't need tools (filter=None case).
		// The Python client needs to receive {"function_name": []} to create
		// a MeshLlmAgent with empty tools (answers using only model + system prompt).
		llmTools[functionName] = filteredTools
	}

	return llmTools, nil
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

	// Filter by tags using enhanced tag matching with priority scoring
	if len(dep.Tags) > 0 && len(candidates) > 0 {
		type candidateWithScore struct {
			AgentID      string
			FunctionName string
			Capability   string
			Version      string
			Tags         []string
			HttpHost     string
			HttpPort     int
			UpdatedAt    time.Time
			Score        int // Priority score from enhanced tag matching
		}

		scoredCandidates := make([]candidateWithScore, 0)

		for _, c := range candidates {
			matches, score := matchesEnhancedTags(c.Tags, dep.Tags)
			if matches {
				scoredCandidates = append(scoredCandidates, candidateWithScore{
					AgentID:      c.AgentID,
					FunctionName: c.FunctionName,
					Capability:   c.Capability,
					Version:      c.Version,
					Tags:         c.Tags,
					HttpHost:     c.HttpHost,
					HttpPort:     c.HttpPort,
					UpdatedAt:    c.UpdatedAt,
					Score:        score,
				})
			}
		}

		// Sort by score descending (highest score = best match first)
		for i := 0; i < len(scoredCandidates); i++ {
			for j := i + 1; j < len(scoredCandidates); j++ {
				if scoredCandidates[j].Score > scoredCandidates[i].Score {
					scoredCandidates[i], scoredCandidates[j] = scoredCandidates[j], scoredCandidates[i]
				}
			}
		}

		// Convert back to original candidate format
		candidates = make([]struct {
			AgentID      string
			FunctionName string
			Capability   string
			Version      string
			Tags         []string
			HttpHost     string
			HttpPort     int
			UpdatedAt    time.Time
		}, len(scoredCandidates))

		for i, sc := range scoredCandidates {
			candidates[i] = struct {
				AgentID      string
				FunctionName string
				Capability   string
				Version      string
				Tags         []string
				HttpHost     string
				HttpPort     int
				UpdatedAt    time.Time
			}{
				AgentID:      sc.AgentID,
				FunctionName: sc.FunctionName,
				Capability:   sc.Capability,
				Version:      sc.Version,
				Tags:         sc.Tags,
				HttpHost:     sc.HttpHost,
				HttpPort:     sc.HttpPort,
				UpdatedAt:    sc.UpdatedAt,
			}
		}
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

// matchesEnhancedTags implements enhanced tag matching with +/- operators
// Returns (matches, score) where:
// - matches: true if the provider satisfies all constraints
// - score: numeric score for ranking providers (higher = better match)
//
// Tag prefixes:
// - No prefix: Required tag (must be present)
// - "+": Preferred tag (bonus points if present, no penalty if missing)
// - "-": Excluded tag (must NOT be present, fails if found)
//
// Examples:
// - "claude" = required
// - "+opus" = preferred (bonus if present)
// - "-experimental" = excluded (fail if present)
func matchesEnhancedTags(providerTags, requiredTags []string) (bool, int) {
	score := 0

	// Handle empty cases
	if len(requiredTags) == 0 {
		return true, 0 // No constraints = always match with zero score
	}

	// Helper function to check if a tag exists in provider tags
	containsTag := func(tags []string, tag string) bool {
		for _, t := range tags {
			if t == tag {
				return true
			}
		}
		return false
	}

	// Process each required tag constraint
	for _, reqTag := range requiredTags {
		if len(reqTag) == 0 {
			continue // Skip empty tags
		}

		switch reqTag[0] {
		case '-':
			// Excluded tag: must NOT be present
			excludedTag := reqTag[1:]
			if excludedTag != "" && containsTag(providerTags, excludedTag) {
				return false, 0 // Hard failure if excluded tag is present
			}
			// No score change for excluded tags (they don't add value, just filter)

		case '+':
			// Preferred tag: bonus points if present, no penalty if missing
			preferredTag := reqTag[1:]
			if preferredTag != "" && containsTag(providerTags, preferredTag) {
				score += 10 // Bonus points for preferred tags
			}
			// No penalty if preferred tag is missing

		default:
			// Required tag: must be present
			if containsTag(providerTags, reqTag) {
				score += 5 // Base points for required tags
			} else {
				return false, 0 // Hard failure if required tag is missing
			}
		}
	}

	return true, score
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

	// Create explicit unregister event before updating status (skip for API services)
	now := time.Now().UTC()
	if currentAgent.AgentType.String() != "api" {
		eventData := map[string]interface{}{
			"agent_type": currentAgent.AgentType.String(),
			"name":       currentAgent.Name,
			"version":    currentAgent.Version,
			"reason":     "graceful_shutdown",
			"source":     "delete_endpoint",
		}

		_, err = tx.RegistryEvent.Create().
			SetEventType(registryevent.EventTypeUnregister).
			SetAgentID(agentID).
			SetTimestamp(now).
			SetData(eventData).
			Save(ctx)
		if err != nil {
			s.logger.Warning("Failed to create unregister event: %v", err)
			// Don't fail the unregistration over event creation
		}
	}

	// Update agent status to unhealthy and update timestamp (like RegisterAgent does)
	agentUpdated, err := tx.Agent.
		Update().
		Where(agent.IDEQ(agentID)).
		SetStatus(agent.StatusUnhealthy).
		SetUpdatedAt(now). // Update timestamp like RegisterAgent does
		Save(ctx)

	if err != nil {
		return fmt.Errorf("failed to update agent %s status to unhealthy: %w", agentID, err)
	}

	if agentUpdated == 0 {
		// Agent doesn't exist, no need to create event
		return nil
	}

	// Commit transaction
	err = tx.Commit()
	if err != nil {
		return fmt.Errorf("failed to commit transaction: %w", err)
	}

	s.logger.Info("Created unregister event and marked agent %s as unhealthy (graceful shutdown)", agentID)
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

		// Recovery event will be created automatically by status change hook
	}

	_, err = updateBuilder.Save(ctx)
	if err != nil {
		return fmt.Errorf("failed to update agent heartbeat timestamp: %w", err)
	}

	s.logger.Debug("Updated heartbeat timestamp for agent %s", agentID)
	return nil
}

// Hook Management Methods

// EnableStatusChangeHooks enables the status change hooks
func (s *EntService) EnableStatusChangeHooks() {
	if s.hookManager != nil {
		s.hookManager.Enable()
	}
}

// DisableStatusChangeHooks disables the status change hooks
func (s *EntService) DisableStatusChangeHooks() {
	if s.hookManager != nil {
		s.hookManager.Disable()
	}
}

// IsStatusChangeHooksEnabled returns whether status change hooks are enabled
func (s *EntService) IsStatusChangeHooksEnabled() bool {
	if s.hookManager != nil {
		return s.hookManager.IsEnabled()
	}
	return false
}

// Helper functions for extracting data from maps

// getString safely extracts a string from a map
func getString(data map[string]interface{}, key string) string {
	if val, ok := data[key]; ok {
		if str, ok := val.(string); ok {
			return str
		}
	}
	return ""
}

// getStringSlice safely extracts a string slice from a map
func getStringSlice(data map[string]interface{}, key string) []string {
	if val, ok := data[key]; ok {
		switch v := val.(type) {
		case []string:
			return v
		case []interface{}:
			result := make([]string, 0, len(v))
			for _, item := range v {
				if str, ok := item.(string); ok {
					result = append(result, str)
				}
			}
			return result
		}
	}
	return []string{}
}
