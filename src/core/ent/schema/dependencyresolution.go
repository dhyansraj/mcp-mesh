package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/dialect/entsql"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
)

// DependencyResolution holds the schema definition for the DependencyResolution entity.
// Tracks both resolved and unresolved dependencies for each agent's tools.
type DependencyResolution struct {
	ent.Schema
}

// Fields of the DependencyResolution.
func (DependencyResolution) Fields() []ent.Field {
	return []ent.Field{
		// Consumer (requester) information
		field.String("consumer_agent_id").
			Comment("Agent ID that requires this dependency"),
		field.String("consumer_function_name").
			Comment("Function/tool name that requires this dependency"),
		field.Int("dep_index").
			Default(0).
			NonNegative().
			Comment("Position of this dependency in the tool's dependency array (0-indexed). Maintains positional integrity for SDK injection."),

		// Required dependency specification
		field.String("capability_required").
			Comment("Required capability name (e.g., 'date_service', 'weather_info')"),
		field.JSON("tags_required", []string{}).
			Optional().
			Comment("Required tags for smart matching"),
		field.String("version_required").
			Optional().
			Comment("Version constraint (e.g., '>=1.0.0')"),
		field.String("namespace_required").
			Default("default").
			Comment("Required namespace"),

		// Provider (resolver) information - nullable if unresolved
		field.String("provider_agent_id").
			Optional().
			Nillable().
			Comment("Agent ID providing this dependency (NULL if unresolved)"),
		field.String("provider_function_name").
			Optional().
			Nillable().
			Comment("MCP tool/function name on provider agent (NULL if unresolved)"),
		field.String("endpoint").
			Optional().
			Nillable().
			Comment("Provider endpoint URL (NULL if unresolved)"),

		// Resolution status
		field.Enum("status").
			Values("available", "unavailable", "unresolved").
			Default("unresolved").
			Comment("Dependency resolution status"),
		field.Time("resolved_at").
			Optional().
			Nillable().
			Comment("When this dependency was last successfully resolved"),

		// Timestamps
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("Creation timestamp"),
		field.Time("updated_at").
			Default(time.Now).
			UpdateDefault(time.Now).
			Comment("Last update timestamp"),
	}
}

// Edges of the DependencyResolution.
func (DependencyResolution) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("consumer_agent", Agent.Type).
			Ref("dependency_resolutions").
			Field("consumer_agent_id").
			Unique().
			Required().
			Annotations(entsql.Annotation{
				OnDelete: entsql.Cascade,
			}).
			Comment("Agent that requires this dependency"),
		edge.To("provider_agent", Agent.Type).
			Field("provider_agent_id").
			Unique().
			Annotations(entsql.Annotation{
				OnDelete: entsql.SetNull,
			}).
			Comment("Agent that provides this dependency (nullable)"),
	}
}

// Indexes of the DependencyResolution.
func (DependencyResolution) Indexes() []ent.Index {
	return []ent.Index{
		// Fast lookup of all dependencies for a consumer agent
		index.Fields("consumer_agent_id", "consumer_function_name"),
		// Fast lookup by position (for ordered dependency retrieval)
		index.Fields("consumer_agent_id", "consumer_function_name", "dep_index"),
		// Fast lookup when provider agent goes offline
		index.Fields("provider_agent_id"),
		// Query by capability
		index.Fields("capability_required"),
		// Query by status
		index.Fields("status"),
		// Composite for finding unresolved dependencies
		index.Fields("consumer_agent_id", "status"),
	}
}
