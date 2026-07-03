package registry

import (
	"context"
	"strings"
	"testing"
	"time"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
)

// availability_test.go covers the transitive capability-availability predicate,
// required-edge cycle detection, and reason exposure added for issue #1249.

// --- test helpers ----------------------------------------------------------

// depSpec builds a dependency map as it appears after the wire-boundary
// normalization in ent_handlers.go (snake_case keys). required==false is
// written explicitly only when the caller asks; omit to exercise defaulting.
func depSpec(capName string, required bool) map[string]interface{} {
	return map[string]interface{}{
		"capability": capName,
		"required":   required,
	}
}

func optionalDepNoFlag(capName string) map[string]interface{} {
	// No "required" key at all — exercises the default-false path.
	return map[string]interface{}{"capability": capName}
}

// depSpecTags is a required/optional dep that also constrains provider tags.
func depSpecTags(capName string, required bool, tags ...string) map[string]interface{} {
	ti := make([]interface{}, len(tags))
	for i, t := range tags {
		ti[i] = t
	}
	return map[string]interface{}{"capability": capName, "required": required, "tags": ti}
}

// depSpecVersion is a required/optional dep that also constrains provider version.
func depSpecVersion(capName string, required bool, version string) map[string]interface{} {
	return map[string]interface{}{"capability": capName, "required": required, "version": version}
}

// buildRegRequest builds a single-capability registration request. version/tags
// describe the PROVIDED capability; deps are its dependency specs.
func buildRegRequest(agentID, capName, version string, tags []string, deps []map[string]interface{}) *AgentRegistrationRequest {
	tool := map[string]interface{}{
		"function_name": capName + "_fn",
		"capability":    capName,
		"version":       version,
	}
	if len(tags) > 0 {
		ti := make([]interface{}, len(tags))
		for i, t := range tags {
			ti[i] = t
		}
		tool["tags"] = ti
	}
	if len(deps) > 0 {
		depsI := make([]interface{}, len(deps))
		for i, d := range deps {
			depsI[i] = d
		}
		tool["dependencies"] = depsI
	}
	return &AgentRegistrationRequest{
		AgentID: agentID,
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       agentID,
			"http_host":  "127.0.0.1",
			"http_port":  8000 + len(agentID),
			"namespace":  "default",
			"tools":      []interface{}{tool},
		},
		Timestamp: time.Now().Format(time.RFC3339),
	}
}

// regAgent registers an agent providing capName@1.0.0 (untagged) with the given
// dependency list (nil for a leaf provider).
func regAgent(t *testing.T, s *EntService, agentID, capName string, deps ...map[string]interface{}) {
	t.Helper()
	if _, err := s.RegisterAgent(buildRegRequest(agentID, capName, "1.0.0", nil, deps)); err != nil {
		t.Fatalf("RegisterAgent(%s) failed: %v", agentID, err)
	}
}

// regProvider registers an agent providing capName at a specific version/tags.
func regProvider(t *testing.T, s *EntService, agentID, capName, version string, tags []string, deps ...map[string]interface{}) {
	t.Helper()
	if _, err := s.RegisterAgent(buildRegRequest(agentID, capName, version, tags, deps)); err != nil {
		t.Fatalf("RegisterAgent(%s) failed: %v", agentID, err)
	}
}

// tryRegAgent is like regAgent but returns the error instead of failing (for
// cycle-rejection assertions).
func tryRegAgent(s *EntService, agentID, capName string, deps ...map[string]interface{}) error {
	_, err := s.RegisterAgent(buildRegRequest(agentID, capName, "1.0.0", nil, deps))
	return err
}

func getCap(t *testing.T, s *EntService, capName string) *ent.Capability {
	t.Helper()
	ctx := context.Background()
	c, err := s.entDB.Capability.Query().
		Where(capability.CapabilityEQ(capName)).
		WithAgent().
		First(ctx)
	if err != nil {
		t.Fatalf("getCap(%s): %v", capName, err)
	}
	return c
}

