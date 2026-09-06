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
// lookup scans when searching for a matching dep_index. Headroom for functions
// with many deps + concurrent writes; raise if you have functions with >64
// deps. Future: push the dep_index filter into SQL via a JSON path expression
// so we don't need to overscan in Go.
//
// The limit applies per event-type set, exactly as it did when each lookup
// issued its own query (#1582 changed WHERE the queries run, not what they
// select). Merging the two sets into one LIMIT-64 window was tried and
// rejected: the window is scoped to (consumer, function), NOT to dep_index, so
// unresolved events from sibling dep slots would evict a slot's own last
// resolved event and silently swallow a chosen-producer flip.
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
	history *auditHistoryCache,
) error {
	if trace == nil {
		return nil
	}

	// Stamp consumer/dep_index into the trace so downstream consumers don't
	// have to reconstruct them from the event metadata.
	trace.Consumer = consumerAgentID
	trace.DepIndex = depIndex

	// Look up the prior emission for this (consumer, function, dep_index).
	//
	// Issue #1582: the two lookups below are unchanged in what they select,
	// but each is now issued once per (consumer, function) and shared by every
	// dependency of that function through `history`, instead of once per
	// dependency. A 32-dep function goes from 64 queries per full heartbeat to
	// 2. They stay separate queries on purpose — see priorTraceLookupLimit.
	priorByDep, err := s.auditLatestByDep(ctx, history, consumerAgentID, functionName, true)
	if err != nil {
		return fmt.Errorf("audit: query prior trace: %w", err)
	}

	priorChosen := ""
	if prior := priorByDep[depIndex]; prior != nil && prior.trace.Chosen != nil {
		priorChosen = prior.trace.Chosen.AgentID
	}
	trace.PriorChosen = priorChosen

	// Look up the most recent audit event (resolved OR unresolved) so we can
	// (a) detect an unresolved→resolved flip even when only one candidate
	// survives, and (b) dedupe identical-trace re-emissions further down.
	anyByDep, err := s.auditLatestByDep(ctx, history, consumerAgentID, functionName, false)
	if err != nil {
		return fmt.Errorf("audit: query last trace: %w", err)
	}
	var (
		lastAnyEvent *ent.RegistryEvent
		lastAny      *AuditTrace
	)
	if last := anyByDep[depIndex]; last != nil {
		lastAnyEvent, lastAny = last.event, last.trace
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
	// sequences also dedupe; without this the relaxed `hasEvictions` rule above
	// would flood the audit log when a transient unhealthy producer re-evicts
	// every heartbeat (see TestAudit_UnresolvedFloodIsDeduped).
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

// auditEventTrace pairs an audit event row with its decoded trace. The raw row
// is kept so callers can inspect EventType (e.g. to distinguish an
// unresolved→resolved flip from a steady-state resolution).
type auditEventTrace struct {
	event *ent.RegistryEvent
	trace *AuditTrace
}

// auditHistoryCache memoizes the prior-event lookups for the duration of a
// single StoreDependencyResolutions call. The queries are per (consumer,
// function) and their results are bucketed by dep_index, so every dependency
// of the same function reuses one query and one decode pass per event-type set
// instead of issuing its own (issue #1582). Two buckets, because the two
// lookups select different event types and must keep their own LIMIT windows.
//
// Events written by the loop that owns the cache are deliberately not visible
// to it: an emission for dep_index i can only ever be the "prior" of dep_index
// i, and each (function, dep_index) slot is processed at most once per call.
type auditHistoryCache struct {
	resolvedOnly map[string]map[int]*auditEventTrace
	anyType      map[string]map[int]*auditEventTrace
}

func newAuditHistoryCache() *auditHistoryCache {
	return &auditHistoryCache{
		resolvedOnly: make(map[string]map[int]*auditEventTrace),
		anyType:      make(map[string]map[int]*auditEventTrace),
	}
}

// auditLatestByDep returns, per dep_index, the most recent audit event for the
// given (consumer, function) — restricted to dependency_resolved when
// `resolvedOnly`, otherwise covering both audit event types. Uses and
// populates `cache` when one is supplied; a nil cache is legal and just runs
// the lookup uncached.
//
// Filters: agent_id == consumer, event_type IN (...), function_name ==
// functionName, ORDER BY timestamp DESC LIMIT priorTraceLookupLimit — i.e.
// the same queries the per-dependency lookups used to issue. The
// (function_name, timestamp, agent_events) index on registry_events serves the
// ordering and the LIMIT; see the schema for what that index does and does not
// guarantee.
func (s *EntService) auditLatestByDep(
	ctx context.Context,
	cache *auditHistoryCache,
	consumerAgentID string,
	functionName string,
	resolvedOnly bool,
) (map[int]*auditEventTrace, error) {
	key := consumerAgentID + "\x00" + functionName

	var bucket map[string]map[int]*auditEventTrace
	if cache != nil {
		bucket = cache.anyType
		if resolvedOnly {
			bucket = cache.resolvedOnly
		}
		if byDep, ok := bucket[key]; ok {
			return byDep, nil
		}
	}

	typeFilter := registryevent.EventTypeIn(
		registryevent.EventTypeDependencyResolved,
		registryevent.EventTypeDependencyUnresolved,
	)
	if resolvedOnly {
		typeFilter = registryevent.EventTypeEQ(registryevent.EventTypeDependencyResolved)
	}

	events, err := s.entDB.RegistryEvent.Query().
		Where(typeFilter).
		Where(registryevent.HasAgentWith(agent.IDEQ(consumerAgentID))).
		Where(registryevent.FunctionNameEQ(functionName)).
		Order(registryevent.ByTimestamp(sql.OrderDesc())).
		Limit(priorTraceLookupLimit).
		All(ctx)
	if err != nil {
		return nil, err
	}

	byDep := indexAuditEventsByDep(events)
	if bucket != nil {
		bucket[key] = byDep
	}
	return byDep, nil
}

// indexAuditEventsByDep walks a newest-first event slice ONCE and keeps, per
// dep_index, the newest event whose payload decodes as an AuditTrace. Rows that
// carry no usable dep_index or fail to decode are skipped, so an older event
// can still fill the slot — matching what the per-dependency scan did.
func indexAuditEventsByDep(events []*ent.RegistryEvent) map[int]*auditEventTrace {
	byDep := make(map[int]*auditEventTrace)
	for _, e := range events {
		di, ok := depIndexOf(e)
		if !ok {
			continue
		}
		if _, seen := byDep[di]; seen {
			continue // a newer row already claimed this slot
		}
		trace := decodeAuditTrace(e)
		if trace == nil {
			continue
		}
		byDep[di] = &auditEventTrace{event: e, trace: trace}
	}
	return byDep
}

// depIndexOf extracts the dep_index from an event payload. data["dep_index"]
// is float64 after the JSON round-trip into map.
func depIndexOf(e *ent.RegistryEvent) (int, bool) {
	if e.Data == nil {
		return 0, false
	}
	switch v := e.Data["dep_index"].(type) {
	case float64:
		return int(v), true
	case int:
		return v, true
	case int64:
		return int(v), true
	default:
		return 0, false
	}
}

// decodeAuditTrace decodes an event payload into an AuditTrace, returning nil
// when the payload isn't a trace.
func decodeAuditTrace(e *ent.RegistryEvent) *AuditTrace {
	raw, err := json.Marshal(e.Data)
	if err != nil {
		return nil
	}
	var t AuditTrace
	if err := json.Unmarshal(raw, &t); err != nil {
		return nil
	}
	return &t
}
