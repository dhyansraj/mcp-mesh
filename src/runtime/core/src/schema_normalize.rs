//! JSON Schema canonicalization + content hashing for cross-language capability matching.
//!
//! This module produces a canonical JSON Schema and a SHA256 hash from raw schemas
//! emitted by Pydantic (Python), Zod (TypeScript), and Jackson (Java). Identical
//! semantic types in different runtimes normalize to the same canonical form, so
//! capability matching reduces to byte-equal hash comparison.
//!
//! See GitHub issue #547 for the design.

use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, HashSet};

/// Origin runtime hint. Currently unused for the actual normalization but
/// reserved for future origin-specific tweaks (API stability).
#[derive(Debug, Clone, Copy)]
pub enum SchemaOrigin {
    Python,
    TypeScript,
    Java,
    Unknown,
}

/// Result of normalizing a raw JSON schema.
pub struct NormalizeResult {
    pub canonical: Value,
    pub hash: String,
    pub verdict: String,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
enum Verdict {
    Ok,
    Warn,
    #[allow(dead_code)] // reserved for future hard-failure rules
    Block,
}

impl Verdict {
    fn as_str(&self) -> &'static str {
        match self {
            Verdict::Ok => "OK",
            Verdict::Warn => "WARN",
            Verdict::Block => "BLOCK",
        }
    }

    fn upgrade(&mut self, other: Verdict) {
        // BLOCK > WARN > OK
        let rank = |v: &Verdict| match v {
            Verdict::Ok => 0,
            Verdict::Warn => 1,
            Verdict::Block => 2,
        };
        if rank(&other) > rank(self) {
            *self = other;
        }
    }
}

struct Ctx {
    defs: Map<String, Value>,
    /// Stack of def names currently being inlined (for cycle detection).
    visiting: Vec<String>,
    /// Names that participate in a cycle. Their $ref must be kept (not inlined),
    /// and the def itself must be preserved in the canonical $defs.
    cyclic: HashSet<String>,
    warnings: Vec<String>,
    verdict: Verdict,
}

impl Ctx {
    fn new() -> Self {
        Self {
            defs: Map::new(),
            visiting: Vec::new(),
            cyclic: HashSet::new(),
            warnings: Vec::new(),
            verdict: Verdict::Ok,
        }
    }

    fn warn(&mut self, msg: impl Into<String>) {
        self.warnings.push(msg.into());
        self.verdict.upgrade(Verdict::Warn);
    }
}

/// Normalize a raw JSON schema (as a string) into a canonical form and content hash.
///
/// On parse error returns a `NormalizeResult` with `verdict="BLOCK"`, empty `hash`,
/// `canonical=Value::Null`, and the parse error in `warnings`.
pub fn normalize_schema(raw_json: &str, origin: SchemaOrigin) -> NormalizeResult {
    let _ = origin; // currently unused; reserved for future origin-specific tweaks

    let parsed: Value = match serde_json::from_str(raw_json) {
        Ok(v) => v,
        Err(e) => {
            return NormalizeResult {
                canonical: Value::Null,
                hash: String::new(),
                verdict: "BLOCK".to_string(),
                warnings: vec![format!("invalid JSON input: {}", e)],
            };
        }
    };

    let mut ctx = Ctx::new();
    // Lift $defs / definitions for ref resolution
    if let Some(obj) = parsed.as_object() {
        for key in &["$defs", "definitions"] {
            if let Some(Value::Object(map)) = obj.get(*key) {
                for (k, v) in map {
                    ctx.defs.insert(k.clone(), v.clone());
                }
            }
        }
    }

    // Pre-compute cyclic defs: any def whose body transitively references itself.
    ctx.cyclic = detect_cyclic_defs(&ctx.defs);

    let inlined = inline_refs(&parsed, &mut ctx);
    let mut normalized = normalize(&inlined, &mut ctx);

    // If we have cyclic defs preserved, normalize them too and attach as canonical $defs.
    // We rename each cyclic def to a stable hash-based name so the canonical form is
    // independent of source-language class naming.
    if !ctx.cyclic.is_empty() {
        let cyclic_names: Vec<String> = ctx.cyclic.iter().cloned().collect();
        // Normalize each cyclic def body (with the same cycle awareness — refs to other
        // cyclic defs are kept as $ref).
        let mut normalized_defs: HashMap<String, Value> = HashMap::new();
        for name in &cyclic_names {
            if let Some(body) = ctx.defs.get(name).cloned() {
                let inlined_body = inline_refs(&body, &mut ctx);
                let normalized_body = normalize(&inlined_body, &mut ctx);
                normalized_defs.insert(name.clone(), normalized_body);
            }
        }
        // Compute stable names: structural hash of the body with $ref pointers replaced
        // by a placeholder (so self-references hash identically across class names).
        let rename: HashMap<String, String> = compute_stable_names(&normalized_defs);
        // Rewrite $refs in main schema and within each def body.
        normalized = rewrite_refs(&normalized, &rename);
        let mut out_defs = Map::new();
        for (orig, body) in &normalized_defs {
            let new_name = rename.get(orig).cloned().unwrap_or_else(|| orig.clone());
            let rewritten = rewrite_refs(body, &rename);
            out_defs.insert(new_name, rewritten);
        }
        // Attach $defs to the top-level node.
        if let Value::Object(ref mut top) = normalized {
            top.insert("$defs".into(), Value::Object(out_defs));
        }
    }

    let canonical = sort_keys(&normalized);

    let serialized = serde_json::to_string(&canonical).unwrap();
    let mut hasher = Sha256::new();
    hasher.update(serialized.as_bytes());
    let hash = format!("sha256:{}", hex::encode(hasher.finalize()));

    NormalizeResult {
        canonical,
        hash,
        verdict: ctx.verdict.as_str().to_string(),
        warnings: ctx.warnings,
    }
}