func reasonFor(t *testing.T, s *EntService, capName string) string {
	t.Helper()
	c := getCap(t, s, capName)
	return s.capabilityUnavailableReason(context.Background(), c.Edges.Agent.ID, c, newAvailEval())
}

func setAgentStatus(t *testing.T, s *EntService, agentID string, status agent.Status) {
	t.Helper()
	_, err := s.entDB.Agent.UpdateOneID(agentID).SetStatus(status).Save(context.Background())
	if err != nil {
		t.Fatalf("setAgentStatus(%s): %v", agentID, err)
	}
}

// --- 1. required flag parsed / persisted / defaulted -----------------------

func TestRequiredFlag_ParsedPersistedDefaulted(t *testing.T) {
	// parseDependencySpec: explicit true, explicit false, absent (default false).
	if spec := parseDependencySpec(map[string]interface{}{"capability": "x", "required": true}); !spec.Required {
		t.Error("parseDependencySpec: required:true should set Required=true")
	}
	if spec := parseDependencySpec(map[string]interface{}{"capability": "x", "required": false}); spec.Required {
		t.Error("parseDependencySpec: required:false should set Required=false")
	}
	if spec := parseDependencySpec(map[string]interface{}{"capability": "x"}); spec.Required {
		t.Error("parseDependencySpec: absent required should default to false")
	}

	// Persistence: the flag rides in the capability.dependencies JSON blob.
	s := setupTestService(t)
	regAgent(t, s, "leaf", "capC")
	regAgent(t, s, "consumer", "capB", depSpec("capC", true), optionalDepNoFlag("capD"))

	deps := getCap(t, s, "capB").Dependencies
	if len(deps) != 2 {
		t.Fatalf("expected 2 deps persisted, got %d", len(deps))
	}
	if r, _ := deps[0]["required"].(bool); !r {
		t.Errorf("dep[0].required expected true, got %v", deps[0]["required"])
	}
	if r, _ := deps[1]["required"].(bool); r {
		t.Errorf("dep[1].required expected false/absent, got %v", deps[1]["required"])
	}
}

// --- 2. chain A→B optional, B→C required -----------------------------------

func TestChain_OptionalDoesNotPropagate_RequiredDoes(t *testing.T) {
	s := setupTestService(t)
	regAgent(t, s, "agent-c", "capC")                        // leaf provider
	regAgent(t, s, "agent-b", "capB", depSpec("capC", true)) // B required→C
	regAgent(t, s, "agent-a", "capA", optionalDepNoFlag("capB"))

	// All healthy: everything available.
	if r := reasonFor(t, s, "capB"); r != "" {
		t.Errorf("capB should be available while C healthy, got %q", r)
	}
	if r := reasonFor(t, s, "capA"); r != "" {
		t.Errorf("capA (optional dep) should be available, got %q", r)
	}

	// C's agent goes unhealthy.
	setAgentStatus(t, s, "agent-c", agent.StatusUnhealthy)

	rB := reasonFor(t, s, "capB")
	if rB == "" || !strings.Contains(rB, "capC") {
		t.Errorf("capB should be unavailable naming capC, got %q", rB)
	}
	// A depends on B only OPTIONALLY — optional deps never propagate.
	if r := reasonFor(t, s, "capA"); r != "" {
		t.Errorf("capA has only an optional dep; must stay available, got %q", r)
	}

	// Recovery flips B back.
	setAgentStatus(t, s, "agent-c", agent.StatusHealthy)
	if r := reasonFor(t, s, "capB"); r != "" {
		t.Errorf("capB should recover to available, got %q", r)
	}
}

