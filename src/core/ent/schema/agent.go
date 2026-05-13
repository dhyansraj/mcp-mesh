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
			Values("mcp_agent", "mesh_tool", "decorator_agent", "api", "a2a").
			Default("mcp_agent").
			Comment("Type of agent (mcp_agent | mesh_tool | decorator_agent | api | a2a)"),
		field.Enum("runtime").
			Values("python", "typescript", "java").
			Default("python").
			Optional().
			Comment("SDK runtime: python, typescript, or java"),
		field.String("name").
			Comment("Human-readable name of the agent"),
		field.String("version").
			Optional().
			Comment("Version of the agent"),
		field.String("description").
			Optional().
			Default("").
			MaxLen(256).
			Comment("Free-form agent description (≤256 chars, plain text)"),
		field.Bool("a2a_producer").
			Optional().
			Default(false).
			Comment("True if this agent has at least one A2A producer surface declared"),
		field.Bool("a2a_consumer").
			Optional().
			Default(false).
			Comment("True if this agent has at least one A2A consumer surface declared"),
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
			Comment("Last update timestamp - manually managed to preserve health check semantics"),
		field.Time("last_full_refresh").
			Default(time.Now).
			Comment("Timestamp of last full heartbeat (vs HEAD check)"),
		field.String("entity_id").
			Optional().
			Nillable().
			Comment("Entity ID from TLS certificate verification"),
		field.JSON("a2a_surfaces", []map[string]interface{}{}).
			Optional().
			Comment("A2A surface metadata (path, skill_id, description, etc.) — populated for a2a-typed agents only. JSON for v1 simplicity; promote to entity if query patterns demand it later."),
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
		edge.To("dependency_resolutions", DependencyResolution.Type).
			Annotations(entsql.Annotation{
				OnDelete: entsql.Cascade,
			}).
			Comment("Dependency resolutions for this agent's tools"),
		edge.To("llm_tool_resolutions", LLMToolResolution.Type).
			Annotations(entsql.Annotation{
				OnDelete: entsql.Cascade,
			}).
			Comment("LLM tool resolutions for @mesh.llm filter"),
		edge.To("llm_provider_resolutions", LLMProviderResolution.Type).
			Annotations(entsql.Annotation{
				OnDelete: entsql.Cascade,
			}).
			Comment("LLM provider resolutions for @mesh.llm provider"),
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
