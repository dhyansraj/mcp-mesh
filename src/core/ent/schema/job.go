package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
)

// Job holds the schema definition for the Job entity.
// Backs the MeshJob substrate (long-running async tool calls). One row per
// submitted job; updated through state transitions:
//
//	working -> input_required (optional) -> completed | failed | cancelled
//
// See MESHJOB_DESIGN.org for the full state machine, lease semantics, and
// retry rules.
type Job struct {
	ent.Schema
}

// Fields of the Job.
func (Job) Fields() []ent.Field {
	return []ent.Field{
		// Identity. Server-generated UUID (~122-bit entropy); the job ID
		// itself acts as the capability for status reads (presigned-URL
		// semantics — see Auth model in design doc).
		field.String("id").
			StorageKey("job_id").
			NotEmpty().
			Comment("Unique identifier for the job (server-generated UUID)"),

		// Routing.
		field.String("capability").
			NotEmpty().
			Comment("Capability name this job targets (e.g. 'render_report')"),
		field.String("owner_instance_id").
			Optional().
			Nillable().
			Comment("Pins job to a specific replica instance; NULL when unclaimed/orphaned and eligible for re-claim"),

		// State.
		field.Enum("status").
			Values("working", "input_required", "completed", "failed", "cancelled").
			Default("working").
			Comment("Current job status"),
		field.Float("progress").
			Optional().
			Nillable().
			Comment("Optional progress fraction in [0.0, 1.0]"),
		field.String("progress_message").
			Optional().
			Nillable().
			Comment("Optional human-readable progress message"),

		// Terminal payload. MCP tool results are JSON-serializable by spec
		// (see Resolved Decisions: result storage is JSON only, binary
		// results use URI/ref convention).
		field.JSON("result", map[string]interface{}{}).
			Optional().
			Comment("Terminal result payload (set on status=completed)"),
		field.String("error").
			Optional().
			Nillable().
			Comment("Error message (set on status=failed)"),

		// Replay payload (full args + headers captured at submit time so a
		// new owner can re-execute on retry).
		field.JSON("submitted_payload", map[string]interface{}{}).
			Optional().
			Comment("Full submitted args + headers, used for retry replay"),

		// Retry bookkeeping.
		field.Int("attempt_count").
			Default(0).
			NonNegative().
			Comment("Number of attempts made so far"),
		field.Int("max_retries").
			Default(1).
			NonNegative().
			Comment("Maximum number of attempts allowed"),

		// Timeouts. Per-attempt soft timeout (seconds) and across-retry
		// total deadline. total_deadline defaults to NULL = unlimited
		// (bounded only by max_duration * max_retries); cron sweep only
		// acts when explicitly set.
		field.Int("max_duration").
			Optional().
			Nillable().
			Positive().
			Comment("Per-attempt soft timeout in seconds (NULL = runtime default)"),
		field.Time("total_deadline").
			Optional().
			Nillable().
			Comment("Wall-clock deadline across all retries (NULL = unlimited)"),

		// Lease + heartbeat. Lease expiry drives orphan reclaim; last
		// heartbeat is informational/diagnostic.
		field.Time("lease_expires_at").
			Optional().
			Nillable().
			Comment("When the current owner's lease expires; orphan reclaim eligible after this"),
		field.Time("last_heartbeat_at").
			Optional().
			Nillable().
			Comment("Timestamp of the most recent heartbeat from the owner"),

		// Submission metadata.
		field.Time("submitted_at").
			Default(time.Now).
			Immutable().
			Comment("When the job was submitted"),
		field.String("submitted_by").
			Optional().
			Nillable().
			Comment("Identity of the submitter (entity ID from TLS, if available)"),
	}
}

// Edges of the Job.
//
// Intentionally none in Phase 1. Owner is referenced by string instance ID
// rather than an FK to Agent because (a) the agent row may be sweep-deleted
// while the job persists for history/audit, and (b) the owner string maps to
// an instance, not necessarily a registered Agent row.
func (Job) Edges() []ent.Edge {
	return nil
}

// Indexes of the Job.
//
// Note: the design doc specifies two partial indexes (jobs_lease_expiry
// WHERE status='working'; jobs_pending_by_capability WHERE status='working'
// AND owner_instance_id IS NULL). Ent does not support partial indexes
// natively across SQLite + Postgres, so we emit plain indexes here and rely
// on a follow-up raw migration to upgrade them to partial indexes per
// dialect. TODO(meshjob): add dialect-specific partial-index migration in
// src/core/ent/migrate after generate-ent runs.
func (Job) Indexes() []ent.Index {
	return []ent.Index{
		// Composite for capability-scoped status queries (e.g. pending-jobs
		// counts in HEAD /heartbeat, plus claim worker scans).
		index.Fields("capability", "status"),
		// Lease-expiry sweep (full index; partial WHERE status='working'
		// applied via raw migration — see note above).
		index.Fields("lease_expires_at"),
		// Owner lookups (orphan reclaim sweep, cancel forwarding).
		index.Fields("owner_instance_id"),
		// Status-only scans (cron sweeps over working/input_required).
		index.Fields("status"),
	}
}
