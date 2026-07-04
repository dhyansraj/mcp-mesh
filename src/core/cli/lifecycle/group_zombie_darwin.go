//go:build darwin

package lifecycle

import (
	"os/exec"
	"strconv"
	"strings"
)

// groupAllZombie reports whether process group pgid is non-empty and EVERY
// member is a zombie (state 'Z'). See the linux build's doc comment for the
// full rationale (zombies hold no port/FDs; an unreaped orphan zombie in a
// container must not hang the group-drain waits forever).
//
// Returns:
//   - (true, nil)  at least one member was found and ALL members are zombies
//   - (false, nil) a live (non-zombie) member exists, or the group is empty
//   - (false, err) the ps scan itself failed — inconclusive; caller MUST NOT
//     treat this as "dead"
//
// Uses `ps -A -o pgid=,stat=` (ps is part of the Darwin base system). Each line
// is `<pgid> <stat>`; stat may carry flag suffixes (e.g. "Z+", "Ss"), so we key
// on the first character.
func groupAllZombie(pgid int) (bool, error) {
	if pgid <= 1 {
		return false, nil
	}
	out, err := exec.Command("ps", "-A", "-o", "pgid=,stat=").Output()
	if err != nil {
		return false, err
	}
	found := false
	for _, line := range strings.Split(string(out), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		pg, err := strconv.Atoi(fields[0])
		if err != nil || pg != pgid {
			continue
		}
		found = true
		if fields[1][0] != 'Z' {
			return false, nil // a live member exists — group not drained
		}
	}
	return found, nil
}
