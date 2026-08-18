package registry

import (
	"context"
	"sort"
	"strings"

	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/capability"
)

// capability_outage.go answers open question 1 of RFC #1515.
//
// # The question
//
// A health check that withdraws its agent is per-agent, but the CONDITION it
// reports usually is not. Broken egress, an expired shared credential, a vendor
// that is down for everyone: each provider of a capability observes it
// independently, each reports unhealthy independently, and the capability goes
// from N providers to zero within one TTL. A partial outage becomes a total one
// with nothing left advertising the capability.
//
// # The decision: no floor, and it belongs nowhere
//
// A "keep the last provider" rule would route to something that has just told
// us it cannot serve. It trades a clean 503 — a fast, typed, retryable answer
// that says "this capability has no provider" — for a guaranteed failure at the
// far end of a call the consumer had to make first, with the provider's own
// error shape and the provider's own latency. That is a worse outcome on every
// axis, and it makes the health check a suggestion.
//
// The floor does not belong at the consumer either, for the same reason. A
// consumer cannot distinguish "the last provider is degraded but limping" from
// "the last provider has withdrawn deliberately" — only the provider knows, and
// it has already said so.
//
// This is also the general position mesh takes on withdrawal: it is cheap and
// self-correcting. A withdrawn agent keeps running, keeps its resolved
// dependencies and re-registers by itself the moment its check passes, so the
// cost of withdrawing one too eagerly is bounded by one TTL. Damping,
// hysteresis and grace periods all buy time against a transition that costs
// almost nothing to reverse, and pay for it with a window where mesh knowingly
// routes to something broken. None are added here.
//
// # What IS added: the signal
//
// "Correct" and "silent" are different things. Every provider withdrawing is
// the right mechanical outcome and a serious operational event, and without a
// signal an operator discovers it through consumer errors — one layer removed
// from the cause, at whatever rate consumers happen to call. So the registry
// says it out loud at the moment it becomes true.
//
// # Why here and not in the resolver
//
// The resolver already knows when a lookup finds no candidate
// (findHealthyProviderWithTrace), and that is the tempting place. It is the
// wrong one twice over. It is per-resolution — every heartbeat of every consumer
// re-resolves, so a single unserved capability would log at the aggregate
// heartbeat rate indefinitely. And it cannot tell an OUTAGE from a capability
// that simply has no provider and never did, which is the normal, benign state
// of every unsatisfied optional dependency in a partly-deployed mesh.
//
// A withdrawal is a transition, so it is reported on the transition: the health
// monitor already has the set of agents it just marked unhealthy, and the check
// below runs only when that set is non-empty. A steady-state mesh pays nothing.
//
// Scope is deliberately the staleness sweep and not graceful unregister. A
// suppressed heartbeat is how a failing health check withdraws an agent, so this
// is the path RFC #1515's failure mode travels. An unregister is an operator
// action with an operator watching, and reporting it would make every rolling
// deploy of a single-replica agent log a total outage it planned.

// capabilitiesLeftWithoutHealthyProvider returns the capability names that the
// given agents were serving and that now have no healthy provider left, sorted
// for deterministic output.
//
// Two queries, both reached only after at least one agent has actually been
// withdrawn: the capabilities those agents own, then which of those names any
// healthy agent still provides. Errors are returned rather than logged so the
// caller can decide — a diagnostic must not become a source of noise of its own.
func (s *EntService) capabilitiesLeftWithoutHealthyProvider(
	ctx context.Context,
	agentIDs []string,
) ([]string, error) {
	if len(agentIDs) == 0 {
		return nil, nil
	}

	// Only the name column: the report names capabilities, and a capability row
	// carries the full tool schema. Selecting the rest would pull every input and
	// output schema of every capability of every withdrawn agent across the wire
	// to build a list of strings.
	var lost []string
	err := s.entDB.Capability.Query().
		Where(capability.HasAgentWith(agent.IDIn(agentIDs...))).
		Select(capability.FieldCapability).
		Scan(ctx, &lost)
	if err != nil {
		return nil, err
	}
	if len(lost) == 0 {
		return nil, nil
	}

	names := make([]string, 0, len(lost))
	seen := map[string]bool{}
	for _, name := range lost {
		if name == "" || seen[name] {
			continue
		}
		seen[name] = true
		names = append(names, name)
	}

	// Deliberately re-queried rather than derived from the withdrawn set: another
	// agent may provide the same capability, and it may have registered or
	// recovered since. The DB is the only thing that knows what is serving NOW.
	var survivors []string
	err = s.entDB.Capability.Query().
		Where(
			capability.CapabilityIn(names...),
			capability.HasAgentWith(agent.StatusEQ(agent.StatusHealthy)),
		).
		Select(capability.FieldCapability).
		Scan(ctx, &survivors)
	if err != nil {
		return nil, err
	}
	for _, name := range survivors {
		delete(seen, name)
	}

	unserved := make([]string, 0, len(seen))
	for name := range seen {
		unserved = append(unserved, name)
	}
	sort.Strings(unserved)
	return unserved, nil
}

// reportCapabilitiesLeftWithoutProvider warns once per capability that has just
// lost its last healthy provider.
//
// WARNING, not ERROR: nothing is broken in the registry, and the state is
// self-correcting the moment a provider's check passes again. It is above INFO
// because every consumer of that capability is now resolving to nothing, and
// that is the kind of thing an operator wants to find in a log search rather
// than infer from a scatter of consumer-side 503s.
func (h *AgentHealthMonitor) reportCapabilitiesLeftWithoutProvider(ctx context.Context, agentIDs []string) {
	unserved, err := h.entService.capabilitiesLeftWithoutHealthyProvider(ctx, agentIDs)
	if err != nil {
		h.logger.Debug("Could not check for capabilities left without a provider: %v", err)
		return
	}
	if len(unserved) == 0 {
		return
	}
	h.logger.Warning(
		"No healthy provider remains for %d capability/capabilities: %s. "+
			"Consumers resolving these will get no candidate until a provider "+
			"re-registers or its health check passes again.",
		len(unserved), strings.Join(unserved, ", "))
}
