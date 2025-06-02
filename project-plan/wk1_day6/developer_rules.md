# MCP Mesh Development Rules - Week 1, Day 5 Extension

## Core Development Principles (Inherited from Week 1, Day 4)

### Rule 1: No Reinventing Wheels - Use MCP SDK As-Is

- **First Priority**: Always check if functionality exists in the official MCP SDK
- **Use Native Features**: Leverage MCP SDK's built-in capabilities (protocol, transport, decorators)
- **Avoid Duplication**: Don't create custom implementations of existing MCP SDK features
- **Interface-Optional DI**: Use MCP protocol for all remote method calls through dynamic proxies

### Rule 2: Complement MCP SDK - Fill Genuine Gaps

- **Auto-Discovery Gap**: MCP SDK lacks service discovery and dependency injection
- **Registry Integration**: Leverage enhanced registry from Week 1, Day 4
- **Package Separation**: Extract proxy interfaces to `mcp-mesh-types` package
- **Example**: Dynamic proxy generation (MCP SDK has none), method signature extraction

### Rule 3: Enhance MCP SDK - Add Value Layer

- **Interface-Optional Enhancement**: Auto-discovery from @mesh_agent without Protocol definitions
- **Preserve Compatibility**: All enhancements must maintain full MCP SDK compatibility
- **Dual Integration**: Use alongside MCP SDK features (@app.tool() + enhanced @mesh_agent)
- **Package Separation**: Extract interfaces to `mcp-mesh-types`, implementations to `mcp-mesh`

## Interface-Optional Dependency Injection Specific Rules

### Rule 4: Zero Protocol Interface Requirements

- **No Boilerplate**: Never require developers to define Protocol interfaces for dependency injection
- **Auto-Discovery**: Extract service contracts from existing @mesh_agent method signatures
- **Type Safety**: Maintain full IDE support through concrete class type hints
- **Migration Path**: Enable upgrading from string dependencies to concrete class dependencies

### Rule 5: Seamless Fallback Chain

- **Environment Agnostic**: Same code must work in mesh and standalone environments
- **Graceful Degradation**: Remote proxy → local instance → clear error message
- **Configuration Free**: No environment-specific configuration required
- **Health Awareness**: Automatic routing around failed services

### Rule 6: Unified Dependency Patterns

- **Three Patterns**: Support string, Protocol interface, and concrete class dependencies simultaneously
- **Backward Compatibility**: No breaking changes to existing string dependency pattern
- **Progressive Enhancement**: Enable gradual adoption of new dependency patterns
- **Type Validation**: Runtime type checking for all dependency injection patterns

## Package Architecture Requirements (Extends Week 1, Day 4)

### Enhanced `mcp-mesh-types` Package (Interface-Optional Extensions)

```python
# Method signature and proxy interfaces
class MethodMetadata:
    method_name: str
    signature: inspect.Signature
    capabilities: List[str]
    return_type: Type
    parameters: Dict[str, Type]

# Proxy interface definitions
class MeshServiceProxy(ABC):
    @abstractmethod
    async def _invoke_remote_method(self, method_name: str, **kwargs) -> Any: ...

# Dependency resolution types
class DependencyResolver(ABC):
    @abstractmethod
    async def resolve_dependency(self, dependency_spec: Union[str, Type]) -> Any: ...

# No-op enhanced decorators
def mesh_agent(dependencies: List[Union[str, Type]] = None, fallback_mode: bool = True, **kwargs):
    def decorator(func):
        func._mesh_config = kwargs
        func._mesh_dependencies = dependencies or []
        func._mesh_fallback_mode = fallback_mode
        return func
    return decorator
```

### Enhanced `mcp-mesh` Package (Full Implementation)

```python
# Dynamic proxy generation
class DynamicProxyGenerator:
    def create_service_proxy(self, service_class: Type) -> ServiceProxy: ...
    def generate_proxy_methods(self, service_class: Type) -> Dict[str, Callable]: ...

# Registry integration for service discovery
class EnhancedRegistryClient:
    async def discover_service_by_class(self, service_class: Type) -> List[ServiceEndpoint]: ...
    async def get_service_contract(self, service_class: Type) -> ServiceContract: ...

# Full dependency injection implementation
class UnifiedDependencyResolver:
    async def resolve_string_dependency(self, dependency_name: str) -> str: ...
    async def resolve_protocol_dependency(self, protocol_type: Type) -> Any: ...
    async def resolve_concrete_dependency(self, concrete_class: Type) -> ServiceProxy: ...
```

## Implementation Guidelines (Interface-Optional Specific)

### Auto-Discovery Requirements

- **Method Signature Extraction**: Use `inspect.signature()` and `get_type_hints()` for complete signature capture
- **Metadata Preservation**: Store method metadata on decorated functions for registry discovery
- **Type Safety**: Maintain all type annotations and hints for IDE support
- **Contract Validation**: Ensure service contract consistency across service instances

### Dynamic Proxy Generation Requirements

- **Type-Safe Proxies**: Generated proxies must match concrete class interfaces exactly
- **IDE Support**: Preserve auto-completion and type checking for all proxy methods
- **MCP Protocol**: All remote calls must use official MCP SDK protocol handling
- **Error Handling**: Meaningful exceptions for remote call failures and service unavailability

### Dependency Injection Requirements

