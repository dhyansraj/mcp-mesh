package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/dialect/entsql"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
)

// LLMProviderResolution holds the schema definition for resolved LLM providers.
// Tracks providers that match the @mesh.llm provider configuration for each function.
type LLMProviderResolution struct {
	ent.Schema
}

// Fields of the LLMProviderResolution.
func (LLMProviderResolution) Fields() []ent.Field {
	return []ent.Field{
		// Consumer (requester) information
		field.String("consumer_agent_id").
			Comment("Agent ID that has the @mesh.llm decorated function"),
		field.String("consumer_function_name").
			Comment("Function/tool name with @mesh.llm decorator"),

		// Provider specification (what was requested)
		field.String("required_capability").
			Comment("Required capability (e.g., 'llm')"),
		field.JSON("required_tags", []string{}).
			Optional().
			Comment("Required tags for smart matching (e.g., ['llm', '+claude'])"),
		field.String("required_version").
			Optional().
			Nillable().
			Comment("Version constraint (e.g., '>=1.0.0')"),
		field.String("required_namespace").
			Default("default").
			Comment("Required namespace"),

		// Provider (resolved) information
		field.String("provider_agent_id").
			Optional().
			Nillable().
			Comment("Agent ID providing LLM capability (NULL if unresolved)"),
		field.String("provider_function_name").
			Optional().
			Nillable().
			Comment("MCP tool/function name on provider agent (e.g., 'llm')"),
		field.String("endpoint").
			Optional().
			Nillable().
			Comment("Provider endpoint URL"),

		// Resolution status
		field.Enum("status").
			Values("available", "unavailable", "unresolved").
			Default("unresolved").
			Comment("Provider resolution status"),
		field.Time("resolved_at").
			Optional().
			Nillable().
			Comment("When this provider was last successfully resolved"),

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

// Edges of the LLMProviderResolution.
func (LLMProviderResolution) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("consumer_agent", Agent.Type).
			Ref("llm_provider_resolutions").
			Field("consumer_agent_id").
			Unique().
			Required().
			Annotations(entsql.Annotation{
				OnDelete: entsql.Cascade,
			}).
			Comment("Agent that has the @mesh.llm function"),
		edge.To("provider_agent", Agent.Type).
			Field("provider_agent_id").
			Unique().
			Annotations(entsql.Annotation{
				OnDelete: entsql.SetNull,
			}).
			Comment("Agent that provides LLM capability (nullable)"),
	}
}

// Indexes of the LLMProviderResolution.
func (LLMProviderResolution) Indexes() []ent.Index {
	return []ent.Index{
		// Fast lookup of all LLM providers for a consumer agent
		index.Fields("consumer_agent_id", "consumer_function_name"),
		// Fast lookup when provider agent goes offline
		index.Fields("provider_agent_id"),
		// Query by required capability
		index.Fields("required_capability"),
		// Query by status
		index.Fields("status"),
		// Composite for finding unresolved providers
		index.Fields("consumer_agent_id", "status"),
	}
}
