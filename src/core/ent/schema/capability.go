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
		field.JSON("tags", []string{}).
			Default([]string{}).
			Comment("Tags for this capability (e.g., ['prod', 'ml', 'gpu'])"),
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
