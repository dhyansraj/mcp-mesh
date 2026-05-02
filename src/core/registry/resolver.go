package registry

import (
	"context"
	"fmt"
	"sort"
	"time"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
	"mcp-mesh/src/core/ent/schemaentry"
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

// findHealthyProviderWithTTL finds a healthy provider using TTL check and strict matching using Ent queries.
// Backwards-compatible wrapper around findHealthyProviderWithTrace; the trace is discarded.
func (s *EntService) findHealthyProviderWithTTL(dep Dependency) *DependencyResolution {
	resolution, _ := s.findHealthyProviderWithTrace(dep)
	return resolution
}

// candidateWithHealth bundles a Candidate with its health verdict so the trace
// can record per-stage health evictions with typed reasons.
type candidateWithHealth struct {
	Candidate
	Healthy          bool
	UnhealthyReason  EvictionReason
	UnhealthyDetails map[string]interface{}
}

// scoredCandidateWithHealth augments candidateWithHealth with a tag-match score
// for tiebreaker ranking.
type scoredCandidateWithHealth struct {
	candidateWithHealth
	Score int
}

// findHealthyProviderWithTrace runs the multi-stage candidate-filtering pipeline
// and returns both the resolution and a stage-by-stage audit trace.
// Stages run in fixed order: health → capability_match → tags → version → schema → tiebreaker.
// Health runs first so subsequent stages operate on the small healthy set rather
// than dragging stale unhealthy candidates through every stage's audit listing.
// The capability_match stage is vestigial — every candidate reaching it already
// matched via the indexed DB query — but it's kept for diagnostic clarity.
// The schema stage filters per #547 when the consumer opts in via dep.MatchMode;
// otherwise it's a pass-through.
func (s *EntService) findHealthyProviderWithTrace(dep Dependency) (*DependencyResolution, *AuditTrace) {
	ctx := context.Background()

	s.logger.Debug("Looking for provider for capability: %s, version: %s, tags: %v", dep.Capability, dep.Version, dep.Tags)

	schemaMode := dep.MatchMode
	if schemaMode == "" {
		schemaMode = "none"
	}
	trace := &AuditTrace{
		Spec: AuditSpec{
			Capability:        dep.Capability,
			Tags:              dep.Tags,
			VersionConstraint: dep.Version,
			SchemaMode:        schemaMode,
		},
	}

	// --- Query capabilities (capability_match stage) -----------------------
	var capabilities []*ent.Capability
	var err error
	maxRetries := 3
	for attempt := 0; attempt < maxRetries; attempt++ {
		capabilities, err = s.entDB.Capability.Query().
			Where(capability.CapabilityEQ(dep.Capability)).
			WithAgent().
			All(ctx)

		if err == nil {
			break
		}

		if isDatabaseLockError(err) {
			s.logger.Warning("Database lock detected on attempt %d for capability %s, retrying...", attempt+1, dep.Capability)
			time.Sleep(time.Duration(50*(1<<attempt)) * time.Millisecond)
			continue
		}
		break
	}

	if err != nil {
		s.logger.Error("Error finding healthy providers for %s after %d attempts: %v", dep.Capability, maxRetries, err)
		return nil, trace
	}

	// Build the post-capability candidate set. We retain unhealthy candidates
	// so the health stage can record them as evictions with typed reasons.
	all := make([]candidateWithHealth, 0, len(capabilities))
	for _, cap := range capabilities {
		if cap.Edges.Agent == nil {
			continue // structurally invalid; skip silently
		}

		c := Candidate{
			AgentID:          cap.Edges.Agent.ID,
			FunctionName:     cap.FunctionName,
			Capability:       cap.Capability,
			Version:          cap.Version,
			Tags:             cap.Tags,
			HttpHost:         cap.Edges.Agent.HTTPHost,
			HttpPort:         cap.Edges.Agent.HTTPPort,
			EntityID:         derefString(cap.Edges.Agent.EntityID),
			OutputSchemaHash: derefString(cap.OutputSchemaHash),
		}

		tc := candidateWithHealth{Candidate: c, Healthy: cap.Edges.Agent.Status == agent.StatusHealthy}
		if !tc.Healthy {
			tc.UnhealthyReason = ReasonUnhealthy
			tc.UnhealthyDetails = map[string]interface{}{
				"status": cap.Edges.Agent.Status.String(),
			}
		}
		all = append(all, tc)
	}

	// Stage 1: health — drop unhealthy candidates first so subsequent stages
	// operate only on the small healthy set. Eviction reasons are typed
	// (Unhealthy, Deregistering, etc.); details carry the agent's status string.
	var afterHealth []candidateWithHealth
	healthStage := AuditStage{Stage: StageHealth}
	for _, tc := range all {
		if tc.Healthy {
			afterHealth = append(afterHealth, tc)
		} else {
			healthStage.Evicted = append(healthStage.Evicted, AuditEvicted{
				ID:      candidateID(tc.AgentID, tc.FunctionName),
				Reason:  tc.UnhealthyReason,
				Details: tc.UnhealthyDetails,
			})
		}
	}
	healthStage.Kept = idsFromCandidates(afterHealth)
	trace.Stages = append(trace.Stages, healthStage)

	if len(afterHealth) == 0 {
		s.logger.Debug("No healthy providers found for %s (no healthy candidates with capability)", dep.Capability)
		return nil, trace
	}

	// Stage 2: capability_match — vestigial. Every candidate reaching here came
	// from the indexed DB query AND survived the health stage; kept = afterHealth.
	// Retained for diagnostic clarity so operators can see "capability matched"
	// as an explicit step in the audit.
	capStage := AuditStage{Stage: StageCapabilityMatch, Kept: idsFromCandidates(afterHealth)}
	trace.Stages = append(trace.Stages, capStage)

	// Stage 3: tags — apply MatchTags with scoring; record per-candidate evictions.
	var afterTags []scoredCandidateWithHealth
	tagStage := AuditStage{Stage: StageTags}
	hasTagFilter := len(dep.Tags) > 0 || len(dep.TagAlternatives) > 0
	for _, tc := range afterHealth {
		if !hasTagFilter {
			afterTags = append(afterTags, scoredCandidateWithHealth{candidateWithHealth: tc, Score: 0})
			continue
		}
		matches, score := s.matcher.MatchTags(tc.Tags, dep.Tags, dep.TagAlternatives)
		if matches {
			afterTags = append(afterTags, scoredCandidateWithHealth{candidateWithHealth: tc, Score: score})
		} else {
			reason, details := classifyTagFailure(tc.Tags, dep.Tags, dep.TagAlternatives)
			tagStage.Evicted = append(tagStage.Evicted, AuditEvicted{
				ID:      candidateID(tc.AgentID, tc.FunctionName),
				Reason:  reason,
				Details: details,
			})
		}
	}
	tagStage.Kept = idsFromScored(afterTags)
	trace.Stages = append(trace.Stages, tagStage)

	if len(afterTags) == 0 {
		return nil, trace
	}

	// Stage 4: version — apply MatchVersion; record per-candidate evictions.
	var afterVersion []scoredCandidateWithHealth
	versionStage := AuditStage{Stage: StageVersion}
	for _, st := range afterTags {
		if dep.Version == "" || s.matcher.MatchVersion(st.Version, dep.Version) {
			afterVersion = append(afterVersion, st)
		} else {
			versionStage.Evicted = append(versionStage.Evicted, AuditEvicted{
				ID:     candidateID(st.AgentID, st.FunctionName),
				Reason: ReasonVersionConstraintFailed,
				Details: map[string]interface{}{
					"version":    st.Version,
					"constraint": dep.Version,
				},
			})
		}
	}
	versionStage.Kept = idsFromScored(afterVersion)
	trace.Stages = append(trace.Stages, versionStage)

	if len(afterVersion) == 0 {
		return nil, trace
	}

	// Stage 5: schema (#547) — when the consumer opts in via dep.MatchMode,
	// drop candidates whose output schema can't satisfy the consumer's expected
	// schema. When the consumer didn't opt in, OR the candidate has no
	// output_schema_hash on file, this stage is a pass-through (we'd rather keep
	// a usable producer than break agents during the schema-rollout window;
	// strict cluster-wide enforcement is the Phase 4 cluster policy).
	var afterSchema []scoredCandidateWithHealth
	schemaStage := AuditStage{Stage: StageSchema}
	schemaCheckEnabled := dep.MatchMode != ""
	for _, st := range afterVersion {
		if !schemaCheckEnabled {
			afterSchema = append(afterSchema, st)
			continue
		}
		candidateHash := st.OutputSchemaHash
		if candidateHash == "" {
			// Legacy/unextracted producer (no published output_schema_hash).
			// Behavior splits per match_mode:
			//   - subset: keep so consumer rollouts don't blackhole producers
			//     that haven't shipped schema extraction yet.
			//   - strict: evict. The consumer asked for byte-equal hashes; a
			//     producer with no published hash cannot satisfy that contract.
			if dep.MatchMode == "strict" {
				schemaStage.Evicted = append(schemaStage.Evicted, AuditEvicted{
					ID:     candidateID(st.AgentID, st.FunctionName),
					Reason: ReasonSchemaIncompatible,
					Details: map[string]interface{}{
						"mode":          "strict",
						"consumer_hash": dep.ExpectedSchemaHash,
						"producer_hash": "",
						"reasons": []map[string]interface{}{
							{"kind": "no_published_hash"},
						},
					},
				})
				continue
			}
			afterSchema = append(afterSchema, st)
			continue
		}
		if dep.ExpectedSchemaHash != "" && dep.ExpectedSchemaHash == candidateHash {
			// Hash equality short-circuit: identical canonical content, no diff needed.
			afterSchema = append(afterSchema, st)
			continue
		}
		if dep.MatchMode == "strict" {
			schemaStage.Evicted = append(schemaStage.Evicted, AuditEvicted{
				ID:     candidateID(st.AgentID, st.FunctionName),
				Reason: ReasonSchemaIncompatible,
				Details: map[string]interface{}{
					"mode":          "strict",
					"consumer_hash": dep.ExpectedSchemaHash,
					"producer_hash": candidateHash,
				},
			})
			continue
		}
		// Subset (or unknown mode → treat as subset). Load the producer's canonical
		// schema and run the structural diff. If the load fails or returns nil
		// (storage hiccup, hash absent from schema_entries), fall through to keep:
		// don't punish a candidate for a registry storage issue.
		producerSchema, loadErr := s.loadCanonicalByHash(ctx, candidateHash)
		if loadErr != nil || producerSchema == nil {
			afterSchema = append(afterSchema, st)
			continue
		}
		compat := IsSchemaCompatible(dep.ExpectedSchemaCanonical, producerSchema, "subset")
		if compat.Compatible {
			afterSchema = append(afterSchema, st)
			continue
		}
		schemaStage.Evicted = append(schemaStage.Evicted, AuditEvicted{
			ID:     candidateID(st.AgentID, st.FunctionName),
			Reason: ReasonSchemaIncompatible,
			Details: map[string]interface{}{
				"mode":          "subset",
				"consumer_hash": dep.ExpectedSchemaHash,
				"producer_hash": candidateHash,
				"reasons":       compat.Reasons,
			},
		})
	}
	schemaStage.Kept = idsFromScored(afterSchema)
	trace.Stages = append(trace.Stages, schemaStage)

	if len(afterSchema) == 0 {
		s.logger.Debug("No providers survived schema stage for %s (mode: %s)", dep.Capability, dep.MatchMode)
		return nil, trace
	}

	// Stage 6: tiebreaker — sort by score DESC then take the head. Document
	// the algorithm name in the audit so changes are visible.
	sort.SliceStable(afterSchema, func(i, j int) bool {
		return afterSchema[i].Score > afterSchema[j].Score
	})
	winner := afterSchema[0]
	trace.Stages = append(trace.Stages, AuditStage{
		Stage:  StageTiebreaker,
		Kept:   idsFromScored(afterSchema),
		Chosen: candidateID(winner.AgentID, winner.FunctionName),
		Reason: TiebreakerHighestScoreFirst,
	})

	endpoint := "stdio://" + winner.AgentID
	if winner.HttpHost != "" && winner.HttpPort > 0 {
		scheme := "http"
		if winner.EntityID != "" {
			scheme = "https"
		}
		endpoint = fmt.Sprintf("%s://%s:%d", scheme, winner.HttpHost, winner.HttpPort)
	}

	resolution := &DependencyResolution{
		AgentID:      winner.AgentID,
		FunctionName: winner.FunctionName,
		Endpoint:     endpoint,
		Capability:   winner.Capability,
		Status:       "available",
	}
	trace.Chosen = &AuditChosen{
		AgentID:      winner.AgentID,
		Endpoint:     endpoint,
		FunctionName: winner.FunctionName,
	}
	return resolution, trace
}

// candidateID returns the per-stage candidate identifier in the form
// "<agent_id>:<function_name>". Two functions on the same agent providing
// the same capability with different tags must be distinguishable in the
// trace, so the trace identifier carries both. See AuditStage doc.
func candidateID(agentID, functionName string) string {
	return fmt.Sprintf("%s:%s", agentID, functionName)
}

// idsFromCandidates returns "<agent_id>:<function_name>" identifiers from a
// candidateWithHealth slice.
func idsFromCandidates(xs []candidateWithHealth) []string {
	out := make([]string, len(xs))
	for i, x := range xs {
		out[i] = candidateID(x.AgentID, x.FunctionName)
	}
	return out
}

// idsFromScored returns "<agent_id>:<function_name>" identifiers from a
// scoredCandidateWithHealth slice.
func idsFromScored(xs []scoredCandidateWithHealth) []string {
	out := make([]string, len(xs))
	for i, x := range xs {
		out[i] = candidateID(x.AgentID, x.FunctionName)
	}
	return out
}

// resolveSingle is the SINGLE SOURCE OF TRUTH for all dependency matching logic.
// It takes a DependencySpec and returns a resolved dependency or nil if not found.
// All resolution logic (capability + version + tags) happens here.
func (s *EntService) resolveSingle(spec DependencySpec) *DependencyResolution {
	resolution, _ := s.resolveSingleWithTrace(spec)
	return resolution
}

// resolveSingleWithTrace mirrors resolveSingle but returns the audit trace too.
func (s *EntService) resolveSingleWithTrace(spec DependencySpec) (*DependencyResolution, *AuditTrace) {
	dep := Dependency{
		Capability:              spec.Capability,
		Version:                 spec.Version,
		Tags:                    spec.Tags,
		TagAlternatives:         spec.TagAlternatives,
		ExpectedSchemaHash:      spec.ExpectedSchemaHash,
		ExpectedSchemaCanonical: spec.ExpectedSchemaCanonical,
		MatchMode:               spec.MatchMode,
	}
	return s.findHealthyProviderWithTrace(dep)
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
		var lastTrace *AuditTrace

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

			resolved, trace := s.resolveSingleWithTrace(spec)
			if resolved != nil {
				s.logger.Debug("OR alternative %d matched: %s -> %s", i, spec.Capability, resolved.FunctionName)
				return IndexedResolution{
					DepIndex:   depIndex,
					Spec:       spec,
					Resolution: resolved,
					Status:     "available",
					Trace:      trace,
				}
			}
			lastTrace = trace
		}

		// None of the alternatives resolved
		s.logger.Debug("All OR alternatives at position %d unresolved", depIndex)
		return IndexedResolution{
			DepIndex:   depIndex,
			Spec:       firstSpec,
			Resolution: nil,
			Status:     "unresolved",
			Trace:      lastTrace,
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

		resolved, trace := s.resolveSingleWithTrace(spec)
		if resolved != nil {
			return IndexedResolution{
				DepIndex:   depIndex,
				Spec:       spec,
				Resolution: resolved,
				Status:     "available",
				Trace:      trace,
			}
		}

		return IndexedResolution{
			DepIndex:   depIndex,
			Spec:       spec,
			Resolution: nil,
			Status:     "unresolved",
			Trace:      trace,
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

// derefString safely dereferences a *string, returning "" if nil.
func derefString(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// loadCanonicalByHash returns the canonical normalized JSON Schema for a given
// content hash, or (nil, nil) if no row exists. Used by the schema stage to
// fetch a producer's output schema for the subset diff.
func (s *EntService) loadCanonicalByHash(ctx context.Context, hash string) (map[string]interface{}, error) {
	if hash == "" {
		return nil, nil
	}
	entry, err := s.entDB.SchemaEntry.Query().
		Where(schemaentry.HashEQ(hash)).
		First(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			return nil, nil
		}
		return nil, err
	}
	return entry.Canonical, nil
}

// classifyTagFailure inspects which tag rule failed for a given provider so the
// audit can carry typed reasons (MissingTag vs ExtraTagDisallowed) plus details.
// Inspects required tags first, then OR alternatives. Returns ReasonMissingTag
// as a fallback when nothing more specific can be identified.
func classifyTagFailure(providerTags, requiredTags []string, tagAlternatives [][]string) (EvictionReason, map[string]interface{}) {
	var missing []string
	for _, req := range requiredTags {
		if len(req) == 0 {
			continue
		}
		switch req[0] {
		case '-':
			ex := req[1:]
			if ex != "" && containsTag(providerTags, ex) {
				return ReasonExtraTagDisallowed, map[string]interface{}{"disallowed": []string{ex}}
			}
		case '+':
			// preferred — never a failure
		default:
			if !containsTag(providerTags, req) {
				missing = append(missing, req)
			}
		}
	}

	if len(missing) > 0 {
		return ReasonMissingTag, map[string]interface{}{"missing": missing}
	}

	// OR group failures: find a group with no satisfying tag.
	for _, group := range tagAlternatives {
		groupMatched := false
		for _, alt := range group {
			if len(alt) == 0 {
				continue
			}
			switch alt[0] {
			case '-':
				ex := alt[1:]
				if ex != "" && containsTag(providerTags, ex) {
					return ReasonExtraTagDisallowed, map[string]interface{}{"disallowed": []string{ex}}
				}
			case '+':
				if containsTag(providerTags, alt[1:]) {
					groupMatched = true
				}
			default:
				if containsTag(providerTags, alt) {
					groupMatched = true
				}
			}
		}
		if !groupMatched {
			return ReasonMissingTag, map[string]interface{}{"missing_one_of": group}
		}
	}

	// No specific failure found — generic missing-tag fallback.
	return ReasonMissingTag, nil
}
