package lifecycle

import (
	"errors"
	"fmt"
	"os"
	"strings"
)

// AgentEntry is what stop/list code needs to know about an agent on disk:
// its name (filename minus .pid), its PID, and whether the kernel still has
// a process entry for it.
type AgentEntry struct {
	Name    string
	PID     int
	Alive   bool
	Group   GroupID // empty if no .group file exists
}

// ListAgents returns all on-disk agent PID files, excluding well-known
// service names (registry, ui) and wrapper-* markers. Used by stop and list
// to enumerate user-facing agents.
//
// Service PID files are excluded because they have separate kill paths and
// are reference-counted via the deps directories.
func ListAgents() ([]AgentEntry, error) {
	entries, err := pidsDirEntries()
	if err != nil {
		return nil, err
	}
	var out []AgentEntry
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if !strings.HasSuffix(name, ".pid") {
			continue
		}
		// Watcher sidecars (<agent>.watcher.pid) are not user-facing agents —
		// they're tracking metadata for stop. Skip them so they don't show up
		// in `meshctl list` or get mass-killed by stopAllAgents.
		if strings.HasSuffix(name, ".watcher.pid") {
			continue
		}
		base := strings.TrimSuffix(name, ".pid")
		if strings.HasPrefix(base, "wrapper-") {
			continue
		}
		// Sentinel placeholders (names starting with "_", e.g. "_ui_only_")
		// are bookkeeping markers in deps files only; they should never have
		// a .pid file, but skip defensively so they never appear as agents.
		if strings.HasPrefix(base, "_") {
			continue
		}
		if isServiceName(base) {
			continue
		}
		pid, err := readPIDFromFile(pidsDirJoin(name))
		if err != nil || pid == 0 {
			continue
		}
		entry := AgentEntry{Name: base, PID: pid, Alive: processAliveFn(pid)}
		// Best-effort group lookup; missing .group means the agent was written
		// by some non-current code path (or via WriteService) — treat as no
		// group. A parse error is loud: half-written/corrupt .group files
		// would otherwise silently orphan deps entries forever.
		g, gErr := LookupGroup(base)
		if gErr == nil {
			entry.Group = g
		} else if !errors.Is(gErr, ErrNoGroup) {
			fmt.Fprintf(os.Stderr, "warning: %v\n", gErr)
		}
		out = append(out, entry)
	}
	return out, nil
}

// IsAgentRunning reports whether an agent with the given name has a live
// process recorded on disk. Returns (true, pid, nil) when the .pid file
// exists AND the kernel still has an entry for that PID. Returns
// (false, 0, nil) when no .pid file is present, the file is empty, or the
// recorded PID is dead. Errors are only returned for unexpected I/O failures
// reading the .pid file (e.g., permission denied) — "no such file" is not an
// error.
//
// Used by `meshctl start` to refuse same-name re-starts before a duplicate
// process can clobber the on-disk PID/group bookkeeping.
func IsAgentRunning(name string) (bool, int, error) {
	pid, err := readPIDFromFile(PIDFile(name))
	if err != nil {
		return false, 0, err
	}
	if pid == 0 {
		return false, 0, nil
	}
	if !processAliveFn(pid) {
		return false, pid, nil
	}
	return true, pid, nil
}

// LookupAgent returns the on-disk record for a single agent, or (nil, nil)
// if the agent has no PID file.
func LookupAgent(name string) (*AgentEntry, error) {
	pid, err := readPIDFromFile(PIDFile(name))
	if err != nil {
		return nil, err
	}
	if pid == 0 {
		return nil, nil
	}
	entry := &AgentEntry{Name: name, PID: pid, Alive: processAliveFn(pid)}
	g, gErr := LookupGroup(name)
	if gErr == nil {
		entry.Group = g
	} else if !errors.Is(gErr, ErrNoGroup) {
		fmt.Fprintf(os.Stderr, "warning: %v\n", gErr)
	}
	return entry, nil
}

// ServicePIDInfo describes a known service's on-disk PID + liveness.
type ServicePIDInfo struct {
	Name  string // "registry" or "ui"
	PID   int
	Alive bool
}

// LookupService returns the PID record for a service, or (nil, nil) if no
// PID file is present.
func LookupService(service string) (*ServicePIDInfo, error) {
	if !isServiceName(service) {
		return nil, nil
	}
	pid, err := readPIDFromFile(PIDFile(service))
	if err != nil {
		return nil, err
	}
	if pid == 0 {
		return nil, nil
	}
	return &ServicePIDInfo{Name: service, PID: pid, Alive: processAliveFn(pid)}, nil
}

// isServiceName reports whether base is a known service PID filename.
func isServiceName(base string) bool {
	switch base {
	case ServiceRegistry, ServiceUI:
		return true
	}
	return false
}
