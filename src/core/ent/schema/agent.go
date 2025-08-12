package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/dialect/entsql"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
)

// Agent holds the schema definition for the Agent entity.
type Agent struct {
	ent.Schema
}

// Fields of the Agent.
func (Agent) Fields() []ent.Field {
	return []ent.Field{
		field.String("id").
			StorageKey("agent_id").
			Comment("Unique identifier for the agent"),
		field.Enum("agent_type").
			Values("mcp_agent", "mesh_tool", "decorator_agent", "api").
			Default("mcp_agent").
			Comment("Type of agent"),
		field.String("name").
			Comment("Human-readable name of the agent"),
		field.String("version").
			Optional().
			Comment("Version of the agent"),
		field.String("http_host").
			Optional().
			Comment("HTTP host for the agent"),
		field.Int("http_port").
			Optional().
			Comment("HTTP port for the agent"),
		field.String("namespace").
			Default("default").
			Comment("Namespace for the agent"),
		field.Enum("status").
			Values("healthy", "unhealthy", "unknown").
			Default("healthy").
			Comment("Current health status of the agent"),
		field.Int("total_dependencies").
			Default(0).
			Comment("Total number of dependencies"),
		field.Int("dependencies_resolved").
			Default(0).
			Comment("Number of resolved dependencies"),
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("Creation timestamp"),
		field.Time("updated_at").
			Default(time.Now).
			UpdateDefault(time.Now).
			Comment("Last update timestamp"),
		field.Time("last_full_refresh").
			Default(time.Now).
			Comment("Timestamp of last full heartbeat (vs HEAD check)"),
	}
}

// Edges of the Agent.
func (Agent) Edges() []ent.Edge {
	return []ent.Edge{
		edge.To("capabilities", Capability.Type).
			Annotations(entsql.Annotation{
				OnDelete: entsql.Cascade,
			}).
			Comment("Capabilities provided by this agent"),
		edge.To("events", RegistryEvent.Type).
			Annotations(entsql.Annotation{
				OnDelete: entsql.Cascade,
			}).
			Comment("Registry events for this agent"),
	}
}

// Indexes of the Agent.
func (Agent) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("namespace"),
		index.Fields("agent_type"),
		index.Fields("updated_at"),
		index.Fields("status"),
		index.Fields("status", "updated_at"), // Composite index for health monitoring queries
	}
}
