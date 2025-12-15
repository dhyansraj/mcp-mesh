package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/dialect/entsql"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
)

// LLMToolResolution holds the schema definition for resolved LLM tools.
// Tracks tools that match the @mesh.llm filter configuration for each function.
type LLMToolResolution struct {
	ent.Schema
}

// Fields of the LLMToolResolution.
func (LLMToolResolution) Fields() []ent.Field {
	return []ent.Field{
		// Consumer (requester) information
		field.String("consumer_agent_id").
			Comment("Agent ID that has the @mesh.llm decorated function"),
		field.String("consumer_function_name").
			Comment("Function/tool name with @mesh.llm decorator"),

		// Filter specification (what was requested)
		field.String("filter_capability").
			Optional().
			Nillable().
			Comment("Capability specified in the filter (e.g., 'time_service')"),
		field.JSON("filter_tags", []string{}).
			Optional().
			Comment("Tags specified in the filter"),
		field.String("filter_mode").
			Default("all").
			Comment("Filter mode: all, best_match, *"),

		// Provider (resolved tool) information
		field.String("provider_agent_id").
			Optional().
			Nillable().
			Comment("Agent ID providing this tool (NULL if unresolved)"),
		field.String("provider_function_name").
			Optional().
			Nillable().
			Comment("MCP tool/function name on provider agent"),
		field.String("provider_capability").
			Optional().
			Nillable().
			Comment("Capability name of the resolved tool"),
		field.String("endpoint").
			Optional().
			Nillable().
			Comment("Provider endpoint URL"),

		// Resolution status
		field.Enum("status").
			Values("available", "unavailable", "unresolved").
			Default("unresolved").
			Comment("Tool resolution status"),
		field.Time("resolved_at").
			Optional().
			Nillable().
			Comment("When this tool was last successfully resolved"),

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

// Edges of the LLMToolResolution.
func (LLMToolResolution) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("consumer_agent", Agent.Type).
			Ref("llm_tool_resolutions").
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
			Comment("Agent that provides this tool (nullable)"),
	}
}

// Indexes of the LLMToolResolution.
func (LLMToolResolution) Indexes() []ent.Index {
	return []ent.Index{
		// Fast lookup of all LLM tools for a consumer agent
		index.Fields("consumer_agent_id", "consumer_function_name"),
		// Fast lookup when provider agent goes offline
		index.Fields("provider_agent_id"),
		// Query by filter capability
		index.Fields("filter_capability"),
		// Query by status
		index.Fields("status"),
		// Composite for finding unresolved tools
		index.Fields("consumer_agent_id", "status"),
	}
}
