# Enhanced Tag Matching Migration Guide

> Upgrading from exact tag matching to smart `+`/`-` operators

This guide helps you migrate existing MCP Mesh applications to take advantage of enhanced tag matching with preference and exclusion operators introduced in v0.4+.

## What Changed

### Before v0.4 - Exact Matching Only

```python
@mesh.tool(
    dependencies=[{
        "capability": "llm_service",
        "tags": ["claude", "opus"]  # ALL tags must match exactly
    }]
)
```

**Problem**: Rigid matching - either exact match or total failure. No fallback options.

### After v0.4 - Smart Matching

```python
@mesh.tool(
    dependencies=[{
        "capability": "llm_service",
        "tags": [
            "claude",       # Required (same as before)
            "+opus",        # Preferred (bonus if present)
            "-experimental" # Excluded (must NOT be present)
        ]
    }]
)
```

**Benefits**: Smart provider selection, graceful degradation, cost control, safety exclusions.

## Backward Compatibility

✅ **100% Backward Compatible**: All existing tag configurations continue to work unchanged.

- Tags without prefixes remain "required" tags
- Existing dependency resolution behavior preserved
- No breaking changes to APIs or data structures
- Zero migration required for basic use cases

## Migration Strategies

### Strategy 1: Gradual Enhancement (Recommended)

Start with your existing exact tags and gradually add preferences/exclusions:

```python
# Phase 1: Existing configuration (works unchanged)
"tags": ["claude", "production"]

# Phase 2: Add preferences for better provider selection
"tags": ["claude", "production", "+opus"]

# Phase 3: Add safety exclusions
"tags": ["claude", "production", "+opus", "-experimental", "-beta"]
```

### Strategy 2: Full Smart Matching

Transform exact requirements into intelligent preferences:

#### Before (Rigid)

```python
@mesh.tool(
    capability="chat_service",
    dependencies=[{
        "capability": "llm_service",
        "tags": ["claude", "opus"]  # Fails if no opus available
    }]
)
def premium_chat(llm_service: mesh.McpMeshAgent = None):
    return llm_service() if llm_service else "Service unavailable"
```

#### After (Smart)

```python
@mesh.tool(
    capability="chat_service",
    dependencies=[{
        "capability": "llm_service",
        "tags": [
            "claude",           # Still require Claude
            "+opus",            # Prefer opus quality
            "+sonnet",          # Fallback to sonnet
            "-experimental"     # Never use experimental
        ]
    }]
)
def adaptive_chat(llm_service: mesh.McpMeshAgent = None):
    """
    Smart chat that adapts to available services:
    - Prefers opus when available
    - Falls back to sonnet if opus unavailable
    - Never uses experimental/unstable services
    """
    return llm_service() if llm_service else "No suitable service available"
```

## Common Migration Patterns

### Pattern 1: Cost Optimization

Transform expensive exact requirements into cost-conscious preferences:

```python
# Before: Always uses expensive premium service
@mesh.tool(
    dependencies=[{"capability": "llm_service", "tags": ["claude", "opus", "premium"]}]
)

# After: Prefers quality but allows cost-effective alternatives
@mesh.tool(
    dependencies=[{
        "capability": "llm_service",
        "tags": [
            "claude",       # Required model family
            "+opus",        # Prefer best quality
            "+sonnet",      # Accept good quality
            "-premium"      # Exclude expensive tiers when cost matters
        ]
    }]
)
```

### Pattern 2: Environment Safety

Add safety exclusions to prevent production issues:

```python
# Before: Could accidentally get experimental services
@mesh.tool(
    dependencies=[{"capability": "database_service", "tags": ["postgres"]}]
)

# After: Explicit safety guardrails
@mesh.tool(
    dependencies=[{
        "capability": "database_service",
        "tags": [
            "postgres",         # Required database type
            "+primary",         # Prefer primary instance
            "+ssd",            # Prefer SSD performance
            "-experimental",    # Safety: no experimental features
            "-beta",           # Safety: no beta versions
            "-replica"         # Safety: no read-only replicas for writes
        ]
    }]
)
```

### Pattern 3: Multi-Region Preferences

Transform region-specific exact matching into intelligent preferences:

```python
# Before: Hard-coded to specific region
@mesh.tool(
    dependencies=[{
        "capability": "storage_service",
        "tags": ["aws", "us-east-1", "primary"]
    }]
)

# After: Regional preferences with fallbacks
@mesh.tool(
    dependencies=[{
        "capability": "storage_service",
        "tags": [
            "aws",              # Required cloud provider
            "+us-east-1",       # Prefer primary region
            "+us-west-2",       # Acceptable fallback region
            "+primary",         # Prefer primary storage
            "-experimental"     # No experimental storage
        ]
    }]
)
```

## Advanced Migration Examples

### Multi-Service Architecture Migration

#### Before: Brittle Exact Matching

```python
@mesh.tool(
    capability="data_pipeline",
    dependencies=[
        {"capability": "database", "tags": ["postgres", "v15", "primary"]},
        {"capability": "cache", "tags": ["redis", "cluster", "v7"]},
        {"capability": "queue", "tags": ["rabbitmq", "ha", "v3.10"]}
    ]
)
def rigid_pipeline():
    """Brittle pipeline that fails if any exact version unavailable."""
    pass
```

#### After: Resilient Smart Matching

