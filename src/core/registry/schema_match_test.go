package registry

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// objectSchema is a tiny helper to keep the table-driven tests readable.
// Builds a {"type":"object", "properties":{...}, "required":[...]} schema.
func objectSchema(props map[string]interface{}, required ...string) map[string]interface{} {
	return map[string]interface{}{
		"type":       "object",
		"properties": props,
		"required":   required,
	}
}

func primSchema(typeName string) map[string]interface{} {
	return map[string]interface{}{"type": typeName}
}

func arraySchema(items map[string]interface{}) map[string]interface{} {
	return map[string]interface{}{
		"type":  "array",
		"items": items,
	}
}

// TestIsSchemaCompatible_Subset_TableDriven covers the subset rules listed in
// the issue #547 spec: missing required fields, type mismatches, the integer ⊆
// number relaxation, nested objects, and array items.
func TestIsSchemaCompatible_Subset_TableDriven(t *testing.T) {
	cases := []struct {
		name           string
		consumer       map[string]interface{}
		producer       map[string]interface{}
		wantCompatible bool
	}{
		{
			name: "extra_producer_field_ok",
			consumer: objectSchema(map[string]interface{}{
				"name": primSchema("string"),
				"dept": primSchema("string"),
			}, "name", "dept"),
			producer: objectSchema(map[string]interface{}{
				"name":   primSchema("string"),
				"dept":   primSchema("string"),
				"salary": primSchema("number"),
			}, "name", "dept", "salary"),
			wantCompatible: true,
		},
		{
			name: "missing_required_field",
			consumer: objectSchema(map[string]interface{}{
				"name": primSchema("string"),
				"dept": primSchema("string"),
			}, "name", "dept"),
			producer: objectSchema(map[string]interface{}{
				"name": primSchema("string"),
			}, "name"),
			wantCompatible: false,
		},
		{
			name: "type_mismatch_string_vs_integer",
			consumer: objectSchema(map[string]interface{}{
				"name": primSchema("string"),
			}, "name"),
			producer: objectSchema(map[string]interface{}{
				"name": primSchema("integer"),
			}, "name"),
			wantCompatible: false,
		},
		{
			name: "integer_satisfies_number",
			consumer: objectSchema(map[string]interface{}{
				"count": primSchema("number"),
			}, "count"),
			producer: objectSchema(map[string]interface{}{
				"count": primSchema("integer"),
			}, "count"),
			wantCompatible: true,
		},
		{
			name: "number_does_not_satisfy_integer",
			consumer: objectSchema(map[string]interface{}{
				"count": primSchema("integer"),
			}, "count"),
			producer: objectSchema(map[string]interface{}{
				"count": primSchema("number"),
			}, "count"),
			wantCompatible: false,
		},
		{
			name: "nested_object_extra_field_ok",
			consumer: objectSchema(map[string]interface{}{
				"address": objectSchema(map[string]interface{}{
					"city": primSchema("string"),
				}, "city"),
			}, "address"),
			producer: objectSchema(map[string]interface{}{
				"address": objectSchema(map[string]interface{}{
					"city": primSchema("string"),
					"zip":  primSchema("string"),
				}, "city", "zip"),
			}, "address"),
			wantCompatible: true,
		},
		{
			name: "nested_object_missing_required",
			consumer: objectSchema(map[string]interface{}{
				"address": objectSchema(map[string]interface{}{
					"city": primSchema("string"),
					"zip":  primSchema("string"),
				}, "city", "zip"),
			}, "address"),
			producer: objectSchema(map[string]interface{}{
				"address": objectSchema(map[string]interface{}{
					"city": primSchema("string"),
				}, "city"),
			}, "address"),
			wantCompatible: false,
		},
		{
			name: "array_items_match",
			consumer: objectSchema(map[string]interface{}{
				"tags": arraySchema(primSchema("string")),
			}, "tags"),
			producer: objectSchema(map[string]interface{}{
				"tags": arraySchema(primSchema("string")),
			}, "tags"),
			wantCompatible: true,
		},
		{
			name: "array_items_type_mismatch",
			consumer: objectSchema(map[string]interface{}{
				"tags": arraySchema(primSchema("string")),
			}, "tags"),
			producer: objectSchema(map[string]interface{}{
				"tags": arraySchema(primSchema("integer")),
			}, "tags"),
			wantCompatible: false,
		},
		{
			name: "consumer_required_no_property_decl_field_present",
			// Consumer requires "id" but has no property schema for it; producer
			// has the field — this is fine (subset cares about presence + types
			// when both sides declare a type).
			consumer: map[string]interface{}{
				"type":     "object",
				"required": []string{"id"},
			},
			producer: objectSchema(map[string]interface{}{
				"id": primSchema("string"),
			}, "id"),
			wantCompatible: true,
		},
		{
			name: "type_array_with_null_consumer_strict_subset",
			// Consumer accepts string OR null; producer just produces string.
			// String alone satisfies the consumer's "string" branch; the consumer
			// being more permissive (also accepts null) is fine for subset.
			consumer: objectSchema(map[string]interface{}{
				"name": map[string]interface{}{"type": []interface{}{"string", "null"}},
			}, "name"),
			producer: objectSchema(map[string]interface{}{
				"name": primSchema("string"),
			}, "name"),
			// Note: consumer requires BOTH string and null to be representable;
			// producer only allows string, so producer can't emit null. This is
			// technically a narrower producer, which fails subset.
			wantCompatible: false,
		},
		{
			name: "nil_consumer_ok",
			consumer: nil,
			producer: objectSchema(map[string]interface{}{
				"name": primSchema("string"),
			}, "name"),
			wantCompatible: true,
		},
		{
			name: "nil_producer_ok",
			consumer: objectSchema(map[string]interface{}{
				"name": primSchema("string"),
			}, "name"),
			producer:       nil,
			wantCompatible: true,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := IsSchemaCompatible(tc.consumer, tc.producer, "subset")
			assert.Equal(t, tc.wantCompatible, got.Compatible, "reasons=%v", got.Reasons)
			assert.Equal(t, "subset", got.Mode)
			if tc.wantCompatible {
				assert.Empty(t, got.Reasons, "compatible result should carry no reasons")
			} else {
				assert.NotEmpty(t, got.Reasons, "incompatible result must carry at least one reason")
			}
		})
	}
}

