package registry

// Schema-aware filtering helpers for the resolver's schema stage (issue #547).
//
// The Rust normalizer guarantees both schemas are already in canonical form:
// camelCase fields, sorted required, no `additionalProperties: false`, etc.
// So this file walks normalized JSON Schema dicts directly — no normalization,
// no Rust call-out, no third-party JSON Schema validator. Keep it small.

// SchemaCompatibility holds a subset/strict diff result.
type SchemaCompatibility struct {
	Compatible bool
	Mode       string                   // "subset" or "strict"
	Reasons    []map[string]interface{} // per-incompatibility detail; empty when Compatible=true
}

// IsSchemaCompatible returns whether producer's output schema satisfies consumer's
// expected schema under the given match mode. Both schemas are expected to be in
// canonical normalized form.
//
// Modes:
//   - "subset": every field the consumer marks required must be present in the
//     producer with a type-compatible declaration. Extra producer fields are fine.
//     Recurses into nested objects and arrays.
//   - "strict": full structural match. The resolver only calls this when hashes
//     already differ, so a "strict" call is by definition incompatible. We still
//     accept the call so the audit gets a uniform Reasons payload.
//
// Behavior on nil/missing: a nil consumer or nil producer schema is treated as
// "anything goes" — no incompatibility recorded. The caller (resolver) decides
// what to do when a candidate has no schema at all (currently: keep, to avoid
// breaking the rollout window).
func IsSchemaCompatible(consumer, producer map[string]interface{}, mode string) SchemaCompatibility {
	out := SchemaCompatibility{Mode: mode}
	if mode == "strict" {
		// Resolver only enters this branch on hash mismatch; for strict that IS
		// the incompatibility. Audit gets a uniform Reasons payload.
		out.Compatible = false
		out.Reasons = []map[string]interface{}{{"path": "", "kind": "strict_hash_mismatch"}}
		return out
	}
	if consumer == nil || producer == nil {
		out.Compatible = true
		return out
	}

	out.Reasons = diffSubset("", consumer, producer)
	out.Compatible = len(out.Reasons) == 0
	return out
}

// diffSubset walks two normalized JSON Schemas and returns a list of reasons
// the producer doesn't satisfy the consumer's subset expectation. Empty list
// means compatible. Path is dotted (e.g., "address.city" for nested fields).
func diffSubset(path string, consumer, producer map[string]interface{}) []map[string]interface{} {
	var reasons []map[string]interface{}

	// Type compatibility at this level.
	if !typesCompatible(consumer["type"], producer["type"]) {
		reasons = append(reasons, map[string]interface{}{
			"path":          path,
			"kind":          "type_mismatch",
			"consumer_type": consumer["type"],
			"producer_type": producer["type"],
		})
		// Even on type mismatch, keep walking — consumers want to see the full
		// picture in `meshctl audit`, not just the first hit.
	}

	// Object: every consumer-required field must exist in producer.properties
	// and recursively be compatible.
	consumerProps, _ := consumer["properties"].(map[string]interface{})
	producerProps, _ := producer["properties"].(map[string]interface{})
	consumerReq := stringSlice(consumer["required"])

	for _, field := range consumerReq {
		producerField, ok := producerProps[field]
		if !ok {
			reasons = append(reasons, map[string]interface{}{
				"path":  joinPath(path, field),
				"kind":  "missing_field",
				"field": field,
			})
			continue
		}
		consumerField, ok := consumerProps[field]
		if !ok {
			// Consumer requires a field but didn't declare its schema — nothing
			// to recurse on, but the field is present in producer, so OK.
			continue
		}
		consumerFieldMap, _ := consumerField.(map[string]interface{})
		producerFieldMap, _ := producerField.(map[string]interface{})
		if consumerFieldMap == nil || producerFieldMap == nil {
			continue
		}
		reasons = append(reasons, diffSubset(joinPath(path, field), consumerFieldMap, producerFieldMap)...)
	}

	// Array items: if consumer has items schema, producer must have a compatible
	// items schema too.
	if consumerItems, ok := consumer["items"].(map[string]interface{}); ok {
		if producerItems, ok := producer["items"].(map[string]interface{}); ok {
			reasons = append(reasons, diffSubset(joinPath(path, "[]"), consumerItems, producerItems)...)
		} else {
			reasons = append(reasons, map[string]interface{}{
				"path": joinPath(path, "[]"),
				"kind": "missing_items_schema",
			})
		}
	}

	return reasons
}

// typesCompatible reports whether a producer's "type" declaration satisfies a
// consumer's "type" declaration under subset rules:
//   - Equal primitives match (string == string).
//   - integer is acceptable where number is required (numbers are a superset).
//   - Type arrays (e.g., ["string", "null"]) on the consumer must each have a
//     compatible producer entry.
//   - Missing types on either side are treated as "anything" — compatible.
func typesCompatible(consumerType, producerType interface{}) bool {
	consumerTypes := normalizeTypeDecl(consumerType)
	producerTypes := normalizeTypeDecl(producerType)

	if len(consumerTypes) == 0 || len(producerTypes) == 0 {
		return true
	}

	for _, ct := range consumerTypes {
		matched := false
		for _, pt := range producerTypes {
			if primitiveCompatible(ct, pt) {
				matched = true
				break
			}
		}
		if !matched {
			return false
		}
	}
	return true
}

// primitiveCompatible reports whether producer primitive pt satisfies consumer
// primitive ct. Encodes the integer ⊆ number relaxation.
func primitiveCompatible(consumerType, producerType string) bool {
	if consumerType == producerType {
		return true
	}
	if consumerType == "number" && producerType == "integer" {
		return true
	}
	return false
}

// normalizeTypeDecl coerces a JSON Schema "type" field — which may be a string
// or an array of strings — into a flat []string. Unknown shapes return nil.
func normalizeTypeDecl(t interface{}) []string {
	switch v := t.(type) {
	case string:
		if v == "" {
			return nil
		}
		return []string{v}
	case []string:
		return v
	case []interface{}:
		out := make([]string, 0, len(v))
		for _, x := range v {
			if s, ok := x.(string); ok && s != "" {
				out = append(out, s)
			}
		}
		return out
	}
	return nil
}

// stringSlice coerces a JSON Schema "required" field — which may be []string or
// []interface{} after JSON round-trip — into []string. Unknown shapes return nil.
func stringSlice(v interface{}) []string {
	switch s := v.(type) {
	case []string:
		return s
	case []interface{}:
		out := make([]string, 0, len(s))
		for _, x := range s {
			if str, ok := x.(string); ok {
				out = append(out, str)
			}
		}
		return out
	}
	return nil
}

// joinPath concatenates two dotted-path segments, omitting an empty parent.
func joinPath(parent, child string) string {
	if parent == "" {
		return child
	}
	return parent + "." + child
}