func TestChain_RequiredEdgePropagates(t *testing.T) {
	s := setupTestService(t)
	regAgent(t, s, "agent-c", "capC")
	regAgent(t, s, "agent-b", "capB", depSpec("capC", true))
	regAgent(t, s, "agent-a", "capA", depSpec("capB", true)) // A required→B

	setAgentStatus(t, s, "agent-c", agent.StatusUnhealthy)

	if r := reasonFor(t, s, "capB"); r == "" {
		t.Error("capB should be unavailable when C unhealthy")
	}
	// A's required dep B is unavailable ⇒ A unavailable too (transitive).
	rA := reasonFor(t, s, "capA")
	if rA == "" || !strings.Contains(rA, "capB") {
		t.Errorf("capA should be unavailable naming capB, got %q", rA)
	}

	setAgentStatus(t, s, "agent-c", agent.StatusHealthy)
	if r := reasonFor(t, s, "capA"); r != "" {
		t.Errorf("capA should recover, got %q", r)
	}
}

// --- 3. transitive depth >=3 ------------------------------------------------

func TestTransitiveDepth(t *testing.T) {
	s := setupTestService(t)
	regAgent(t, s, "agent-d", "capD")
	regAgent(t, s, "agent-c", "capC", depSpec("capD", true))
	regAgent(t, s, "agent-b", "capB", depSpec("capC", true))
	regAgent(t, s, "agent-a", "capA", depSpec("capB", true))

	setAgentStatus(t, s, "agent-d", agent.StatusUnhealthy)

	for _, c := range []string{"capA", "capB", "capC"} {
		if r := reasonFor(t, s, c); r == "" {
			t.Errorf("%s should be unavailable at depth from D, got available", c)
		}
	}
	setAgentStatus(t, s, "agent-d", agent.StatusHealthy)
	for _, c := range []string{"capA", "capB", "capC"} {
		if r := reasonFor(t, s, c); r != "" {
			t.Errorf("%s should recover, got %q", c, r)
		}
	}
}

// --- 4. diamond: two paths, one required one optional -----------------------

func TestDiamond_RequiredPathBreaksOptionalPathDoesNot(t *testing.T) {
	s := setupTestService(t)
	regAgent(t, s, "agent-d", "capD")
	regAgent(t, s, "agent-b", "capB", depSpec("capD", true)) // required path leg
	regAgent(t, s, "agent-c", "capC", depSpec("capD", true)) // optional path leg
	// A depends on D via B (required) and C (optional).
	regAgent(t, s, "agent-a", "capA", depSpec("capB", true), optionalDepNoFlag("capC"))

	setAgentStatus(t, s, "agent-d", agent.StatusUnhealthy)

	// Both intermediaries lose D.
	if r := reasonFor(t, s, "capB"); r == "" {
		t.Error("capB should be unavailable when D down")
	}
	if r := reasonFor(t, s, "capC"); r == "" {
		t.Error("capC should be unavailable when D down")
	}
	// A is unavailable because its REQUIRED leg (B) is unavailable.
	if r := reasonFor(t, s, "capA"); r == "" || !strings.Contains(r, "capB") {
		t.Errorf("capA should be unavailable via required leg capB, got %q", r)
	}
}

func TestDiamond_OptionalLegBrokenKeepsConsumerAvailable(t *testing.T) {
	s := setupTestService(t)
	regAgent(t, s, "agent-req", "capReq") // required-leg provider (leaf, healthy)
	regAgent(t, s, "agent-d", "capD")     // optional-leg dependency
	regAgent(t, s, "agent-opt", "capOpt", depSpec("capD", true))
	// A: required→capReq (healthy), optional→capOpt.
	regAgent(t, s, "agent-a", "capA", depSpec("capReq", true), optionalDepNoFlag("capOpt"))

	setAgentStatus(t, s, "agent-d", agent.StatusUnhealthy) // breaks the OPTIONAL leg only

	if r := reasonFor(t, s, "capOpt"); r == "" {
		t.Error("capOpt should be unavailable when D down")
	}
	// A's required leg is fine; the broken optional leg must not propagate.
	if r := reasonFor(t, s, "capA"); r != "" {
		t.Errorf("capA required leg healthy ⇒ must stay available, got %q", r)
	}
}