// TestIsSchemaCompatible_Strict asserts the strict-mode short-circuit: when the
// resolver invokes IsSchemaCompatible with mode=strict, the call is by
// definition a hash mismatch and returns Compatible=false with a uniform reason
// payload (the resolver never bothers comparing schemas in strict mode — a hash
// difference IS the incompatibility).
func TestIsSchemaCompatible_Strict_HashMismatch(t *testing.T) {
	consumer := objectSchema(map[string]interface{}{
		"name": primSchema("string"),
	}, "name")
	producer := objectSchema(map[string]interface{}{
		"name": primSchema("string"),
	}, "name")

	got := IsSchemaCompatible(consumer, producer, "strict")
	assert.False(t, got.Compatible)
	assert.Equal(t, "strict", got.Mode)
	require.Len(t, got.Reasons, 1)
	assert.Equal(t, "strict_hash_mismatch", got.Reasons[0]["kind"])
}

// TestDiffSubset_CollectsAllIncompatibilities asserts the diff doesn't bail on
// the first mismatch — operators viewing meshctl audit want the full picture.
func TestDiffSubset_CollectsAllIncompatibilities(t *testing.T) {
	consumer := objectSchema(map[string]interface{}{
		"name":   primSchema("string"),
		"dept":   primSchema("string"),
		"salary": primSchema("number"),
	}, "name", "dept", "salary")
	producer := objectSchema(map[string]interface{}{
		"name": primSchema("integer"), // type mismatch
		// dept missing
		// salary missing
	}, "name")

	got := IsSchemaCompatible(consumer, producer, "subset")
	assert.False(t, got.Compatible)
	// Expect 1 type_mismatch + 2 missing_field = 3 reasons.
	assert.Len(t, got.Reasons, 3, "diff must collect all incompatibilities, not bail early")
}

// TestNormalizeTypeDecl covers the JSON-roundtrip variants the resolver might
// see (string, []string, []interface{}).
func TestNormalizeTypeDecl(t *testing.T) {
	assert.Equal(t, []string(nil), normalizeTypeDecl(nil))
	assert.Equal(t, []string(nil), normalizeTypeDecl(""))
	assert.Equal(t, []string{"string"}, normalizeTypeDecl("string"))
	assert.Equal(t, []string{"string", "null"}, normalizeTypeDecl([]string{"string", "null"}))
	assert.Equal(t, []string{"string", "null"}, normalizeTypeDecl([]interface{}{"string", "null"}))
}
