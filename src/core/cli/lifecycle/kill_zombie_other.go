//go:build !linux && !darwin

package lifecycle

// isZombie is a no-op on platforms other than Linux and macOS. The caller's
// aliveness check (signal 0) governs death detection on those platforms.
func isZombie(pid int) (bool, error) {
	return false, nil
}
