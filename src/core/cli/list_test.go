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
