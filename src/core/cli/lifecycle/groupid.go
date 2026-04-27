package lifecycle

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// GroupID identifies a single `meshctl start` invocation. All agents (and
// optional UI dep) started by one invocation share the same group-id, so stop
// can find the right deps files even when multiple meshctl instances run
// concurrently.
//
// Format: "<unix-millis>-<wrapper-pid>-<seq>" where seq disambiguates rapid
// successive calls within the same millisecond from the same process.
type GroupID string

// seq grows monotonically across NewGroupID calls within a single process.
// Combined with the millisecond timestamp + PID it eliminates collisions even
// under tight loops in tests.
var seq atomic.Uint64

// NewGroupID returns a fresh group-id derived from wall-clock time, this
// process's PID, and a per-process monotonic sequence. The returned ID is
// safe to use as a filename component (no path separators or shell metas).
func NewGroupID() GroupID {
	n := seq.Add(1)
	return GroupID(fmt.Sprintf("%d-%d-%d", time.Now().UnixMilli(), os.Getpid(), n))
}

// String returns the group-id as a plain string.
func (g GroupID) String() string { return string(g) }

// Parse validates a group-id string and returns it. Format check only — does
// not verify that any process currently owns the group. Returns an error for
// anything that wouldn't be safe as a filename component or that doesn't match
// the expected "<int>-<int>-<int>" shape (also accepts the legacy 2-segment
// form for any old files lingering from in-flight test runs).
func Parse(s string) (GroupID, error) {
	if s == "" {
		return "", fmt.Errorf("group-id is empty")
	}
	if strings.ContainsAny(s, "/\\\x00") {
		return "", fmt.Errorf("group-id %q contains invalid characters", s)
	}
	parts := strings.Split(s, "-")
	if len(parts) < 2 || len(parts) > 3 {
		return "", fmt.Errorf("group-id %q has wrong shape, want <ms>-<pid>[-<seq>]", s)
	}
	for _, p := range parts {
		if p == "" {
			return "", fmt.Errorf("group-id %q has empty segment", s)
		}
		if _, err := strconv.ParseUint(p, 10, 64); err != nil {
			return "", fmt.Errorf("group-id %q segment %q is not a number: %w", s, p, err)
		}
	}
	return GroupID(s), nil
}

// LookupGroup reads <root>/pids/<agent>.group and returns the group-id that
// owns the agent. Returns ErrNoGroup when the file is missing — callers that
// want best-effort cleanup of unowned agents should check for this sentinel.
func LookupGroup(agent string) (GroupID, error) {
	data, err := os.ReadFile(GroupFile(agent))
	if err != nil {
		if os.IsNotExist(err) {
			return "", ErrNoGroup
		}
		return "", err
	}
	return Parse(strings.TrimSpace(string(data)))
}

// ErrNoGroup is returned by LookupGroup when no .group file exists for the
// requested agent. Caller can treat this as a soft "agent not tracked by the
// new lifecycle layer" signal.
var ErrNoGroup = fmt.Errorf("lifecycle: no group file for agent")

// resetSeqForTests is exposed for the test package only via this helper.
// Plain tests (same package) can call it; external code cannot.
var resetMu sync.Mutex

func resetSeqForTests() {
	resetMu.Lock()
	defer resetMu.Unlock()
	seq.Store(0)
}