// --- 5. cycle rejection -----------------------------------------------------

func TestCycle_RequiredEdgesRejected(t *testing.T) {
	s := setupTestService(t)
	// A required→B accepted (B not yet present — bootstrap).
	if err := tryRegAgent(s, "agent-a", "capA", depSpec("capB", true)); err != nil {
		t.Fatalf("agentA registration should succeed, got %v", err)
	}
	// B required→A closes the cycle — must be rejected, naming the loop.
	err := tryRegAgent(s, "agent-b", "capB", depSpec("capA", true))
	if err == nil {
		t.Fatal("expected cycle rejection registering capB required→capA")
	}
	msg := err.Error()
	if !strings.Contains(msg, "required dependency cycle") ||
		!strings.Contains(msg, "capA") || !strings.Contains(msg, "capB") {
		t.Errorf("cycle error should name the loop with capA and capB, got %q", msg)
	}
}

func TestCycle_OptionalEdgeAccepted(t *testing.T) {
	s := setupTestService(t)
	if err := tryRegAgent(s, "agent-a", "capA", depSpec("capB", true)); err != nil {
		t.Fatalf("agentA registration should succeed, got %v", err)
	}
	// B optional→A: optional edges never form a required cycle → accepted.
	if err := tryRegAgent(s, "agent-b", "capB", optionalDepNoFlag("capA")); err != nil {
		t.Errorf("optional back-edge must be accepted, got %v", err)
	}
}

// --- 6. bootstrap: consumer registers before provider ----------------------

func TestBootstrap_RequiredDepUnresolvedThenResolves(t *testing.T) {
	s := setupTestService(t)
	// B required→C, but C not registered yet. Registration must NOT error.
	regAgent(t, s, "agent-b", "capB", depSpec("capC", true))

	r := reasonFor(t, s, "capB")
	if r == "" || !strings.Contains(r, "unresolved") || !strings.Contains(r, "capC") {
		t.Errorf("capB should be unavailable with 'unresolved' reason naming capC, got %q", r)
	}

	// C registers → B becomes available.
	regAgent(t, s, "agent-c", "capC")
	if r := reasonFor(t, s, "capB"); r != "" {
		t.Errorf("capB should become available once capC registers, got %q", r)
	}
}

// --- 7. resolution exclusion via the existing propagation channel -----------

func TestResolutionExclusion_UnavailableCapabilityExcluded(t *testing.T) {
	s := setupTestService(t)
	regAgent(t, s, "agent-c", "capC")
	regAgent(t, s, "agent-b", "capB", depSpec("capC", true))

	// While B available, a consumer resolving capB gets B's provider.
	if res := s.findHealthyProviderWithTTL(Dependency{Capability: "capB"}); res == nil {
		t.Fatal("capB should resolve while available")
	}

	// C unhealthy ⇒ B unavailable ⇒ resolving capB now excludes B exactly like
	// a dead provider (nil), via the resolver's health stage.
	setAgentStatus(t, s, "agent-c", agent.StatusUnhealthy)
	if res := s.findHealthyProviderWithTTL(Dependency{Capability: "capB"}); res != nil {
		t.Errorf("capB must be excluded while unavailable, got provider %s", res.AgentID)
	}

	// Recovery re-includes it.
	setAgentStatus(t, s, "agent-c", agent.StatusHealthy)
	if res := s.findHealthyProviderWithTTL(Dependency{Capability: "capB"}); res == nil {
		t.Error("capB should resolve again after recovery")
	}
}

// --- 8. reason strings for unresolved and unhealthy-provider cases ----------

