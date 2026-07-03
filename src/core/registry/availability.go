package registry

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
)

// availability.go implements the transitive capability-availability predicate
// and required-edge cycle detection for issue #1249.
//
// Predicate: a capability is AVAILABLE ⇔ its owning agent is healthy AND every
// one of its *required* dependencies resolves to an available provider capability
// (evaluated transitively). Optional dependencies never affect availability.
//
// The predicate is computed as derived state on the events that already drive
// dependency-resolution updates (registrations, unregistrations, heartbeat
// health transitions). It hooks into the resolver's health stage so an
// unavailable capability is excluded from consumers' resolution exactly like a
// dead provider — reusing the existing propagation channel, no new event types.

// requiredDepCapabilities returns the capability names of the required (required==true)
// dependencies declared by a capability. Optional deps are excluded. Used ONLY by
// the name-level cycle detector; availability evaluation uses requiredDepEntries so
// it can apply the full matching constraints (tags/version/schema).
func requiredDepCapabilities(deps []map[string]interface{}) []string {
	var out []string
	for _, d := range requiredDepEntries(deps) {
		if capName, ok := d["capability"].(string); ok && capName != "" {
			out = append(out, capName)
		}
	}
	return out
}

// requiredDepEntries returns the full dependency entries (capability + all
// matching constraints) that are marked required==true, in declaration order.
func requiredDepEntries(deps []map[string]interface{}) []map[string]interface{} {
	var out []map[string]interface{}
	for _, d := range deps {
		if req, _ := d["required"].(bool); req {
			out = append(out, d)
		}
	}
	return out
}

// availKey is the required-dependency evaluation key: agent + capability.
func availKey(agentID, capName string) string {
	return agentID + "\x00" + capName
}

// availEval carries the per-evaluation state for the availability predicate:
//   - visiting: the DFS stack, for fail-closed cycle detection.
//   - memo:     a verdict cache (availKey -> reason; "" = available; presence =
//     cached) that collapses repeated node evaluation. Without it, diamond /
//     stacked-diamond required subgraphs re-evaluate shared nodes once per path
//     — O(R^D) capability queries; with it, each node is evaluated once, so the
//     work is O(nodes + edges). A cycle-sentinel result is deliberately NOT
//     memoized (it is stack-contextual, not a stable node verdict).
//
// One availEval spans a single logical evaluation: one resolver top-level call,
// or one whole ListAgents response (so a capability shared across many agents'
// required chains is evaluated once for the entire response).
type availEval struct {
	visiting map[string]bool
	memo     map[string]string
}

func newAvailEval() *availEval {
	return &availEval{
		visiting: map[string]bool{},
		memo:     map[string]string{},
	}
}

// capabilityUnavailableReason evaluates the transitive required-dependency
// predicate for cap and returns a one-level reason string naming the FIRST
// broken required edge, or "" when every required dep RESOLVES to an available
// provider.
//
// "Resolves" means the exact same matching the resolver applies for ordinary
// consumer resolution: capability + tags + version + schema. Each required edge
// is evaluated by re-entering findHealthyProviderWithTrace with a Dependency
// built from the edge's declared constraints. Because the resolver's health
// stage already evicts candidates that are themselves unavailable (#1249),
// transitive recursion is IMPLICIT — a required edge only resolves to a
// candidate that is itself available under the full predicate.
//
// It evaluates ONLY the required-dependency half of the predicate; the caller
// checks cap's own agent health (the resolver's health stage does; ListAgents
// checks agent status separately).
//
// eval carries the shared DFS stack (for cycle detection) and verdict memo (see
// availEval). On a revisit (a required-edge cycle that slipped past
// registration-time detection, or a transient graph inconsistency) we FAIL
// CLOSED for this node — a required cycle can never converge, so treating it as
// unavailable is the only safe verdict; that sentinel is not memoized.
func (s *EntService) capabilityUnavailableReason(ctx context.Context, agentID string, cap *ent.Capability, eval *availEval) string {
	if eval == nil {
		eval = newAvailEval()
	}
	key := availKey(agentID, cap.Capability)
	if v, ok := eval.memo[key]; ok {
		return v
	}
	if eval.visiting[key] {
		return fmt.Sprintf("required dependency evaluation cycle at '%s'", cap.Capability)
	}
	eval.visiting[key] = true

	reason := ""
	for _, entry := range requiredDepEntries(cap.Dependencies) {
		edgeDep := dependencyFromEntry(entry)
		if edgeDep.Capability == "" {
			continue
		}
		resolution, _ := s.findHealthyProviderWithTrace(edgeDep, eval)
		if resolution == nil {
			reason = s.describeUnresolvedRequiredEdge(ctx, edgeDep)
			break
		}
	}

	delete(eval.visiting, key)
	eval.memo[key] = reason
	return reason
}

