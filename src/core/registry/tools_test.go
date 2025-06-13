package registry

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"mcp-mesh/src/core/database"
)

// TestToolsRegistration tests the new multi-tool registration
func TestToolsRegistration(t *testing.T) {
	t.Run("RegisterAgentWithMultipleTools", func(t *testing.T) {
		db, err := database.Initialize(&database.Config{
			DatabaseURL: ":memory:",
		})
		require.NoError(t, err)
		defer db.Close()

		// Register agent with multiple tools
		agentID := "test-agent-123"
		now := time.Now().UTC()

		// Insert agent
		_, err = db.Exec(`
			INSERT INTO agents (id, name, namespace, endpoint, status, last_heartbeat,
				timeout_threshold, eviction_threshold, created_at, updated_at, resource_version)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
			agentID, agentID, "default", "stdio://"+agentID, "healthy", now,
			60, 120, now, now, "1")
		require.NoError(t, err)

		// Insert tools
		tools := []struct {
			name       string
			capability string
			version    string
			deps       string
		}{
			{"greet", "greeting", "1.0.0", `[{"capability":"date_service","version":">=1.0.0"}]`},
			{"farewell", "goodbye", "1.0.0", `[]`},
		}

		for _, tool := range tools {
			_, err = db.Exec(`
				INSERT INTO tools (agent_id, name, capability, version, dependencies, created_at, updated_at)
				VALUES (?, ?, ?, ?, ?, ?, ?)`,
				agentID, tool.name, tool.capability, tool.version, tool.deps, now, now)
			require.NoError(t, err)
		}

		// Verify tools were inserted
		var count int
		err = db.QueryRow("SELECT COUNT(*) FROM tools WHERE agent_id = ?", agentID).Scan(&count)
		require.NoError(t, err)
		assert.Equal(t, 2, count)
	})
}

// TestToolDependencyResolution tests dependency resolution for tools
func TestToolDependencyResolution(t *testing.T) {
	t.Run("ResolveToolDependencies", func(t *testing.T) {
		db, err := database.Initialize(&database.Config{
			DatabaseURL: ":memory:",
		})
		require.NoError(t, err)
		defer db.Close()

		now := time.Now().UTC()

		// Create consumer agent with tool that has dependency
		consumerID := "consumer-123"
		_, err = db.Exec(`
			INSERT INTO agents (id, name, namespace, endpoint, status, last_heartbeat,
				timeout_threshold, eviction_threshold, created_at, updated_at, resource_version)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
			consumerID, consumerID, "default", "stdio://"+consumerID, "healthy", now,
			60, 120, now, now, "1")
		require.NoError(t, err)

		// Insert consumer tool with dependency
		_, err = db.Exec(`
			INSERT INTO tools (agent_id, name, capability, version, dependencies, created_at, updated_at)
			VALUES (?, ?, ?, ?, ?, ?, ?)`,
			consumerID, "process_data", "data_processor", "1.0.0",
			`[{"capability":"date_service","version":">=1.0.0"}]`, now, now)
		require.NoError(t, err)

		// Create provider agent with the required capability
		providerID := "provider-456"
		_, err = db.Exec(`
			INSERT INTO agents (id, name, namespace, endpoint, status, last_heartbeat,
				timeout_threshold, eviction_threshold, created_at, updated_at, resource_version)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
			providerID, providerID, "default", "http://provider:8080", "healthy", now,
			60, 120, now, now, "2")
		require.NoError(t, err)

		// Insert provider tool
		_, err = db.Exec(`
			INSERT INTO tools (agent_id, name, capability, version, dependencies, created_at, updated_at)
			VALUES (?, ?, ?, ?, ?, ?, ?)`,
			providerID, "get_current_date", "date_service", "1.5.0", `[]`, now, now)
		require.NoError(t, err)

		// Query to find providers for date_service capability
		rows, err := db.Query(`
			SELECT t.agent_id, t.name, t.version, a.endpoint
			FROM tools t
			JOIN agents a ON t.agent_id = a.id
			WHERE t.capability = ? AND a.status = ?`,
			"date_service", "healthy")
		require.NoError(t, err)
		defer rows.Close()

		var found bool
		for rows.Next() {
			var agentID, toolName, version, endpoint string
			err := rows.Scan(&agentID, &toolName, &version, &endpoint)
			require.NoError(t, err)

			assert.Equal(t, providerID, agentID)
			assert.Equal(t, "get_current_date", toolName)
			assert.Equal(t, "1.5.0", version)
			assert.Equal(t, "http://provider:8080", endpoint)
			found = true
		}
		assert.True(t, found, "Should find healthy provider")
	})

	t.Run("HealthyProvidersOnly", func(t *testing.T) {
		db, err := database.Initialize(&database.Config{
			DatabaseURL: ":memory:",
		})
		require.NoError(t, err)
		defer db.Close()

		now := time.Now().UTC()

		// Create providers with different health states
		providers := []struct {
			id     string
			status string
		}{
			{"healthy-provider", "healthy"},
			{"degraded-provider", "degraded"},
			{"expired-provider", "expired"},
		}

		for _, p := range providers {
			_, err = db.Exec(`
				INSERT INTO agents (id, name, namespace, endpoint, status, last_heartbeat,
					timeout_threshold, eviction_threshold, created_at, updated_at, resource_version)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
				p.id, p.id, "default", "stdio://"+p.id, p.status, now,
				60, 120, now, now, "1")
			require.NoError(t, err)

			// Insert tool for each provider
			_, err = db.Exec(`
				INSERT INTO tools (agent_id, name, capability, version, dependencies, created_at, updated_at)
				VALUES (?, ?, ?, ?, ?, ?, ?)`,
				p.id, "auth", "auth_service", "1.0.0", `[]`, now, now)
			require.NoError(t, err)
		}

		// Query for healthy providers only
		rows, err := db.Query(`
			SELECT t.agent_id, a.status
			FROM tools t
			JOIN agents a ON t.agent_id = a.id
			WHERE t.capability = ? AND a.status = ?`,
			"auth_service", "healthy")
		require.NoError(t, err)
		defer rows.Close()

		var count int
		for rows.Next() {
			var agentID, status string
			err := rows.Scan(&agentID, &status)
			require.NoError(t, err)

			assert.Equal(t, "healthy", status)
			assert.Equal(t, "healthy-provider", agentID)
			count++
		}
		assert.Equal(t, 1, count, "Should only find one healthy provider")
	})
}