/// Walk a value and collect every $ref name that points into our defs.
fn collect_ref_names(v: &Value, out: &mut Vec<String>) {
    match v {
        Value::Object(map) => {
            if let Some(Value::String(r)) = map.get("$ref") {
                if let Some(name) = ref_name(r) {
                    out.push(name);
                }
            }
            for (_, val) in map {
                collect_ref_names(val, out);
            }
        }
        Value::Array(arr) => {
            for x in arr {
                collect_ref_names(x, out);
            }
        }
        _ => {}
    }
}

/// Detect which defs are part of a cycle. A def is cyclic if it can transitively
/// reach itself via $refs.
fn detect_cyclic_defs(defs: &Map<String, Value>) -> HashSet<String> {
    // Build adjacency: name -> set of names it references.
    let mut graph: HashMap<String, HashSet<String>> = HashMap::new();
    for (name, body) in defs {
        let mut refs = Vec::new();
        collect_ref_names(body, &mut refs);
        let mut set = HashSet::new();
        for r in refs {
            if defs.contains_key(&r) {
                set.insert(r);
            }
        }
        graph.insert(name.clone(), set);
    }
    // For each node, DFS and see if we can reach itself.
    let mut cyclic = HashSet::new();
    for start in defs.keys() {
        if reachable_self(start, &graph) {
            cyclic.insert(start.clone());
        }
    }
    // Also include any node on a path between two cyclic nodes (mutual recursion case).
    // Simple closure: any node reachable from a cyclic node that can reach back into the
    // cyclic set is itself cyclic.
    loop {
        let mut added = false;
        let snapshot = cyclic.clone();
        for name in defs.keys() {
            if snapshot.contains(name) {
                continue;
            }
            if let Some(neighbors) = graph.get(name) {
                if neighbors.iter().any(|n| snapshot.contains(n))
                    && reachable_to_set(name, &snapshot, &graph)
                {
                    cyclic.insert(name.clone());
                    added = true;
                }
            }
        }
        if !added {
            break;
        }
    }
    cyclic
}

fn reachable_self(start: &str, graph: &HashMap<String, HashSet<String>>) -> bool {
    let mut stack: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    if let Some(neighbors) = graph.get(start) {
        for n in neighbors {
            stack.push(n.clone());
        }
    }
    while let Some(node) = stack.pop() {
        if node == start {
            return true;
        }
        if seen.contains(&node) {
            continue;
        }
        seen.insert(node.clone());
        if let Some(neighbors) = graph.get(&node) {
            for n in neighbors {
                stack.push(n.clone());
            }
        }
    }
    false
}

