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

/// Keys this normalizer strips as non-contract metadata.
///
/// Shared between the strip rule in [`normalize`] and the nested-union
/// detection in [`nested_union_branches`] so the two cannot drift: "is this
/// branch a bare nested union?" has to ask the same question the strip rule
/// answers, or the two runtimes' spellings stop converging.
const STRIPPED_METADATA_KEYS: &[&str] = &[
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
];

/// Ceiling on the total number of JSON nodes `inline_refs` may materialize for
/// one schema, and the env var that overrides it.
///
/// `inline_refs` expands a shared `$def` once per *use site*, so defs forming a
/// diamond (`Ln` references `Ln-1` twice) expand as 2^depth: a 1.6 KB input with
/// 16 such levels materializes 524,288 nodes / 6.3 MB, and 17 levels doubles
/// that again. The canonical form is hashed for capability matching, so
/// silently truncating the expansion would let two different schemas collapse
/// onto the same dangling-`$ref` form — a false match. Exceeding the budget is
/// therefore a BLOCK, not a degradation.
///
/// The budget counts **materialized nodes, not `$ref` sites**, because node
/// count is what bounds output size: a site inlines a def body of unbounded
/// size, so N sites says nothing about how large the result is. Each expansion
/// is charged the node count of the body it splices in, and nested refs inside
/// that body are charged separately as they expand, so the total charged
/// tracks the total emitted.
///
/// The default is calibrated against a realistic Pydantic-shaped model, not the
/// fixture corpus — every nested `BaseModel` and `Enum` becomes a `$defs` entry
/// `$ref`'d per use site, so use-site counts climb fast without the schema being
/// pathological. Measured: a 40-sub-model × 50-shared-enum domain model is 2,040
/// use sites but only 27,205 nodes / 198 KB. 500,000 nodes is ~18× that, and
/// lands somewhere around 3.5–6 MB of canonical output at the 7–12 bytes/node
/// these shapes measure at.
///
/// Operators who genuinely exceed it can raise (or lower) it via the env var
/// rather than restructuring their models: the consumer-side `expected_type`
/// path hardcodes `tool_strict=true`, so a BLOCK there has no per-tool escape
/// hatch and this knob is the only remedy.
const DEFAULT_MAX_INLINED_NODES: usize = 500_000;

/// Env override for [`DEFAULT_MAX_INLINED_NODES`]. Values that do not parse as a
/// positive integer are ignored (with a log line) rather than turned into a
/// warning, since a typo here must not become a startup refusal via
/// `MCP_MESH_SCHEMA_STRICT`.
const MAX_INLINED_NODES_ENV: &str = "MCP_MESH_SCHEMA_MAX_INLINED_NODES";

/// Parsing half of [`resolved_node_budget`], split out so the value rules can be
/// exercised without mutating process-global env.
fn parse_node_budget(raw: Option<&str>) -> usize {
    match raw {
        None => DEFAULT_MAX_INLINED_NODES,
        Some(raw) => match raw.trim().parse::<usize>() {
            Ok(n) if n > 0 => n,
            _ => {
                static WARNED: std::sync::Once = std::sync::Once::new();
                WARNED.call_once(|| {
                    tracing::warn!(
                        "{}={:?} is not a positive integer; using the default of {}",
                        MAX_INLINED_NODES_ENV,
                        raw,
                        DEFAULT_MAX_INLINED_NODES
                    );
                });
                DEFAULT_MAX_INLINED_NODES
            }
        },
    }
}

fn resolved_node_budget() -> usize {
    parse_node_budget(std::env::var(MAX_INLINED_NODES_ENV).ok().as_deref())
}

