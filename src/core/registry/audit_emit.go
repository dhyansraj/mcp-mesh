package registry

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"time"

	"entgo.io/ent/dialect/sql"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/registryevent"
)

// priorTraceLookupLimit caps how many recent registry events the prior-trace
// lookups scan when searching for a matching dep_index. Headroom for functions
// with many deps + concurrent writes; raise if you have functions with >64
// deps. Future: push the dep_index filter into SQL via a JSON path expression
// so we don't need to overscan in Go.
const priorTraceLookupLimit = 64

// emitAuditEventIfInteresting writes a dependency_resolved or dependency_unresolved
// event to the RegistryEvent table when warranted. Gating logic:
//   - Resolved + multi-candidate decision (≥2 candidates entered any stage) → candidate to emit
//   - Resolved + chosen producer flipped vs prior emission for same (consumer, function, dep_index) → candidate to emit
//   - Unresolved + ≥2 candidates entered any stage → candidate to emit
//   - Unresolved + at least one candidate was evicted → candidate to emit (single-rogue
//     eviction is the canonical "why isn't my dep wired" signal)
//   - Unresolved + prior emission was resolved (resolved→unresolved flip) → candidate to emit
//   - Single forced choice with no flip → skip (noise)
//
// In addition to the rules above, an emission is suppressed when the canonical
// hash of the new trace is identical to the most recent prior trace for the
// same (consumer, function, dep_index). This dedupes the steady-state case
// where every heartbeat re-resolution produces the same multi-candidate trace.
//
// trace must be non-nil. consumerAgentID is the entity emitting the event.
// The function returns nil on a successful skip; only DB errors propagate.
func (s *EntService) emitAuditEventIfInteresting(
	ctx context.Context,
	consumerAgentID string,
	functionName string,
	depIndex int,
	trace *AuditTrace,
	resolved *DependencyResolution,
) error {
	if trace == nil {
		return nil
	}

	// Stamp consumer/dep_index into the trace so downstream consumers don't
	// have to reconstruct them from the event metadata.
	trace.Consumer = consumerAgentID
	trace.DepIndex = depIndex

	// Look up the prior emission for this (consumer, function, dep_index).
	prior, err := s.lastResolvedTraceFor(ctx, consumerAgentID, functionName, depIndex)
	if err != nil {
		return fmt.Errorf("audit: query prior trace: %w", err)
	}

	priorChosen := ""
	if prior != nil && prior.Chosen != nil {
		priorChosen = prior.Chosen.AgentID
	}
	trace.PriorChosen = priorChosen

	// Look up the most recent audit event (resolved OR unresolved) so we can
	// (a) detect an unresolved→resolved flip even when only one candidate
	// survives, and (b) dedupe identical-trace re-emissions further down.
	lastAnyEvent, lastAny, err := s.lastAuditTraceFor(ctx, consumerAgentID, functionName, depIndex)
	if err != nil {
		return fmt.Errorf("audit: query last trace: %w", err)
	}

	// Decide event type and gating.
	var eventType registryevent.EventType
	if resolved == nil {
		eventType = registryevent.EventTypeDependencyUnresolved
		// Emit unresolved when:
		//   (a) ≥2 candidates entered the pipeline (real decision), OR
		//   (b) at least one candidate was evicted (operator needs to see why
		//       their dep isn't wired — single-rogue eviction is the canonical
		//       case), OR
		//   (c) prior emission was a resolved event (now flipping to unresolved).
		// Skip only the truly-empty case (no candidate ever existed at all).
		hasEvictions := false
		for _, st := range trace.Stages {
			if len(st.Evicted) > 0 {
				hasEvictions = true
				break
			}
		}
		if !trace.IsInteresting() && !hasEvictions && priorChosen == "" {
			return nil
		}
	} else {
		eventType = registryevent.EventTypeDependencyResolved
		flipped := priorChosen != "" && priorChosen != resolved.AgentID
		// Treat unresolved→resolved as a flip even with a single candidate:
		// the most recent emission for this dep slot was "unresolved" (no
		// providers existed), and now exactly one has appeared. Operators
		// want to see this transition. priorChosen comes from the most
		// recent *resolved* event only, so it's "" here even though the
		// dep slot has a relevant prior history; consult lastAnyEvent
		// directly to detect the transition.
		unresolvedToResolved := lastAnyEvent != nil &&
			lastAnyEvent.EventType == registryevent.EventTypeDependencyUnresolved
		// Gating: skip when single forced choice AND no flip AND no
		// unresolved→resolved transition.
		if !trace.IsInteresting() && !flipped && !unresolvedToResolved {
			return nil
		}
	}

	// Identical-trace dedupe. After all other gating, suppress emission when
	// the canonicalized hash matches the most recent prior trace for the same
	// (consumer, function, dep_index). This collapses the steady-state where a
	// stable mesh re-runs resolution every heartbeat and produces an identical
	// trace — we don't want to fill the audit log with copies. The lookup
	// considers BOTH resolved and unresolved prior events so unresolved→unresolved
	// sequences also dedupe.
	newHash, err := canonicalTraceHash(trace)
	if err != nil {
		return fmt.Errorf("audit: canonicalize trace: %w", err)
	}
	if lastAny != nil {
		priorHash, herr := canonicalTraceHash(lastAny)
		if herr == nil && priorHash == newHash {
			return nil
		}
	}

	// Marshal trace into a generic map so it round-trips through Ent's JSON column
	// (which is map[string]interface{}). Direct struct assignment doesn't work
	// because the column type is map.
	traceJSON, err := json.Marshal(trace)
	if err != nil {
		return fmt.Errorf("audit: marshal trace: %w", err)
	}
	var data map[string]interface{}
	if err := json.Unmarshal(traceJSON, &data); err != nil {
		return fmt.Errorf("audit: unmarshal trace into map: %w", err)
	}

	_, err = s.entDB.RegistryEvent.Create().
		SetEventType(eventType).
		SetAgentID(consumerAgentID).
		SetFunctionName(functionName).
		SetTimestamp(time.Now().UTC()).
		SetData(data).
		Save(ctx)
	if err != nil {
		return fmt.Errorf("audit: create event: %w", err)
	}

	s.logger.Debug("audit: emitted %s for %s/%s[%d] (prior_chosen=%q)",
		eventType, consumerAgentID, functionName, depIndex, priorChosen)
	return nil
}

