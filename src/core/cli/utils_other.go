//go:build !linux && !darwin

package cli

// isProcessZombie is a no-op on platforms other than Linux and macOS.
// Linux uses /proc/<pid>/stat (utils_linux.go), macOS uses ps (utils_darwin.go).
// On remaining platforms (Windows via WSL2 compiles as Linux), zombies don't apply.
func isProcessZombie(pid int) bool {
	return false
}
