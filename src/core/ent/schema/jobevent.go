package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
)

// JobEvent holds the schema definition for the JobEvent entity.
// Backs the MeshJob event-injection substrate (issue #1032): a consumer or
// the registry itself appends events into the per-job ordered log that an
// executing job can `recv_event` from. One row per posted event; rows are
// never updated — appended only — and are garbage-collected by the sweep
// after the parent job has been terminal beyond the retention window.
//
// Mirrors Job's convention of referencing the parent by string job_id
// (no FK edge) — see the comment on Job.Edges for the rationale (parent
// row may be sweep-deleted while events persist briefly for tailers).
type JobEvent struct {
	ent.Schema
}

// Fields of the JobEvent.
func (JobEvent) Fields() []ent.Field {
	return []ent.Field{
		// Server-assigned monotonic sequence per job. Assigned inside a
		// transaction as max(seq)+1 with the (job_id, seq) UNIQUE index
		// acting as the concurrency guard — concurrent posters either
		// land on different seq values or one retries on conflict.
		field.Int64("seq").
			Comment("Per-job monotonic sequence number, assigned by registry on POST"),

		// Job pointer by string (mirrors Job.owner_instance_id convention —
		// string FK rather than ent edge so events outlive the job row by
		// the sweep grace window).
		field.String("job_id").
			NotEmpty().
			Comment("ID of the job this event belongs to"),

		// Event content.
		field.String("type").
			NotEmpty().
			Comment("Event type tag (e.g. 'extend_deadline', 'cancelled', user-defined)"),
		field.JSON("payload", map[string]interface{}{}).
			Optional().
			Comment("Arbitrary JSON event payload"),

		// Observability: W3C trace context propagated from sender for
		// child-span linkage. Optional — synthetic events (e.g. the cancel
		// post inside CancelJob) carry no trace context.
		field.JSON("trace_context", map[string]interface{}{}).
			Optional().
			Comment("W3C trace context (traceparent + tracestate) propagated from sender"),

		// Audit. Sender identity extracted from request context if available
		// (mTLS entity_id, etc.); nillable so synthetic / unauthenticated
		// posts can omit it.
		field.String("posted_by").
			Optional().
			Nillable().
			Comment("Identity of the sender (entity ID from TLS, if available)"),

		// Timing.
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("Server-assigned timestamp"),
	}
}

// Edges of the JobEvent. None — parent linkage is via the job_id string
// field, matching Job's "no edges in Phase 1" stance (see Job.Edges).
func (JobEvent) Edges() []ent.Edge { return nil }

// Indexes of the JobEvent.
func (JobEvent) Indexes() []ent.Index {
	return []ent.Index{
		// Primary read path: events for one job ordered by seq. Uniqueness
		// enforces per-job monotonic seq under concurrent posters — the
		// service layer relies on this to detect lost races and retry.
		index.Fields("job_id", "seq").Unique(),
		// Sweep GC index: events older than job termination + grace window.
		index.Fields("job_id", "created_at"),
	}
}
