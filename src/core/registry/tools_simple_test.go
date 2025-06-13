package registry

import (
	"database/sql"
	"testing"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// setupSimpleTestDB creates a minimal database for testing tools functionality
func setupSimpleTestDB(t *testing.T) (*sql.DB, func()) {
	db, err := sql.Open("sqlite3", ":memory:")
	require.NoError(t, err)

	// Create essential tables
	schemas := []string{
		`CREATE TABLE agents (
			id TEXT PRIMARY KEY,
			name TEXT NOT NULL,
			namespace TEXT NOT NULL DEFAULT 'default',
			endpoint TEXT NOT NULL,
			status TEXT NOT NULL DEFAULT 'healthy',
			last_heartbeat TIMESTAMP,
			timeout_threshold INTEGER DEFAULT 60,
			eviction_threshold INTEGER DEFAULT 120,
			created_at TIMESTAMP NOT NULL,
			updated_at TIMESTAMP NOT NULL,
			resource_version TEXT NOT NULL
		)`,
		`CREATE TABLE tools (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			agent_id TEXT NOT NULL,
			name TEXT NOT NULL,
			capability TEXT NOT NULL,
			version TEXT DEFAULT '1.0.0',
			dependencies TEXT DEFAULT '[]',
			config TEXT DEFAULT '{}',
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
			UNIQUE(agent_id, name)
		)`,
	}

	for _, schema := range schemas {
		_, err := db.Exec(schema)
		require.NoError(t, err)
	}

	cleanup := func() {
		db.Close()
	}

	return db, cleanup
}

// TestSimpleToolsRegistration tests basic tool registration
func TestSimpleToolsRegistration(t *testing.T) {
	t.Run("RegisterAndQueryTools", func(t *testing.T) {
		db, cleanup := setupSimpleTestDB(t)
		defer cleanup()

		// Register agent with multiple tools
		agentID := "test-agent-123"
		now := time.Now().UTC()

		// Insert agent
		_, err := db.Exec(`
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

		// Verify tool details
		rows, err := db.Query("SELECT name, capability, version FROM tools WHERE agent_id = ? ORDER BY name", agentID)
		require.NoError(t, err)
		defer rows.Close()

		var tools_found []struct {
			name       string
			capability string
			version    string
		}

		for rows.Next() {
			var tool struct {
				name       string
				capability string
				version    string
			}
			err := rows.Scan(&tool.name, &tool.capability, &tool.version)
			require.NoError(t, err)
			tools_found = append(tools_found, tool)
		}

		assert.Len(t, tools_found, 2)
		assert.Equal(t, "farewell", tools_found[0].name)
		assert.Equal(t, "goodbye", tools_found[0].capability)
		assert.Equal(t, "greet", tools_found[1].name)
		assert.Equal(t, "greeting", tools_found[1].capability)
	})
}

// TestSimpleDependencyResolution tests basic dependency resolution
func TestSimpleDependencyResolution(t *testing.T) {
	t.Run("FindHealthyProviders", func(t *testing.T) {
		db, cleanup := setupSimpleTestDB(t)
		defer cleanup()

		now := time.Now().UTC()

		// Create consumer agent with tool that has dependency
		consumerID := "consumer-123"
		_, err := db.Exec(`
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

	t.Run("OnlyHealthyProviders", func(t *testing.T) {
		db, cleanup := setupSimpleTestDB(t)
		defer cleanup()

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
			_, err := db.Exec(`
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

// TestSimpleHealthStates tests agent health state management
func TestSimpleHealthStates(t *testing.T) {
	t.Run("AgentStateTransitions", func(t *testing.T) {
		db, cleanup := setupSimpleTestDB(t)
		defer cleanup()

		agentID := "test-agent"
		now := time.Now().UTC()

		// Insert healthy agent
		_, err := db.Exec(`
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

		// Update status to degraded
		_, err = db.Exec("UPDATE agents SET status = ? WHERE id = ?", "degraded", agentID)
		require.NoError(t, err)

		err = db.QueryRow("SELECT status FROM agents WHERE id = ?", agentID).Scan(&status)
		require.NoError(t, err)
		assert.Equal(t, "degraded", status)

		// Update status to expired
		_, err = db.Exec("UPDATE agents SET status = ? WHERE id = ?", "expired", agentID)
		require.NoError(t, err)

		err = db.QueryRow("SELECT status FROM agents WHERE id = ?", agentID).Scan(&status)
		require.NoError(t, err)
		assert.Equal(t, "expired", status)

		// Health check should exclude expired agents
		var count int
		err = db.QueryRow("SELECT COUNT(*) FROM agents WHERE status = ?", "healthy").Scan(&count)
		require.NoError(t, err)
		assert.Equal(t, 0, count)
	})
}
