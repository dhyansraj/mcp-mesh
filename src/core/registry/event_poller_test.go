package registry

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/registry/generated"
)

func ptr[T any](v T) *T {
	return &v
}

func TestDiffAgents_NewAgent(t *testing.T) {
	lastSnap := make(map[string]agentSnapshot)

	rt := generated.AgentInfoRuntime("python")
	agents := []generated.AgentInfo{
		{
			Id:                   "agent-1",
			Name:                 "greeter",
			Status:               "healthy",
			Runtime:              &rt,
			TotalDependencies:    2,
			DependenciesResolved: 1,
		},
	}

	events := diffAgents(lastSnap, agents)
	require.Len(t, events, 1)
	assert.Equal(t, "agent_registered", events[0].Type)
	assert.Equal(t, "agent-1", events[0].AgentID)
	assert.Equal(t, "greeter", events[0].AgentName)
	assert.Equal(t, "python", events[0].Runtime)
	assert.Equal(t, "healthy", events[0].Status)
	assert.Equal(t, 2, events[0].Data["total_dependencies"])
	assert.Equal(t, 1, events[0].Data["dependencies_resolved"])

	// lastSnap should now contain the agent
	require.Contains(t, lastSnap, "agent-1")
	assert.Equal(t, "greeter", lastSnap["agent-1"].Name)
}

func TestDiffAgents_AgentDeregistered(t *testing.T) {
	lastSnap := map[string]agentSnapshot{
		"agent-old": {
			Name:    "old-agent",
			Status:  "healthy",
			Runtime: "java",
		},
	}

	// Empty agent list: agent-old is gone
	events := diffAgents(lastSnap, []generated.AgentInfo{})
	require.Len(t, events, 1)
	assert.Equal(t, "agent_deregistered", events[0].Type)
	assert.Equal(t, "agent-old", events[0].AgentID)
	assert.Equal(t, "old-agent", events[0].AgentName)
	assert.Equal(t, "java", events[0].Runtime)

	// lastSnap should be empty now
	assert.Empty(t, lastSnap)
}

func TestDiffAgents_StatusChange(t *testing.T) {
	lastSnap := map[string]agentSnapshot{
		"agent-1": {
			Name:   "svc",
			Status: "healthy",
		},
	}

	agents := []generated.AgentInfo{
		{
			Id:     "agent-1",
			Name:   "svc",
			Status: "unhealthy",
		},
	}

	events := diffAgents(lastSnap, agents)
	require.Len(t, events, 1)
	assert.Equal(t, "agent_unhealthy", events[0].Type)
	assert.Equal(t, "agent-1", events[0].AgentID)
	assert.Equal(t, "unhealthy", events[0].Status)
	assert.Equal(t, "healthy", events[0].Data["previous_status"])
}

func TestDiffAgents_StatusChangeToHealthy(t *testing.T) {
	lastSnap := map[string]agentSnapshot{
		"agent-1": {
			Name:   "svc",
			Status: "unhealthy",
		},
	}

	agents := []generated.AgentInfo{
		{
			Id:     "agent-1",
			Name:   "svc",
			Status: "healthy",
		},
	}

	events := diffAgents(lastSnap, agents)
	require.Len(t, events, 1)
	assert.Equal(t, "agent_healthy", events[0].Type)
}

func TestDiffAgents_DependencyResolved(t *testing.T) {
	lastSnap := map[string]agentSnapshot{
		"agent-1": {
			Name:                 "svc",
			Status:               "healthy",
			DependenciesResolved: 1,
			TotalDependencies:    3,
		},
	}

	agents := []generated.AgentInfo{
		{
			Id:                   "agent-1",
			Name:                 "svc",
			Status:               "healthy",
			DependenciesResolved: 2,
			TotalDependencies:    3,
		},
	}

	events := diffAgents(lastSnap, agents)
	require.Len(t, events, 1)
	assert.Equal(t, "dependency_resolved", events[0].Type)
	assert.Equal(t, 1, events[0].Data["previous_resolved"])
	assert.Equal(t, 2, events[0].Data["current_resolved"])
	assert.Equal(t, 3, events[0].Data["total"])
}

func TestDiffAgents_DependencyLost(t *testing.T) {
	lastSnap := map[string]agentSnapshot{
		"agent-1": {
			Name:                 "svc",
			Status:               "healthy",
			DependenciesResolved: 3,
			TotalDependencies:    3,
		},
	}

	agents := []generated.AgentInfo{
		{
			Id:                   "agent-1",
			Name:                 "svc",
			Status:               "healthy",
			DependenciesResolved: 2,
			TotalDependencies:    3,
		},
	}

	events := diffAgents(lastSnap, agents)
	require.Len(t, events, 1)
	assert.Equal(t, "dependency_lost", events[0].Type)
}

func TestDiffAgents_NoChange(t *testing.T) {
	lastSnap := map[string]agentSnapshot{
		"agent-1": {
			Name:                 "svc",
			Status:               "healthy",
			Runtime:              "python",
			DependenciesResolved: 2,
			TotalDependencies:    2,
		},
	}

	rt := generated.AgentInfoRuntime("python")
	agents := []generated.AgentInfo{
		{
			Id:                   "agent-1",
			Name:                 "svc",
			Status:               "healthy",
			Runtime:              &rt,
			DependenciesResolved: 2,
			TotalDependencies:    2,
		},
	}

	events := diffAgents(lastSnap, agents)
	assert.Empty(t, events)
}

func TestDiffAgents_MultipleChanges(t *testing.T) {
	lastSnap := map[string]agentSnapshot{
		"agent-1": {
			Name:                 "svc",
			Status:               "healthy",
			DependenciesResolved: 1,
			TotalDependencies:    2,
		},
	}

	// Status changed AND dependencies changed
	agents := []generated.AgentInfo{
		{
			Id:                   "agent-1",
			Name:                 "svc",
			Status:               "unhealthy",
			DependenciesResolved: 0,
			TotalDependencies:    2,
		},
	}

	events := diffAgents(lastSnap, agents)
	require.Len(t, events, 2)

	types := make(map[string]bool)
	for _, e := range events {
		types[e.Type] = true
	}
	assert.True(t, types["agent_unhealthy"])
	assert.True(t, types["dependency_lost"])
}

func TestDiffAgents_NilRuntime(t *testing.T) {
	lastSnap := make(map[string]agentSnapshot)

	agents := []generated.AgentInfo{
		{
			Id:      "agent-no-rt",
			Name:    "mystery",
			Status:  "healthy",
			Runtime: nil,
		},
	}

	events := diffAgents(lastSnap, agents)
	require.Len(t, events, 1)
	assert.Equal(t, "", events[0].Runtime)
}