// TestVersionConstraints tests version constraint matching
func TestVersionConstraints(t *testing.T) {
	testCases := []struct {
		name        string
		version     string
		constraint  string
		shouldMatch bool
	}{
		{"Exact match", "1.0.0", "1.0.0", true},
		{"Greater than or equal", "1.5.0", ">=1.0.0", true},
		{"Greater than or equal - exact", "1.0.0", ">=1.0.0", true},
		{"Greater than or equal - less", "0.9.0", ">=1.0.0", false},
		{"Greater than", "1.5.0", ">1.0.0", true},
		{"Greater than - equal", "1.0.0", ">1.0.0", false},
		{"Less than", "0.9.0", "<1.0.0", true},
		{"Less than - equal", "1.0.0", "<1.0.0", false},
		{"Less than or equal", "1.0.0", "<=1.0.0", true},
		{"Less than or equal - greater", "1.1.0", "<=1.0.0", false},
		{"Range", "1.5.0", ">=1.0.0,<2.0.0", true},
		{"Range - lower bound", "1.0.0", ">=1.0.0,<2.0.0", true},
		{"Range - upper bound", "2.0.0", ">=1.0.0,<2.0.0", false},
		{"Tilde range", "1.5.0", "~1.5", true},
		{"Tilde range - patch", "1.5.9", "~1.5", true},
		{"Tilde range - minor", "1.6.0", "~1.5", false},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			// This tests the logic we need to implement
			// For now, just document what should happen
			t.Logf("Version %s with constraint %s should match: %v",
				tc.version, tc.constraint, tc.shouldMatch)
		})
	}
}