/// Total number of JSON values in a tree (objects, arrays and scalars alike).
fn count_nodes(v: &Value) -> usize {
    match v {
        Value::Object(map) => 1 + map.values().map(count_nodes).sum::<usize>(),
        Value::Array(arr) => 1 + arr.iter().map(count_nodes).sum::<usize>(),
        _ => 1,
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
    /// Nodes materialized by `$ref` inlining so far. See [`DEFAULT_MAX_INLINED_NODES`].
    inlined_nodes: usize,
    /// Ceiling for `inlined_nodes`.
    node_budget: usize,
    /// Memoized `count_nodes` per def body, so a def referenced from many use
    /// sites is measured once.
    def_node_counts: HashMap<String, usize>,
}

impl Ctx {
    fn new(node_budget: usize) -> Self {
        Self {
            defs: Map::new(),
            visiting: Vec::new(),
            cyclic: HashSet::new(),
            warnings: Vec::new(),
            verdict: Verdict::Ok,
            inlined_nodes: 0,
            node_budget,
            def_node_counts: HashMap::new(),
        }
    }

    fn warn(&mut self, msg: impl Into<String>) {
        self.warnings.push(msg.into());
        self.verdict.upgrade(Verdict::Warn);
    }

    fn block(&mut self, msg: impl Into<String>) {
        self.warnings.push(msg.into());
        self.verdict.upgrade(Verdict::Block);
    }

    /// Node count of a def body, memoized.
    fn def_node_count(&mut self, name: &str) -> usize {
        if let Some(n) = self.def_node_counts.get(name) {
            return *n;
        }
        let n = self.defs.get(name).map(count_nodes).unwrap_or(0);
        self.def_node_counts.insert(name.to_string(), n);
        n
    }

    /// Charge one expansion against the node budget. Returns false once the
    /// budget is exhausted (recording the BLOCK exactly once).
    fn charge_nodes(&mut self, cost: usize) -> bool {
        if self.verdict == Verdict::Block {
            return false;
        }
        self.inlined_nodes = self.inlined_nodes.saturating_add(cost);
        if self.inlined_nodes > self.node_budget {
            self.block(format!(
                "schema exceeds the $ref inlining budget of {} nodes: shared $defs \
                 are inlined once per use site, so a diamond-shaped $defs graph \
                 expands exponentially. Simplify the model, or raise the ceiling \
                 with {}",
                self.node_budget, MAX_INLINED_NODES_ENV
            ));
            return false;
        }
        true
    }
}

/// Normalize a raw JSON schema (as a string) into a canonical form and content hash.
///
/// On parse error returns a `NormalizeResult` with `verdict="BLOCK"`, empty `hash`,
/// `canonical=Value::Null`, and the parse error in `warnings`.
pub fn normalize_schema(raw_json: &str, origin: SchemaOrigin) -> NormalizeResult {
    normalize_schema_with_budget(raw_json, origin, resolved_node_budget())
}

/// [`normalize_schema`] with the inlining ceiling supplied explicitly.
///
/// Split out so budget behaviour is testable without mutating the process
/// environment (which would race any concurrently running test).
fn normalize_schema_with_budget(
    raw_json: &str,
    origin: SchemaOrigin,
    node_budget: usize,
) -> NormalizeResult {
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

    let mut ctx = Ctx::new(node_budget);
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
    // Budget exhausted: the partially expanded tree carries dangling $refs, so
    // emitting a hash for it would risk a false capability match. Bail before
    // normalizing rather than after.
    if ctx.verdict == Verdict::Block {
        return block_result(ctx.warnings);
    }
    let mut normalized = normalize(&inlined, &mut ctx);

    // If we have cyclic defs preserved, normalize them too and attach as canonical $defs.
    // We rename each cyclic def to a stable hash-based name so the canonical form is
    // independent of source-language class naming.
    if !ctx.cyclic.is_empty() {
        // Sorted: `cyclic` is a HashSet, and normalizing the bodies in its
        // iteration order would make the ORDER of any warnings they emit
        // nondeterministic across runs.
        let mut cyclic_names: Vec<String> = ctx.cyclic.iter().cloned().collect();
        cyclic_names.sort();
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

    // The cyclic-def bodies above share the same expansion budget, so re-check
    // before hashing: a BLOCK must never ship a hash.
    if ctx.verdict == Verdict::Block {
        return block_result(ctx.warnings);
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
        warnings: dedupe_warnings(ctx.warnings),
    }
}

/// A BLOCK verdict carries no canonical form and no hash — callers must not be
/// able to match on a schema the normalizer refused to canonicalize.
fn block_result(warnings: Vec<String>) -> NormalizeResult {
    NormalizeResult {
        canonical: Value::Null,
        hash: String::new(),
        verdict: Verdict::Block.as_str().to_string(),
        warnings: dedupe_warnings(warnings),
    }
}

/// Collapse repeated warnings, keeping first-occurrence order.
///
/// A def inlined at many use sites re-emits any warning its body produces once
/// per site, so a single lossy property in a widely shared `$def` would
/// otherwise fill the list with copies of one message.
fn dedupe_warnings(warnings: Vec<String>) -> Vec<String> {
    let mut seen: HashSet<String> = HashSet::new();
    warnings
        .into_iter()
        .filter(|w| seen.insert(w.clone()))
        .collect()
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
                    if ctx.defs.contains_key(&name) {
                        // Charge the body's node count BEFORE cloning it, so an
                        // over-budget schema stops allocating here rather than
                        // materializing one more copy first. `normalize_schema`
                        // turns the recorded BLOCK into a hash-less envelope, so
                        // the truncated $ref below never escapes.
                        let cost = ctx.def_node_count(&name);
                        if !ctx.charge_nodes(cost) {
                            let mut out = Map::new();
                            out.insert("$ref".into(), Value::String(format!("#/$defs/{}", name)));
                            return Value::Object(out);
                        }
                        let target = ctx.defs.get(&name).cloned().unwrap_or(Value::Null);
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
            for key in STRIPPED_METADATA_KEYS {
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
                // Track which source property produced each canonical key so a
                // collision can name both sides.
                let mut origin: HashMap<String, String> = HashMap::new();
                for (k, val) in props {
                    let new_key = to_camel_case(&k);
                    if new_key != k {
                        rename.insert(k.clone(), new_key.clone());
                    }
                    // camelCasing is not injective: `value`/`Value` and
                    // `user_id`/`userID` both collapse onto one canonical key, and
                    // `Map::insert` would silently drop the earlier property from
                    // the hashed form. Signal it — a WARN is surfaced to the SDKs
                    // and MCP_MESH_SCHEMA_STRICT promotes it to a startup refusal.
                    if let Some(prev) = origin.get(&new_key) {
                        ctx.warn(format!(
                            "property name collision after camelCase normalization: \
                             source properties '{}' and '{}' both normalize to the \
                             canonical key '{}'. The canonical schema keeps ONE \
                             definition under '{}' (the last one declared wins, here \
                             '{}'), so '{}' is dropped from schema matching. Rename \
                             one of them",
                            prev, k, new_key, new_key, k, prev
                        ));
                    } else {
                        origin.insert(new_key.clone(), k.clone());
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

/// The canonical null branch of a union.
fn null_branch() -> Value {
    let mut m = Map::new();
    m.insert("type".into(), Value::String("null".into()));
    Value::Object(m)
}

/// Is this union branch the `{"type":"null"}` marker?
fn is_null_branch(b: &Value) -> bool {
    matches!(
        b.as_object().and_then(|m| m.get("type")),
        Some(Value::String(t)) if t == "null"
    )
}

/// If this union branch is a bare *nested union*, return its branches.
///
/// "Bare" is judged against the canonical spelling, not the raw one. Two things
/// make the raw spelling differ between runtimes at this point in the pipeline,
/// because `normalize_nullable` runs BEFORE the `discriminator` strip and the
/// `oneOf`->`anyOf` rewrite, and those two rules only ever apply to the node
/// being visited — never to a branch nested inside it:
///
///   * the keyword: Pydantic writes `oneOf` for a discriminated union, Zod and
///     Jackson write `anyOf`;
///   * metadata siblings: Pydantic hangs `discriminator` (and sometimes `title`)
///     off the same object.
///
/// So Pydantic's `{"discriminator":{..},"oneOf":[Cat,Dog]}` and Zod's
/// `{"anyOf":[Cat,Dog]}` are the same branch, and both must splice. Matching on
/// "sole key, spelled exactly like the parent" would splice only Zod's and make
/// `Optional[Pet]` stop resolving across runtimes.
///
/// A branch with a *contentful* sibling (`{"anyOf":[..],"minItems":1}`) is left
/// alone: splicing would drop the sibling.
fn nested_union_branches(branch: &Value) -> Option<&Vec<Value>> {
    let map = branch.as_object()?;
    let mut composite: Option<&Vec<Value>> = None;
    for (k, v) in map {
        if STRIPPED_METADATA_KEYS.contains(&k.as_str()) {
            continue;
        }
        if k == "anyOf" || k == "oneOf" {
            // Two composite keywords on one branch: not a bare nested union.
            if composite.is_some() {
                return None;
            }
            composite = Some(v.as_array()?);
            continue;
        }
        return None; // a contentful sibling
    }
    composite
}

/// Splice bare nested unions into the parent branch list:
/// `[{"anyOf":[A,B]}, C]` becomes `[A, B, C]`. Recursive, so arbitrarily deep
/// nesting flattens onto the same form the flat spelling produces.
fn flatten_union_branches(branches: Vec<Value>) -> Vec<Value> {
    let mut out: Vec<Value> = Vec::with_capacity(branches.len());
    for branch in branches {
        match nested_union_branches(&branch) {
            Some(inner) => out.extend(flatten_union_branches(inner.clone())),
            None => out.push(branch),
        }
    }
    out
}

/// Infer a `type` for a branch that has none, from the concrete values it pins.
///
/// Pydantic emits `Optional[Literal["a","b"]]` as
/// `{"anyOf":[{"enum":[..]},{"type":"null"}]}` and `Optional[Literal["x"]]` as
/// `{"anyOf":[{"const":"x"},{"type":"null"}]}`, while Zod spells both branches
/// with an explicit `"type":"string"`. Without this, the Pydantic spelling has
/// no `type` to hang "null" on and silently loses the nullability. Mirrors
/// `normalize_enum`'s own inference, which otherwise only runs *after* the
/// promotion has already discarded it.
///
/// Deliberately NOT consulted when the branch or the enclosing node already
/// supplies a `type` — see [`nullable_promotion_type`].
fn inferred_literal_type(branch: &Map<String, Value>) -> Option<Value> {
    if let Some(Value::Array(vals)) = branch.get("enum") {
        return infer_uniform_type(vals).map(Value::String);
    }
    if let Some(c) = branch.get("const") {
        return infer_uniform_type(std::slice::from_ref(c)).map(Value::String);
    }
    None
}

/// The `type` that the promoted node should carry "null" on, or `None` if
/// nothing supplies one (a kept `$ref`, or a composite with siblings).
///
/// Precedence is the branch's own `type`, then the enclosing node's, and only
/// then a literal-inferred one. The middle term preserves the pre-existing
/// behaviour for the odd `{"type":"integer","anyOf":[{"enum":["a"]},null]}`
/// shape, where the merge leaves the enclosing `type` in place: inference must
/// not override a `type` that is actually present.
fn nullable_promotion_type(
    branch: &Map<String, Value>,
    node: &Map<String, Value>,
) -> Option<Value> {
    branch
        .get("type")
        .or_else(|| node.get("type"))
        .cloned()
        .or_else(|| inferred_literal_type(branch))
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
            // Collapse nested unions first, so Pydantic's
            // `{"anyOf":[{"discriminator":..,"oneOf":[A,B]},{"type":"null"}]}`,
            // Zod's `{"anyOf":[{"anyOf":[A,B]},{"type":"null"}]}` and Jackson's
            // flat `{"anyOf":[A,B,{"type":"null"}]}` all reach the null handling
            // below with the same branch list.
            let flattened = flatten_union_branches(branches);
            let has_null = flattened.iter().any(is_null_branch);
            let non_null: Vec<Value> = flattened
                .into_iter()
                .filter(|b| !is_null_branch(b))
                .collect();

            if !has_null {
                node.insert((*key).to_string(), Value::Array(non_null));
                continue;
            }

            if non_null.len() == 1 {
                // Promote the single non-null branch to top level + null type
                let inner = non_null.into_iter().next().unwrap();
                if let Value::Object(inner_map) = inner {
                    match nullable_promotion_type(&inner_map, &node) {
                        Some(t) => {
                            node.remove(*key);
                            for (ik, iv) in inner_map {
                                node.insert(ik, iv);
                            }
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
                        None => {
                            // Nothing carries a `type` to hang "null" on — a kept
                            // `$ref` (cyclic def), or a composite with siblings.
                            // Promoting would DROP the null and make `Optional[X]`
                            // hash identically to `X`; a `"type"` sibling next to
                            // `$ref` is ignored under pre-2019-09 drafts, so that is
                            // not an option either. Keep the explicit union instead.
                            node.insert(
                                (*key).to_string(),
                                Value::Array(vec![Value::Object(inner_map), null_branch()]),
                            );
                        }
                    }
                } else {
                    node.insert(
                        (*key).to_string(),
                        Value::Array(vec![inner, null_branch()]),
                    );
                }
            } else {
                // A genuine union that also admits null. Keep it as a union, but
                // pin the null branch last (and collapse duplicates) so the form
                // does not depend on where the generator happened to put it.
                let mut out = non_null;
                out.push(null_branch());
                node.insert((*key).to_string(), Value::Array(out));
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
    // Issue #1587: nested-union spellings. `normalize_nullable` runs before the
    // `discriminator` strip and the oneOf->anyOf rewrite, and neither of those
    // reaches a nested branch, so these two patterns are the ones that catch a
    // flattener keyed on the raw spelling. Three spellings of one type:
    // Pydantic nests + writes `oneOf` + hangs `discriminator` off the branch,
    // Zod nests + writes `anyOf`, Jackson writes it flat.
    pattern_tests!(optional_discriminated_union, "OptionalDiscriminatedUnion");
    pattern_tests!(nested_union, "NestedUnion");

    // ---------------------------------------------------------------
    // Issue #1587: nullable promotion must not drop `null`
    // ---------------------------------------------------------------

    /// A `$ref` kept for a cyclic def carries no `type`, so promoting it out of
    /// the nullable wrapper used to leave nothing to hang `"null"` on and
    /// `Optional[Node]` hashed byte-identically to `Node`.
    #[test]
    fn optional_cyclic_ref_does_not_hash_like_the_required_form() {
        let optional = r##"{
          "$defs": {"Node": {"type": "object", "properties": {
              "name": {"type": "string"},
              "child": {"anyOf": [{"$ref": "#/$defs/Node"}, {"type": "null"}]}
          }}},
          "type": "object",
          "properties": {"root": {"anyOf": [{"$ref": "#/$defs/Node"}, {"type": "null"}]}}
        }"##;
        let required = r##"{
          "$defs": {"Node": {"type": "object", "properties": {
              "name": {"type": "string"},
              "child": {"anyOf": [{"$ref": "#/$defs/Node"}, {"type": "null"}]}
          }}},
          "type": "object",
          "properties": {"root": {"$ref": "#/$defs/Node"}}
        }"##;
        let opt = normalize_schema(optional, SchemaOrigin::Python);
        let req = normalize_schema(required, SchemaOrigin::Python);
        assert_ne!(
            opt.hash, req.hash,
            "Optional[Node] must not canonicalize to Node: {}",
            serde_json::to_string(&opt.canonical).unwrap()
        );
        // The nullable form keeps an explicit two-branch union, null last.
        let root = opt.canonical["properties"]["root"].clone();
        let branches = root["anyOf"].as_array().expect("anyOf preserved");
        assert_eq!(branches.len(), 2);
        assert!(branches[0].get("$ref").is_some());
        assert_eq!(branches[1]["type"], "null");
        // Refs inside the preserved union are still rewritten to stable names.
        assert!(branches[0]["$ref"]
            .as_str()
            .unwrap()
            .starts_with("#/$defs/Recursive_"));
    }

    /// The nullable wrapper is order-independent: Pydantic puts the null branch
    /// last, some generators put it first.
    #[test]
    fn optional_ref_is_canonical_regardless_of_branch_order() {
        let null_last = r##"{"$defs":{"N":{"type":"object","properties":{"c":{"$ref":"#/$defs/N"}}}},
          "type":"object","properties":{"r":{"anyOf":[{"$ref":"#/$defs/N"},{"type":"null"}]}}}"##;
        let null_first = r##"{"$defs":{"N":{"type":"object","properties":{"c":{"$ref":"#/$defs/N"}}}},
          "type":"object","properties":{"r":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/N"}]}}}"##;
        let a = normalize_schema(null_last, SchemaOrigin::Python);
        let b = normalize_schema(null_first, SchemaOrigin::TypeScript);
        assert_eq!(a.hash, b.hash);
    }

    /// `Optional[Union[A, B]]`: Pydantic emits the branches flat, Zod nests the
    /// union inside the nullable wrapper. Both must canonicalize identically —
    /// and the nested form used to lose the null entirely.
    #[test]
    fn optional_union_matches_between_flat_and_nested_shapes() {
        let flat = r##"{"type":"object","properties":{"v":{"anyOf":[
            {"type":"string"},{"type":"integer"},{"type":"null"}]}}}"##;
        let nested = r##"{"type":"object","properties":{"v":{"anyOf":[
            {"anyOf":[{"type":"string"},{"type":"integer"}]},{"type":"null"}]}}}"##;
        let f = normalize_schema(flat, SchemaOrigin::Python);
        let n = normalize_schema(nested, SchemaOrigin::TypeScript);
        assert_eq!(
            f.hash,
            n.hash,
            "flat={} nested={}",
            serde_json::to_string(&f.canonical).unwrap(),
            serde_json::to_string(&n.canonical).unwrap()
        );
        // And the nullability survives.
        assert!(n.canonical["properties"]["v"]["anyOf"]
            .as_array()
            .unwrap()
            .iter()
            .any(|b| b["type"] == "null"));
    }

    /// `Optional[Literal[...]]`: Pydantic omits `type` on the enum branch, Zod
    /// includes it. Inferring the branch type makes both promote to
    /// `{"type":["string","null"]}` instead of one dropping the null.
    #[test]
    fn optional_enum_branch_keeps_null_and_matches_across_runtimes() {
        let py = r##"{"type":"object","properties":{"m":{"anyOf":[
            {"enum":["a","b"]},{"type":"null"}]}}}"##;
        let ts = r##"{"type":"object","properties":{"m":{"anyOf":[
            {"type":"string","enum":["a","b"]},{"type":"null"}]}}}"##;
        let p = normalize_schema(py, SchemaOrigin::Python);
        let t = normalize_schema(ts, SchemaOrigin::TypeScript);
        assert_eq!(p.canonical["properties"]["m"]["type"], serde_json::json!(["string", "null"]));
        assert_eq!(p.hash, t.hash);
    }

    /// The ordinary `Optional[str]` / `Optional[Model]` promotion is untouched:
    /// a branch that already carries a `type` still collapses into a type array.
    #[test]
    fn optional_typed_branch_still_promotes() {
        let raw = r##"{"type":"object","properties":{"n":{"anyOf":[
            {"type":"string"},{"type":"null"}]}}}"##;
        let r = normalize_schema(raw, SchemaOrigin::Python);
        assert_eq!(r.canonical["properties"]["n"]["type"], serde_json::json!(["string", "null"]));
        assert!(r.canonical["properties"]["n"].get("anyOf").is_none());
    }

    /// `Optional[Literal["x"]]`: Pydantic emits a bare `{"const":"x"}` branch,
    /// Zod spells it `{"type":"string","const":"x"}`. Both must keep the null
    /// and land on the same canonical form.
    #[test]
    fn optional_const_branch_keeps_null_and_matches_across_runtimes() {
        let py = r##"{"type":"object","properties":{"k":{"anyOf":[
            {"const":"x"},{"type":"null"}]}}}"##;
        let ts = r##"{"type":"object","properties":{"k":{"anyOf":[
            {"type":"string","const":"x"},{"type":"null"}]}}}"##;
        let p = normalize_schema(py, SchemaOrigin::Python);
        let t = normalize_schema(ts, SchemaOrigin::TypeScript);
        assert_eq!(
            p.canonical["properties"]["k"]["type"],
            serde_json::json!(["string", "null"])
        );
        assert_eq!(p.hash, t.hash);
    }

    /// Literal-type inference is a LAST resort. When the enclosing node already
    /// carries a `type`, the merge leaves that type in place and inference must
    /// not overwrite it.
    #[test]
    fn enclosing_type_wins_over_inferred_literal_type() {
        let raw = r##"{"type":"object","properties":{"v":{
            "type":"integer","anyOf":[{"enum":["a","b"]},{"type":"null"}]}}}"##;
        let r = normalize_schema(raw, SchemaOrigin::Python);
        assert_eq!(
            r.canonical["properties"]["v"]["type"],
            serde_json::json!(["integer", "null"]),
            "the node's own type must survive: {}",
            serde_json::to_string(&r.canonical).unwrap()
        );
    }

    /// A union that admits null AND has several non-null branches keeps its
    /// union form, with the null branch pinned last so the canonical form does
    /// not depend on where the generator put it. Newly load-bearing: the nested
    /// spelling now flattens into this case instead of collapsing away.
    #[test]
    fn multi_branch_nullable_union_pins_null_last() {
        let variants = [
            r##"{"type":"object","properties":{"v":{"anyOf":[
                {"type":"string"},{"type":"integer"},{"type":"null"}]}}}"##,
            r##"{"type":"object","properties":{"v":{"anyOf":[
                {"type":"null"},{"type":"string"},{"type":"integer"}]}}}"##,
            r##"{"type":"object","properties":{"v":{"anyOf":[
                {"type":"string"},{"type":"null"},{"type":"integer"}]}}}"##,
            // nested spelling, null first
            r##"{"type":"object","properties":{"v":{"anyOf":[
                {"type":"null"},{"anyOf":[{"type":"string"},{"type":"integer"}]}]}}}"##,
        ];
        let first = normalize_schema(variants[0], SchemaOrigin::Python);
        let branches = first.canonical["properties"]["v"]["anyOf"]
            .as_array()
            .expect("union preserved");
        assert_eq!(branches.len(), 3);
        assert_eq!(branches[2]["type"], "null", "null must be last");

        for (i, raw) in variants.iter().enumerate().skip(1) {
            let r = normalize_schema(raw, SchemaOrigin::TypeScript);
            assert_eq!(
                r.hash,
                first.hash,
                "variant {} must canonicalize identically: {}",
                i,
                serde_json::to_string(&r.canonical).unwrap()
            );
        }
    }

    /// Splicing is spelling-aware but not greedy: a nested composite carrying a
    /// CONTENTFUL sibling must be left alone, because splicing would drop it.
    #[test]
    fn nested_union_with_a_contentful_sibling_is_not_spliced() {
        let raw = r##"{"type":"object","properties":{"v":{"anyOf":[
            {"anyOf":[{"type":"string"},{"type":"integer"}],"minItems":1},
            {"type":"boolean"}]}}}"##;
        let r = normalize_schema(raw, SchemaOrigin::Python);
        let branches = r.canonical["properties"]["v"]["anyOf"].as_array().unwrap();
        assert_eq!(branches.len(), 2, "must not splice: {}", serde_json::to_string(&r.canonical).unwrap());
        assert_eq!(branches[0]["minItems"], 1, "the sibling must survive");
    }

    // ---------------------------------------------------------------
    // Issue #1587: camelCase rename collisions
    // ---------------------------------------------------------------

    #[test]
    fn camel_case_collision_emits_warn_naming_both_properties() {
        let raw = r##"{"type":"object","properties":{
            "value":{"type":"string"},
            "Value":{"type":"integer"},
            "user_id":{"type":"string"},
            "userID":{"type":"integer"}
        }}"##;
        let r = normalize_schema(raw, SchemaOrigin::Python);
        assert_eq!(r.verdict, "WARN");
        assert_eq!(r.warnings.len(), 2, "warnings: {:?}", r.warnings);

        // Both source names, and the canonical key they collide on, must appear
        // — and the message must not claim the surviving KEY is the source name.
        let value_warning = r
            .warnings
            .iter()
            .find(|w| w.contains("'value' and 'Value'"))
            .unwrap_or_else(|| panic!("no value/Value warning in {:?}", r.warnings));
        assert!(
            value_warning.contains("canonical key 'value'"),
            "must name the surviving canonical key: {}",
            value_warning
        );
        assert!(
            value_warning.contains("here 'Value'"),
            "must name the source property whose definition wins: {}",
            value_warning
        );
        assert!(
            !value_warning.contains("only 'Value' is kept"),
            "must not imply the key 'Value' survives: {}",
            value_warning
        );

        let id_warning = r
            .warnings
            .iter()
            .find(|w| w.contains("canonical key 'userId'"))
            .unwrap_or_else(|| panic!("no userId warning in {:?}", r.warnings));
        assert!(
            id_warning.contains("'user_id' and 'userID'"),
            "must name both source properties: {}",
            id_warning
        );

        // The canonical form is still produced (lossily) — the WARN is the signal.
        let props = r.canonical["properties"].as_object().unwrap();
        assert_eq!(props.len(), 2);
        assert!(props.contains_key("value") && props.contains_key("userId"));
    }

    #[test]
    fn distinct_property_names_do_not_warn() {
        let raw = r##"{"type":"object","properties":{
            "market_cap":{"type":"number"},"hireDate":{"type":"string"}}}"##;
        let r = normalize_schema(raw, SchemaOrigin::Python);
        assert_eq!(r.verdict, "OK", "warnings: {:?}", r.warnings);
    }

    /// A lossy property inside a widely shared `$def` is re-walked at every use
    /// site, so the identical warning must not be repeated once per site.
    #[test]
    fn repeated_warnings_are_deduped() {
        let raw = r##"{
          "$defs": {"Shared": {"type":"object","properties":{
              "value": {"type":"string"}, "Value": {"type":"integer"}}}},
          "type": "object",
          "properties": {
            "a": {"$ref": "#/$defs/Shared"},
            "b": {"$ref": "#/$defs/Shared"},
            "c": {"$ref": "#/$defs/Shared"}
          }
        }"##;
        let r = normalize_schema(raw, SchemaOrigin::Python);
        assert_eq!(r.verdict, "WARN");
        assert_eq!(
            r.warnings.len(),
            1,
            "one collision, three use sites, one warning: {:?}",
            r.warnings
        );
    }

    // ---------------------------------------------------------------
    // Issue #1587: bounded $ref inlining
    // ---------------------------------------------------------------

    /// Build a diamond `$defs` graph: each level references the level below
    /// twice, so inlining materializes 2^levels copies of the leaf.
    /// Node counts (measured): 12 levels = 32,768; 16 = 524,288; 18 = 2,097,152.
    fn diamond_schema(levels: usize) -> String {
        let mut defs =
            String::from(r##""L0":{"type":"object","properties":{"a":{"type":"string"}}}"##);
        for i in 1..=levels {
            defs.push_str(&format!(
                concat!(
                    r##","L{i}":{{"type":"object","properties":{{"x":{{"$ref":"##,
                    r##""#/$defs/L{p}"}},"y":{{"$ref":"#/$defs/L{p}"}}}}}}"##
                ),
                i = i,
                p = i - 1
            ));
        }
        format!(
            concat!(
                r##"{{"$defs":{{{defs}}},"type":"object","##,
                r##""properties":{{"root":{{"$ref":"#/$defs/L{levels}"}}}}}}"##
            ),
            defs = defs,
            levels = levels
        )
    }

    #[test]
    fn diamond_defs_graph_blocks_instead_of_exploding() {
        // 18 levels is ~1.8 KB of input and 2.1M nodes (~25 MB) unbounded.
        let r = normalize_schema(&diamond_schema(18), SchemaOrigin::Python);
        assert_eq!(r.verdict, "BLOCK");
        assert_eq!(r.hash, "", "a BLOCK must never ship a hash");
        assert!(r.canonical.is_null());
        let w = r.warnings.join(" ");
        assert!(w.contains("inlining budget"), "warnings: {:?}", r.warnings);
        // The remedy must be discoverable from the message — a consumer-side
        // BLOCK has no per-tool escape hatch, so this env var is the only one.
        assert!(
            w.contains(MAX_INLINED_NODES_ENV),
            "the warning must name the override: {:?}",
            r.warnings
        );
    }

    #[test]
    fn diamond_defs_graph_under_budget_still_normalizes() {
        // 12 levels = 32,768 nodes, comfortably inside the 500,000 default.
        let r = normalize_schema(&diamond_schema(12), SchemaOrigin::Python);
        assert_eq!(r.verdict, "OK", "warnings: {:?}", r.warnings);
        assert!(r.hash.starts_with("sha256:"));
    }

    /// The bound is on materialized nodes, not `$ref` use sites. A schema with
    /// many cheap use sites must pass where a schema with few expensive ones
    /// fails — that distinction is the whole reason the metric changed.
    #[test]
    fn budget_counts_nodes_not_ref_sites() {
        // 400 use sites of a tiny def: many sites, few nodes.
        let mut props = Vec::new();
        for i in 0..400 {
            props.push(format!(r##""p{}":{{"$ref":"#/$defs/Tiny"}}"##, i));
        }
        let many_cheap = format!(
            r##"{{"$defs":{{"Tiny":{{"type":"string"}}}},"type":"object","properties":{{{}}}}}"##,
            props.join(",")
        );
        let r = normalize_schema_with_budget(&many_cheap, SchemaOrigin::Python, 5_000);
        assert_eq!(
            r.verdict, "OK",
            "400 use sites of a 3-node def is ~1200 nodes: {:?}",
            r.warnings
        );

        // The same 400 sites pointing at a def big enough to blow the same
        // budget must BLOCK, even though the site count is identical.
        let big_props: Vec<String> = (0..60)
            .map(|i| format!(r##""f{}":{{"type":"string"}}"##, i))
            .collect();
        let many_expensive = format!(
            r##"{{"$defs":{{"Tiny":{{"type":"object","properties":{{{}}}}}}},"type":"object","properties":{{{}}}}}"##,
            big_props.join(","),
            props.join(",")
        );
        let r = normalize_schema_with_budget(&many_expensive, SchemaOrigin::Python, 5_000);
        assert_eq!(r.verdict, "BLOCK", "same site count, far more nodes");
    }

    /// The default must admit a large-but-ordinary Pydantic domain model. This
    /// is the shape the previous 2,000-`$ref`-site bound rejected: every nested
    /// BaseModel and Enum is a `$defs` entry re-referenced per use site, so the
    /// site count climbs fast while the output stays small (measured: 2,040
    /// sites, 27,205 nodes, 198 KB).
    #[test]
    fn default_budget_admits_a_realistic_pydantic_model() {
        let mut defs: Vec<String> = Vec::new();
        for e in 0..50 {
            defs.push(format!(
                r##""E{}":{{"enum":["a","b","c","d","e","f","g","h"],"title":"E{}","type":"string"}}"##,
                e, e
            ));
        }
        for m in 0..40 {
            let mut props: Vec<String> = (0..6)
                .map(|f| format!(r##""f{}":{{"title":"F{}","type":"string"}}"##, f, f))
                .collect();
            for e in 0..50 {
                props.push(format!(r##""e{}":{{"$ref":"#/$defs/E{}"}}"##, e, e));
            }
            if m > 0 {
                props.push(format!(r##""child":{{"$ref":"#/$defs/M{}"}}"##, m - 1));
            }
            defs.push(format!(
                r##""M{}":{{"properties":{{{}}},"title":"M{}","type":"object"}}"##,
                m,
                props.join(","),
                m
            ));
        }
        let raw = format!(
            r##"{{"$defs":{{{}}},"type":"object","properties":{{"root":{{"$ref":"#/$defs/M39"}}}}}}"##,
            defs.join(",")
        );
        let r = normalize_schema(&raw, SchemaOrigin::Python);
        assert_eq!(
            r.verdict, "OK",
            "a 40-model x 50-enum domain model must not be refused: {:?}",
            r.warnings
        );
        assert!(r.hash.starts_with("sha256:"));
    }

    /// The budget also covers the second inlining pass over cyclic def bodies —
    /// a schema whose top-level ref is cyclic (so the main pass expands nothing)
    /// must still not smuggle a diamond in through the def body.
    #[test]
    fn diamond_inside_a_cyclic_def_body_also_blocks() {
        let mut defs =
            String::from(r##""L0":{"type":"object","properties":{"a":{"type":"string"}}}"##);
        for i in 1..=18 {
            defs.push_str(&format!(
                concat!(
                    r##","L{i}":{{"type":"object","properties":{{"x":{{"$ref":"##,
                    r##""#/$defs/L{p}"}},"y":{{"$ref":"#/$defs/L{p}"}}}}}}"##
                ),
                i = i,
                p = i - 1
            ));
        }
        defs.push_str(
            r##","R":{"type":"object","properties":{"me":{"$ref":"#/$defs/R"},"big":{"$ref":"#/$defs/L18"}}}"##,
        );
        let raw = format!(
            concat!(
                r##"{{"$defs":{{{defs}}},"type":"object","##,
                r##""properties":{{"root":{{"$ref":"#/$defs/R"}}}}}}"##
            ),
            defs = defs
        );
        let r = normalize_schema(&raw, SchemaOrigin::Python);
        assert_eq!(r.verdict, "BLOCK");
        assert_eq!(r.hash, "", "a BLOCK must never ship a hash");
        assert!(r.canonical.is_null());
    }

    /// The ceiling is an operator knob, not a constant: a consumer-side BLOCK
    /// hardcodes `tool_strict=true` in all three SDKs, so without an override an
    /// agent that trips it has no way to start.
    #[test]
    fn node_budget_is_overridable() {
        let raw = diamond_schema(12); // 32,768 nodes
        assert_eq!(
            normalize_schema_with_budget(&raw, SchemaOrigin::Python, 1_000).verdict,
            "BLOCK",
            "a lowered ceiling must bite"
        );
        assert_eq!(
            normalize_schema_with_budget(&raw, SchemaOrigin::Python, 100_000).verdict,
            "OK",
            "a raised ceiling must let it through"
        );
    }

    /// Value rules for that knob, against the pure parser — no process-global
    /// state, so a failing assertion cannot leak into later tests.
    #[test]
    fn node_budget_env_parsing() {
        assert_eq!(parse_node_budget(None), DEFAULT_MAX_INLINED_NODES);
        assert_eq!(parse_node_budget(Some(" 12345 ")), 12_345);

        // A typo must fall back to the default, NOT become a warning — a WARN
        // here would be promoted to a startup refusal by MCP_MESH_SCHEMA_STRICT.
        for bad in ["", "0", "-1", "lots"] {
            assert_eq!(
                parse_node_budget(Some(bad)),
                DEFAULT_MAX_INLINED_NODES,
                "{:?} must fall back to the default",
                bad
            );
            let r = normalize_schema_with_budget(
                r#"{"type":"string"}"#,
                SchemaOrigin::Python,
                parse_node_budget(Some(bad)),
            );
            assert_eq!(r.verdict, "OK", "a bad env value must not taint the verdict");
        }
    }

    /// Restores `MAX_INLINED_NODES_ENV` on scope exit, including on a panicking
    /// assertion, so the one test that touches global state cannot leak it.
    struct EnvGuard(Option<String>);

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            match self.0.take() {
                Some(v) => std::env::set_var(MAX_INLINED_NODES_ENV, v),
                None => std::env::remove_var(MAX_INLINED_NODES_ENV),
            }
        }
    }

    /// The parsing rules above say nothing about the env var actually being
    /// read. This is the only test that touches process-global state, and it
    /// exists solely to keep that plumbing covered.
    #[test]
    fn node_budget_env_is_wired_up() {
        let _guard = EnvGuard(std::env::var(MAX_INLINED_NODES_ENV).ok());

        std::env::set_var(MAX_INLINED_NODES_ENV, "4321");
        let observed = resolved_node_budget();

        assert_eq!(
            observed, 4_321,
            "resolved_node_budget must read {}",
            MAX_INLINED_NODES_ENV
        );
    }

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
