package lifecycle

import (
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
		if isServiceName(base) {
			continue
		}
		pid, err := readPIDFromFile(pidsDirJoin(name))
		if err != nil || pid == 0 {
			continue
		}
		entry := AgentEntry{Name: base, PID: pid, Alive: processAliveFn(pid)}
		// Best-effort group lookup; missing .group means the agent was written
		// by some non-current code path (or via WriteService) — treat as no group.
		if g, err := LookupGroup(base); err == nil {
			entry.Group = g
		}
		out = append(out, entry)
	}
	return out, nil
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
	if g, err := LookupGroup(name); err == nil {
		entry.Group = g
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

// agentPIDFileExists is a sanity helper — used by tests and validators.
func agentPIDFileExists(name string) bool {
	_, err := os.Stat(PIDFile(name))
	return err == nil
}
