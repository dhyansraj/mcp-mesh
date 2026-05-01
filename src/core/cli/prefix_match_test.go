package cli

import (
	"fmt"
	"strings"
	"testing"
)

func TestResolveAgentByPrefix(t *testing.T) {
	agents := []EnhancedAgent{
		{ID: "calc-agent-1234", Name: "calc-agent", Status: "healthy"},
		{ID: "calculator-5678", Name: "calculator", Status: "healthy"},
		{ID: "weather-agent-9abc", Name: "weather-agent", Status: "healthy"},
		{ID: "unhealthy-agent-def0", Name: "unhealthy-agent", Status: "unhealthy"},
	}

	testCases := []struct {
		name        string
		prefix      string
		healthyOnly bool
		expectMatch bool
		expectMulti bool
		expectName  string
		expectExact bool
	}{
		// Exact match tests
		{"exact name match", "calc-agent", true, true, false, "calc-agent", true},
		{"exact id match", "calc-agent-1234", true, true, false, "calc-agent", true},

		// Prefix match tests
		{"unique prefix", "wea", true, true, false, "weather-agent", false},
		{"ambiguous prefix", "calc", true, false, true, "", false},

		// No match tests
		{"no match prefix", "xyz", true, false, false, "", false},

		// Health filtering tests
		{"unhealthy exact match with filter", "unhealthy-agent", true, false, false, "", false},
		{"unhealthy exact match without filter", "unhealthy-agent", false, true, false, "unhealthy-agent", true},

		// Case insensitivity
		{"case insensitive prefix", "WEATH", true, true, false, "weather-agent", false},
		{"case insensitive exact", "CALC-AGENT", true, true, false, "calc-agent", false}, // prefix match, not exact
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result := ResolveAgentByPrefix(agents, tc.prefix, tc.healthyOnly)

			if tc.expectMulti {
				if len(result.Matches) <= 1 {
					t.Errorf("expected multiple matches, got %d", len(result.Matches))
				}
				if result.Error == nil {
					t.Error("expected error for multiple matches")
				}
				return
			}

			if tc.expectMatch {
				if result.Agent == nil {
					t.Errorf("expected match but got nil, error: %v", result.Error)
					return
				}
				if result.Agent.Name != tc.expectName {
					t.Errorf("expected agent name %s, got %s", tc.expectName, result.Agent.Name)
				}
				if tc.expectExact && !result.IsExact {
					t.Error("expected exact match but got prefix match")
				}
				if !tc.expectExact && result.IsExact {
					t.Error("expected prefix match but got exact match")
				}
			} else {
				if result.Agent != nil && len(result.Matches) <= 1 {
					t.Errorf("expected no match but got %s", result.Agent.Name)
				}
				if result.Error == nil {
					t.Error("expected error for no match")
				}
			}
		})
	}
}

func TestResolveAgentByPrefix_EmptyList(t *testing.T) {
	result := ResolveAgentByPrefix([]EnhancedAgent{}, "test", false)
	if result.Agent != nil {
		t.Error("expected no match for empty agent list")
	}
	if result.Error == nil {
		t.Error("expected error for empty agent list")
	}
}

func TestResolveAgentByPrefix_AllUnhealthy(t *testing.T) {
	agents := []EnhancedAgent{
		{ID: "agent-1", Name: "agent-one", Status: "unhealthy"},
		{ID: "agent-2", Name: "agent-two", Status: "degraded"},
	}

	result := ResolveAgentByPrefix(agents, "agent", true)
	if result.Agent != nil {
		t.Error("expected no match when all agents are unhealthy and healthyOnly=true")
	}
	if result.Error == nil || !strings.Contains(result.Error.Error(), "no healthy agent") {
		t.Errorf("expected 'no healthy agent' error, got: %v", result.Error)
	}
}

func TestAgentMatchResult_FormattedError(t *testing.T) {
	t.Run("no error returns nil", func(t *testing.T) {
		result := &AgentMatchResult{
			Agent: &EnhancedAgent{ID: "test", Name: "test"},
		}
		if result.FormattedError() != nil {
			t.Error("expected nil error")
		}
	})

	t.Run("single match error returns simple error", func(t *testing.T) {
		result := &AgentMatchResult{
			Error: fmt.Errorf("no agent found"),
		}
		err := result.FormattedError()
		if err == nil || err.Error() != "no agent found" {
			t.Errorf("expected simple error, got: %v", err)
		}
	})

	t.Run("multiple matches returns formatted error", func(t *testing.T) {
		result := &AgentMatchResult{
			Error: fmt.Errorf("multiple agents match"),
			Matches: []EnhancedAgent{
				{ID: "a-1", Name: "agent-a", Status: "healthy"},
				{ID: "a-2", Name: "agent-b", Status: "healthy"},
			},
		}
		err := result.FormattedError()
		if err == nil {
			t.Error("expected error")
			return
		}
		errStr := err.Error()
		if !strings.Contains(errStr, "agent-a") || !strings.Contains(errStr, "agent-b") {
			t.Errorf("expected formatted error with agent names, got: %s", errStr)
		}
	})
}