func TestReasonStrings(t *testing.T) {
	s := setupTestService(t)

	// Unresolved: required dep provider never registered.
	regAgent(t, s, "agent-b", "capB", depSpec("capMissing", true))
	if r := reasonFor(t, s, "capB"); r != "required dep 'capMissing' unresolved" {
		t.Errorf("unresolved reason mismatch, got %q", r)
	}

	// Unhealthy provider: required dep provider present but its agent unhealthy.
	regAgent(t, s, "agent-p", "capP")
	regAgent(t, s, "agent-q", "capQ", depSpec("capP", true))
	setAgentStatus(t, s, "agent-p", agent.StatusUnhealthy)
	r := reasonFor(t, s, "capQ")
	if r != "required dep 'capP' unavailable (provider agent-p unhealthy)" {
		t.Errorf("unhealthy-provider reason mismatch, got %q", r)
	}
}

// --- 8a. stale-provider masking: health must not shadow constraint failure --

// A dead provider that ALSO fails the edge's constraints must not mask the real
// "no provider matches …" cause. The resolver evicts it at the health stage
// (which runs before tag/version matching), so the reason logic must re-check
// constraints before crediting any health/availability eviction.
func TestReason_StaleDeadNonMatchingProvider_DoesNotMaskConstraints(t *testing.T) {
	s := setupTestService(t)
	regProvider(t, s, "agent-c-dead", "capC", "1.0.0", nil)               // untagged → will be unhealthy
	regProvider(t, s, "agent-c-live", "capC", "1.0.0", []string{"other"}) // healthy but wrong tag
	setAgentStatus(t, s, "agent-c-dead", agent.StatusUnhealthy)
	regAgent(t, s, "agent-b", "capB", depSpecTags("capC", true, "needs-this-tag"))

	r := reasonFor(t, s, "capB")
	if !strings.Contains(r, "no provider matches") || !strings.Contains(r, "needs-this-tag") {
		t.Errorf("reason should name the tag constraint (no provider matches), got %q", r)
	}
	if strings.Contains(r, "unhealthy") {
		t.Errorf("stale dead non-matching provider must not surface as the cause, got %q", r)
	}
}

// When the ONLY constraint-matching provider is the dead one, its health IS the
// real cause and must be named.
func TestReason_StaleDeadMatchingProvider_NamesHealth(t *testing.T) {
	s := setupTestService(t)
	regProvider(t, s, "agent-c-dead", "capC", "1.0.0", []string{"needs-this-tag"})
	setAgentStatus(t, s, "agent-c-dead", agent.StatusUnhealthy)
	regAgent(t, s, "agent-b", "capB", depSpecTags("capC", true, "needs-this-tag"))

	r := reasonFor(t, s, "capB")
	if r != "required dep 'capC' unavailable (provider agent-c-dead unhealthy)" {
		t.Errorf("matching-but-unhealthy provider should be named, got %q", r)
	}
}

// --- 8b. full matching semantics: constraints affect availability ----------

func TestFullMatching_VersionTooLow_Unavailable(t *testing.T) {
	s := setupTestService(t)
	regProvider(t, s, "agent-c", "capC", "1.0.0", nil) // provider is v1.0.0
	// B requires capC >=2.0.0 — the healthy provider is too old.
	regAgent(t, s, "agent-b", "capB", depSpecVersion("capC", true, ">=2.0.0"))

	r := reasonFor(t, s, "capB")
	if r == "" || !strings.Contains(r, "capC") {
		t.Errorf("capB must be unavailable: matching provider version too low, got %q", r)
	}

	// Upgrade the provider to a satisfying version ⇒ B becomes available.
	regProvider(t, s, "agent-c", "capC", "2.1.0", nil)
	if r := reasonFor(t, s, "capB"); r != "" {
		t.Errorf("capB should be available once a >=2.0.0 provider exists, got %q", r)
	}
}

