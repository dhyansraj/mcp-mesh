//go:build darwin

package cli

import (
	"os/exec"
	"strconv"
	"strings"
)

// isProcessZombie returns true if the given PID is a zombie on macOS.
// Uses ps to query the process state; a leading 'Z' indicates zombie.
func isProcessZombie(pid int) bool {
	out, err := exec.Command("ps", "-o", "state=", "-p", strconv.Itoa(pid)).Output()
	if err != nil {
		return false
	}
	state := strings.TrimSpace(string(out))
	return len(state) > 0 && state[0] == 'Z'
}