// dependencyFromEntry converts a stored dependency map into a resolver
// Dependency, carrying every matching constraint (tags, version, schema) so the
// availability edge is evaluated under identical semantics to consumer
// resolution. Reuses parseDependencySpec so there's a single parse path.
func dependencyFromEntry(entry map[string]interface{}) Dependency {
	spec := parseDependencySpec(entry)
	return Dependency{
		Capability:              spec.Capability,
		Version:                 spec.Version,
		Tags:                    spec.Tags,
		TagAlternatives:         spec.TagAlternatives,
		ExpectedSchemaHash:      spec.ExpectedSchemaHash,
		ExpectedSchemaCanonical: spec.ExpectedSchemaCanonical,
		MatchMode:               spec.MatchMode,
	}
}

// describeUnresolvedRequiredEdge builds the one-level reason for a required edge
// that failed to resolve. It preserves the pre-#1249 reason forms:
//   - "required dep 'X' unavailable (provider Y unhealthy)"   — a CONSTRAINT-MATCHING provider is down
//   - "required dep 'X' unavailable (provider Y unavailable)" — a CONSTRAINT-MATCHING provider is unavailable via its own chain
//   - "required dep 'X' unresolved"                            — no provider at all
//   - "required dep 'X' unresolved (no provider matches ...)" — providers exist but none satisfy the constraints
//
// Correctness (live-validation fix): a health/availability cause is reported
// ONLY for candidates that passed the edge's constraint matching (tags/version).
// The resolver runs its health stage FIRST, so a stale dead provider that also
// fails the constraints would otherwise mask the real "no provider matches …"
// cause (observed: a dead untagged instance shadowing a tag requirement). We
// therefore re-derive the reason from the constraint-matching subset, using the
// same matcher the resolver's tags/version stages use. This query is diagnostic
// only (the availability VERDICT is purely resolver-based); it runs solely on
// the already-unresolved path.
func (s *EntService) describeUnresolvedRequiredEdge(ctx context.Context, dep Dependency) string {
	capName := dep.Capability

	caps, err := s.entDB.Capability.Query().
		Where(capability.CapabilityEQ(capName)).
		WithAgent().
		All(ctx)
	if err != nil || len(caps) == 0 {
		// No provider row at all (or a query hiccup) → plain unresolved.
		return unresolvedReason(dep)
	}

	// Keep only candidates that satisfy the edge's tag + version constraints.
	// Schema (#547) is opt-in and structurally heavier; it is intentionally not
	// factored into the reason classification (the verdict already accounts for
	// it via the resolver). A constraint-failing provider is irrelevant to WHY
	// the edge is broken, so its health must not surface here.
	hasTagFilter := len(dep.Tags) > 0 || len(dep.TagAlternatives) > 0
	var matching []*ent.Capability
	for _, c := range caps {
		if hasTagFilter {
			if ok, _ := s.matcher.MatchTags(c.Tags, dep.Tags, dep.TagAlternatives); !ok {
				continue
			}
		}
		if dep.Version != "" && !s.matcher.MatchVersion(c.Version, dep.Version) {
			continue
		}
		matching = append(matching, c)
	}

	if len(matching) == 0 {
		// Providers exist but none satisfy the constraints — the real cause.
		return unresolvedReason(dep)
	}

	// A constraint-matching provider exists but the edge still didn't resolve, so
	// each matching candidate is either unhealthy or unavailable via its own
	// required chain. Prefer naming an unhealthy one; otherwise it's chain-driven.
	for _, c := range matching {
		if c.Edges.Agent == nil || c.Edges.Agent.Status != agent.StatusHealthy {
			id := "unknown"
			if c.Edges.Agent != nil {
				id = c.Edges.Agent.ID
			}
			return fmt.Sprintf("required dep '%s' unavailable (provider %s unhealthy)", capName, id)
		}
	}
	return fmt.Sprintf("required dep '%s' unavailable (provider %s unavailable)", capName, matching[0].Edges.Agent.ID)
}

