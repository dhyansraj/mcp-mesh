# Week 1, Day 5: Interface-Optional Dependency Injection - Tasks

## Pre-Implementation Phase (1 hour)
### Dependency Verification (CRITICAL)
**🔍 MUST VERIFY: Week 1, Day 4 completion before starting!**
- [ ] Verify enhanced registry database schema is operational
- [ ] Confirm semantic capability matching works with @mesh_agent metadata
- [ ] Validate agent versioning system integration
- [ ] Test package separation (mcp-mesh-types vs mcp-mesh) functionality
- [ ] Document any gaps that need addressing before proceeding

## Phase 1: Core Auto-Discovery Foundation (4 hours)
### Enhanced Method Signature Extraction
**⚠️ CRITICAL: Extends @mesh_agent decorator from Week 1, Day 4!**
- [ ] **Package Placement**: Signature types in mcp-mesh-types, extraction logic in mcp-mesh
- [ ] Implement MethodMetadata class for storing extracted signatures:
  ```python
  class MethodMetadata:
      method_name: str
      signature: inspect.Signature
      capabilities: List[str] 
      return_type: Type
      parameters: Dict[str, Type]
      type_hints: Dict[str, Type]
  ```
- [ ] Enhance @mesh_agent decorator to extract method signatures automatically
- [ ] Store method metadata on decorated functions for registry discovery
- [ ] Integrate with existing capability registration from Week 1, Day 4

### Registry Schema Enhancement for Service Contracts
**📦 Package Placement**: Contract types in mcp-mesh-types, storage logic in mcp-mesh
- [ ] Extend registry database schema to store service contracts:
  - Service method signatures and return types
  - Parameter validation rules and type information
  - Capability-to-method mapping for discovery
  - Version compatibility information for contract evolution
- [ ] Implement ServiceContract storage and retrieval operations
- [ ] Add contract validation to ensure signature consistency
- [ ] Create registry tools for contract management:
  - store_service_contract(class_type: Type, metadata: MethodMetadata) -> ContractResult
  - get_service_contract(class_type: Type) -> ServiceContract
  - validate_contract_compatibility(contract: ServiceContract) -> ValidationResult

## Phase 2: Dynamic Proxy Generation (5 hours)
### Base Proxy Infrastructure
**📦 Package Placement**: Proxy interfaces in mcp-mesh-types, generation logic in mcp-mesh
- [ ] Implement MeshServiceProxy base class:
  ```python
  class MeshServiceProxy:
      def __init__(self, service_class: Type, registry_client: RegistryClient, endpoint: str)
      def _generate_proxy_methods(self) -> None
      def _create_proxy_method(self, method_name: str, metadata: MethodMetadata) -> Callable
  ```
- [ ] Create proxy method generation using service contracts from registry
- [ ] Implement remote method call translation through MCP protocol
- [ ] Add error handling and retry logic for remote calls

### Dynamic Class Generation
**⚠️ CRITICAL: Must maintain type safety for IDE support!**
- [ ] Implement dynamic proxy class creation matching concrete class interfaces
- [ ] Preserve type annotations and method signatures in generated proxies
- [ ] Add runtime type checking for method parameters and return values
- [ ] Create proxy factory for generating service proxies:
  - create_service_proxy(service_class: Type) -> ServiceProxy
  - resolve_service_endpoint(service_class: Type) -> EndpointInfo
  - validate_proxy_compatibility(proxy: ServiceProxy, contract: ServiceContract) -> bool

### Registry Integration for Service Discovery
**🔗 DEPENDENCIES: Requires enhanced registry from Week 1, Day 4**
- [ ] Implement service endpoint resolution through registry client
- [ ] Add health-aware proxy creation excluding degraded services
- [ ] Create service discovery with capability matching:
  - discover_service_by_class(service_class: Type) -> List[ServiceEndpoint]
  - select_best_service_instance(service_class: Type, criteria: SelectionCriteria) -> ServiceEndpoint
  - monitor_service_health(service_class: Type, callback: Callable) -> HealthMonitor

## Phase 3: Unified Dependency Injection (6 hours)
### Fallback Chain Implementation  
**🔄 CRITICAL: Seamless degradation from remote to local!**
- [ ] **Package Placement**: Fallback interfaces in mcp-mesh-types, logic in mcp-mesh
- [ ] Implement dependency resolution chain:
  1. Try remote proxy via registry discovery
  2. Fall back to local class instantiation
  3. Provide graceful error handling if both fail