func TestFullMatching_TagMismatch_Unavailable(t *testing.T) {
	s := setupTestService(t)
	regProvider(t, s, "agent-c", "capC", "1.0.0", []string{"gpu"}) // provider tagged gpu
	// B requires capC with tag "anthropic" — the healthy provider doesn't match.
	regAgent(t, s, "agent-b", "capB", depSpecTags("capC", true, "anthropic"))

	if r := reasonFor(t, s, "capB"); r == "" || !strings.Contains(r, "capC") {
		t.Errorf("capB must be unavailable on tag mismatch, got %q", r)
	}

	// A provider carrying the required tag makes B available.
	regProvider(t, s, "agent-c2", "capC", "1.0.0", []string{"anthropic"})
	if r := reasonFor(t, s, "capB"); r != "" {
		t.Errorf("capB should be available once a tag-matching provider exists, got %q", r)
	}
}

func TestFullMatching_FullMatch_Available(t *testing.T) {
	s := setupTestService(t)
	regProvider(t, s, "agent-c", "capC", "2.3.0", []string{"anthropic"})
	regAgent(t, s, "agent-b", "capB",
		map[string]interface{}{
			"capability": "capC",
			"required":   true,
			"version":    ">=2.0.0",
			"tags":       []interface{}{"anthropic"},
		})
	if r := reasonFor(t, s, "capB"); r != "" {
		t.Errorf("capB should be available when provider satisfies tags+version, got %q", r)
	}
}

// TestFullMatching_MatchingProviderUnavailableViaChain proves the predicate is
// resolver-based, not "some healthy provider of the capability exists": the only
// CONSTRAINT-MATCHING provider is unavailable through its own required chain,
// while a healthy but NON-matching provider also exists. The consumer must be
// unavailable — the healthy non-matching provider must not rescue it.
func TestFullMatching_MatchingProviderUnavailableViaChain(t *testing.T) {
	s := setupTestService(t)
	// Downstream dependency of the matching provider; will be taken unhealthy.
	regProvider(t, s, "agent-d", "capD", "1.0.0", nil)
	// Matching provider of capC: tagged v2, but required→capD (its chain).
	regProvider(t, s, "agent-c-good", "capC", "1.0.0", []string{"v2"}, depSpec("capD", true))
	// Non-matching healthy provider of capC: tagged v1, no deps (always available).
	regProvider(t, s, "agent-c-other", "capC", "1.0.0", []string{"v1"})
	// Consumer B requires capC with tag v2.
	regAgent(t, s, "agent-b", "capB", depSpecTags("capC", true, "v2"))

	// Baseline: matching provider's chain is intact ⇒ B available.
	if r := reasonFor(t, s, "capB"); r != "" {
		t.Fatalf("capB should be available at baseline, got %q", r)
	}

	// Break the matching provider's chain. The healthy v1 provider still exists
	// but does NOT match tag v2, so it cannot satisfy the edge.
	setAgentStatus(t, s, "agent-d", agent.StatusUnhealthy)
	if r := reasonFor(t, s, "capB"); r == "" {
		t.Error("capB must be unavailable: only the tag-matching provider is unavailable; " +
			"the healthy non-matching provider must not satisfy the required edge")
	}

	// Restore the chain ⇒ B available again.
	setAgentStatus(t, s, "agent-d", agent.StatusHealthy)
	if r := reasonFor(t, s, "capB"); r != "" {
		t.Errorf("capB should recover once the matching provider's chain heals, got %q", r)
	}
}

// --- 9. API reason exposure (ListAgents) -----------------------------------

func TestListAgents_ExposesAvailabilityAndReason(t *testing.T) {
	s := setupTestService(t)
	regAgent(t, s, "agent-c", "capC")
	regAgent(t, s, "agent-b", "capB", depSpec("capC", true))
	setAgentStatus(t, s, "agent-c", agent.StatusUnhealthy)

	resp, err := s.ListAgents(nil)
	if err != nil {
		t.Fatalf("ListAgents: %v", err)
	}

	var sawB bool
	for _, a := range resp.Agents {
		for _, c := range a.Capabilities {
			if c.Name != "capB" {
				continue
			}
			sawB = true
			if c.Available == nil || *c.Available {
				t.Error("capB.available should be false")
			}
			if c.UnavailableReason == nil || !strings.Contains(*c.UnavailableReason, "capC") {
				t.Errorf("capB.unavailable_reason should name capC, got %v", c.UnavailableReason)
			}
		}
	}
	if !sawB {
		t.Fatal("capB not found in ListAgents response")
	}
}