// unresolvedReason renders the "no matching provider" reason, naming the
// constraints when the edge has any beyond capability name.
func unresolvedReason(dep Dependency) string {
	if c := constraintSummary(dep); c != "" {
		return fmt.Sprintf("required dep '%s' unresolved (%s)", dep.Capability, c)
	}
	return fmt.Sprintf("required dep '%s' unresolved", dep.Capability)
}

// constraintSummary renders the non-capability matching constraints of a
// required edge for the unresolved-reason string. Empty when the edge only
// constrains by capability name.
func constraintSummary(dep Dependency) string {
	var parts []string
	if len(dep.Tags) > 0 {
		parts = append(parts, fmt.Sprintf("tags=%v", dep.Tags))
	}
	if dep.Version != "" {
		parts = append(parts, "version "+dep.Version)
	}
	if dep.MatchMode != "" {
		parts = append(parts, "schema="+dep.MatchMode)
	}
	if len(parts) == 0 {
		return ""
	}
	return "no provider matches " + strings.Join(parts, ", ")
}

// ---------------------------------------------------------------------------
// Required-edge cycle detection (issue #1249 correctness requirement #1)
// ---------------------------------------------------------------------------

// extractRequiredEdges pulls the required-edge adjacency (capability name ->
// set of required dependency capability names) declared by an agent's tools in
// a registration/heartbeat metadata payload. Only required==true deps produce
// edges; optional deps are ignored (they remain the legal bootstrapping path
// for cycles).
func extractRequiredEdges(metadata map[string]interface{}) map[string]map[string]bool {
	edges := map[string]map[string]bool{}

	toolsData, ok := metadata["tools"].([]interface{})
	if !ok {
		return edges
	}
	for _, toolData := range toolsData {
		toolMap, ok := toolData.(map[string]interface{})
		if !ok {
			continue
		}
		capName, _ := toolMap["capability"].(string)
		if capName == "" {
			continue
		}
		deps := coerceDependencies(toolMap["dependencies"])
		for _, depCap := range requiredDepCapabilities(deps) {
			if edges[capName] == nil {
				edges[capName] = map[string]bool{}
			}
			edges[capName][depCap] = true
		}
	}
	return edges
}

// requiredEdgeGraphExcluding builds the cluster-wide required-edge graph
// (capability name -> set of required dep capability names) from all currently
// registered capabilities, EXCLUDING those owned by excludeAgentID (whose edges
// are about to be replaced by the in-flight registration/heartbeat).
//
// Scale note: this is a full capability scan, filtered in-memory to the rows
// that actually declare required edges (requiredDepCapabilities drops the rest).
// It is reached ONLY by a register/heartbeat that itself declares ≥1 required
// edge (see checkRequiredCycles' gate and guardedCapabilityWrite) — required
// deps are opt-in and uncommon, so the scan is off the hot path. The dependency
// specs live in a JSON blob column with no portable index for a cheaper
// server-side filter, and a cache+invalidation layer isn't justified at registry
// capability counts; a gated in-memory scan is the deliberate trade-off.
func (s *EntService) requiredEdgeGraphExcluding(ctx context.Context, excludeAgentID string) (map[string]map[string]bool, error) {
	caps, err := s.entDB.Capability.Query().WithAgent().All(ctx)
	if err != nil {
		return nil, err
	}
	graph := map[string]map[string]bool{}
	for _, c := range caps {
		if c.Edges.Agent != nil && c.Edges.Agent.ID == excludeAgentID {
			continue
		}
		for _, depCap := range requiredDepCapabilities(c.Dependencies) {
			if graph[c.Capability] == nil {
				graph[c.Capability] = map[string]bool{}
			}
			graph[c.Capability][depCap] = true
		}
	}
	return graph, nil
}

// mergeRequiredEdges overlays incoming edges onto graph in place.
func mergeRequiredEdges(graph, incoming map[string]map[string]bool) {
	for from, tos := range incoming {
		if graph[from] == nil {
			graph[from] = map[string]bool{}
		}
		for to := range tos {
			graph[from][to] = true
		}
	}
}

