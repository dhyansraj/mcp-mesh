package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
)

// Capability holds the schema definition for the Capability entity.
type Capability struct {
	ent.Schema
}

// Fields of the Capability.
func (Capability) Fields() []ent.Field {
	return []ent.Field{
		field.String("function_name").
			Comment("Name of the function (e.g., 'smart_greet', 'get_weather_report')"),
		field.String("capability").
			Comment("Capability identifier (e.g., 'personalized_greeting', 'weather_report')"),
		field.String("version").
			Default("1.0.0").
			Comment("Version of the capability"),
		field.String("description").
			Optional().
			Comment("Description of what this capability does"),
		field.JSON("input_schema", map[string]interface{}{}).
			Optional().
			Comment("JSON Schema for function parameters (MCP tool format). Auto-generated from function signature by FastMCP. Used by LLM agents to understand how to call this tool."),
		field.JSON("llm_filter", map[string]interface{}{}).
			Optional().
			Comment("LLM tool filter specification when function is decorated with @mesh.llm. Defines which tools this LLM agent needs access to."),
		field.JSON("tags", []string{}).
			Default([]string{}).
			Comment("Tags for this capability (e.g., ['prod', 'ml', 'gpu'])"),
		field.JSON("kwargs", map[string]interface{}{}).
			Optional().
			Comment("Additional kwargs from @mesh.tool decorator for enhanced client proxy configuration (timeout, retry_count, custom_headers, streaming, auth_required, etc.)"),
		field.JSON("dependencies", []map[string]interface{}{}).
			Optional().
			Comment("Dependencies required by this capability/function. Stores the raw dependency specifications from the tool registration."),
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

// Edges of the Capability.
func (Capability) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("agent", Agent.Type).
			Ref("capabilities").
			Unique().
			Required().
			Comment("Agent that provides this capability"),
	}
}

// Indexes of the Capability.
func (Capability) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("capability"),
		index.Fields("function_name"),
	}
}
