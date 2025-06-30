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
			Values("register", "heartbeat", "expire", "update", "unregister").
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
	}
}
