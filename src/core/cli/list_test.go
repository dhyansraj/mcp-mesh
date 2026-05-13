package cli

import (
	"testing"

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
