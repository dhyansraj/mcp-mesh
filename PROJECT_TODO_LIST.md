# MCP Mesh Project TODO List

## 🚨 Critical Production Blockers (Immediate Priority)

### ☐ Fix Registry Independence and Graceful Degradation

- [ ] Ensure agents start successfully when no registry is available
- [ ] Fix agents to survive registry crashes/restarts without dying
- [ ] Make auto-registration non-blocking and failure-tolerant
- [ ] Enable agents to maintain discovered connections after registry failure
- [ ] Add reconnection logic with exponential backoff for registry connections

### ☐ Fix CLI Process Management Issues

- [ ] Fix `mcp_mesh_dev list` command to not kill registry and agents
- [ ] Resolve registry shutdown when individual agents stop (Issue #3)
- [ ] Implement proper process isolation between registry and agents
- [ ] Add signal handling to prevent cascade shutdowns
- [ ] Fix process tracking to work across multiple CLI sessions

### ☐ Fix Agent Registration Flow

- [ ] Debug why agents show as "Unregistered" despite registry connection
- [ ] Verify auto-enhancement triggers properly in subprocess agents
- [ ] Fix HTTP POST to `/agents/register_with_metadata` success rate
- [ ] Ensure registry state is properly shared between CLI sessions
- [ ] Add registration retry mechanism with proper error handling

### ☐ Add CLI Connect-Only Mode

- [ ] Implement `--registry-url` flag to connect to external registry
- [ ] Add `--no-registry` flag for pure agent mode
- [ ] Honor `MCP_MESH_REGISTRY_URL` environment variable in CLI
- [ ] Add `--connect-only` mode to prevent local registry startup
- [ ] Support production K8s registry connection scenarios

## 🔧 Core Functionality (High Priority)

### ☐ Stabilize HTTP Wrapper Implementation

- [ ] Add authentication/authorization for HTTP endpoints
- [ ] Implement rate limiting and request throttling
- [ ] Add SSL/TLS support for secure communication
- [ ] Implement proper error handling for failed HTTP calls
- [ ] Add request/response logging with correlation IDs

### ☐ Finalize Dependency Injection System

- [ ] Design and implement McpMeshAgent interface for clean DI
- [ ] Document parameter name matching requirements clearly
- [ ] Add validation for circular dependencies
- [ ] Implement dependency versioning support
- [ ] Add dependency health checking before injection

### ☐ Document Decorator Application Requirements

- [ ] Document that @mesh_agent decorators must be at module level
- [ ] Clarify decorator ordering (@server.tool() first recommended)
- [ ] Add examples showing correct and incorrect usage
- [ ] Create troubleshooting guide for common decorator issues
- [ ] Update all example files to follow best practices

### ☐ Complete Package Architecture Consolidation (Task 19)

- [ ] Finish consolidating mcp_mesh and mcp_mesh_runtime packages
- [ ] Update all import statements across the codebase
- [ ] Ensure backward compatibility or migration guide
- [ ] Update package installation documentation
- [ ] Test package distribution and installation process

### ☐ Implement Multi-Language Architecture Support

- [ ] Finalize Go registry implementation and testing
- [ ] Create language-agnostic protocol specifications
- [ ] Add TypeScript/JavaScript runtime support
- [ ] Implement cross-language integration tests
- [ ] Document multi-language development patterns

## 🧪 Testing & Quality (Medium Priority)

### ☐ Expand Test Coverage

- [ ] Add end-to-end tests for complete workflows
- [ ] Implement performance and load testing suite
- [ ] Add chaos testing for registry failures
- [ ] Create integration tests for K8s deployments
- [ ] Add security vulnerability scanning

### ☐ Improve Error Handling and Recovery

- [ ] Implement circuit breaker patterns for service calls
- [ ] Add comprehensive error categorization
- [ ] Create error recovery strategies documentation
- [ ] Implement dead letter queues for failed operations
- [ ] Add alerting for critical errors

### ☐ Add Monitoring and Observability

- [ ] Implement OpenTelemetry instrumentation
- [ ] Add Prometheus metrics endpoints
- [ ] Create Grafana dashboard templates
- [ ] Implement distributed tracing
- [ ] Add structured logging with log aggregation support

## 📚 Documentation & Developer Experience (Medium Priority)

### ☐ Create Production Deployment Guide

- [ ] Write Kubernetes deployment best practices
- [ ] Document scaling strategies and limits
- [ ] Create troubleshooting runbooks
- [ ] Add monitoring and alerting setup guide
- [ ] Document backup and disaster recovery procedures

### ☐ Update API Documentation

- [ ] Generate OpenAPI specs for all HTTP endpoints
- [ ] Create interactive API documentation (Swagger UI)
- [ ] Document all MCP protocol extensions
- [ ] Add code examples in multiple languages
- [ ] Create API versioning strategy

### ☐ Improve Developer Onboarding

- [ ] Create quickstart tutorial (< 5 minutes)
- [ ] Add video tutorials for common scenarios
- [ ] Create project template/scaffolding tool
- [ ] Add VS Code extension for development
- [ ] Create debugging guide with common issues

### ☐ Handle Multiple Capability Providers

- [ ] Document how registry handles multiple providers for same capability
- [ ] Implement selection criteria (first wins, last wins, or scoring)
- [ ] Add capability versioning patterns (greeting:v1, greeting:v2)
- [ ] Create examples showing different capability naming patterns
- [ ] Document proxy selection logic for multiple providers

## 🚀 Feature Enhancements (Lower Priority)

### ☐ Advanced Service Discovery Features

- [ ] Implement capability-based routing
- [ ] Add service mesh integration (Istio/Linkerd)
- [ ] Create service catalog UI
- [ ] Add GraphQL API for complex queries
- [ ] Implement service dependency visualization

### ☐ Security Enhancements

- [ ] Add mutual TLS (mTLS) support
- [ ] Implement API key management
- [ ] Add OAuth2/OIDC integration
- [ ] Create security policy enforcement
- [ ] Add audit logging for compliance

### ☐ Developer Tooling

- [ ] Create CLI plugin system
- [ ] Add agent scaffolding generator
- [ ] Implement hot-reload for development
- [ ] Create browser-based development environment
- [ ] Add performance profiling tools

### ☐ Community and Open Source Preparation

- [ ] Prepare repository for public release
- [ ] Create contribution guidelines
- [ ] Set up CI/CD for community contributions
- [ ] Create project website and documentation site
- [ ] Plan community engagement strategy

## 📅 Weekly Maintenance Tasks

### ☐ Code Quality and Maintenance

- [ ] Run security vulnerability scans
- [ ] Update dependencies to latest versions
- [ ] Review and merge community PRs
- [ ] Update documentation based on user feedback
- [ ] Performance optimization based on profiling

## Notes

- Items marked with 🚨 are production blockers that must be resolved before any production deployment
- Each checkbox item should become a GitHub issue with appropriate labels
- Sub-items can be converted to tasks within each issue
- Priority levels are based on production readiness requirements and user impact
- This list should be reviewed and updated weekly based on progress and new findings
