package registry

import (
	"context"
	"fmt"
	"time"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
)

// ResolveAllDependenciesIndexed resolves all dependencies and returns full IndexedResolution data.
// This is the single source of truth for dependency resolution - includes spec, position, and resolution.
// Use this for database storage. Use ResolveAllDependenciesFromMetadata for API responses.
func (s *EntService) ResolveAllDependenciesIndexed(metadata map[string]interface{}) []IndexedResolution {
	var allResolutions []IndexedResolution

	// Extract tools from metadata
	toolsData, exists := metadata["tools"]
	if !exists {
		return allResolutions
	}

	toolsList, ok := toolsData.([]interface{})
	if !ok {
		return allResolutions
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

		if deps, exists := toolMap["dependencies"]; exists {
			// Handle []interface{} - each item can be:
			// - map[string]interface{} : single spec
			// - []interface{} : OR alternatives (array of specs)
			if depsSlice, ok := deps.([]interface{}); ok {
				for depIndex, depData := range depsSlice {
					result := s.resolveAtPosition(depIndex, depData)
					result.FunctionName = functionName
					allResolutions = append(allResolutions, result)
				}
			} else if depsMapSlice, ok := deps.([]map[string]interface{}); ok {
				// Handle direct []map[string]interface{} (backward compatibility)
				for depIndex, depMap := range depsMapSlice {
					result := s.resolveAtPosition(depIndex, depMap)
					result.FunctionName = functionName
					allResolutions = append(allResolutions, result)
				}
			}
		}
	}

	return allResolutions
}

