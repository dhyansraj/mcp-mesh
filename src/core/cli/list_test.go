package cli

import (
	"encoding/json"
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

// TestRegistryCountsDiscloseDownBuckets is an end-to-end guard over issue #1198:
// the header count surface must route a blocking down instance to the red
// "unhealthy" alarm while an orphaned non-blocking down instance is disclosed in
// gray as "inactive" — never red. It mirrors how outputDockerComposeStyle feeds
// the headerView into the count formatter (headerView.total superseded,
// len(headerView.blocking) blocking).
func TestRegistryCountsDiscloseDownBuckets(t *testing.T) {
	base := time.Now().Add(-1 * time.Hour)

	// provider-solo is down AND explains consumer-1's unresolved dependency:
	// genuine blocking alarm.
	provider := testAgent("provider-solo", "provider", "unhealthy", base, nil)
	provider.Tools = []ToolInfo{{Name: "date_service", Capability: "date_service"}}
	consumer := testAgent("consumer-1", "consumer", "healthy", base, nil)
	consumer.DependencyResolutions = []DependencyResolution{
		{Capability: "date_service", Status: "unresolved"},
	}
	// stale-solo is down, has no healthy replacement and blocks nothing: an
	// orphaned non-blocking down instance.
	stale := testAgent("stale-solo", "stale", "unhealthy", base, nil)

	agents := []EnhancedAgent{provider, consumer, stale}
	view := computeSupersessionView(agents)

	require.True(t, view.blocking["provider-solo"], "provider-solo must be the blocking down instance")
	require.False(t, view.blocking["stale-solo"], "stale-solo blocks nothing")
	require.False(t, view.superseded["stale-solo"], "stale-solo has no healthy replacement, so it is not superseded")
	require.Equal(t, 0, view.total, "no superseded instances in this fixture")

	// Registry reports 1 healthy (consumer) and 2 unhealthy (provider + stale).
	// The header derives superseded from view.total and blocking from
	// len(view.blocking), exactly as showRegistryStatus does.
	s := formatRegistryAgentCounts(1, 2, view.total, len(view.blocking))

	assert.Contains(t, s, colorRed+"1 unhealthy",
		"the blocking down instance is the genuine alarm and renders red")
	assert.Contains(t, s, colorGray+"1 inactive",
		"the orphaned non-blocking down instance is a muted gray 'inactive' disclosure, not red")
	assert.NotContains(t, s, "2 unhealthy",
		"a down instance that blocks nothing must not inflate the red unhealthy count")

	// And the footer (orphaned down hidden, blocking promoted to a row).
	_, summary := collapseDefaultView(agents, view)
	require.Equal(t, 1, summary.hiddenDownAgents, "only the orphaned down instance is hidden")
	footer := formatListFooter(2, 1, summary)
	assert.Contains(t, footer, colorGray+"1 inactive instance hidden",
		"the hidden orphan is disclosed as gray inactive in the footer, not red 'agent down'")
	assert.NotContains(t, footer, colorRed,
		"nothing in the footer is a genuine alarm: the blocking instance is a visible red row, not a footer count")
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

	t.Run("inactive and superseded clauses", func(t *testing.T) {
		footer := formatListFooter(3, 3, listDefaultSummary{hiddenSuperseded: 2, hiddenDownAgents: 1})
		assert.Contains(t, footer, "3 agents (3 healthy)")
		assert.Contains(t, footer, "1 inactive instance hidden (use --all)")
		assert.Contains(t, footer, "2 superseded hidden")
		// Orphaned non-blocking down instances block nothing, so they are a
		// muted gray "inactive" disclosure rather than a red "agent down"
		// alarm (issue #1198).
		assert.Contains(t, footer, colorGray+"1 inactive instance hidden",
			"a hidden non-blocking down instance is a neutral gray disclosure, not a red alarm")
		assert.NotContains(t, footer, colorRed,
			"no clause in this footer is a genuine alarm, so nothing renders red")
		assert.NotContains(t, footer, "agent down",
			"the alarming 'agent down' wording is reserved; hidden orphans read as 'inactive'")
		assert.Contains(t, footer, colorGray+"2 superseded hidden",
			"the superseded clause is neutral gray")
		assert.NotContains(t, footer, "superseded hidden (use --all)",
			"--all hint is not repeated when the inactive clause already carries it")
	})

	t.Run("superseded-only clause carries the --all hint", func(t *testing.T) {
		footer := formatListFooter(7, 7, listDefaultSummary{hiddenSuperseded: 8})
		assert.Contains(t, footer, "8 superseded hidden (use --all)")
		assert.NotContains(t, footer, "inactive")
	})

	t.Run("plural inactive clause", func(t *testing.T) {
		footer := formatListFooter(1, 1, listDefaultSummary{hiddenDownAgents: 2})
		assert.Contains(t, footer, "1 agent (1 healthy)")
		assert.Contains(t, footer, "2 inactive instances hidden (use --all)")
		assert.NotContains(t, footer, colorRed)
	})
}

func TestFormatRegistryAgentCounts(t *testing.T) {
	t.Run("blocking down is red unhealthy, superseded is gray", func(t *testing.T) {
		// 9 down total: 8 superseded, of the remaining 1 genuine all 1 blocks.
		s := formatRegistryAgentCounts(7, 9, 8, 1)
		assert.Contains(t, s, "7 healthy")
		assert.Contains(t, s, "1 unhealthy", "blocking down instances are the red alarm")
		assert.Contains(t, s, "8 superseded")
		// Only the genuinely-blocking down count is the alarm surface (red);
		// superseded is neutral (gray).
		assert.Contains(t, s, colorRed+"1 unhealthy")
		assert.Contains(t, s, colorGray+"8 superseded")
		assert.NotContains(t, s, "inactive")
	})

	t.Run("orphaned non-blocking down is gray inactive, not red", func(t *testing.T) {
		// 3 down total: 0 superseded, 0 blocking -> all 3 orphaned/inactive.
		s := formatRegistryAgentCounts(5, 3, 0, 0)
		assert.Contains(t, s, "5 healthy")
		assert.Contains(t, s, "3 inactive",
			"orphaned non-blocking down instances disclose as gray 'inactive', not red 'unhealthy'")
		assert.Contains(t, s, colorGray+"3 inactive")
		assert.NotContains(t, s, "unhealthy",
			"a down instance that blocks nothing must not inflate the red unhealthy count (issue #1198)")
		assert.NotContains(t, s, colorRed)
	})

	t.Run("splits down into red blocking and gray inactive", func(t *testing.T) {
		// 5 down total: 1 superseded, of the remaining 4 genuine 1 blocks and
		// 3 are inactive orphans.
		s := formatRegistryAgentCounts(2, 5, 1, 1)
		assert.Contains(t, s, colorRed+"1 unhealthy", "only the blocking down instance is red")
		assert.Contains(t, s, colorGray+"3 inactive", "non-blocking orphans are gray inactive")
		assert.Contains(t, s, colorGray+"1 superseded")
	})

	t.Run("all superseded omits unhealthy and inactive clauses", func(t *testing.T) {
		s := formatRegistryAgentCounts(7, 8, 8, 0)
		assert.NotContains(t, s, "unhealthy")
		assert.NotContains(t, s, "inactive")
		assert.Contains(t, s, "8 superseded")
	})

	t.Run("no unhealthy at all", func(t *testing.T) {
		s := formatRegistryAgentCounts(3, 0, 0, 0)
		assert.Equal(t, fmt.Sprintf("%s3 healthy%s", colorGreen, colorReset), s)
	})

	t.Run("clamps superseded to unhealthy on fetch skew", func(t *testing.T) {
		s := formatRegistryAgentCounts(3, 2, 5, 0)
		assert.Contains(t, s, "2 superseded")
		assert.NotContains(t, s, "unhealthy")
		assert.NotContains(t, s, "inactive")
	})

	t.Run("clamps blocking to genuine down on skew", func(t *testing.T) {
		// blocking reported higher than the genuine down count must not
		// produce a negative inactive count.
		s := formatRegistryAgentCounts(3, 2, 1, 5)
		assert.Contains(t, s, colorRed+"1 unhealthy")
		assert.NotContains(t, s, "inactive")
	})
}

func TestFormatSupersededAnnotation(t *testing.T) {
	assert.Empty(t, formatSupersededAnnotation(0))
	assert.Empty(t, formatSupersededAnnotation(-1))
	assert.Contains(t, formatSupersededAnnotation(2), "(+2 superseded)")
}

// --- Capability availability rendering (issue #1249) ------------------------
//
// The registry marks a capability unavailable (available:false + a reason)
// when its owning agent is healthy but a required dependency's chain is broken.
// meshctl must surface that on healthy agents without needing jq on the API.

func boolPtr(b bool) *bool { return &b }

// TestCountUnavailableCapabilities covers the nil/true/false tri-state of the
// per-capability Available pointer. nil (older registries that don't report
// availability) must be treated as available and never counted.
func TestCountUnavailableCapabilities(t *testing.T) {
	agent := EnhancedAgent{
		Tools: []ToolInfo{
			{Name: "greet", Available: boolPtr(true)},
			{Name: "forecast", Available: boolPtr(false), UnavailableReason: "required dep 'weather-api' unresolved"},
			{Name: "legacy", Available: nil}, // registry didn't report -> available
			{Name: "enrich", Available: boolPtr(false)},
		},
	}
	assert.Equal(t, 2, countUnavailableCapabilities(agent),
		"only capabilities with Available==false count; nil is treated as available")

	assert.Equal(t, 0, countUnavailableCapabilities(EnhancedAgent{
		Tools: []ToolInfo{{Name: "a", Available: boolPtr(true)}, {Name: "b"}},
	}), "an agent with no unavailable capabilities counts zero")
}

// TestFormatUnavailableAnnotation guards the compact per-row marker: empty when
// nothing is unavailable, singular/plural wording otherwise, and always red so
// it reads as an alarm even on a healthy (green) row.
func TestFormatUnavailableAnnotation(t *testing.T) {
	// All available -> no annotation.
	assert.Empty(t, formatUnavailableAnnotation(EnhancedAgent{
		Status: "healthy",
		Tools:  []ToolInfo{{Name: "a", Available: boolPtr(true)}},
	}))
	// nil Available -> treated as available -> no annotation.
	assert.Empty(t, formatUnavailableAnnotation(EnhancedAgent{
		Status: "healthy",
		Tools:  []ToolInfo{{Name: "a"}},
	}))

	one := formatUnavailableAnnotation(EnhancedAgent{
		Status: "healthy",
		Tools:  []ToolInfo{{Name: "a", Available: boolPtr(false)}},
	})
	assert.Contains(t, one, "(1 capability unavailable)")
	assert.Contains(t, one, colorRed, "the marker must render red")

	two := formatUnavailableAnnotation(EnhancedAgent{
		Status: "healthy",
		Tools: []ToolInfo{
			{Name: "a", Available: boolPtr(false)},
			{Name: "b", Available: boolPtr(false)},
		},
	})
	assert.Contains(t, two, "(2 capabilities unavailable)")
}

// TestFormatUnavailableAnnotation_SuppressedForUnhealthyAgent guards the
// double-signal fix: the registry marks EVERY capability of an unhealthy agent
// available:false (reason "agent unhealthy"), which is redundant with the row's
// own red status. The annotation must therefore be suppressed on a non-live
// agent even though its capabilities are technically unavailable.
func TestFormatUnavailableAnnotation_SuppressedForUnhealthyAgent(t *testing.T) {
	for _, status := range []string{"unhealthy", "", "unknown"} {
		agent := EnhancedAgent{
			Status: status,
			Tools: []ToolInfo{
				{Name: "a", Available: boolPtr(false), UnavailableReason: "agent unhealthy"},
				{Name: "b", Available: boolPtr(false), UnavailableReason: "agent unhealthy"},
			},
		}
		assert.Empty(t, formatUnavailableAnnotation(agent),
			"unavailable annotation must be suppressed for non-live status %q", status)
	}
}

// TestFormatToolUnavailableMarker covers the bulk `--tools` table suffix: shown
// (red) only for an unavailable capability on a LIVE agent; suppressed for
// available caps, nil availability, and every capability of an unhealthy agent.
func TestFormatToolUnavailableMarker(t *testing.T) {
	// Unavailable on a live agent -> red marker.
	m := formatToolUnavailableMarker(ToolListItem{AgentHealthy: true, Available: boolPtr(false)})
	assert.Contains(t, m, "unavailable")
	assert.Contains(t, m, colorRed)

	// Available on a live agent -> no marker.
	assert.Empty(t, formatToolUnavailableMarker(ToolListItem{AgentHealthy: true, Available: boolPtr(true)}))
	// nil availability -> no marker.
	assert.Empty(t, formatToolUnavailableMarker(ToolListItem{AgentHealthy: true}))
	// Unavailable but agent unhealthy -> suppressed (redundant "agent unhealthy").
	assert.Empty(t, formatToolUnavailableMarker(ToolListItem{AgentHealthy: false, Available: boolPtr(false)}))
}

// TestProcessAgentData_ParsesAvailability verifies the registry's
// available/unavailable_reason fields survive the map round-trip in
// processAgentData and land on the right ToolInfo. This is the wiring the
// rendering above depends on.
func TestProcessAgentData_ParsesAvailability(t *testing.T) {
	data := map[string]interface{}{
		"id":     "analyst-abc123",
		"name":   "analyst",
		"status": "healthy",
		"capabilities": []interface{}{
			map[string]interface{}{
				"name":          "summarize",
				"function_name": "summarize",
				"version":       "1.0.0",
				"available":     true,
			},
			map[string]interface{}{
				"name":               "forecast",
				"function_name":      "forecast",
				"version":            "1.0.0",
				"available":          false,
				"unavailable_reason": "required dep 'weather-api' unresolved (via analyst → enricher)",
			},
		},
	}

	agent := processAgentData(data)
	require.Len(t, agent.Tools, 2)

	byName := map[string]ToolInfo{}
	for _, tool := range agent.Tools {
		byName[tool.Name] = tool
	}

	summarize := byName["summarize"]
	require.NotNil(t, summarize.Available)
	assert.True(t, *summarize.Available)
	assert.Empty(t, summarize.UnavailableReason)

	forecast := byName["forecast"]
	require.NotNil(t, forecast.Available)
	assert.False(t, *forecast.Available)
	assert.Equal(t,
		"required dep 'weather-api' unresolved (via analyst → enricher)",
		forecast.UnavailableReason)

	// And the derived aggregate the row marker uses.
	assert.Equal(t, 1, countUnavailableCapabilities(agent))
}

// --- RFC #1280 phase 4: service grouping (display-only) ---------------------

func TestSplitServiceCapability(t *testing.T) {
	cases := []struct {
		name, wantService, wantMethod string
	}{
		{"media.caption", "media", "caption"},       // single-segment prefix
		{"media.v2.caption", "media.v2", "caption"}, // multi-segment prefix
		{"greeting", "", "greeting"},                // undotted → ungrouped
		{"a.b.c.d", "a.b.c", "d"},                   // deep nesting
		{".leading", "", ".leading"},                // degenerate → ungrouped
		{"trailing.", "", "trailing."},              // degenerate → ungrouped
	}
	for _, c := range cases {
		svc, method := splitServiceCapability(c.name)
		assert.Equal(t, c.wantService, svc, "service for %q", c.name)
		assert.Equal(t, c.wantMethod, method, "method for %q", c.name)
	}
}

func TestGroupCapabilitiesByService(t *testing.T) {
	tools := []ToolInfo{
		{Name: "zeta", Capability: "media.zeta"},
		{Name: "caption", Capability: "media.caption"},
		{Name: "greeting", Capability: "greeting"}, // ungrouped
		{Name: "encode", Capability: "audio.encode"},
		{Name: "solo", Capability: "solo.only"}, // single tool in a group
	}
	groups := groupCapabilitiesByService(tools)

	// Services sorted alphabetically, ungrouped LAST.
	require.Len(t, groups, 4)
	assert.Equal(t, "audio", groups[0].Service)
	assert.Equal(t, "media", groups[1].Service)
	assert.Equal(t, "solo", groups[2].Service)
	assert.Equal(t, "", groups[3].Service) // ungrouped last

	// Methods sorted by capability within a group.
	require.Len(t, groups[1].Tools, 2)
	assert.Equal(t, "media.caption", groups[1].Tools[0].Capability)
	assert.Equal(t, "media.zeta", groups[1].Tools[1].Capability)

	// Single tool in a group.
	require.Len(t, groups[2].Tools, 1)
	assert.Equal(t, "solo.only", groups[2].Tools[0].Capability)

	// Ungrouped bucket.
	require.Len(t, groups[3].Tools, 1)
	assert.Equal(t, "greeting", groups[3].Tools[0].Capability)
}

func TestGroupCapabilitiesByService_NoDots(t *testing.T) {
	groups := groupCapabilitiesByService([]ToolInfo{
		{Capability: "b"}, {Capability: "a"},
	})
	require.Len(t, groups, 1)
	assert.Equal(t, "", groups[0].Service)
	assert.Equal(t, "a", groups[0].Tools[0].Capability)
	assert.Equal(t, "b", groups[0].Tools[1].Capability)
}

func TestBuildServiceGroupView_MultiAgentAndUngrouped(t *testing.T) {
	base := time.Now()
	capA := testAgent("caption-provider-abc", "caption-provider", "healthy", base, nil)
	capA.Tools = []ToolInfo{{Name: "caption", Capability: "media.caption", Available: boolPtr(true)}}

	// Same capability from a second agent → one provider row per (cap, agent).
	capB := testAgent("caption-backup-def", "caption-backup", "healthy", base, nil)
	capB.Tools = []ToolInfo{{Name: "caption", Capability: "media.caption", Available: boolPtr(true)}}

	thumb := testAgent("thumb-xyz", "thumb-provider", "healthy", base, nil)
	thumb.Tools = []ToolInfo{
		{Name: "thumbnail", Capability: "media.thumbnail", Available: boolPtr(false), UnavailableReason: "dep down"},
		{Name: "greet", Capability: "greeting"}, // ungrouped
		// Framework-internal synthetics must be excluded entirely — they must
		// not appear in any group NOR inflate the ungrouped count (the note
		// sends users to --tools, which filters these identically).
		{Name: "__mesh_service_deps", FunctionName: "__mesh_service_deps", Capability: "__mesh_service_deps"},
		{Name: "__mesh_job_status", FunctionName: "__mesh_job_status", Capability: "__mesh_job_status"},
	}

	view := buildServiceGroupView([]EnhancedAgent{thumb, capB, capA}, false)

	// One service ("media"), methods sorted by capability.
	require.Len(t, view.Services, 1)
	assert.Equal(t, "media", view.Services[0].Service)
	methods := view.Services[0].Methods
	require.Len(t, methods, 2)
	assert.Equal(t, "media.caption", methods[0].Capability)
	assert.Equal(t, "caption", methods[0].Method)
	assert.Equal(t, "media.thumbnail", methods[1].Capability)

	// media.caption has two providers, sorted by agent id.
	require.Len(t, methods[0].Providers, 2)
	assert.Equal(t, "caption-backup-def", methods[0].Providers[0].AgentID)
	assert.Equal(t, "caption-provider-abc", methods[0].Providers[1].AgentID)

	// Ungrouped capability tracked + counted — framework synthetics excluded,
	// so only "greeting" remains and N is 1 (reconciles with --tools).
	require.Len(t, view.Ungrouped, 1)
	assert.Equal(t, "greeting", view.Ungrouped[0].Capability)
	assert.Equal(t, 1, view.ungroupedCount())

	// No __mesh_* synthetic leaks anywhere in the view.
	for _, e := range view.Services {
		for _, m := range e.Methods {
			assert.NotContains(t, m.Capability, "__mesh_", "framework synthetic must not appear in a service group")
		}
	}
	for _, m := range view.Ungrouped {
		assert.NotContains(t, m.Capability, "__mesh_", "framework synthetic must not appear in the ungrouped bucket")
	}
}

func TestServiceProviderStatus(t *testing.T) {
	assert.Equal(t, "available", serviceProviderStatus(svcProvider{Available: boolPtr(true)}))
	assert.Equal(t, "available", serviceProviderStatus(svcProvider{})) // nil = available
	un := serviceProviderStatus(svcProvider{Available: boolPtr(false), UnavailableReason: "dep down"})
	assert.Contains(t, un, "unavailable")
	assert.Contains(t, un, "dep down")
	assert.Contains(t, un, colorRed)
}

func TestGroupResolutionsByService(t *testing.T) {
	res := []DependencyResolution{
		{Capability: "media.thumbnail", ProviderAgentID: "t1", Status: "available"},
		{Capability: "media.caption", ProviderAgentID: "c1", Status: "available"},
		{Capability: "date_service", ProviderAgentID: "d1", Status: "unresolved"}, // ungrouped
	}
	groups := groupResolutionsByService(res)
	require.Len(t, groups, 2)
	assert.Equal(t, "media", groups[0].Service)
	require.Len(t, groups[0].Resolutions, 2)
	assert.Equal(t, "media.caption", groups[0].Resolutions[0].Capability) // sorted
	assert.Equal(t, "media.thumbnail", groups[0].Resolutions[1].Capability)
	assert.Equal(t, "", groups[1].Service) // ungrouped last
	assert.Equal(t, "date_service", groups[1].Resolutions[0].Capability)
}

// TestServiceGroupView_EmptyMarshalsArrays guards the HIGH-1 fix: an empty
// --services --json view must emit {"services":[],"ungrouped":[]} (arrays, never
// null/omitted) so consumers iterate unconditionally.
func TestServiceGroupView_EmptyMarshalsArrays(t *testing.T) {
	view := buildServiceGroupView(nil, false)
	require.NotNil(t, view.Services)
	require.NotNil(t, view.Ungrouped)

	data, err := json.Marshal(view)
	require.NoError(t, err)
	assert.JSONEq(t, `{"services":[],"ungrouped":[]}`, string(data))
}

// TestBuildServiceGroupView_ShowFramework verifies MED-2: with showFramework the
// __mesh_* synthetics group by their names as ordinary entries.
func TestBuildServiceGroupView_ShowFramework(t *testing.T) {
	base := time.Now()
	agent := testAgent("a-1", "a", "healthy", base, nil)
	agent.Tools = []ToolInfo{
		{Name: "caption", Capability: "media.caption"},
		{Name: "__mesh_service_deps", FunctionName: "__mesh_service_deps", Capability: "__mesh_service_deps"},
		{Name: "__mesh_job_status", FunctionName: "__mesh_job_status", Capability: "__mesh_job_status"},
	}

	// Default: synthetics excluded.
	hidden := buildServiceGroupView([]EnhancedAgent{agent}, false)
	require.Len(t, hidden.Services, 1)
	assert.Equal(t, "media", hidden.Services[0].Service)
	assert.Empty(t, hidden.Ungrouped)

	// --show-framework: synthetics appear as ordinary entries (undotted →
	// ungrouped by their names).
	shown := buildServiceGroupView([]EnhancedAgent{agent}, true)
	caps := map[string]bool{}
	for _, m := range shown.Ungrouped {
		caps[m.Capability] = true
	}
	assert.True(t, caps["__mesh_service_deps"], "framework synthetic must appear with --show-framework")
	assert.True(t, caps["__mesh_job_status"], "framework synthetic must appear with --show-framework")
}

// TestOutputServiceGroupView_TableAndNote covers the table rendering + the
// ungrouped-note path (both flagged as untested).
func TestOutputServiceGroupView_TableAndNote(t *testing.T) {
	base := time.Now()
	a := testAgent("cap-1", "caption-provider", "healthy", base, nil)
	a.Tools = []ToolInfo{
		{Name: "caption", Capability: "media.caption", Available: boolPtr(true)},
		{Name: "thumbnail", Capability: "media.thumbnail", Available: boolPtr(false), UnavailableReason: "dep down"},
		{Name: "greet", Capability: "greeting"}, // ungrouped → note
	}
	view := buildServiceGroupView([]EnhancedAgent{a}, false)

	out := captureStdout(t, func() {
		require.NoError(t, outputServiceGroupView(view))
	})
	assert.Contains(t, out, "SERVICE")
	assert.Contains(t, out, "METHOD")
	assert.Contains(t, out, "media")
	assert.Contains(t, out, "caption")
	assert.Contains(t, out, "caption-provider")
	assert.Contains(t, out, "available")
	assert.Contains(t, out, "unavailable (dep down)")
	// One ungrouped capability -> singular note pointing at --tools.
	assert.Contains(t, out, "(1 ungrouped capability not shown — use --tools)")
}

// TestOutputServiceGroupView_EmptyWithUngroupedNote covers the no-services path.
func TestOutputServiceGroupView_EmptyWithUngroupedNote(t *testing.T) {
	base := time.Now()
	a := testAgent("u-1", "u", "healthy", base, nil)
	a.Tools = []ToolInfo{{Name: "greet", Capability: "greeting"}, {Name: "farewell", Capability: "farewell"}}
	view := buildServiceGroupView([]EnhancedAgent{a}, false)

	out := captureStdout(t, func() {
		require.NoError(t, outputServiceGroupView(view))
	})
	assert.Contains(t, out, "No dot-namespaced services found")
	assert.Contains(t, out, "(2 ungrouped capabilities not shown — use --tools)")
}

// TestBuildServiceGroupView_DedupeProviderByAgent verifies one provider row per
// (capability, agent): an agent registering the same capability via two
// functions produces indistinguishable provider entries, so they collapse.
func TestBuildServiceGroupView_DedupeProviderByAgent(t *testing.T) {
	base := time.Now()
	a := testAgent("dup-1", "dup-provider", "healthy", base, nil)
	a.Tools = []ToolInfo{
		{Name: "caption_a", FunctionName: "caption_a", Capability: "media.caption", Available: boolPtr(true)},
		{Name: "caption_b", FunctionName: "caption_b", Capability: "media.caption", Available: boolPtr(true)},
	}

	view := buildServiceGroupView([]EnhancedAgent{a}, false)
	require.Len(t, view.Services, 1)
	require.Len(t, view.Services[0].Methods, 1)
	assert.Equal(t, "media.caption", view.Services[0].Methods[0].Capability)
	require.Len(t, view.Services[0].Methods[0].Providers, 1,
		"one provider row per (capability, agent) despite two registering functions")
	assert.Equal(t, "dup-1", view.Services[0].Methods[0].Providers[0].AgentID)
}
