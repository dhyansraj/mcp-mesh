//go:build !linux && !darwin

package lifecycle

// groupAllZombie is a no-op on platforms without a supported process-table
// probe: it reports "not all-zombie" so the group-drain waits fall back to
// their kill(-pgid, 0) behavior unchanged. (Windows uses a separate lifecycle
// path entirely.)
func groupAllZombie(pgid int) (bool, error) {
	return false, nil
}
