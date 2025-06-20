# Fix E2E Tests in CI Pipeline

**Type**: bug
**Priority**: medium
**Area**: testing
**Component**: deployment
**Effort**: large

## Problem/Request

End-to-end (E2E) tests are temporarily disabled in CI pipeline to get basic testing working. Need to investigate and fix E2E test failures to restore full end-to-end validation in CI.

## Background

E2E tests were disabled in CI as part of incremental fix strategy:

- Unit tests: ✅ Passing locally and in CI
- Integration tests: ❌ Disabled (Issue #13)
- E2E tests: ❌ Status unknown, temporarily disabled

Current CI matrix: `test-group: ["unit"]` (was `["unit", "integration", "e2e"]`)

## Analysis Needed

1. **Run E2E tests locally** to identify specific failures
2. **Check infrastructure requirements** - Kubernetes, Docker, external services
3. **Review test environment complexity** - multi-service orchestration needs
4. **Investigate CI environment limitations** - GitHub Actions runner constraints
5. **Check test lifecycle management** - cluster setup, teardown, cleanup

## Potential Issues

**Infrastructure Complexity**:

- **Kubernetes cluster**: E2E tests may need full K8s environment
- **Multi-service setup**: Registry, agents, databases, networking
- **Container orchestration**: Docker Compose or K8s manifests
- **Service mesh**: Complex networking and service discovery

**CI Environment Limitations**:

- **Resource constraints**: GitHub Actions runners have limited CPU/memory
- **Network restrictions**: Firewall, port limitations, external access
- **Time limits**: E2E tests may exceed CI timeout limits
- **Isolation**: Tests may interfere with each other or runner environment

**Test Infrastructure**:

- **Test data**: Large datasets, complex configurations
- **External dependencies**: Cloud services, APIs, registries
- **State management**: Test cleanup, database resets, service restarts

## Acceptance Criteria

- [ ] E2E tests run successfully in CI pipeline OR alternative testing strategy implemented
- [ ] All E2E test failures identified and documented
- [ ] CI matrix includes E2E tests or alternative validation approach
- [ ] E2E tests pass consistently across Python 3.11 and 3.12
- [ ] Test execution time reasonable for CI environment (< 30 min)
- [ ] Proper test isolation and infrastructure cleanup

## Implementation Notes

**Investigation Steps**:

1. Run `pytest tests/e2e/ -v` locally and document results
2. Document E2E test infrastructure requirements (K8s, Docker, services)
3. Evaluate GitHub Actions runner capabilities vs E2E needs
4. Research alternative testing strategies (mocked services, lightweight scenarios)

**Possible Solutions**:

**Option 1: Full E2E in CI**

- Set up K8s cluster in GitHub Actions (kind, minikube)
- Configure all required services and dependencies
- May be resource-intensive and slow

**Option 2: Lightweight E2E**

- Mock external dependencies
- Use Docker Compose instead of K8s
- Focus on critical user journeys only

**Option 3: Nightly E2E**

- Move E2E tests to nightly/scheduled runs
- Keep PR checks fast with unit/integration only
- Full E2E validation on separate schedule

**Option 4: External E2E**

- Use external testing environment (staging cluster)
- Trigger E2E tests after deployment
- Separate from code validation pipeline

**Testing Strategy**:

- Start with lightweight approach and expand
- Prioritize most critical E2E scenarios
- Ensure E2E tests don't block development workflow

Labels: `bug`, `priority: medium`, `area: testing`, `component: deployment`, `effort: large`
