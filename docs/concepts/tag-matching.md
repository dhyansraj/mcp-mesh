# Tag Matching

> Smart service selection with +/- operators

## Overview

When multiple providers offer the same capability, tags determine which one gets selected. MCP Mesh uses a scoring system with preference operators.

## Tag Operators

| Operator  | Prefix | Meaning             | Effect                       |
| --------- | ------ | ------------------- | ---------------------------- |
| Required  | none   | Must be present     | Provider rejected if missing |
| Preferred | `+`    | Bonus if present    | Higher score if present      |
| Excluded  | `-`    | Must NOT be present | Provider rejected if present |

## Examples

```python
# Required: must have "claude"
# Preferred: bonus for "opus"
# Excluded: never use "experimental"
tags = ["claude", "+opus", "-experimental"]
```

## Scoring Algorithm

### Point Values

| Tag Type            | Points                  |
| ------------------- | ----------------------- |
| Required (present)  | 5 points                |
| Preferred (present) | 10 bonus points         |
| Preferred (missing) | 0 points                |
| Excluded (present)  | **Provider eliminated** |

### Scoring Example

Available providers:

```python
# Provider A: claude-haiku
tags = ["claude", "haiku", "fast"]

# Provider B: claude-sonnet
tags = ["claude", "sonnet", "balanced"]

# Provider C: claude-opus
tags = ["claude", "opus", "premium"]

# Provider D: claude-experimental
tags = ["claude", "experimental"]
```

Consumer request:

```python
tags = ["claude", "+opus", "-experimental"]
```

Scoring:

| Provider            | Calculation          | Score  | Result             |
| ------------------- | -------------------- | ------ | ------------------ |
| claude-haiku        | claude(5)            | 5      | Candidate          |
| claude-sonnet       | claude(5)            | 5      | Candidate          |
| claude-opus         | claude(5) + opus(10) | **15** | **SELECTED**       |
| claude-experimental | ELIMINATED           | -      | Has "experimental" |

## Use Cases

### Cost Optimization

```python
# Prefer cheaper models, exclude premium
@mesh.tool(dependencies=[{
    "capability": "llm",
    "tags": ["claude", "+haiku", "-premium"]
}])
```

### Quality Prioritization

```python
# Prefer highest quality
@mesh.tool(dependencies=[{
    "capability": "llm",
    "tags": ["claude", "+opus", "+premium"]
}])
```

### Production Safety

```python
# Never use experimental or beta
@mesh.tool(dependencies=[{
    "capability": "database",
    "tags": ["postgres", "-experimental", "-beta", "-staging"]
}])
```

### Multi-Preference

```python
# Multiple preferences (additive scoring)
@mesh.tool(dependencies=[{
    "capability": "storage",
    "tags": [
        "s3",          # Required
        "+fast",       # Prefer fast
        "+ssd",        # Prefer SSD
        "+replicated", # Prefer replicated
        "-beta"        # Exclude beta
    ]
}])
```

## Tie Breaking

When multiple providers have the same score:

1. **Version** - Higher version wins
2. **Registration time** - Earlier wins
3. **Random** - If still tied

## Combining with Versions

Tags work with version constraints:

```python
@mesh.tool(dependencies=[{
    "capability": "api",
    "tags": ["rest", "+v2", "-deprecated"],
    "version": ">=2.0.0,<3.0.0"
}])
```

Both tags AND version must match.

## Namespace Interaction

Tags operate within namespaces:

```python
@mesh.tool(dependencies=[{
    "capability": "database",
    "tags": ["+primary"],
    "namespace": "production"  # Only search production
}])
```

## Best Practices

### 1. Use Descriptive Tags

```python
# ✅ Good - clear categories
tags = ["llm", "claude", "sonnet", "balanced", "production"]

# ❌ Bad - vague
tags = ["service", "v1"]
```

### 2. Required + Preferred

```python
# ✅ Good - required base, preferred optimization
tags = ["claude", "+opus", "+fast"]

# ❌ Bad - all required (too strict)
tags = ["claude", "opus", "fast"]  # May find nothing
```

### 3. Safety Exclusions

```python
# ✅ Always exclude unsafe options in production
tags = ["database", "-experimental", "-beta", "-test"]
```

### 4. Document Tag Conventions

```
# Project tag conventions:
# - llm providers: claude, openai, local
# - quality tiers: haiku, sonnet, opus
# - environments: production, staging, development
# - stability: stable, beta, experimental
```

## Debugging

### Check Available Tags

```bash
curl http://localhost:8000/agents | jq '.agents[].capabilities | to_entries[] | {capability: .key, tags: .value.tags}'
```

### Test Matching

```bash
# Use meshctl to test capability resolution
meshctl call my_tool  # See which provider was selected
```

## See Also

- [Architecture](architecture.md) - System overview
- [Dependency Injection](../python/dependency-injection.md) - DI patterns
- [Capabilities & Tags](../python/capabilities-tags.md) - Full reference