fn reachable_to_set(
    start: &str,
    target: &HashSet<String>,
    graph: &HashMap<String, HashSet<String>>,
) -> bool {
    let mut stack: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    if let Some(neighbors) = graph.get(start) {
        for n in neighbors {
            stack.push(n.clone());
        }
    }
    while let Some(node) = stack.pop() {
        if target.contains(&node) {
            return true;
        }
        if seen.contains(&node) {
            continue;
        }
        seen.insert(node.clone());
        if let Some(neighbors) = graph.get(&node) {
            for n in neighbors {
                stack.push(n.clone());
            }
        }
    }
    false
}

/// Compute stable hash-based names for cyclic defs. The hash is over the def body
/// with all $ref values replaced by a fixed placeholder string. This way, two defs
/// with the same structure but different source-language class names hash identically.
fn compute_stable_names(defs: &HashMap<String, Value>) -> HashMap<String, String> {
    let mut rename = HashMap::new();
    for (name, body) in defs {
        let placeholder_body = strip_ref_targets(body);
        let serialized = serde_json::to_string(&sort_keys(&placeholder_body)).unwrap();
        let mut hasher = Sha256::new();
        hasher.update(serialized.as_bytes());
        let h = hex::encode(hasher.finalize());
        let new_name = format!("Recursive_{}", &h[..12]);
        rename.insert(name.clone(), new_name);
    }
    rename
}