// TestResolveAgentByPrefix_HealthyPreference covers the disambiguation rule
// where multiple agents share a name/prefix and the resolver should prefer
// healthy over unhealthy.
//
// Bug background: the registry can hold a stale unhealthy row alongside the
// current healthy agent (same Name, different ID). Sweeping eventually purges
// the stale row, but until then `meshctl audit <name>` (which calls with
// healthyOnly=false) used to lex-sort and pick the unhealthy one.
//
// The new rule: when multiple matches exist and at least one is healthy,
// prefer healthy. When all are unhealthy, return lex-first deterministically.
func TestResolveAgentByPrefix_HealthyPreference(t *testing.T) {
	// Agents share name "api"; lex-smaller ID is the unhealthy stale row.
	// Callers pass agents pre-sorted by ID (see getEnhancedAgents), so we
	// mirror that here.
	apiUnhealthyFirst := []EnhancedAgent{
		{ID: "api-12e47b97", Name: "api", Status: "unhealthy"},
		{ID: "api-bd59c884", Name: "api", Status: "healthy"},
	}
	apiBothHealthy := []EnhancedAgent{
		{ID: "api-12e47b97", Name: "api", Status: "healthy"},
		{ID: "api-bd59c884", Name: "api", Status: "healthy"},
	}
	apiBothUnhealthy := []EnhancedAgent{
		{ID: "api-12e47b97", Name: "api", Status: "unhealthy"},
		{ID: "api-bd59c884", Name: "api", Status: "degraded"},
	}
	apiSingleHealthy := []EnhancedAgent{
		{ID: "api-12e47b97", Name: "api", Status: "healthy"},
	}
	apiSingleUnhealthy := []EnhancedAgent{
		{ID: "api-12e47b97", Name: "api", Status: "unhealthy"},
	}

	t.Run("exact: single healthy match returned", func(t *testing.T) {
		r := ResolveAgentByPrefix(apiSingleHealthy, "api", false)
		if r.Error != nil || r.Agent == nil {
			t.Fatalf("expected match, got err=%v agent=%v", r.Error, r.Agent)
		}
		if r.Agent.ID != "api-12e47b97" {
			t.Errorf("got ID %s", r.Agent.ID)
		}
		if !r.IsExact {
			t.Error("expected IsExact=true")
		}
	})

	t.Run("exact: single unhealthy match returned", func(t *testing.T) {
		r := ResolveAgentByPrefix(apiSingleUnhealthy, "api", false)
		if r.Error != nil || r.Agent == nil {
			t.Fatalf("expected match, got err=%v agent=%v", r.Error, r.Agent)
		}
		if r.Agent.ID != "api-12e47b97" {
			t.Errorf("got ID %s", r.Agent.ID)
		}
	})

	t.Run("exact: multiple matches, prefer healthy (the bug)", func(t *testing.T) {
		// Original bug: returned unhealthy api-12e47b97 because lex-first.
		// New behavior: returns healthy api-bd59c884.
		r := ResolveAgentByPrefix(apiUnhealthyFirst, "api", false)
		if r.Error != nil {
			t.Fatalf("expected no error, got %v", r.Error)
		}
		if r.Agent == nil {
			t.Fatal("expected agent, got nil")
		}
		if r.Agent.ID != "api-bd59c884" {
			t.Errorf("expected healthy api-bd59c884, got %s (status=%s)", r.Agent.ID, r.Agent.Status)
		}
		if !r.IsExact {
			t.Error("expected IsExact=true (matched on Name)")
		}
	})

	t.Run("exact: multiple healthy, error to disambiguate", func(t *testing.T) {
		r := ResolveAgentByPrefix(apiBothHealthy, "api", false)
		if r.Error == nil {
			t.Fatal("expected error for multiple healthy matches")
		}
		if !strings.Contains(r.Error.Error(), "multiple agents match") {
			t.Errorf("expected 'multiple agents match' error, got: %v", r.Error)
		}
		if len(r.Matches) != 2 {
			t.Errorf("expected 2 matches in disambiguation list, got %d", len(r.Matches))
		}
	})

	t.Run("exact: all unhealthy, return lex-first deterministically", func(t *testing.T) {
		r := ResolveAgentByPrefix(apiBothUnhealthy, "api", false)
		if r.Error != nil {
			t.Fatalf("expected no error for all-unhealthy multi-match, got %v", r.Error)
		}
		if r.Agent == nil {
			t.Fatal("expected agent, got nil")
		}
		// Lex-first by ID is api-12e47b97
		if r.Agent.ID != "api-12e47b97" {
			t.Errorf("expected lex-first api-12e47b97, got %s", r.Agent.ID)
		}
	})

	// Prefix-phase variants of the same rules
	prefixUnhealthyFirst := []EnhancedAgent{
		{ID: "apex-1", Name: "apex", Status: "unhealthy"},
		{ID: "apple-2", Name: "apple", Status: "healthy"},
	}
	prefixBothHealthy := []EnhancedAgent{
		{ID: "apex-1", Name: "apex", Status: "healthy"},
		{ID: "apple-2", Name: "apple", Status: "healthy"},
	}
	prefixBothUnhealthy := []EnhancedAgent{
		{ID: "apex-1", Name: "apex", Status: "unhealthy"},
		{ID: "apple-2", Name: "apple", Status: "degraded"},
	}
	prefixSingleHealthy := []EnhancedAgent{
		{ID: "apex-1", Name: "apex", Status: "healthy"},
	}

	t.Run("prefix: single healthy match returned", func(t *testing.T) {
		r := ResolveAgentByPrefix(prefixSingleHealthy, "ap", false)
		if r.Error != nil || r.Agent == nil {
			t.Fatalf("expected match, got err=%v agent=%v", r.Error, r.Agent)
		}
		if r.Agent.Name != "apex" {
			t.Errorf("got name %s", r.Agent.Name)
		}
		if r.IsExact {
			t.Error("expected IsExact=false (prefix match)")
		}
	})

	t.Run("prefix: multiple matches, prefer healthy", func(t *testing.T) {
		r := ResolveAgentByPrefix(prefixUnhealthyFirst, "ap", false)
		if r.Error != nil {
			t.Fatalf("expected no error, got %v", r.Error)
		}
		if r.Agent == nil {
			t.Fatal("expected agent, got nil")
		}
		if r.Agent.Name != "apple" || r.Agent.Status != "healthy" {
			t.Errorf("expected healthy apple, got name=%s status=%s", r.Agent.Name, r.Agent.Status)
		}
		if r.IsExact {
			t.Error("expected IsExact=false (prefix match)")
		}
	})

	t.Run("prefix: multiple healthy, error to disambiguate", func(t *testing.T) {
		r := ResolveAgentByPrefix(prefixBothHealthy, "ap", false)
		if r.Error == nil {
			t.Fatal("expected error for multiple healthy matches")
		}
		if !strings.Contains(r.Error.Error(), "multiple agents match") {
			t.Errorf("expected 'multiple agents match' error, got: %v", r.Error)
		}
	})

	t.Run("prefix: all unhealthy, return lex-first deterministically", func(t *testing.T) {
		r := ResolveAgentByPrefix(prefixBothUnhealthy, "ap", false)
		if r.Error != nil {
			t.Fatalf("expected no error for all-unhealthy multi-match, got %v", r.Error)
		}
		if r.Agent == nil {
			t.Fatal("expected agent, got nil")
		}
		// Lex-first by ID is apex-1
		if r.Agent.ID != "apex-1" {
			t.Errorf("expected lex-first apex-1, got %s", r.Agent.ID)
		}
	})

	t.Run("no match returns error", func(t *testing.T) {
		r := ResolveAgentByPrefix(apiBothHealthy, "zzz", false)
		if r.Error == nil {
			t.Fatal("expected error for no match")
		}
		if r.Agent != nil {
			t.Errorf("expected nil agent, got %v", r.Agent)
		}
	})

	t.Run("healthyOnly=true pre-filters unhealthy then resolves", func(t *testing.T) {
		// Unhealthy stale + healthy current; healthyOnly=true should leave
		// only the healthy one as a candidate, returning it as a single match.
		r := ResolveAgentByPrefix(apiUnhealthyFirst, "api", true)
		if r.Error != nil {
			t.Fatalf("expected no error, got %v", r.Error)
		}
		if r.Agent == nil || r.Agent.ID != "api-bd59c884" {
			t.Errorf("expected healthy api-bd59c884, got %v", r.Agent)
		}
	})

	t.Run("healthyOnly=true with all unhealthy errors", func(t *testing.T) {
		r := ResolveAgentByPrefix(apiBothUnhealthy, "api", true)
		if r.Error == nil {
			t.Fatal("expected error when no healthy candidates and healthyOnly=true")
		}
		if r.Agent != nil {
			t.Errorf("expected nil agent, got %v", r.Agent)
		}
	})
}

func TestFormatAgentMatchOptions(t *testing.T) {
	matches := []EnhancedAgent{
		{ID: "agent-1234", Name: "agent-one", Status: "healthy"},
		{ID: "agent-5678", Name: "agent-two", Status: "unhealthy"},
	}

	output := FormatAgentMatchOptions(matches)

	// Check that output contains expected elements
	if !strings.Contains(output, "agent-one") {
		t.Error("output should contain agent-one")
	}
	if !strings.Contains(output, "agent-two") {
		t.Error("output should contain agent-two")
	}
	if !strings.Contains(output, "agent-1234") {
		t.Error("output should contain agent ID")
	}
	if !strings.Contains(output, "Matching agents:") {
		t.Error("output should contain header")
	}
	if !strings.Contains(output, "Please specify") {
		t.Error("output should contain instruction")
	}
}