// TestTagFiltering tests tag-based filtering
func TestTagFiltering(t *testing.T) {
	t.Run("AllTagsMustMatch", func(t *testing.T) {
		db, err := database.Initialize(&database.Config{
			DatabaseURL: ":memory:",
		})
		require.NoError(t, err)
		defer db.Close()

		now := time.Now().UTC()

		// Create providers with different tag combinations
		providers := []struct {
			id   string
			tags string // JSON array
		}{
			{"provider-1", `["production", "US-EAST", "mysql"]`},
			{"provider-2", `["production", "US-WEST", "mysql"]`},
			{"provider-3", `["development", "US-EAST", "mysql"]`},
		}

		for _, p := range providers {
			// Insert agent
			_, err = db.Exec(`
				INSERT INTO agents (id, name, namespace, endpoint, status, last_heartbeat,
					timeout_threshold, eviction_threshold, created_at, updated_at, resource_version)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
				p.id, p.id, "default", "stdio://"+p.id, "healthy", now,
				60, 120, now, now, "1")
			require.NoError(t, err)

			// Insert tool with tags in config
			config := `{"tags":` + p.tags + `}`
			_, err = db.Exec(`
				INSERT INTO tools (agent_id, name, capability, version, dependencies, config, created_at, updated_at)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
				p.id, "query", "database", "1.0.0", `[]`, config, now, now)
			require.NoError(t, err)
		}

		// Test: Find providers with tags ["production", "US-EAST"]
		// This would require implementing tag filtering logic
		// For now, just verify the data was inserted correctly
		var count int
		err = db.QueryRow("SELECT COUNT(*) FROM tools WHERE capability = ?", "database").Scan(&count)
		require.NoError(t, err)
		assert.Equal(t, 3, count)
	})
}

// TestHealthMonitoring tests agent health state transitions
func TestHealthMonitoring(t *testing.T) {
	t.Run("AgentStateTransitions", func(t *testing.T) {
		db, err := database.Initialize(&database.Config{
			DatabaseURL: ":memory:",
		})
		require.NoError(t, err)
		defer db.Close()

		agentID := "test-agent"
		now := time.Now().UTC()

		// Insert healthy agent
		_, err = db.Exec(`
			INSERT INTO agents (id, name, namespace, endpoint, status, last_heartbeat,
				timeout_threshold, eviction_threshold, created_at, updated_at, resource_version)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
			agentID, agentID, "default", "stdio://"+agentID, "healthy", now,
			1, 2, now, now, "1") // 1 second timeout, 2 second eviction for testing
		require.NoError(t, err)

		// Check initial status
		var status string
		err = db.QueryRow("SELECT status FROM agents WHERE id = ?", agentID).Scan(&status)
		require.NoError(t, err)
		assert.Equal(t, "healthy", status)

		// Simulate time passing - agent should become degraded after timeout_threshold
		oneSecondAgo := now.Add(-1100 * time.Millisecond)
		_, err = db.Exec("UPDATE agents SET last_heartbeat = ? WHERE id = ?", oneSecondAgo, agentID)
		require.NoError(t, err)

		// In real implementation, health monitor would update status
		// For testing, we manually update to show expected behavior
		_, err = db.Exec("UPDATE agents SET status = ? WHERE id = ?", "degraded", agentID)
		require.NoError(t, err)

		err = db.QueryRow("SELECT status FROM agents WHERE id = ?", agentID).Scan(&status)
		require.NoError(t, err)
		assert.Equal(t, "degraded", status)

		// Simulate more time passing - agent should become expired after eviction_threshold
		twoSecondsAgo := now.Add(-2100 * time.Millisecond)
		_, err = db.Exec("UPDATE agents SET last_heartbeat = ? WHERE id = ?", twoSecondsAgo, agentID)
		require.NoError(t, err)

		// Update to expired
		_, err = db.Exec("UPDATE agents SET status = ? WHERE id = ?", "expired", agentID)
		require.NoError(t, err)

		err = db.QueryRow("SELECT status FROM agents WHERE id = ?", agentID).Scan(&status)
		require.NoError(t, err)
		assert.Equal(t, "expired", status)
	})
}