// canonicalTraceHash computes a deterministic SHA-256 hex digest of the
// resolution-outcome portion of an AuditTrace. The hash deliberately excludes
// PriorChosen (a derivative metadata field that updates every time we emit)
// so that two traces with identical resolution behavior always produce the
// same hash regardless of emission order.
//
// Canonicalization rules:
//   - Stages are not reordered (resolver always emits them in fixed order;
//     reordering would lose semantic meaning if any stage were missing).
//   - Within each stage, Kept is sorted lexicographically.
//   - Within each stage, Evicted is sorted by ID lexicographically.
//   - Spec.Tags is sorted lexicographically.
//   - PriorChosen is zeroed before marshaling.
//
// JSON marshal then provides a stable byte representation (Go's encoding/json
// emits struct fields in declaration order and map keys alphabetically).
func canonicalTraceHash(t *AuditTrace) (string, error) {
	if t == nil {
		return "", nil
	}
	// Deep-copy via marshal/unmarshal so we don't mutate caller's data.
	raw, err := json.Marshal(t)
	if err != nil {
		return "", err
	}
	var c AuditTrace
	if err := json.Unmarshal(raw, &c); err != nil {
		return "", err
	}
	c.PriorChosen = ""
	if c.Spec.Tags != nil {
		sort.Strings(c.Spec.Tags)
	}
	for i := range c.Stages {
		s := &c.Stages[i]
		if len(s.Kept) > 1 {
			sort.Strings(s.Kept)
		}
		if len(s.Evicted) > 1 {
			sort.Slice(s.Evicted, func(a, b int) bool {
				return s.Evicted[a].ID < s.Evicted[b].ID
			})
		}
	}
	canonical, err := json.Marshal(&c)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(canonical)
	return hex.EncodeToString(sum[:]), nil
}