/// Replace every {"$ref": "#/$defs/X"} with {"$ref": "__CYCLIC__"} for hashing purposes.
fn strip_ref_targets(v: &Value) -> Value {
    match v {
        Value::Object(map) => {
            let mut out = Map::new();
            for (k, val) in map {
                if k == "$ref" {
                    out.insert(k.clone(), Value::String("__CYCLIC__".into()));
                } else {
                    out.insert(k.clone(), strip_ref_targets(val));
                }
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(strip_ref_targets).collect()),
        other => other.clone(),
    }
}

/// Rewrite $ref pointers using the rename map.
fn rewrite_refs(v: &Value, rename: &HashMap<String, String>) -> Value {
    match v {
        Value::Object(map) => {
            let mut out = Map::new();
            for (k, val) in map {
                if k == "$ref" {
                    if let Value::String(r) = val {
                        if let Some(name) = ref_name(r) {
                            if let Some(new_name) = rename.get(&name) {
                                out.insert(
                                    k.clone(),
                                    Value::String(format!("#/$defs/{}", new_name)),
                                );
                                continue;
                            }
                        }
                    }
                    out.insert(k.clone(), val.clone());
                } else {
                    out.insert(k.clone(), rewrite_refs(val, rename));
                }
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(|x| rewrite_refs(x, rename)).collect()),
        other => other.clone(),
    }
}

/// Recursively inline $ref pointers using ctx.defs. On cycle detection (or refs into
/// known-cyclic defs), keep the $ref intact so the canonical form preserves recursion.
fn inline_refs(v: &Value, ctx: &mut Ctx) -> Value {
    match v {
        Value::Object(map) => {
            // Handle $ref
            if let Some(Value::String(r)) = map.get("$ref") {
                let name = ref_name(r);
                if let Some(name) = name {
                    // If this def is cyclic OR currently being visited, keep the $ref.
                    if ctx.cyclic.contains(&name) || ctx.visiting.iter().any(|n| n == &name) {
                        let mut out = Map::new();
                        out.insert("$ref".into(), Value::String(format!("#/$defs/{}", name)));
                        // Preserve siblings (rare). Drop $defs/definitions — we manage
                        // those centrally and reattach at the end.
                        for (k, val) in map {
                            if k == "$ref" || k == "$defs" || k == "definitions" {
                                continue;
                            }
                            out.insert(k.clone(), inline_refs(val, ctx));
                        }
                        return Value::Object(out);
                    }
                    if let Some(target) = ctx.defs.get(&name).cloned() {
                        ctx.visiting.push(name.clone());
                        let resolved = inline_refs(&target, ctx);
                        ctx.visiting.pop();
                        // Merge sibling keys (other than $ref) — rare but possible
                        let mut merged = match resolved {
                            Value::Object(m) => m,
                            other => {
                                let mut m = Map::new();
                                m.insert("__resolved__".into(), other);
                                m
                            }
                        };
                        for (k, val) in map {
                            if k == "$ref" {
                                continue;
                            }
                            merged.insert(k.clone(), inline_refs(val, ctx));
                        }
                        return Value::Object(merged);
                    } else {
                        ctx.warn(format!("unresolved $ref: {}", r));
                        return Value::Object(Map::new());
                    }
                } else {
                    ctx.warn(format!("non-local $ref kept: {}", r));
                    let mut new = Map::new();
                    new.insert("$ref".into(), Value::String(r.clone()));
                    return Value::Object(new);
                }
            }

            let mut out = Map::new();
            for (k, val) in map {
                if k == "$defs" || k == "definitions" {
                    continue;
                }
                out.insert(k.clone(), inline_refs(val, ctx));
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(|x| inline_refs(x, ctx)).collect()),
        other => other.clone(),
    }
}

fn ref_name(r: &str) -> Option<String> {
    // Accept "#/$defs/Name" or "#/definitions/Name"
    for prefix in &["#/$defs/", "#/definitions/"] {
        if let Some(stripped) = r.strip_prefix(*prefix) {
            return Some(stripped.to_string());
        }
    }
    None
}

/// Apply rules: nullable forms, required normalization, date type pass-through,
/// enum normalization, strip non-contract metadata, camelCase property names.
fn normalize(v: &Value, ctx: &mut Ctx) -> Value {
    match v {
        Value::Object(map) => {
            // First, normalize nullable representation at THIS node
            let mut node = map.clone();

            // Rule: nullable normalization
            node = normalize_nullable(node, ctx);

            // Rule: strip non-contract metadata
            for key in &[
                "title",
                "description",
                "examples",
                "default",
                "$schema",
                "$id",
                "$defs",
                "definitions",
                "markdownDescription",
                // Pydantic-specific discriminator metadata (mapping + propertyName).
                // The discriminator info is already encoded in each branch via `const`,
                // which is sufficient for structural disambiguation. Strip so Pydantic's
                // `oneOf + discriminator` matches Zod/Jackson `anyOf`.
                "discriminator",
            ] {
                node.remove(*key);
            }

            // Rule (opinionated): rewrite oneOf -> anyOf unconditionally. Per the
            // #547 spec, this is one of 7 documented opinionated normalizer
            // policies — for structural disambiguation we don't need exclusive-
            // match semantics, and Pydantic/Zod/Jackson don't agree on which
            // keyword to emit for discriminated unions (Pydantic: oneOf;
            // Zod/Jackson: anyOf). Canonicalizing both keywords to `anyOf` is
            // what makes cross-runtime hashes converge.
            //
            // Note: the earlier nullable rule may have already collapsed `oneOf`
            // into a top-level type array (when there was exactly one non-null
            // branch + a null branch); in that case `node.remove("oneOf")`
            // returns None and this block is a no-op.
            if let Some(Value::Array(branches)) = node.remove("oneOf") {
                node.insert("anyOf".into(), Value::Array(branches));
            }
            // Strip additionalProperties regardless of true/false — different generators
            // emit different defaults.
            if let Some(v) = node.remove("additionalProperties") {
                if let Value::Bool(true) = v {
                    ctx.warn("stripped additionalProperties: true (lossy)".to_string());
                }
            }

            // Rule: enum normalization
            if node.contains_key("enum") {
                normalize_enum(&mut node);
            }

            // Rule: camelCase the keys of "properties" (and rewrite "required" entries).
            if let Some(Value::Object(props)) = node.remove("properties") {
                let mut new_props = Map::new();
                let mut rename: HashMap<String, String> = HashMap::new();
                for (k, val) in props {
                    let new_key = to_camel_case(&k);
                    if new_key != k {
                        rename.insert(k.clone(), new_key.clone());
                    }
                    new_props.insert(new_key, val);
                }
                node.insert("properties".into(), Value::Object(new_props));
                if !rename.is_empty() {
                    if let Some(Value::Array(req)) = node.get("required").cloned() {
                        let new_req: Vec<Value> = req
                            .into_iter()
                            .map(|x| match x {
                                Value::String(s) => Value::String(
                                    rename.get(&s).cloned().unwrap_or(s),
                                ),
                                other => other,
                            })
                            .collect();
                        node.insert("required".into(), Value::Array(new_req));
                    }
                }
            }

            // Rule: required normalization (sort alphabetically) — after camelCase rename.
            if let Some(Value::Array(req)) = node.get("required").cloned() {
                let mut strs: Vec<String> = req
                    .iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_string()))
                    .collect();
                strs.sort();
                let new = strs.into_iter().map(Value::String).collect();
                node.insert("required".into(), Value::Array(new));
            }

            // Recurse into children
            let mut out = Map::new();
            for (k, val) in node {
                let normalized_child = match k.as_str() {
                    // Don't recurse into enum values (they are concrete data)
                    // Don't touch type/required arrays as JSON Values directly.
                    "enum" | "required" | "type" => val,
                    _ => normalize(&val, ctx),
                };
                out.insert(k, normalized_child);
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(|x| normalize(x, ctx)).collect()),
        other => other.clone(),
    }
}

/// Convert a snake_case / PascalCase / mixed identifier into camelCase.
///
/// Acronym handling: a run of two-or-more uppercase letters is treated as an acronym
/// and lowercased entirely when it appears at the start of the identifier; when it
/// appears mid-identifier (preceded by a lowercase letter), only the trailing letter
/// of the acronym is kept uppercase if it is followed by another lowercase letter
/// (CamelCase boundary). This is a simplification — see comments below.
///
/// Examples:
///   market_cap -> marketCap
///   hire_date -> hireDate
///   is_active -> isActive
///   URLPath   -> urlPath          (leading acronym fully lowercased; "Path" begins next word)
///   userID    -> userId           (trailing acronym treated as a word)
///   HTTPStatus -> httpStatus
///   already_camelCase -> alreadyCamelCase
fn to_camel_case(s: &str) -> String {
    if s.is_empty() {
        return String::new();
    }
    // Tokenize into words by splitting on:
    //   - underscore or hyphen
    //   - lowercase->uppercase transition (camelHump)
    //   - uppercase->lowercase transition within a run of uppercase (acronym followed by Word)
    let chars: Vec<char> = s.chars().collect();
    let mut words: Vec<String> = Vec::new();
    let mut cur = String::new();

    let push = |words: &mut Vec<String>, cur: &mut String| {
        if !cur.is_empty() {
            words.push(std::mem::take(cur));
        }
    };

    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '_' || c == '-' || c == ' ' {
            push(&mut words, &mut cur);
            i += 1;
            continue;
        }
        if c.is_uppercase() {
            // Look at context: if previous char was lowercase, this is a new word boundary.
            let prev_lower = i > 0 && chars[i - 1].is_lowercase();
            let prev_upper = i > 0 && chars[i - 1].is_uppercase();
            // If next char is lowercase and previous is uppercase, this uppercase letter
            // starts a new word (XMLParser -> XML, Parser -> "xml", "parser").
            let next_lower = i + 1 < chars.len() && chars[i + 1].is_lowercase();

            if prev_lower {
                push(&mut words, &mut cur);
                cur.push(c);
            } else if prev_upper && next_lower {
                // Acronym/word boundary: previous uppercase letters belong to acronym word,
                // current uppercase letter starts a new word.
                push(&mut words, &mut cur);
                cur.push(c);
            } else {
                cur.push(c);
            }
        } else {
            cur.push(c);
        }
        i += 1;
    }
    push(&mut words, &mut cur);

    // Lowercase every word; capitalize the first letter of each except the first.
    let mut out = String::new();
    for (idx, w) in words.iter().enumerate() {
        let lower = w.to_lowercase();
        if idx == 0 {
            out.push_str(&lower);
        } else {
            let mut chs = lower.chars();
            if let Some(first) = chs.next() {
                for u in first.to_uppercase() {
                    out.push(u);
                }
                out.push_str(chs.as_str());
            }
        }
    }
    out
}

/// Convert various nullable forms into canonical {"type": ["X", "null"]}.
fn normalize_nullable(mut node: Map<String, Value>, _ctx: &mut Ctx) -> Map<String, Value> {
    // Form A: nullable: true
    if let Some(Value::Bool(true)) = node.get("nullable") {
        node.remove("nullable");
        if let Some(t) = node.get("type").cloned() {
            match t {
                Value::String(s) => {
                    if s != "null" {
                        node.insert("type".into(), Value::Array(vec![
                            Value::String(s),
                            Value::String("null".into()),
                        ]));
                    }
                }
                Value::Array(mut arr) => {
                    if !arr.iter().any(|v| v.as_str() == Some("null")) {
                        arr.push(Value::String("null".into()));
                    }
                    node.insert("type".into(), Value::Array(arr));
                }
                _ => {}
            }
        }
    }

    // Form B/C: anyOf/oneOf with a null branch
    for key in &["anyOf", "oneOf"] {
        if let Some(Value::Array(branches)) = node.get(*key).cloned() {
            // Find a null branch
            let null_idx = branches.iter().position(|b| {
                if let Value::Object(m) = b {
                    if let Some(Value::String(t)) = m.get("type") {
                        return t == "null";
                    }
                }
                false
            });
            if let Some(idx) = null_idx {
                let mut non_null: Vec<Value> = branches.clone();
                non_null.remove(idx);
                if non_null.len() == 1 {
                    // Promote the single non-null branch to top level + null type
                    let inner = non_null.into_iter().next().unwrap();
                    if let Value::Object(inner_map) = inner {
                        node.remove(*key);
                        for (ik, iv) in inner_map {
                            node.insert(ik, iv);
                        }
                        if let Some(t) = node.get("type").cloned() {
                            match t {
                                Value::String(s) => {
                                    if s != "null" {
                                        node.insert(
                                            "type".into(),
                                            Value::Array(vec![
                                                Value::String(s),
                                                Value::String("null".into()),
                                            ]),
                                        );
                                    }
                                }
                                Value::Array(mut arr) => {
                                    if !arr.iter().any(|v| v.as_str() == Some("null")) {
                                        arr.push(Value::String("null".into()));
                                    }
                                    node.insert("type".into(), Value::Array(arr));
                                }
                                _ => {}
                            }
                        }
                    }
                }
                // else: leave anyOf/oneOf in place (genuine union with multiple non-null branches)
            }
        }
    }

    // Sort/canonicalize the type array if present: put "null" last, others sorted.
    if let Some(Value::Array(arr)) = node.get("type").cloned() {
        let mut others: Vec<String> = arr
            .iter()
            .filter_map(|v| v.as_str())
            .filter(|s| *s != "null")
            .map(|s| s.to_string())
            .collect();
        others.sort();
        let has_null = arr.iter().any(|v| v.as_str() == Some("null"));
        let mut new: Vec<Value> = others.into_iter().map(Value::String).collect();
        if has_null {
            new.push(Value::String("null".into()));
        }
        node.insert("type".into(), Value::Array(new));
    }

    node
}

fn normalize_enum(node: &mut Map<String, Value>) {
    let enum_vals = match node.get("enum").cloned() {
        Some(Value::Array(a)) => a,
        _ => return,
    };

    // If type is missing, infer if all values are same primitive type
    if !node.contains_key("type") {
        let inferred = infer_uniform_type(&enum_vals);
        if let Some(t) = inferred {
            node.insert("type".into(), Value::String(t));
        }
    }

    // Sort enum values alphabetically only if all are strings
    let all_strings = enum_vals.iter().all(|v| v.is_string());
    if all_strings {
        let mut s: Vec<String> = enum_vals
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect();
        s.sort();
        let new: Vec<Value> = s.into_iter().map(Value::String).collect();
        node.insert("enum".into(), Value::Array(new));
    }
}

fn infer_uniform_type(vals: &[Value]) -> Option<String> {
    let mut iter = vals.iter();
    let first = iter.next()?;
    let t = json_value_type(first)?;
    for v in iter {
        if json_value_type(v)? != t {
            return None;
        }
    }
    Some(t.to_string())
}

fn json_value_type(v: &Value) -> Option<&'static str> {
    match v {
        Value::String(_) => Some("string"),
        Value::Bool(_) => Some("boolean"),
        Value::Number(n) => {
            if n.is_i64() || n.is_u64() {
                Some("integer")
            } else {
                Some("number")
            }
        }
        Value::Null => Some("null"),
        _ => None,
    }
}