// ResolveAllDependenciesFromMetadata resolves dependencies and returns map for API responses.
// Internally uses ResolveAllDependenciesIndexed and extracts just the resolved dependencies.
// Implements strict dependency resolution: ALL dependencies must resolve or function fails
func (s *EntService) ResolveAllDependenciesFromMetadata(metadata map[string]interface{}) (map[string][]*DependencyResolution, error) {
	resolved := make(map[string][]*DependencyResolution)

	// Use the indexed resolver as single source of truth
	allResolutions := s.ResolveAllDependenciesIndexed(metadata)

	// Group by function name and extract only resolved dependencies
	for _, res := range allResolutions {
		if res.Resolution != nil {
			resolved[res.FunctionName] = append(resolved[res.FunctionName], res.Resolution)
		} else {
			// Ensure function exists in map even if no resolutions
			if _, exists := resolved[res.FunctionName]; !exists {
				resolved[res.FunctionName] = []*DependencyResolution{}
			}
			s.logger.Debug("Dependency at position %d unresolved for function %s (capability: %s)",
				res.DepIndex, res.FunctionName, res.Spec.Capability)
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
		return llmTools, nil
	}

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

		// Check if tool has llm_filter
		llmFilterData, exists := toolMap["llm_filter"]
		if !exists {
			continue
		}

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

		// Extract filter_mode (default to "all")
		filterMode := "all"
		if filterModeData, exists := llmFilterMap["filter_mode"]; exists {
			if fm, ok := filterModeData.(string); ok {
				filterMode = fm
			}
		}

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
		if isDatabaseLockError(err) {
			s.logger.Warning("Database lock detected on attempt %d for capability %s, retrying...", attempt+1, dep.Capability)
			time.Sleep(time.Duration(50*(1<<attempt)) * time.Millisecond) // Exponential backoff: 50, 100, 200, 400, 800ms
			continue
		}

		// Non-lock error, don't retry
		break
	}

	if err != nil {
		s.logger.Error("Error finding healthy providers for %s after %d attempts: %v", dep.Capability, maxRetries, err)
		return nil
	}

	// Convert to candidates using the Candidate type (eliminates repeated anonymous structs)
	var candidates []Candidate

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

		candidates = append(candidates, Candidate{
			AgentID:      cap.Edges.Agent.ID,
			FunctionName: cap.FunctionName,
			Capability:   cap.Capability,
			Version:      cap.Version,
			Tags:         cap.Tags,
			HttpHost:     cap.Edges.Agent.HTTPHost,
			HttpPort:     cap.Edges.Agent.HTTPPort,
		})
	}

	s.logger.Debug("Total candidates found for %s: %d", dep.Capability, len(candidates))

	// Filter by version constraint using Matcher
	if dep.Version != "" && len(candidates) > 0 {
		filtered := make([]Candidate, 0)
		for _, c := range candidates {
			if s.matcher.MatchVersion(c.Version, dep.Version) {
				filtered = append(filtered, c)
			}
		}
		candidates = filtered
	}

	// Filter by tags using Matcher with priority scoring
	if (len(dep.Tags) > 0 || len(dep.TagAlternatives) > 0) && len(candidates) > 0 {
		scoredCandidates := make([]ScoredCandidate, 0)

		for _, c := range candidates {
			matches, score := s.matcher.MatchTags(c.Tags, dep.Tags, dep.TagAlternatives)
			if matches {
				scoredCandidates = append(scoredCandidates, ScoredCandidate{
					Candidate: c,
					Score:     score,
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

		// Extract candidates from scored list
		candidates = make([]Candidate, len(scoredCandidates))
		for i, sc := range scoredCandidates {
			candidates[i] = sc.Candidate
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

// resolveSingle is the SINGLE SOURCE OF TRUTH for all dependency matching logic.
// It takes a DependencySpec and returns a resolved dependency or nil if not found.
// All resolution logic (capability + version + tags) happens here.
func (s *EntService) resolveSingle(spec DependencySpec) *DependencyResolution {
	// Convert DependencySpec to Dependency for the existing findHealthyProviderWithTTL
	dep := Dependency{
		Capability:      spec.Capability,
		Version:         spec.Version,
		Tags:            spec.Tags,
		TagAlternatives: spec.TagAlternatives,
	}
	return s.findHealthyProviderWithTTL(dep)
}

// resolveAtPosition handles resolution for a single position in the dependency array.
// It handles both:
//   - Single spec (map): A single dependency requirement
//   - OR alternatives (array): Try each spec in order, first match wins
//
// Returns an IndexedResolution with the position, matched spec, and resolution result.
func (s *EntService) resolveAtPosition(depIndex int, depData interface{}) IndexedResolution {
	// Check if it's an OR alternative (array of specs)
	if alternatives, ok := depData.([]interface{}); ok {
		// OR alternatives: try each spec in order until one resolves
		var firstSpec DependencySpec

		for i, alt := range alternatives {
			altMap, ok := alt.(map[string]interface{})
			if !ok {
				continue
			}

			spec := parseDependencySpec(altMap)

			// Store first spec for unresolved case
			if i == 0 {
				firstSpec = spec
			}

			s.logger.Debug("Trying OR alternative %d at position %d: capability=%s, tags=%v",
				i, depIndex, spec.Capability, spec.Tags)

			if resolved := s.resolveSingle(spec); resolved != nil {
				s.logger.Debug("OR alternative %d matched: %s -> %s", i, spec.Capability, resolved.FunctionName)
				return IndexedResolution{
					DepIndex:   depIndex,
					Spec:       spec, // The spec that matched
					Resolution: resolved,
					Status:     "available",
				}
			}
		}

		// None of the alternatives resolved
		s.logger.Debug("All OR alternatives at position %d unresolved", depIndex)
		return IndexedResolution{
			DepIndex:   depIndex,
			Spec:       firstSpec, // Store first spec for reference
			Resolution: nil,
			Status:     "unresolved",
		}
	}

	// Single spec (map): standard case
	if depMap, ok := depData.(map[string]interface{}); ok {
		spec := parseDependencySpec(depMap)

		if spec.Capability == "" {
			return IndexedResolution{
				DepIndex:   depIndex,
				Spec:       spec,
				Resolution: nil,
				Status:     "unresolved",
			}
		}

		s.logger.Debug("Resolving single spec at position %d: capability=%s, tags=%v",
			depIndex, spec.Capability, spec.Tags)

		resolved := s.resolveSingle(spec)
		if resolved != nil {
			return IndexedResolution{
				DepIndex:   depIndex,
				Spec:       spec,
				Resolution: resolved,
				Status:     "available",
			}
		}

		return IndexedResolution{
			DepIndex:   depIndex,
			Spec:       spec,
			Resolution: nil,
			Status:     "unresolved",
		}
	}

	// Unknown format
	s.logger.Warning("Unknown dependency format at position %d: %T", depIndex, depData)
	return IndexedResolution{
		DepIndex:   depIndex,
		Spec:       DependencySpec{},
		Resolution: nil,
		Status:     "unresolved",
	}
}
