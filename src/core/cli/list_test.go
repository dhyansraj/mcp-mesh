package cli

import (
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestListCommand_ShowFrameworkFlag guards the wiring of the --show-framework
// flag introduced for issue #956 item #15. A regression where this flag is
// removed (or its default flipped) would silently change what `meshctl list
// --tools` prints — this test forces an explicit decision in code review.
func TestListCommand_ShowFrameworkFlag(t *testing.T) {
	cmd := NewListCommand()

	flag := cmd.Flags().Lookup("show-framework")
	require.NotNil(t, flag, "--show-framework flag must be registered on `meshctl list`")
	assert.Equal(t, "false", flag.DefValue,
		"--show-framework must default to false so framework-internal tools stay hidden by default")

	// Setting the flag should round-trip back as a bool.
	require.NoError(t, cmd.Flags().Set("show-framework", "true"))
	val, err := cmd.Flags().GetBool("show-framework")
	require.NoError(t, err)
	assert.True(t, val, "--show-framework=true must parse as bool true")
}

// TestFormatAgentTypeDisplay covers every agent_type string the registry can
// stamp on an AgentInfo, plus the unknown-fallback path. Issue #984: the
// switch was missing the "a2a" case, which made `meshctl list` print
// "Unknown" for any A2A-typed agent. Keep this in lockstep with the SPA's
// getAgentTypeLabel (src/ui/lib/api.ts) — a divergence here is exactly the
// bug we're guarding against.
func TestFormatAgentTypeDisplay(t *testing.T) {
	cases := []struct {
		agentType string
		want      string
	}{
		{"mcp_agent", "Agent"},
		{"api", "API"},
		{"mesh_tool", "Tool"},
		{"decorator_agent", "Agent"},
		{"a2a", "A2A"},
		{"", "Unknown"},
		{"future_unknown_kind", "Unknown"},
	}
	for _, tc := range cases {
		t.Run(tc.agentType, func(t *testing.T) {
			assert.Equal(t, tc.want, formatAgentTypeDisplay(tc.agentType),
				"display label for agent_type=%q", tc.agentType)
		})
	}
}

// --- Supersession model tests (issue #1195) ---------------------------------
//
// Watch-driven dev loops re-register agents under new instance ids on every
// restart, leaving the prior instance unhealthy until the retention purge.
// computeSupersessionView classifies those instances as superseded so the
// table can collapse them; a genuinely-down singleton must stay prominent.

// testAgent builds a minimal EnhancedAgent for supersession tests.
func testAgent(id, name, status string, createdAt time.Time, lastSeen *time.Time) EnhancedAgent {
	return EnhancedAgent{
		ID:            id,
		Name:          name,
		Status:        status,
		CreatedAt:     createdAt,
		LastHeartbeat: lastSeen,
	}
}

func TestComputeSupersessionView_NewestWins(t *testing.T) {
	base := time.Now().Add(-1 * time.Hour)
	agents := []EnhancedAgent{
		testAgent("hello-aaa", "hello", "unhealthy", base, nil),
		testAgent("hello-bbb", "hello", "unhealthy", base.Add(10*time.Minute), nil),
		testAgent("hello-ccc", "hello", "healthy", base.Add(20*time.Minute), nil),
	}

	view := computeSupersessionView(agents)

	assert.True(t, view.superseded["hello-aaa"], "oldest stale instance must be superseded")
	assert.True(t, view.superseded["hello-bbb"], "middle stale instance must be superseded")
	assert.False(t, view.superseded["hello-ccc"], "newest healthy instance must not be superseded")
	assert.Equal(t, 2, view.byName["hello"])
	assert.Equal(t, 2, view.total)
	assert.Equal(t, "hello-ccc", view.newestID["hello"],
		"the newest non-superseded instance anchors the (+N superseded) annotation")
}

func TestComputeSupersessionView_SingletonDownNotSuperseded(t *testing.T) {
	agents := []EnhancedAgent{
		testAgent("solo-aaa", "solo", "unhealthy", time.Now().Add(-30*time.Minute), nil),
	}

	view := computeSupersessionView(agents)

	assert.False(t, view.superseded["solo-aaa"],
		"a genuinely-down agent with no newer instance must stay prominent")
	assert.Equal(t, 0, view.total)
	assert.Equal(t, "solo-aaa", view.newestID["solo"])
}

func TestComputeSupersessionView_NewestUnhealthyGroupStaysProminent(t *testing.T) {
	// All instances down: older ones are superseded, but the newest one is
	// not — it is the genuinely-down representative (counted in the footer's
	// down clause by the default view; a red row under --all).
	base := time.Now().Add(-1 * time.Hour)
	agents := []EnhancedAgent{
		testAgent("svc-old", "svc", "unhealthy", base, nil),
		testAgent("svc-new", "svc", "unhealthy", base.Add(5*time.Minute), nil),
	}

	view := computeSupersessionView(agents)

	assert.True(t, view.superseded["svc-old"])
	assert.False(t, view.superseded["svc-new"],
		"newest instance has no newer sibling so it is genuinely down, not superseded")
	assert.Equal(t, "svc-new", view.newestID["svc"])
}

func TestComputeSupersessionView_HealthyReplicasNeverSuperseded(t *testing.T) {
	base := time.Now().Add(-1 * time.Hour)
	agents := []EnhancedAgent{
		testAgent("api-r1", "api", "healthy", base, nil),
		testAgent("api-r2", "api", "healthy", base.Add(10*time.Minute), nil),
	}

	view := computeSupersessionView(agents)

	assert.False(t, view.superseded["api-r1"],
		"healthy replicas of the same name must never be superseded")
	assert.False(t, view.superseded["api-r2"])
	assert.Equal(t, 0, view.total)
}

func TestComputeSupersessionView_LastSeenTiebreak(t *testing.T) {
	created := time.Now().Add(-1 * time.Hour)
	olderSeen := created.Add(5 * time.Minute)
	newerSeen := created.Add(30 * time.Minute)
	agents := []EnhancedAgent{
		testAgent("tie-aaa", "tie", "unhealthy", created, &olderSeen),
		testAgent("tie-bbb", "tie", "healthy", created, &newerSeen),
	}

	view := computeSupersessionView(agents)

	assert.True(t, view.superseded["tie-aaa"],
		"equal created_at must tiebreak on last_seen: stale instance with older last_seen is superseded")
	assert.False(t, view.superseded["tie-bbb"])
	assert.Equal(t, "tie-bbb", view.newestID["tie"])
}

func TestComputeSupersessionView_MixedNames(t *testing.T) {
	base := time.Now().Add(-1 * time.Hour)
	agents := []EnhancedAgent{
		testAgent("hello-old", "hello", "unhealthy", base, nil),
		testAgent("hello-new", "hello", "healthy", base.Add(10*time.Minute), nil),
		testAgent("weather-1", "weather", "healthy", base, nil),
		testAgent("down-solo", "down", "unhealthy", base, nil),
	}

	view := computeSupersessionView(agents)

	assert.True(t, view.superseded["hello-old"])
	assert.False(t, view.superseded["hello-new"])
	assert.False(t, view.superseded["weather-1"])
	assert.False(t, view.superseded["down-solo"], "down singleton stays prominent")
	assert.Equal(t, 1, view.total)
	assert.Equal(t, 1, view.byName["hello"])
	assert.Equal(t, 0, view.byName["weather"])
	assert.Equal(t, 0, view.byName["down"])
}

func TestComputeSupersessionView_BlockingCapabilityStaysProminent(t *testing.T) {
	// A stale instance that declares a capability some live agent has an
	// unresolved dependency on might explain the gap — it must not be dimmed
	// or collapsed.
	base := time.Now().Add(-1 * time.Hour)
	provider := testAgent("provider-old", "provider", "unhealthy", base, nil)
	provider.Tools = []ToolInfo{{Name: "date_service", Capability: "date_service"}}
	providerNew := testAgent("provider-new", "provider", "healthy", base.Add(10*time.Minute), nil)

	consumer := testAgent("consumer-1", "consumer", "healthy", base, nil)
	consumer.DependencyResolutions = []DependencyResolution{
		{Capability: "date_service", Status: "unresolved"},
	}

	view := computeSupersessionView([]EnhancedAgent{provider, providerNew, consumer})

	assert.False(t, view.superseded["provider-old"],
		"stale instance declaring a capability matching a live agent's unresolved dependency must stay prominent")
	assert.True(t, view.blocking["provider-old"],
		"blocking instance must be recorded so the default view promotes it to a named row")
	assert.Equal(t, 0, view.total)
}

func TestComputeSupersessionView_BlockingDownSingleton(t *testing.T) {
	// A genuinely-down singleton (no siblings at all) that explains a live
	// agent's dependency gap must be marked blocking too — the promotion is
	// independent of sibling ordering.
	base := time.Now().Add(-1 * time.Hour)
	provider := testAgent("provider-solo", "provider", "unhealthy", base, nil)
	provider.Tools = []ToolInfo{{Name: "date_service", Capability: "date_service"}}

	consumer := testAgent("consumer-1", "consumer", "healthy", base, nil)
	consumer.DependencyResolutions = []DependencyResolution{
		{Capability: "date_service", Status: "unresolved"},
	}

	view := computeSupersessionView([]EnhancedAgent{provider, consumer})

	assert.True(t, view.blocking["provider-solo"])
	assert.False(t, view.superseded["provider-solo"])
}

func TestComputeSupersessionView_ResolvedDepsAllowDimming(t *testing.T) {
	// Same shape as above, but the consumer's dependency is resolved — the
	// stale provider instance no longer explains anything and is superseded.
	base := time.Now().Add(-1 * time.Hour)
	provider := testAgent("provider-old", "provider", "unhealthy", base, nil)
	provider.Tools = []ToolInfo{{Name: "date_service", Capability: "date_service"}}
	providerNew := testAgent("provider-new", "provider", "healthy", base.Add(10*time.Minute), nil)

	consumer := testAgent("consumer-1", "consumer", "healthy", base, nil)
	consumer.DependencyResolutions = []DependencyResolution{
		{Capability: "date_service", Status: "available"},
	}

	view := computeSupersessionView([]EnhancedAgent{provider, providerNew, consumer})

	assert.True(t, view.superseded["provider-old"],
		"with all live dependencies resolved, the stale instance is plain superseded")
	assert.Equal(t, 1, view.total)
}

func TestCollapseDefaultView(t *testing.T) {
	base := time.Now().Add(-1 * time.Hour)

	t.Run("down agent hidden, named row contract preserved", func(t *testing.T) {
		agents := []EnhancedAgent{
			testAgent("hello-old", "hello", "unhealthy", base, nil),
			testAgent("hello-new", "hello", "healthy", base.Add(10*time.Minute), nil),
			testAgent("down-solo", "down", "unhealthy", base, nil),
		}
		view := computeSupersessionView(agents)

		kept, summary := collapseDefaultView(agents, view)

		require.Len(t, kept, 1)
		assert.Equal(t, "hello-new", kept[0].ID)
		assert.Equal(t, 1, summary.hiddenSuperseded)
		assert.Equal(t, 1, summary.hiddenDownAgents,
			"a non-blocking down agent must be hidden and counted namelessly — `meshctl list | grep -q <name>` matching must imply a live agent")
	})

	t.Run("blocking down instance promoted to named row", func(t *testing.T) {
		provider := testAgent("provider-solo", "provider", "unhealthy", base, nil)
		provider.Tools = []ToolInfo{{Name: "date_service", Capability: "date_service"}}
		consumer := testAgent("consumer-1", "consumer", "healthy", base, nil)
		consumer.DependencyResolutions = []DependencyResolution{
			{Capability: "date_service", Status: "unresolved"},
		}
		agents := []EnhancedAgent{provider, consumer}
		view := computeSupersessionView(agents)

		kept, summary := collapseDefaultView(agents, view)

		require.Len(t, kept, 2)
		keptIDs := []string{kept[0].ID, kept[1].ID}
		assert.Contains(t, keptIDs, "provider-solo",
			"down instance explaining a live dependency gap must stay visible as a named row")
		assert.Equal(t, 0, summary.hiddenDownAgents)
		assert.Equal(t, 0, summary.hiddenSuperseded)
	})

	t.Run("all instances of a name down counts the name once", func(t *testing.T) {
		agents := []EnhancedAgent{
			testAgent("svc-old", "svc", "unhealthy", base, nil),
			testAgent("svc-new", "svc", "unhealthy", base.Add(5*time.Minute), nil),
		}
		view := computeSupersessionView(agents)

		kept, summary := collapseDefaultView(agents, view)

		assert.Empty(t, kept)
		assert.Equal(t, 1, summary.hiddenSuperseded)
		assert.Equal(t, 1, summary.hiddenDownAgents,
			"down clause counts distinct names, not instances")
	})
}

// TestCollapseDefaultView_PostFilterConsistency guards the rule that the
// (+N superseded) annotation and the footer counts derive from the SAME
// post --filter/--since set: a view computed over a filtered subset that
// excludes the newer sibling must classify the stale instance as down (it has
// no newer sibling within the visible set), not superseded — so the footer
// can never report superseded instances the annotation set doesn't contain.
func TestCollapseDefaultView_PostFilterConsistency(t *testing.T) {
	base := time.Now().Add(-1 * time.Hour)
	full := []EnhancedAgent{
		testAgent("hello-old", "hello", "unhealthy", base, nil),
		testAgent("hello-new", "hello", "healthy", base.Add(10*time.Minute), nil),
	}
	globalView := computeSupersessionView(full)
	assert.True(t, globalView.superseded["hello-old"], "globally the old instance is superseded")

	// Simulate a --since window that excludes the newer sibling.
	filtered := full[:1]
	localView := computeSupersessionView(filtered)
	kept, summary := collapseDefaultView(filtered, localView)

	assert.Empty(t, kept)
	assert.Equal(t, 0, summary.hiddenSuperseded)
	assert.Equal(t, 0, localView.byName["hello"],
		"annotation count and footer count agree because both come from the filtered set")
	assert.Equal(t, 1, summary.hiddenDownAgents)
}

func TestFormatListFooter(t *testing.T) {
	t.Run("no hidden clauses when zero", func(t *testing.T) {
		footer := formatListFooter(7, 7, listDefaultSummary{})
		assert.Equal(t, "7 agents (7 healthy)", footer)
	})

	t.Run("down and superseded clauses", func(t *testing.T) {
		footer := formatListFooter(3, 3, listDefaultSummary{hiddenSuperseded: 2, hiddenDownAgents: 1})
		assert.Contains(t, footer, "3 agents (3 healthy)")
		assert.Contains(t, footer, "1 agent down (use --all)")
		assert.Contains(t, footer, "2 superseded hidden")
		assert.Contains(t, footer, colorRed+"1 agent down",
			"the down clause is the alarm surface and renders red")
		assert.Contains(t, footer, colorGray+"2 superseded hidden",
			"the superseded clause is neutral gray")
		assert.NotContains(t, footer, "superseded hidden (use --all)",
			"--all hint is not repeated when the down clause already carries it")
	})

	t.Run("superseded-only clause carries the --all hint", func(t *testing.T) {
		footer := formatListFooter(7, 7, listDefaultSummary{hiddenSuperseded: 8})
		assert.Contains(t, footer, "8 superseded hidden (use --all)")
		assert.NotContains(t, footer, "down")
	})

	t.Run("plural down clause", func(t *testing.T) {
		footer := formatListFooter(1, 1, listDefaultSummary{hiddenDownAgents: 2})
		assert.Contains(t, footer, "1 agent (1 healthy)")
		assert.Contains(t, footer, "2 agents down (use --all)")
	})
}

func TestFormatRegistryAgentCounts(t *testing.T) {
	t.Run("splits superseded out of unhealthy", func(t *testing.T) {
		s := formatRegistryAgentCounts(7, 9, 8)
		assert.Contains(t, s, "7 healthy")
		assert.Contains(t, s, "1 unhealthy", "genuine unhealthy = unhealthy - superseded")
		assert.Contains(t, s, "8 superseded")
		// Genuine unhealthy is the alarm surface (red); superseded is neutral (gray).
		assert.Contains(t, s, colorRed+"1 unhealthy")
		assert.Contains(t, s, colorGray+"8 superseded")
	})

	t.Run("all superseded omits unhealthy clause", func(t *testing.T) {
		s := formatRegistryAgentCounts(7, 8, 8)
		assert.NotContains(t, s, "unhealthy")
		assert.Contains(t, s, "8 superseded")
	})

	t.Run("no unhealthy at all", func(t *testing.T) {
		s := formatRegistryAgentCounts(3, 0, 0)
		assert.Equal(t, fmt.Sprintf("%s3 healthy%s", colorGreen, colorReset), s)
	})

	t.Run("clamps superseded to unhealthy on fetch skew", func(t *testing.T) {
		s := formatRegistryAgentCounts(3, 2, 5)
		assert.Contains(t, s, "2 superseded")
		assert.NotContains(t, s, "unhealthy")
	})
}

func TestFormatSupersededAnnotation(t *testing.T) {
	assert.Empty(t, formatSupersededAnnotation(0))
	assert.Empty(t, formatSupersededAnnotation(-1))
	assert.Contains(t, formatSupersededAnnotation(2), "(+2 superseded)")
}