```python
# ✅ Correct Enhanced @mesh_agent Usage
@app.tool()  # Rule 1: Use MCP SDK as-is
@mesh_agent(dependencies=[OAuth2AuthService], fallback_mode=True)  # Rule 3: Enhance
async def secure_operation(auth: OAuth2AuthService):
    # Same code works with remote proxy OR local instance
    return await auth.validate_token(token)

# ✅ Unified Pattern Support
@mesh_agent(dependencies=[
    "legacy_auth",           # String (existing pattern)
    AuthService,             # Protocol interface (traditional)
    OAuth2AuthService,       # Concrete class (new auto-discovery)
])
async def flexible_function(
    legacy_auth: str,
    auth_service: AuthService,
    oauth2_auth: OAuth2AuthService
):
    # All three patterns work simultaneously!
```

### Sample Code Requirements (Interface-Optional Extensions)

**✅ Correct Sample Imports**:

```python
# All samples MUST import from mcp-mesh-types
from mcp_mesh_types.decorators import mesh_agent
from mcp_mesh_types.proxies import MeshServiceProxy
from mcp_mesh_types.types import MethodMetadata, ServiceContract
```

**❌ Forbidden Sample Imports**:

```python
# NEVER import from mcp-mesh in samples
from mcp_mesh.proxies import DynamicProxyGenerator  # ❌ FORBIDDEN
from mcp_mesh.resolution import UnifiedDependencyResolver  # ❌ FORBIDDEN
```

## Integration with Week 1, Day 4 Requirements

### Registry Service Integration

- **Contract Storage**: Use enhanced registry database schema for service contract storage
- **Capability Matching**: Integrate with semantic capability matching for service discovery
- **Agent Selection**: Leverage intelligent agent selection for proxy target selection
- **Health Monitoring**: Use health-aware selection for proxy endpoint resolution

### Backward Compatibility Requirements

- **No Breaking Changes**: All Week 1, Day 4 functionality must continue to work unchanged
- **Enhanced Features**: New interface-optional features must be additive only
- **Migration Safety**: Existing deployments must be unaffected by new features
- **Package Evolution**: Package separation must remain consistent with Week 1, Day 4 architecture

## Quality Standards (Interface-Optional Specific)

### Type Safety Standards

- **Full IDE Support**: Generated proxies must provide complete auto-completion and type checking
- **Runtime Validation**: Type checking for all dependency injection and remote method calls
- **Error Messages**: Clear, actionable error messages for type mismatches and resolution failures
- **Documentation**: Type hints and docstrings for all public interfaces and methods

### Performance Standards

- **Proxy Generation**: Dynamic proxy creation must not impact application startup significantly
- **Remote Calls**: Proxy method calls must have acceptable latency overhead
- **Memory Usage**: Service proxy caching must not create memory leaks
- **Registry Queries**: Service discovery must maintain sub-100ms response times

### Operational Standards

- **Monitoring**: Comprehensive metrics for dependency resolution success/failure rates
- **Logging**: Detailed logging for troubleshooting service discovery and proxy issues
- **Health Checks**: Continuous monitoring of service availability for fallback decisions
- **Alerting**: Notifications for service discovery failures and fallback chain activations

## Decision Flow (Extended for Interface-Optional)

When implementing interface-optional dependency injection features:

1. **Does MCP SDK provide service discovery?** → No, complement with registry integration (Rule 2)
2. **Does MCP SDK provide dependency injection?** → No, complement with auto-discovery (Rule 2)
3. **Can we enhance @mesh_agent without breaking MCP?** → Yes, enhance with auto-discovery (Rule 3)
4. **Does this require Protocol interface definitions?** → No, use concrete class auto-discovery (Rule 4)
5. **Does this work in standalone environments?** → Yes, implement fallback chain (Rule 5)
6. **Does this support all dependency patterns?** → Yes, implement unified resolution (Rule 6)

## Validation Checklist (Interface-Optional Extensions)

Before implementing interface-optional dependency injection features:

- [ ] Verified Week 1, Day 4 completion and stability
- [ ] Confirmed no Protocol interface requirements for new patterns
- [ ] Designed fallback chain for seamless environment transitions
- [ ] Ensured unified support for all three dependency patterns
- [ ] Maintained full MCP SDK compatibility and protocol usage
- [ ] **Extracted all interfaces to `mcp-mesh-types` package**
- [ ] **Implemented all runtime logic in `mcp-mesh` package only**
- [ ] **All samples import from `mcp-mesh-types` only**
- [ ] **No references to `mcp-mesh` in any sample code**
- [ ] Works in vanilla MCP environment with types package only
- [ ] Examples demonstrate proper MCP SDK patterns with optional mesh enhancements

## Success Metrics (Interface-Optional)

### Developer Experience Metrics

- **Zero Interface Definitions**: No Protocol interfaces required for dependency injection
- **Same Code Everywhere**: Identical code works in mesh and standalone environments
- **Full IDE Support**: Complete auto-completion and type checking for all service proxies
- **Migration Simplicity**: Single decorator addition enables auto-discovery

### Operational Metrics

- **Configuration-Free**: No hard-coded service endpoints in production code
- **Health-Aware**: Automatic routing around failed services
- **Environment-Agnostic**: Single deployment artifact works across all environments
- **Graceful Degradation**: Service failures don't cause application crashes

---

_These rules ensure interface-optional dependency injection builds on the solid foundation of Week 1, Day 4 while maintaining the core principles of MCP SDK compliance, package separation, and community readiness._
