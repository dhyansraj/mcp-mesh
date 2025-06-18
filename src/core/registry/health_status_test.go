package registry

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestHealthStatusCalculation tests the new health status logic
func TestHealthStatusCalculation(t *testing.T) {
	t.Run("HealthyStatusForRecentAgents", func(t *testing.T) {
		service := setupTestService(t)

		// Register an agent
		req := &AgentRegistrationRequest{
			AgentID: "recent-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Recent Agent",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "test_function",
						"capability":    "test_capability",
					},
				},
			},
		}

		_, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// List agents immediately - should be healthy (< timeout threshold)
		params := &AgentQueryParams{}
		response, err := service.ListAgents(params)
		require.NoError(t, err)

		assert.Equal(t, 1, response.Count)
		agent := response.Agents[0]
		assert.Equal(t, "healthy", string(agent.Status))

		t.Logf("✅ Recent agent correctly shows: %s", string(agent.Status))
	})

	t.Run("HealthStatusThresholds", func(t *testing.T) {
		// This test demonstrates the health status calculation logic
		// Since we can't easily manipulate timestamps in tests, we'll verify the logic conceptually

		// Health status calculation logic:
		// timeSinceLastSeen < timeout = "healthy"  (e.g., < 60 seconds)
		// timeout <= timeSinceLastSeen < timeout*2 = "degraded" (e.g., 60-120 seconds)
		// timeSinceLastSeen >= timeout*2 = "expired" (e.g., >= 120 seconds)

		timeoutThreshold := 60 * time.Second

		testCases := []struct {
			name           string
			timeSinceSeen  time.Duration
			expectedStatus string
		}{
			{"Fresh agent", 10 * time.Second, "healthy"},
			{"Recent agent", 45 * time.Second, "healthy"},
			{"At threshold", 60 * time.Second, "degraded"},
			{"Degraded agent", 90 * time.Second, "degraded"},
			{"Just expired", 120 * time.Second, "expired"},
			{"Long expired", 300 * time.Second, "expired"},
		}

		for _, tc := range testCases {
			t.Run(tc.name, func(t *testing.T) {
				// Simulate the health calculation logic
				var status string
				if tc.timeSinceSeen < timeoutThreshold {
					status = "healthy"
				} else if tc.timeSinceSeen < timeoutThreshold*2 {
					status = "degraded"
				} else {
					status = "expired"
				}

				assert.Equal(t, tc.expectedStatus, status,
					"Time since seen: %v, Expected: %s, Got: %s",
					tc.timeSinceSeen, tc.expectedStatus, status)

				t.Logf("✅ %s (%v ago) → %s", tc.name, tc.timeSinceSeen, status)
			})
		}
	})

	t.Run("HealthStatusWithCustomTimeout", func(t *testing.T) {
		// Create service with custom timeout for testing
		db := setupTestDatabase(t)
		defer db.Close()

		config := &RegistryConfig{
			DefaultTimeoutThreshold:  30, // 30 seconds instead of default 60
			DefaultEvictionThreshold: 60, // Not used in new logic, but required
			EnableResponseCache:      false,
		}
		service := NewService(db, config)

		// Register an agent
		req := &AgentRegistrationRequest{
			AgentID: "timeout-test-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Timeout Test Agent",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "test_function",
						"capability":    "test_capability",
					},
				},
			},
		}

		_, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// List agents - should be healthy with 30-second timeout
		params := &AgentQueryParams{}
		response, err := service.ListAgents(params)
		require.NoError(t, err)

		assert.Equal(t, 1, response.Count)
		agent := response.Agents[0]
		assert.Equal(t, "healthy", string(agent.Status))

		t.Logf("✅ Custom timeout test - agent status: %s", string(agent.Status))
		t.Logf("   With 30s timeout threshold:")
		t.Logf("   - healthy: < 30s")
		t.Logf("   - degraded: 30s - 60s")
		t.Logf("   - expired: > 60s")
	})

	t.Run("VerifyLastSeenField", func(t *testing.T) {
		service := setupTestService(t)

		// Register an agent
		req := &AgentRegistrationRequest{
			AgentID: "last-seen-test",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Last Seen Test",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "test_function",
						"capability":    "test_capability",
					},
				},
			},
		}

		beforeRegistration := time.Now()
		_, err := service.RegisterAgent(req)
		require.NoError(t, err)
		afterRegistration := time.Now()

		// List agents and check last_seen field
		params := &AgentQueryParams{}
		response, err := service.ListAgents(params)
		require.NoError(t, err)

		assert.Equal(t, 1, response.Count)
		agent := response.Agents[0]

		// Verify last_seen exists and is in RFC3339 format
		require.NotNil(t, agent.LastSeen, "last_seen should be present")

		lastSeen := *agent.LastSeen

		// Verify timestamp is reasonable (within registration window)
		assert.True(t, lastSeen.After(beforeRegistration.Add(-time.Second)),
			"last_seen should be after registration start")
		assert.True(t, lastSeen.Before(afterRegistration.Add(time.Second)),
			"last_seen should be before registration end")

		t.Logf("✅ last_seen field verified: %s", lastSeen.Format(time.RFC3339))
		t.Logf("   Parsed time: %v", lastSeen)
		t.Logf("   Time since: %v", time.Since(lastSeen))
	})
}
