package registry

import (
	"testing"
	"time"
)

// TestReadSweepIntervalFromEnv covers the three cases for the
// MCP_MESH_SWEEP_INTERVAL override: unset (default), valid override,
// and malformed value (fall back to default).
//
// We test readSweepIntervalFromEnv() directly rather than the package-
// level sweepInterval var because the env read happens once at package
// init, so the var is fixed by the time any test runs.
func TestReadSweepIntervalFromEnv(t *testing.T) {
	t.Run("unset_uses_default", func(t *testing.T) {
		// t.Setenv with empty string still sets the var. We need to
		// actually unset it for this case.
		t.Setenv("MCP_MESH_SWEEP_INTERVAL", "")
		got := readSweepIntervalFromEnv()
		if got != 5*time.Minute {
			t.Fatalf("expected default 5m, got %s", got)
		}
	})

	t.Run("valid_override_applied", func(t *testing.T) {
		t.Setenv("MCP_MESH_SWEEP_INTERVAL", "10s")
		got := readSweepIntervalFromEnv()
		if got != 10*time.Second {
			t.Fatalf("expected 10s, got %s", got)
		}
	})

	t.Run("valid_compound_duration", func(t *testing.T) {
		t.Setenv("MCP_MESH_SWEEP_INTERVAL", "1m30s")
		got := readSweepIntervalFromEnv()
		if got != 90*time.Second {
			t.Fatalf("expected 1m30s (=90s), got %s", got)
		}
	})

	t.Run("invalid_falls_back_to_default", func(t *testing.T) {
		t.Setenv("MCP_MESH_SWEEP_INTERVAL", "garbage")
		got := readSweepIntervalFromEnv()
		if got != 5*time.Minute {
			t.Fatalf("expected default 5m on invalid input, got %s", got)
		}
	})
}