- [ ] Add configuration for fallback behavior:
  ```python
  @mesh_agent(dependencies=[OAuth2AuthService], fallback_mode=True)
  async def secure_operation(auth: OAuth2AuthService):
      # Works with remote proxy OR local instance
  ```
- [ ] Create fallback monitoring and logging for operational visibility

### Unified Dependency Pattern Support
**🎯 GOAL: Support 3 patterns simultaneously without breaking existing code**
- [ ] **Package Placement**: Dependency types in mcp-mesh-types, resolution in mcp-mesh
- [ ] Implement unified dependency resolver supporting:
  - String dependencies: `"legacy_auth"` (existing from Week 1, Day 4)
  - Protocol interfaces: `AuthService` (traditional interface-based)
  - Concrete classes: `OAuth2AuthService` (new auto-discovery pattern)
- [ ] Add dependency injection at function call time:
  ```python
  @mesh_agent(dependencies=[
      "legacy_auth",           # String (existing)
      AuthService,             # Protocol interface 
      OAuth2AuthService,       # Concrete class (new)
  ])
  async def flexible_function(
      legacy_auth: str,
      auth_service: AuthService,
      oauth2_auth: OAuth2AuthService
  ):
      # All three patterns work simultaneously!
  ```
- [ ] Create dependency validation and type checking

### Enhanced @mesh_agent Integration
**⚠️ CRITICAL: Must maintain backward compatibility with Week 1, Day 4!**
- [ ] Extend @mesh_agent decorator to handle dependency injection:
  - Dependency resolution at runtime
  - Proxy creation for concrete class dependencies
  - Fallback chain execution
  - Error handling and logging
- [ ] Add dependency injection tools:
  - resolve_dependency(dependency_spec: Union[str, Type, Protocol]) -> Any
  - inject_dependencies(func: Callable, dependencies: List[Any]) -> Callable
  - validate_dependency_types(dependencies: List[Any]) -> ValidationResult

## Integration and Testing (2 hours)
### Comprehensive Integration Testing
**📦 Package Placement**: Test interfaces in mcp-mesh-types, test logic in mcp-mesh
- [ ] Create integration tests covering all dependency patterns
- [ ] Test fallback chain functionality (remote → local → error)
- [ ] Validate type safety and IDE support with generated proxies
- [ ] Ensure backward compatibility with existing Week 1, Day 4 functionality

### Documentation and Examples
**📖 CRITICAL: All examples must import only from mcp-mesh-types!**
- [ ] Create comprehensive examples demonstrating:
  - Interface-optional dependency injection patterns
  - Fallback behavior in different environments  
  - Migration from string dependencies to concrete classes
  - All three dependency patterns working together
- [ ] Document service contract auto-discovery process
- [ ] Provide troubleshooting guide for common integration issues

## Package Separation Checklist (EXTENDS Week 1, Day 4)
### mcp-mesh-types Package (Interfaces Only)
- [ ] Method signature metadata types (MethodMetadata, ServiceContract)
- [ ] Proxy interface definitions (MeshServiceProxy, ServiceEndpoint)
- [ ] Dependency injection types (DependencyResolver, FallbackConfig)
- [ ] Auto-discovery stub decorators preserving metadata
- [ ] Zero runtime dependencies except MCP SDK

### mcp-mesh Package (Full Implementation)
- [ ] Dynamic proxy generation and method creation
- [ ] Registry integration for service discovery and contracts
- [ ] Dependency resolution and injection logic
- [ ] Fallback chain implementation and monitoring
- [ ] Enhanced @mesh_agent with full auto-discovery features

## Validation Requirements
- [ ] All sample code imports only from mcp-mesh-types
- [ ] Examples work with `pip install mcp mcp-mesh-types` only
- [ ] Concrete class dependencies resolve to working proxies
- [ ] Fallback chain degrades gracefully without runtime errors
- [ ] Type safety maintained for IDE support and development experience
- [ ] Backward compatibility with all Week 1, Day 4 features maintained

## Success Metrics
- [ ] Zero Protocol interface definitions required for dependency injection
- [ ] Service contracts auto-extracted from @mesh_agent decorated methods
- [ ] Dynamic proxies provide seamless remote service calls
- [ ] All 3 dependency patterns (string, Protocol, concrete) work simultaneously
- [ ] Fallback chain enables same code to work in mesh and standalone environments
- [ ] Full type safety and IDE support maintained throughout