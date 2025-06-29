package database

import (
	"context"
	"os"
	"testing"
	"time"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestSQLiteCompatibility tests Ent with SQLite database
func TestSQLiteCompatibility(t *testing.T) {
	// Create temporary SQLite database
	tempFile := "/tmp/test_ent_sqlite.db"
	defer os.Remove(tempFile)

	config := &Config{
		DatabaseURL:        tempFile,
		EnableForeignKeys:  true,
		MaxOpenConnections: 5,
		MaxIdleConnections: 2,
		ConnMaxLifetime:    300,
	}

	// Initialize Ent database
	entDB, err := InitializeEnt(config, false)
	require.NoError(t, err, "Failed to initialize SQLite database with Ent")
	defer entDB.Close()

	// Test basic operations
	testBasicEntOperations(t, entDB)
}

// TestPostgreSQLCompatibility tests Ent with PostgreSQL database
// This test will only run if PostgreSQL is available
func TestPostgreSQLCompatibility(t *testing.T) {
	// Skip if no PostgreSQL connection string is provided
	pgURL := os.Getenv("TEST_POSTGRES_URL")
	if pgURL == "" {
		t.Skip("Skipping PostgreSQL test - set TEST_POSTGRES_URL environment variable")
	}

	config := &Config{
		DatabaseURL:        pgURL,
		MaxOpenConnections: 5,
		MaxIdleConnections: 2,
		ConnMaxLifetime:    300,
	}

	// Initialize Ent database
	entDB, err := InitializeEnt(config, false)
	require.NoError(t, err, "Failed to initialize PostgreSQL database with Ent")
	defer entDB.Close()

	// Test basic operations
	testBasicEntOperations(t, entDB)
}

// testBasicEntOperations tests basic CRUD operations with Ent
func testBasicEntOperations(t *testing.T, entDB *EntDatabase) {
	ctx := context.Background()

	// Test Agent creation
	testAgent, err := entDB.Agent.Create().
		SetID("test-agent-123").
		SetAgentType(agent.AgentTypeMcpAgent).
		SetName("Test Agent").
		SetNamespace("test").
		SetVersion("1.0.0").
		SetHTTPHost("localhost").
		SetHTTPPort(8080).
		Save(ctx)

	require.NoError(t, err, "Failed to create test agent")
	assert.Equal(t, "test-agent-123", testAgent.ID)
	assert.Equal(t, "Test Agent", testAgent.Name)
	assert.Equal(t, "test", testAgent.Namespace)

	// Test Agent query
	foundAgent, err := entDB.Agent.Query().
		Where(agent.IDEQ("test-agent-123")).
		Only(ctx)

	require.NoError(t, err, "Failed to query test agent")
	assert.Equal(t, testAgent.ID, foundAgent.ID)

	// Test Capability creation
	testCapability, err := entDB.Capability.Create().
		SetAgentID("test-agent-123").
		SetFunctionName("test_function").
		SetCapability("test_capability").
		SetVersion("1.0.0").
		SetDescription("Test capability description").
		SetTags([]string{"test", "example"}).
		Save(ctx)

	require.NoError(t, err, "Failed to create test capability")
	assert.Equal(t, "test_function", testCapability.FunctionName)
	assert.Equal(t, "test_capability", testCapability.Capability)

	// Test Registry Event creation
	testEvent, err := entDB.RegistryEvent.Create().
		SetEventType("register").
		SetAgentID("test-agent-123").
		SetTimestamp(time.Now().UTC()).
		SetData(map[string]interface{}{
			"test": "data",
		}).
		Save(ctx)

	require.NoError(t, err, "Failed to create test event")
	assert.Equal(t, "register", string(testEvent.EventType))

	// Test relationships - load agent with capabilities
	agentWithCapabilities, err := entDB.Agent.Query().
		Where(agent.IDEQ("test-agent-123")).
		WithCapabilities().
		Only(ctx)

	require.NoError(t, err, "Failed to load agent with capabilities")
	assert.Len(t, agentWithCapabilities.Edges.Capabilities, 1)
	assert.Equal(t, "test_capability", agentWithCapabilities.Edges.Capabilities[0].Capability)

	// Test agent update
	updatedAgent, err := testAgent.Update().
		SetName("Updated Test Agent").
		SetTotalDependencies(5).
		SetDependenciesResolved(3).
		Save(ctx)

	require.NoError(t, err, "Failed to update test agent")
	assert.Equal(t, "Updated Test Agent", updatedAgent.Name)
	assert.Equal(t, 5, updatedAgent.TotalDependencies)
	assert.Equal(t, 3, updatedAgent.DependenciesResolved)

	// Test deletion
	err = entDB.Agent.DeleteOne(testAgent).Exec(ctx)
	require.NoError(t, err, "Failed to delete test agent")

	// Verify agent is deleted
	_, err = entDB.Agent.Query().Where(agent.IDEQ("test-agent-123")).Only(ctx)
	assert.True(t, ent.IsNotFound(err), "Agent should be deleted")

	// Verify capabilities are deleted (cascade)
	capabilities, err := entDB.Capability.Query().All(ctx)
	require.NoError(t, err, "Failed to query capabilities after agent deletion")
	assert.Empty(t, capabilities, "Capabilities should be deleted with agent")
}

// TestDatabaseStats tests the GetStats method with both databases
func TestDatabaseStats(t *testing.T) {
	// Test with SQLite
	tempFile := "/tmp/test_ent_stats.db"
	defer os.Remove(tempFile)

	config := &Config{
		DatabaseURL: tempFile,
	}

	entDB, err := InitializeEnt(config, false)
	require.NoError(t, err)
	defer entDB.Close()

	// Create test data
	ctx := context.Background()
	_, err = entDB.Agent.Create().
		SetID("stats-test-agent").
		SetName("Stats Test").
		SetNamespace("default").
		Save(ctx)
	require.NoError(t, err)

	// Test stats
	stats, err := entDB.GetStats()
	require.NoError(t, err, "Failed to get database stats")

	assert.Contains(t, stats, "total_agents")
	assert.Contains(t, stats, "agents_by_namespace")
	assert.Contains(t, stats, "unique_capabilities")
	assert.Contains(t, stats, "recent_events_last_hour")

	totalAgents, ok := stats["total_agents"].(int)
	assert.True(t, ok, "total_agents should be an integer")
	assert.Equal(t, 1, totalAgents)
}

// TestCrossArchitectureCompatibility ensures Ent works on different architectures
func TestCrossArchitectureCompatibility(t *testing.T) {
	// This test verifies that Ent generates proper Go code that works across architectures
	tempFile := "/tmp/test_ent_arch.db"
	defer os.Remove(tempFile)

	config := &Config{
		DatabaseURL: tempFile,
	}

	entDB, err := InitializeEnt(config, false)
	require.NoError(t, err, "Ent should work on current architecture")
	defer entDB.Close()

	// Test that we can perform basic operations
	ctx := context.Background()

	// Test integer handling (important for different architectures)
	agent, err := entDB.Agent.Create().
		SetID("arch-test").
		SetName("Architecture Test").
		SetHTTPPort(65535). // Test max port number
		SetTotalDependencies(999999). // Test large integers
		Save(ctx)

	require.NoError(t, err, "Should handle integers properly across architectures")
	assert.Equal(t, 65535, agent.HTTPPort)
	assert.Equal(t, 999999, agent.TotalDependencies)

	// Test timestamp handling
	now := time.Now().UTC()
	event, err := entDB.RegistryEvent.Create().
		SetEventType("register").
		SetAgentID("arch-test").
		SetTimestamp(now).
		SetData(map[string]interface{}{}).
		Save(ctx)

	require.NoError(t, err, "Should handle timestamps properly")
	assert.WithinDuration(t, now, event.Timestamp, time.Second)
}
