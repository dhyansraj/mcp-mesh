**Goal: An enterprise AI framework for maximum official MCP SDK compliance with minimum boiler plate code for users**

# Week 1, Day 5: Interface-Optional Dependency Injection Foundation

## Primary Objectives

- Implement interface-optional dependency injection eliminating Protocol interface requirements
- Enable auto-discovery of service contracts from @mesh_agent decorated methods
- Create dynamic proxy generation for seamless remote service integration
- Establish unified dependency injection supporting 3 patterns (string, Protocol, concrete class)

## Strategic Value Proposition

**"Kubernetes + Spring Framework for MCP"**

- **Service Discovery**: Registry-based service location (from Kubernetes)
- **Dependency Injection**: Type-safe interface injection (from Spring Framework)
- **Zero Configuration**: Eliminate hard-coded service endpoints
- **Production Ready**: Make MCP applications operationally elegant

## MCP SDK Requirements

- Leverage enhanced registry service from Week 1, Day 4 for service contract storage
- Maintain full MCP SDK compliance with @app.tool() decorator integration
- Use MCP protocol for all remote method calls through dynamic proxies
- Follow MCP resource metadata patterns for service discovery

## Technical Requirements

### Phase 1: Core Auto-Discovery Foundation

**Dependencies**: Requires completion of Week 1, Day 4 registry enhancements

- Method signature extraction from @mesh_agent decorated functions
- Enhanced decorator to capture method metadata automatically
- Registry schema extension for storing service contracts
- Basic service contract validation and storage

### Phase 2: Dynamic Proxy Generation

**Dependencies**: Requires Phase 1 completion

- Dynamic proxy class generation matching concrete class interfaces
- Remote method call translation through MCP protocol
- Registry-based service endpoint resolution
- Fallback chain implementation (remote → local → error)

### Phase 3: Unified Dependency Injection

**Dependencies**: Requires Phase 2 completion

- Support for 3 dependency patterns simultaneously:
  - String dependencies: `"legacy_auth"` (existing pattern)
  - Protocol interfaces: `AuthService` (traditional interface-based)
  - Concrete classes: `OAuth2AuthService` (new auto-discovery pattern)
- Seamless dependency resolution and injection
- Type-safe proxy generation with full IDE support

## Package Architecture Requirements

**Critical**: Follow dual-package separation established in Week 1, Day 4

- **mcp-mesh-types**: Auto-discovery interfaces, proxy stubs, method metadata types
- **mcp-mesh**: Full proxy generation, registry integration, dependency resolution
- **Sample Code**: Must import only from mcp-mesh-types for vanilla MCP compatibility

## Developer Experience Goals

- **Zero Boilerplate**: No interface definitions required
- **Seamless Migration**: Add @mesh_agent decorator to existing classes
- **Perfect Fallback**: Same code works in mesh and standalone environments
- **Type Safety**: Full IDE support with concrete class type hints

## Key Pain Points Addressed

1. **Hard-coded Configuration Hell**: Eliminate manual service endpoint configuration
2. **No Service Discovery**: Enable automatic service location and health awareness
3. **String-Based Dependencies**: Upgrade to type-safe concrete class injection
4. **Environment Complexity**: Single codebase works across dev/staging/prod

## Success Criteria

- Developers can inject concrete classes without defining Protocol interfaces
- Service contracts auto-extracted from @mesh_agent method signatures
- Dynamic proxies provide seamless remote service calls through MCP protocol
- Unified dependency injection supports all 3 patterns simultaneously
- Zero configuration required for service discovery in production environments

## Implementation Phases

**Phase 1 (Foundation)**: Method signature extraction and registry integration
**Phase 2 (Proxy Magic)**: Dynamic proxy generation and remote call handling
**Phase 3 (Integration)**: Unified dependency injection and comprehensive testing

## Dependencies on Previous Work

**CRITICAL**: This phase cannot begin until Week 1, Day 4 is fully completed:

- Enhanced registry database schema (AC-3.1)
- Semantic capability matching (AC-1.1)
- @mesh_agent decorator metadata extraction (AC-1.1)
- Agent versioning system (AC-1.3)
- Package separation architecture (mcp-mesh-types vs mcp-mesh)
