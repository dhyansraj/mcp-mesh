package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
)

// RegistryEvent holds the schema definition for the RegistryEvent entity.
type RegistryEvent struct {
	ent.Schema
}

// Fields of the RegistryEvent.
func (RegistryEvent) Fields() []ent.Field {
	return []ent.Field{
		field.Enum("event_type").
			Values("register", "heartbeat", "expire", "update", "unregister", "unhealthy", "rotate", "dependency_resolved", "dependency_unresolved").
			Comment("Type of registry event"),
		field.String("function_name").
			Optional().
			Comment("Function name for function-level events (NULL for agent-level events)"),
		field.Time("timestamp").
			Default(time.Now).
			Comment("When this event occurred"),
		field.JSON("data", map[string]interface{}{}).
			Default(map[string]interface{}{}).
			Comment("Additional event data as JSON"),
	}
}

// Edges of the RegistryEvent.
func (RegistryEvent) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("agent", Agent.Type).
			Ref("events").
			Unique().
			Required().
			Comment("Agent this event relates to"),
	}
}

// Indexes of the RegistryEvent.
func (RegistryEvent) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("timestamp"),
		index.Fields("event_type"),
		// Supports the dependency-audit prior-trace lookup, which runs on every
		// full heartbeat that re-resolves dependencies (issue #1582):
		//   WHERE function_name = ? AND event_type IN (...) AND <consumer agent>
		//   ORDER BY timestamp DESC LIMIT 64
		// Emitted column order is (function_name, timestamp, agent_events) —
		// ent always places Fields() columns before Edges() columns, so the FK
		// column behind the `agent` edge cannot lead.
		//
		// What the shape guarantees: function_name is an equality prefix and
		// timestamp the ordered suffix, so the ORDER BY ... LIMIT is served by
		// an index scan instead of a full scan plus sort. What it does NOT
		// guarantee: event_type is not in the index (it is a recheck), and the
		// consumer filter reaches the query as an EXISTS subquery rather than
		// `agent_events = ?`, so the trailing FK column is not inherently an
		// access predicate — how many index entries the LIMIT touches depends
		// on the planner. (Postgres 16 was observed folding the semi-join
		// equality into the index scan, making both function_name and
		// agent_events access predicates; that is a planner behavior, not a
		// property of the index.) Also narrows `meshctl audit` / GET /events
		// when filtered by function name.
		index.Fields("function_name", "timestamp").Edges("agent"),
	}
}
