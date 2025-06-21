# Fix Integration Tests in CI Pipeline

**Type**: bug
**Priority**: medium
**Area**: testing
**Component**: runtime
**Effort**: medium

## Problem/Request

Integration tests are temporarily disabled in CI pipeline to get basic unit testing working. Need to investigate and fix integration test failures to restore full test coverage in CI.

## Background

Integration tests were disabled in CI as part of incremental fix strategy:

- Unit tests: ✅ Passing locally and in CI
- Integration tests: ❌ Status unknown, temporarily disabled
- E2E tests: ❌ Status unknown, temporarily disabled

Current CI matrix: `test-group: ["unit"]` (was `["unit", "integration", "e2e"]`)

## Analysis Needed

1. **Run integration tests locally** to identify specific failures
2. **Check test dependencies** - Docker, external services, network access
3. **Review test environment setup** - CI vs local differences
4. **Investigate path/import issues** - integration tests may have different requirements
5. **Check test data/fixtures** - missing test databases, config files, etc.

## Potential Issues

- **Service dependencies**: Integration tests may need external services (registry, database)
- **Environment setup**: CI environment missing required services
- **Network isolation**: GitHub Actions runner network restrictions
- **Test configuration**: Different config needed for CI vs local environment
- **Resource constraints**: CI runner memory/CPU limitations
- **Timing issues**: Tests may need longer timeouts in CI environment

## Acceptance Criteria

- [ ] Integration tests run successfully in CI pipeline
- [ ] All integration test failures identified and fixed
- [ ] CI matrix restored to include integration tests
- [ ] Integration tests pass consistently across Python 3.11 and 3.12
- [ ] Test execution time reasonable for CI environment
- [ ] Proper test isolation and cleanup

## Implementation Notes

**Investigation Steps**:

1. Run `pytest tests/integration/ -v` locally and document results
2. Check integration test dependencies and requirements
3. Review CI environment setup needs (Docker, services, etc.)
4. Compare test configuration between local and CI environments

**Likely Fixes**:

- Add service dependencies to CI workflow (Docker, databases)
- Update test configuration for CI environment
- Fix import paths or test discovery issues
- Add proper test data setup/teardown
- Adjust timeouts for CI environment

**Testing Strategy**:

- Test integration fixes on PR branch before merging
- Ensure integration tests don't significantly slow down CI
- Maintain test isolation and parallelization

Labels: `bug`, `priority: medium`, `area: testing`, `component: runtime`, `effort: medium`