// detectRequiredCycle returns a cycle path (e.g. ["a","b","a"]) if the required-
// edge graph contains a directed cycle, or nil if it is acyclic. Edges are keyed
// by capability name; every edge in this graph is a required edge, so any cycle
// is a rejectable required cycle. Neighbors are visited in sorted order for
// deterministic reporting.
//
// Cycle detection stays deliberately at capability-NAME granularity, even though
// availability evaluation (capabilityUnavailableReason) applies full tag/version/
// schema matching. This is conservative on purpose: a "pseudo-cycle" whose edges
// are actually tag- or version-disjoint (and so could never resolve back onto
// itself at runtime) is still rejected at registration. A loud, deterministic
// false-positive at registration beats a silent runtime deadlock — the operator
// gets a named loop to break instead of a capability that is mysteriously,
// permanently unavailable.
func detectRequiredCycle(graph map[string]map[string]bool) []string {
	const (
		white = 0 // unvisited
		gray  = 1 // on the current DFS stack
		black = 2 // fully explored
	)
	color := map[string]int{}
	var stack []string
	var found []string

	var dfs func(node string) bool
	dfs = func(node string) bool {
		color[node] = gray
		stack = append(stack, node)

		neighbors := make([]string, 0, len(graph[node]))
		for n := range graph[node] {
			neighbors = append(neighbors, n)
		}
		sort.Strings(neighbors)

		for _, next := range neighbors {
			switch color[next] {
			case gray:
				// Back-edge closes a cycle: slice the stack from `next` to top,
				// then append `next` again to name the loop (a → b → a).
				idx := 0
				for i, n := range stack {
					if n == next {
						idx = i
						break
					}
				}
				found = append(append([]string{}, stack[idx:]...), next)
				return true
			case white:
				if dfs(next) {
					return true
				}
			}
		}

		stack = stack[:len(stack)-1]
		color[node] = black
		return false
	}

	roots := make([]string, 0, len(graph))
	for n := range graph {
		roots = append(roots, n)
	}
	sort.Strings(roots)
	for _, n := range roots {
		if color[n] == white {
			if dfs(n) {
				return found
			}
		}
	}
	return nil
}

// checkRequiredCycles rejects a registration/heartbeat whose required
// dependencies would close a required-edge cycle. A write declaring no required
// edges cannot close a cycle, so the graph build is skipped entirely.
func (s *EntService) checkRequiredCycles(ctx context.Context, agentID string, metadata map[string]interface{}) error {
	incoming := extractRequiredEdges(metadata)
	if len(incoming) == 0 {
		return nil
	}
	return s.checkRequiredCyclesForEdges(ctx, agentID, incoming)
}

// checkRequiredCyclesForEdges merges the incoming agent's required edges onto the
// current cluster graph (minus the agent's own prior edges) and reports the first
// cycle found, naming the loop. Cycles that route through an optional edge are
// legal and never appear here (optional deps aren't added to the graph). Callers
// must have already confirmed incoming is non-empty.
func (s *EntService) checkRequiredCyclesForEdges(ctx context.Context, agentID string, incoming map[string]map[string]bool) error {
	graph, err := s.requiredEdgeGraphExcluding(ctx, agentID)
	if err != nil {
		return fmt.Errorf("cycle check: failed to load capability graph: %w", err)
	}
	mergeRequiredEdges(graph, incoming)

	if cycle := detectRequiredCycle(graph); cycle != nil {
		loop := ""
		for i, n := range cycle {
			if i > 0 {
				loop += " → "
			}
			loop += n
		}
		return fmt.Errorf("required dependency cycle: %s", loop)
	}
	return nil
}

// guardedCapabilityWrite serializes the required-edge cycle check with the
// capability write in fn under cycleWriteMu, releasing the lock via defer so a
// panic in either the check or fn can't strand it (PR #1255 finding 1).
//
// The lock — and the whole-graph scan the check performs — is taken ONLY when
// this write declares ≥1 required edge. A zero-required-edge write cannot close
// a cycle and cannot affect a concurrent check's verdict (its rows contribute no
// required edges to any graph), so it skips both the lock and the scan entirely,
// making required-free meshes pay nothing (PR #1255 finding 2).
//
// Returns the cycle-rejection error (fn NOT run) and fn's error separately so
// each caller can shape its own error/response.
func (s *EntService) guardedCapabilityWrite(
	ctx context.Context,
	agentID string,
	metadata map[string]interface{},
	fn func() error,
) (cycleErr, writeErr error) {
	incoming := extractRequiredEdges(metadata)
	if len(incoming) == 0 {
		return nil, fn()
	}

	s.cycleWriteMu.Lock()
	defer s.cycleWriteMu.Unlock()

	if err := s.checkRequiredCyclesForEdges(ctx, agentID, incoming); err != nil {
		return err, nil
	}
	return nil, fn()
}