// --- 10. heartbeat capability-sync cycle guard (finding 1) ------------------

// A running agent's full heartbeat re-syncs its capabilities. If new code (e.g.
// after a non-graceful redeploy with the row retained) declares a cycle-closing
// required edge, the heartbeat must be rejected exactly like registration —
// otherwise the permanent-unavailable deadlock slips in silently.
func TestHeartbeat_CycleClosingRequiredEdge_Rejected(t *testing.T) {
	s := setupTestService(t)
	regAgent(t, s, "agent-a", "capA", depSpec("capB", true)) // A required→B
	regAgent(t, s, "agent-b", "capB")                        // B leaf, no deps

	// Control: heartbeat re-sending capB with no new edges → success.
	okMeta := buildRegRequest("agent-b", "capB", "1.0.0", nil, nil).Metadata
	resp, err := s.UpdateHeartbeat(&HeartbeatRequest{AgentID: "agent-b", Status: "healthy", Metadata: okMeta})
	if err != nil {
		t.Fatalf("control heartbeat error: %v", err)
	}
	if resp.Status != "success" {
		t.Fatalf("control heartbeat should succeed, got status=%q msg=%q", resp.Status, resp.Message)
	}

	// Cycle-closing heartbeat: capB now required→capA. Must be rejected.
	badMeta := buildRegRequest("agent-b", "capB", "1.0.0", nil, []map[string]interface{}{depSpec("capA", true)}).Metadata
	resp, err = s.UpdateHeartbeat(&HeartbeatRequest{AgentID: "agent-b", Status: "healthy", Metadata: badMeta})
	if err != nil {
		t.Fatalf("cycle heartbeat returned transport error: %v", err)
	}
	if resp.Status != "error" || !strings.Contains(resp.Message, "required dependency cycle") {
		t.Errorf("cycle-closing heartbeat should be rejected, got status=%q msg=%q", resp.Status, resp.Message)
	}
	// The cycle-closing edge must NOT have persisted.
	if deps := getCap(t, s, "capB").Dependencies; len(deps) != 0 {
		t.Errorf("cycle-closing edge must not persist, got deps=%v", deps)
	}
}

// --- 11. memoized evaluation: each node once (finding 2) --------------------

// A diamond (A→B, A→C, B→D, C→D) shares the tail D on two paths. The per-eval
// verdict memo must evaluate each capability node exactly once — proving the
// shared tail isn't re-explored per path (the O(R^D) → O(nodes) collapse).
func TestAvailability_MemoEvaluatesEachNodeOnce(t *testing.T) {
	s := setupTestService(t)
	regAgent(t, s, "agent-d", "capD")
	regAgent(t, s, "agent-b", "capB", depSpec("capD", true))
	regAgent(t, s, "agent-c", "capC", depSpec("capD", true))
	regAgent(t, s, "agent-a", "capA", depSpec("capB", true), depSpec("capC", true))

	eval := newAvailEval()
	a := getCap(t, s, "capA")
	if r := s.capabilityUnavailableReason(context.Background(), a.Edges.Agent.ID, a, eval); r != "" {
		t.Fatalf("capA should be available, got %q", r)
	}

	for _, k := range []string{
		availKey("agent-a", "capA"),
		availKey("agent-b", "capB"),
		availKey("agent-c", "capC"),
		availKey("agent-d", "capD"),
	} {
		if _, ok := eval.memo[k]; !ok {
			t.Errorf("expected memo entry for %q", k)
		}
	}
	if len(eval.memo) != 4 {
		t.Errorf("expected exactly 4 memoized nodes (D evaluated once), got %d: %v", len(eval.memo), eval.memo)
	}
}