```python
@mesh.tool(
    capability="data_pipeline",
    dependencies=[
        {
            "capability": "database",
            "tags": [
                "postgres",         # Required database
                "+primary",         # Prefer primary instance
                "+v15",            # Prefer latest version
                "+ssd",            # Prefer SSD performance
                "-experimental",    # No experimental versions
                "-replica"         # No read-only for this pipeline
            ]
        },
        {
            "capability": "cache",
            "tags": [
                "redis",           # Required cache type
                "+cluster",        # Prefer clustered setup
                "+v7",            # Prefer latest Redis 7.x
                "+memory-optimized", # Prefer memory optimization
                "-single-node"     # Avoid single points of failure
            ]
        },
        {
            "capability": "queue",
            "tags": [
                "rabbitmq",        # Required message queue
                "+ha",            # Prefer high availability
                "+v3.10",         # Prefer stable version
                "-beta"           # No beta versions in production
            ]
        }
    ]
)
def resilient_pipeline():
    """
    Resilient pipeline that:
    - Prefers optimal configurations
    - Gracefully degrades when needed
    - Maintains safety guardrails
    """
    pass
```

## Testing Your Migration

### 1. Validate Enhanced Matching Works

```bash
# Start multiple providers with different tags
python provider_haiku.py   # Tags: ["claude", "haiku", "fast"]
python provider_sonnet.py  # Tags: ["claude", "sonnet", "balanced"]
python provider_opus.py    # Tags: ["claude", "opus", "premium"]

# Test consumer with preferences
python consumer.py         # Tags: ["claude", "+opus", "-experimental"]
# Should select opus provider (preferred)

# Stop opus provider
pkill -f provider_opus.py

# Test fallback behavior
python consumer.py         # Should fallback to sonnet provider
```

### 2. Verify Exclusion Works

```bash
# Start experimental provider
python experimental.py     # Tags: ["claude", "experimental"]

# Test exclusion
python consumer.py         # Tags: ["claude", "-experimental"]
# Should find NO providers (experimental excluded)
```

### 3. Monitor Provider Selection

```bash
# Check which providers are selected
curl -s http://localhost:8000/agents | \
  jq '.agents[] | select(.dependencies_resolved > 0) |
      {name: .name, resolved_dependencies: .resolved_dependencies}'
```

## Performance Considerations

### Scoring Overhead

Enhanced matching adds minimal overhead:

- **Simple string prefix checking**: O(n) with number of tags
- **Priority scoring**: O(n) calculation per provider
- **Provider ranking**: O(n log n) sorting of candidates

### Network Efficiency

Smart matching can improve network efficiency:

- **Better provider selection** reduces retry attempts
- **Regional preferences** minimize latency
- **Cost exclusions** prevent expensive provider usage

## Troubleshooting Migration

### Issue: No Providers Match

```bash
# Check what providers are available
curl -s http://localhost:8000/agents | jq '.agents[].capabilities'

# Verify your tag requirements aren't too restrictive
# Try removing some exclusions or changing requirements to preferences
```

### Issue: Unexpected Provider Selected

```bash
# Debug provider scoring
# Add logging to see scoring decisions:
export MCP_MESH_LOG_LEVEL=DEBUG
python your_consumer.py

# Look for log messages like:
# "Provider score: agent_id=claude-opus score=15"
# "Selected provider: claude-opus (highest score)"
```

### Issue: Legacy Behavior Changed

If you need exactly the old behavior:

```python
# Ensure all tags are required (no + or -)
"tags": ["claude", "opus"]  # Exact matching preserved
```

## Best Practices After Migration

### 1. Use Descriptive Tag Hierarchies

```python
# Good: Clear hierarchy and purpose
"tags": [
    "llm",                    # Service type
    "claude",                 # Provider
    "+opus",                  # Preferred model
    "+us-east-1",            # Preferred region
    "-experimental",          # Safety exclusion
    "-expensive"             # Cost control
]

# Avoid: Cryptic or overly generic tags
"tags": ["svc", "v1", "+opt", "-bad"]
```

### 2. Balance Preferences vs Requirements

```python
# Good: Some requirements, some preferences
"tags": [
    "postgres",              # Required: specific database
    "+primary",              # Preferred: better performance
    "-experimental"          # Safety: exclude risky versions
]

# Avoid: All preferences (too loose) or all requirements (too rigid)
"tags": ["+postgres", "+primary", "+ssd"]  # Too loose
"tags": ["postgres", "v15.2", "us-east-1a", "i3.xlarge"]  # Too rigid
```

### 3. Document Your Tag Strategy

```python
@mesh.tool(
    capability="financial_processor",
    dependencies=[{
        "capability": "database_service",
        "tags": [
            # Required for compliance
            "postgres",          # SOX compliance requirement
            "encrypted",         # PCI DSS requirement

            # Performance preferences
            "+primary",          # Prefer primary for consistency
            "+ssd",             # Prefer SSD for speed

            # Safety exclusions
            "-experimental",     # Never use experimental in finance
            "-replica"          # Never use read-only for transactions
        ]
    }],
    description="Financial processor with strict compliance and performance requirements"
)
```

## Summary

Enhanced tag matching provides powerful capabilities while maintaining full backward compatibility:

✅ **Zero breaking changes** - existing code works unchanged
✅ **Gradual migration** - enhance at your own pace
✅ **Smart fallbacks** - graceful degradation when preferred services unavailable
✅ **Cost control** - exclude expensive services with `-premium`
✅ **Safety guardrails** - exclude experimental/beta with `-experimental`, `-beta`
✅ **Regional preferences** - prefer local services with `+us-east-1`

Start small with simple preferences, then gradually add more sophisticated matching logic as you see the benefits in your specific use cases.
