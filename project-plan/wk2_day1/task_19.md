# Task 19: Consolidate mcp-mesh and mcp-mesh-runtime into Single Package

## Overview

Refactor the current two-package architecture (mcp-mesh + mcp-mesh-runtime) into a single, unified mcp-mesh package. This aligns with our multi-language vision where each language has a lightweight runtime package that interfaces with the central Go registry.

## Background

Currently, we have:

- `mcp-mesh`: Contains decorators and types
- `mcp-mesh-runtime`: Contains runtime enhancement and processing

This split causes:

- Import order issues (mesh_agent must be enhanced by runtime)
- Complex monkey-patching across package boundaries
- User confusion about which package to install
- Maintenance overhead

## Requirements

### Functional Requirements

1. Single package installation: `pip install mcp-mesh`
2. Automatic runtime initialization on import
3. No breaking changes to existing decorator API
4. Maintain all current functionality (registration, heartbeat, injection)

### Technical Requirements

1. Merge all code from mcp-mesh-runtime into mcp-mesh
2. Single pyproject.toml with unified dependencies
3. Automatic decorator processing without explicit runtime import
4. Clean module structure within single package

### User Experience Requirements

1. Simple import: `from mcp_mesh import mesh_agent`
2. No manual runtime initialization needed
3. Works immediately after installation
4. Clear error messages if registry unavailable

## Design

### Repository Structure

```
mcp-mesh/
├── src/
│   ├── core/                    # Go registry and CLI (the brain)
│   │   ├── registry/           # Registry service
│   │   ├── database/           # Database layer
│   │   ├── cli/                # CLI commands
│   │   └── config/             # Configuration
│   └── runtime/                 # Language-specific runtimes
│       ├── python/             # Python runtime package
│       │   ├── pyproject.toml
│       │   └── src/
│       │       └── mcp_mesh/
│       │           ├── __init__.py
│       │           ├── decorators.py
│       │           ├── runtime/
│       │           ├── types.py
│       │           └── utils.py
│       ├── rust/               # Future: Rust runtime
│       ├── javascript/         # Future: JS/TS runtime
│       └── go/                 # Future: Go runtime
├── cmd/                         # Go binary entry points
├── examples/                    # Cross-language examples
└── docs/                        # Documentation
```

### Python Package Structure

```
src/runtime/python/
├── pyproject.toml          # Single package definition
├── src/
│   └── mcp_mesh/
│       ├── __init__.py     # Auto-initialize runtime
│       ├── decorators.py   # mesh_agent decorator
│       ├── runtime/        # Runtime components
│       │   ├── __init__.py
│       │   ├── processor.py
│       │   ├── registry_client.py
│       │   └── health_monitor.py
│       ├── types.py        # Shared types
│       └── utils.py        # Utilities
```

### Initialization Flow

```python
# mcp_mesh/__init__.py
from .decorators import mesh_agent
from .runtime import initialize_runtime

# Auto-start runtime if enabled
if os.getenv('MCP_MESH_ENABLED', 'true').lower() == 'true':
    initialize_runtime()

__all__ = ['mesh_agent']
```

## Implementation Plan

### Phase 0: Repository Restructuring

1. Move current Go code from `internal/` to `src/core/`
2. Create `src/runtime/python/` directory structure
3. Move Python packages to new location
4. Update all import paths and build scripts
5. Update GitHub Actions workflows

### Phase 1: Code Consolidation

1. Create unified package structure in `src/runtime/python/`
2. Move all runtime code into single mcp_mesh package
3. Update imports and module references
4. Merge pyproject.toml dependencies

### Phase 2: Auto-Initialization

1. Implement automatic runtime startup on import
2. Remove manual enhancement/monkey-patching
3. Test import order independence
4. Ensure backward compatibility

### Phase 3: Testing & Validation

1. Test with hello_world.py and system_agent.py
2. Verify dependency injection works
3. Test in container environment
4. Performance testing (startup time, memory)

### Phase 4: Documentation & Migration

1. Update README and documentation
2. Create migration guide for existing users
3. Update all examples to use single import
4. Deprecation notices for old packages

## Testing Requirements

### Unit Tests

- [ ] Decorator creation and wrapping
- [ ] Automatic runtime initialization
- [ ] Registry client connection
- [ ] Dependency injection mechanism

### Integration Tests

- [ ] Full flow with hello_world example
- [ ] Multiple decorators in same file
- [ ] Cross-file dependency resolution
- [ ] Graceful handling when registry unavailable

### Performance Tests

- [ ] Import time < 100ms
- [ ] Memory overhead < 10MB
- [ ] No impact on non-decorated functions

## Success Criteria

1. `pip install mcp-mesh` provides complete functionality
2. `from mcp_mesh import mesh_agent` just works
3. All existing examples run without modification
4. No import order dependencies
5. Clear path for other language implementations

## Risks and Mitigations

### Risk 1: Breaking Existing Users

- **Mitigation**: Provide compatibility layer that redirects old imports
- **Mitigation**: Clear migration documentation

### Risk 2: Circular Import Issues

- **Mitigation**: Careful module design with clear dependencies
- **Mitigation**: Lazy imports where necessary

### Risk 3: Performance Regression

- **Mitigation**: Benchmark before/after
- **Mitigation**: Make runtime initialization async where possible

## Future Considerations

This refactoring sets the stage for:

1. Rust implementation: `mcp-mesh` crate
2. Go implementation: `github.com/mcp/mesh` module
3. JavaScript implementation: `@mcp/mesh` package

Each will follow the same pattern: single package with decorator/annotation and lightweight runtime that talks to the Go registry.

## Acceptance Criteria

- [ ] Single package installs and imports correctly
- [ ] Hello world example works with just `from mcp_mesh import mesh_agent`
- [ ] System agent example works with dependency injection
- [ ] No import order dependencies
- [ ] Runtime starts automatically without user intervention
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Migration guide created

## Dependencies

- Completion of Task 18 (decorator order fix)
- Go registry must be running for full testing

## Build Process Updates

### Go Builds

- Update `go.mod` module paths if needed
- Update Makefile targets to reference `src/core/`
- Ensure `go build` commands use correct paths

### Python Package

- Python package builds from `src/runtime/python/`
- Update CI/CD to `cd src/runtime/python` before pip install
- Ensure examples can find the package

### Installation Instructions

```bash
# For development
cd src/runtime/python
pip install -e .

# For users
pip install mcp-mesh
```

## Estimated Effort

- Repository restructuring: 2-3 hours
- Implementation: 4-6 hours
- Testing: 2-3 hours
- Documentation: 1-2 hours
- Total: 1.5-2.5 days