/// Recursively sort all object keys alphabetically using a BTreeMap, then convert back.
fn sort_keys(v: &Value) -> Value {
    match v {
        Value::Object(map) => {
            let mut sorted: BTreeMap<String, Value> = BTreeMap::new();
            for (k, val) in map {
                sorted.insert(k.clone(), sort_keys(val));
            }
            let mut out = Map::new();
            for (k, val) in sorted {
                out.insert(k, val);
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(sort_keys).collect()),
        other => other.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Macro: generate three per-runtime tests + one cross-runtime parity test for a pattern.
    ///
    /// Each per-runtime test reads the raw fixture and the expected hash, normalizes,
    /// and asserts the produced hash matches. The parity test asserts all three runtimes
    /// produce the same hash for the pattern.
    macro_rules! pattern_tests {
        ($mod_name:ident, $pattern:literal) => {
            mod $mod_name {
                use super::*;

                fn expected_hash(lang: &str) -> String {
                    // hash files look like: "sha256:abc...\n"
                    let raw = match lang {
                        "py" => include_str!(concat!(
                            "../tests/fixtures/schema_normalize/hash-py-",
                            $pattern,
                            ".txt"
                        )),
                        "ts" => include_str!(concat!(
                            "../tests/fixtures/schema_normalize/hash-ts-",
                            $pattern,
                            ".txt"
                        )),
                        "java" => include_str!(concat!(
                            "../tests/fixtures/schema_normalize/hash-java-",
                            $pattern,
                            ".txt"
                        )),
                        _ => panic!("unknown lang"),
                    };
                    raw.trim().to_string()
                }

                fn raw_schema(lang: &str) -> &'static str {
                    match lang {
                        "py" => include_str!(concat!(
                            "../tests/fixtures/schema_normalize/raw-py-",
                            $pattern,
                            ".json"
                        )),
                        "ts" => include_str!(concat!(
                            "../tests/fixtures/schema_normalize/raw-ts-",
                            $pattern,
                            ".json"
                        )),
                        "java" => include_str!(concat!(
                            "../tests/fixtures/schema_normalize/raw-java-",
                            $pattern,
                            ".json"
                        )),
                        _ => panic!("unknown lang"),
                    }
                }

                #[test]
                fn python_hash_matches_fixture() {
                    let result = normalize_schema(raw_schema("py"), SchemaOrigin::Python);
                    assert_eq!(result.hash, expected_hash("py"), "python hash mismatch for {}", $pattern);
                }

                #[test]
                fn typescript_hash_matches_fixture() {
                    let result = normalize_schema(raw_schema("ts"), SchemaOrigin::TypeScript);
                    assert_eq!(result.hash, expected_hash("ts"), "typescript hash mismatch for {}", $pattern);
                }

                #[test]
                fn java_hash_matches_fixture() {
                    let result = normalize_schema(raw_schema("java"), SchemaOrigin::Java);
                    assert_eq!(result.hash, expected_hash("java"), "java hash mismatch for {}", $pattern);
                }

                #[test]
                fn cross_runtime_parity() {
                    let py = normalize_schema(raw_schema("py"), SchemaOrigin::Python);
                    let ts = normalize_schema(raw_schema("ts"), SchemaOrigin::TypeScript);
                    let java = normalize_schema(raw_schema("java"), SchemaOrigin::Java);
                    assert_eq!(py.hash, ts.hash, "py vs ts hash mismatch for {}", $pattern);
                    assert_eq!(py.hash, java.hash, "py vs java hash mismatch for {}", $pattern);
                }
            }
        };
    }

    pattern_tests!(primitives, "Primitives");
    pattern_tests!(optional, "Optional");
    pattern_tests!(with_date, "WithDate");
    pattern_tests!(with_enum, "WithEnum");
    pattern_tests!(nested, "Nested");
    pattern_tests!(with_array, "WithArray");
    pattern_tests!(case_conversion, "CaseConversion");
    pattern_tests!(discriminated_union, "DiscriminatedUnion");
    pattern_tests!(recursive, "Recursive");
    pattern_tests!(inheritance, "Inheritance");
    pattern_tests!(number_constraints, "NumberConstraints");
    pattern_tests!(untagged_union, "UntaggedUnion");

    #[test]
    fn parse_error_returns_block_verdict() {
        let result = normalize_schema("not json {", SchemaOrigin::Unknown);
        assert_eq!(result.verdict, "BLOCK");
        assert_eq!(result.hash, "");
        assert!(result.canonical.is_null());
        assert_eq!(result.warnings.len(), 1);
        assert!(result.warnings[0].contains("invalid JSON"));
    }
}
