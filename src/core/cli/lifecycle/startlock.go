package lifecycle

import (
	"os"
	"path/filepath"
	"syscall"
)

// WithStartLock acquires the start.lock for a service so concurrent
// `meshctl start` invocations cleanly serialize on the start path.
//
// The loser of the race acquires the lock after the winner releases it,
// then re-checks IsRegistryRunning / IsUIRunning, sees true, and falls
// into the reuse branch instead of trying to bind the port.
//
// service must be ServiceRegistry or ServiceUI.
func WithStartLock(service string, fn func() error) error {
	var lockPath string
	switch service {
	case ServiceRegistry:
		lockPath = RegistryStartLock()
	case ServiceUI:
		lockPath = UIStartLock()
	default:
		return fn()
	}

	if err := os.MkdirAll(filepath.Dir(lockPath), 0755); err != nil {
		return err
	}
	f, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return err
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	return fn()
}
