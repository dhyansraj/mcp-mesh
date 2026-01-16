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