// lastResolvedTraceFor returns the most recent dependency_resolved AuditTrace
// for the given (consumer, function, dep_index). Returns (nil, nil) when none
// exists. Used by gating to detect chosen-producer flips.
//
// Filters: agent_id == consumer, event_type == dependency_resolved,
// function_name == functionName, ORDER BY timestamp DESC LIMIT priorTraceLookupLimit.
// The (event_type, timestamp) indexes on registry_events make this cheap.
func (s *EntService) lastResolvedTraceFor(
	ctx context.Context,
	consumerAgentID string,
	functionName string,
	depIndex int,
) (*AuditTrace, error) {
	q := s.entDB.RegistryEvent.Query().
		Where(registryevent.EventTypeEQ(registryevent.EventTypeDependencyResolved)).
		Where(registryevent.HasAgentWith(agent.IDEQ(consumerAgentID))).
		Where(registryevent.FunctionNameEQ(functionName)).
		Order(registryevent.ByTimestamp(sql.OrderDesc())).
		Limit(priorTraceLookupLimit)

	events, err := q.All(ctx)
	if err != nil {
		return nil, err
	}
	_, trace := pickEventWithDepIndex(events, depIndex)
	return trace, nil
}

// lastAuditTraceFor returns the most recent audit event (resolved OR unresolved)
// for the given (consumer, function, dep_index) along with its decoded trace.
// The raw event row is returned so callers can inspect EventType (e.g., to
// distinguish an unresolved→resolved flip from a steady-state resolution).
// Used by the dedupe step that suppresses repeat emissions whose canonical
// hashes are identical.
func (s *EntService) lastAuditTraceFor(
	ctx context.Context,
	consumerAgentID string,
	functionName string,
	depIndex int,
) (*ent.RegistryEvent, *AuditTrace, error) {
	q := s.entDB.RegistryEvent.Query().
		Where(registryevent.EventTypeIn(
			registryevent.EventTypeDependencyResolved,
			registryevent.EventTypeDependencyUnresolved,
		)).
		Where(registryevent.HasAgentWith(agent.IDEQ(consumerAgentID))).
		Where(registryevent.FunctionNameEQ(functionName)).
		Order(registryevent.ByTimestamp(sql.OrderDesc())).
		Limit(priorTraceLookupLimit)

	events, err := q.All(ctx)
	if err != nil {
		return nil, nil, err
	}
	evt, trace := pickEventWithDepIndex(events, depIndex)
	return evt, trace, nil
}

// pickEventWithDepIndex walks events newest-first and returns the first event
// whose decoded AuditTrace dep_index matches, along with that decoded trace.
// Returns (nil, nil) when nothing matches.
func pickEventWithDepIndex(events []*ent.RegistryEvent, depIndex int) (*ent.RegistryEvent, *AuditTrace) {
	for _, e := range events {
		if e.Data == nil {
			continue
		}
		// data["dep_index"] is float64 after JSON round-trip into map.
		var di int
		switch v := e.Data["dep_index"].(type) {
		case float64:
			di = int(v)
		case int:
			di = v
		case int64:
			di = int(v)
		default:
			continue
		}
		if di != depIndex {
			continue
		}

		raw, err := json.Marshal(e.Data)
		if err != nil {
			continue
		}
		var t AuditTrace
		if err := json.Unmarshal(raw, &t); err != nil {
			continue
		}
		return e, &t
	}
	return nil, nil
}
