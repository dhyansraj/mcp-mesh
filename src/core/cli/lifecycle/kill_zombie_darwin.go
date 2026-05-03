//go:build darwin

package lifecycle

import (
	"fmt"
	"os/exec"
	"strconv"
	"strings"
)

// isZombie shells out to `ps -o stat= -p <pid>` to detect zombie state on
// macOS. ps is part of the Darwin base system so this is always available.
//
// Returns (zombie bool, err error):
//   - zombie=true, err=nil  -> kernel reports state 'Z' (defunct)
//   - zombie=false, err=nil -> process exists with a non-zombie state, OR ps
//     reported "no such process" (exit code 1, empty output). The aliveness
//     judgement belongs to processAliveFn — isZombie only differentiates
//     zombie-vs-not when the process is known to exist.
//   - zombie=false, err!=nil -> ps failed for some OTHER reason (e.g. EAGAIN
//     on fork under load, RLIMIT_NPROC, transient resource exhaustion). The
//     caller MUST NOT interpret this as "dead" — that flips death detection
//     to true while the process is still alive, orphaning everything.
func isZombie(pid int) (bool, error) {
	if pid <= 0 {
		return false, nil
	}
	cmd := exec.Command("ps", "-o", "stat=", "-p", strconv.Itoa(pid))
	out, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok && exitErr.ExitCode() == 1 && len(out) == 0 {
			return false, nil
		}
		return false, fmt.Errorf("lifecycle: ps probe pid %d: %w", pid, err)
	}
	state := strings.TrimSpace(string(out))
	if state == "" {
		return false, nil
	}
	return state[0] == 'Z', nil
}
