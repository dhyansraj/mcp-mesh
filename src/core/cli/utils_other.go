//go:build !linux

package cli

// isProcessZombie is a no-op on non-Linux platforms. macOS reaping is
// aggressive enough that the zombie window is effectively zero for
// meshctl's use case, and the main environments where this check matters
// (tsuite Linux containers) are covered by utils_linux.go.
func isProcessZombie(pid int) bool {
	return false
}
