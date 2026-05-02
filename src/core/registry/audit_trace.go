package registry

// EvictionReason is a typed enum for why a candidate was dropped from the
// dependency-resolution pipeline. New reasons MUST be added to this enum
// (rather than freeform strings) so audit consumers can pattern-match.
type EvictionReason string

const (
	// ReasonMissingTag — provider lacks a required tag.
	ReasonMissingTag EvictionReason = "MissingTag"
	// ReasonExtraTagDisallowed — provider has a tag explicitly excluded by the consumer.
	ReasonExtraTagDisallowed EvictionReason = "ExtraTagDisallowed"
	// ReasonVersionConstraintFailed — provider's version does not satisfy the consumer's constraint.
	ReasonVersionConstraintFailed EvictionReason = "VersionConstraintFailed"
	// ReasonSchemaIncompatible — provider's schema does not satisfy the consumer's schema mode.
	// Emitted by the schema stage (#547) when the consumer opted in via match_mode and
	// the producer's canonical output schema doesn't match (subset or strict).
	ReasonSchemaIncompatible EvictionReason = "SchemaIncompatible"
	// ReasonUnhealthy — provider is not healthy at resolution time.
	ReasonUnhealthy EvictionReason = "Unhealthy"
	// ReasonDeregistering — provider is in the middle of a graceful shutdown.
	ReasonDeregistering EvictionReason = "Deregistering"
	// ReasonUnreachable — provider's endpoint can't be reached for invocation.
	ReasonUnreachable EvictionReason = "Unreachable"
)

// Audit-trail stage names. Stages run in this order:
// health → capability_match → tags → version → schema → tiebreaker.
// Health runs first so subsequent stages don't drag stale unhealthy candidates
// through every stage's audit listing. Each stage records what it kept and what
// it evicted (with reason). The "tiebreaker" stage records the final pick from
// the survivors.
const (
	StageHealth          = "health" // catches unhealthy/deregistering
	StageCapabilityMatch = "capability_match"
	StageTags            = "tags"
	StageVersion         = "version"
	StageSchema          = "schema" // opt-in canonical-schema check (#547); no-op when consumer's match_mode is empty
	StageTiebreaker      = "tiebreaker"
)

// TiebreakerHighestScoreFirst names the current resolver's tiebreaker logic:
// candidates are sorted by tag-match score (descending) and the first is picked.
// Documenting this in the audit makes it explicit; configurable tiebreakers
// are out of scope for v1.
const TiebreakerHighestScoreFirst = "HighestScoreFirst"

// AuditTrace is the JSON payload stored in RegistryEvent.data for
// dependency_resolved / dependency_unresolved events.
type AuditTrace struct {
	Consumer    string       `json:"consumer"`
	DepIndex    int          `json:"dep_index"`
	Spec        AuditSpec    `json:"spec"`
	Stages      []AuditStage `json:"stages"`
	Chosen      *AuditChosen `json:"chosen,omitempty"`       // nil for dependency_unresolved
	PriorChosen string       `json:"prior_chosen,omitempty"` // empty on initial wire
}

// AuditSpec captures the consumer's dependency requirement.
type AuditSpec struct {
	Capability        string   `json:"capability"`
	Tags              []string `json:"tags,omitempty"`
	VersionConstraint string   `json:"version_constraint,omitempty"`
	SchemaMode        string   `json:"schema_mode"` // "none" | "subset" | "strict" (#547)
}

// AuditStage records what happened at one step of the resolution pipeline.
//
// Candidate identifiers in Kept and Chosen use the format
// "<agent_id>:<function_name>" so that two functions on the same agent
// providing the same capability with different tags can be distinguished
// in the trace. The Chosen.AgentID field on AuditTrace remains the bare
// agent ID (the chosen producer); only per-stage candidate identifiers
// carry the colon-form. Older events stored in the registry may use the
// bare-agent-id format; renderers should display IDs as-is without
// special handling.
type AuditStage struct {
	Stage   string         `json:"stage"`
	Kept    []string       `json:"kept"`
	Evicted []AuditEvicted `json:"evicted,omitempty"`
	Chosen  string         `json:"chosen,omitempty"` // only set on the tiebreaker stage; format "<agent_id>:<function_name>"
	Reason  string         `json:"reason,omitempty"` // only set on the tiebreaker stage (e.g., "HighestScoreFirst")
}

// AuditEvicted records a single dropped candidate with a typed reason and
// optional structured details (e.g., {"version": "1.4", "constraint": ">=2.0"}).
//
// ID format is "<agent_id>:<function_name>" — see AuditStage doc for rationale.
type AuditEvicted struct {
	ID      string                 `json:"id"`
	Reason  EvictionReason         `json:"reason"`
	Details map[string]interface{} `json:"details,omitempty"`
}

// AuditChosen identifies the producer the resolver picked.
type AuditChosen struct {
	AgentID      string `json:"agent_id"`
	Endpoint     string `json:"endpoint"`
	FunctionName string `json:"function_name"`
}

// IsInteresting returns true if this trace warrants emitting an audit event.
// A trace is interesting when ≥2 candidates entered any stage of the pipeline.
// The other interesting case (chosen producer differs from prior_chosen) is
// detected by the caller, which has access to the previously-stored event.
func (t *AuditTrace) IsInteresting() bool {
	for _, s := range t.Stages {
		// Count entry to this stage = kept + evicted (the tiebreaker doesn't
		// evict but its kept count carries over from the previous stage).
		if len(s.Kept)+len(s.Evicted) >= 2 {
			return true
		}
	}
	return false
}
