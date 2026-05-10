# tc07 — disabled pending #920

This test case mirrors `uc25_a2a_consumer_python/tc07_consumer_death_surfaces_failure`
for the Java A2A consumer. It validates that when a long-running bridge consumer
is killed mid-flight, the framework's orphan-reset behavior surfaces the failure
to the caller (owner_instance_id flips to null, attempt_count increments).

## Why disabled

The test was originally placed at `tc07_consumer_death_surfaces_failure/`, but
during initial verification it consistently failed at the "Kill the bridging
Java consumer mid-job" step — `meshctl stop` reported the consumer was already
not running. Investigation (debug-agent in PR for #916 Phase 3) confirmed:

- The Java consumer JVM exits **gracefully via SIGTERM**, not via crash or OOM
- All 3 agents in the test container (Python long-task-provider + Python
  report-a2a-agent + Java consumer) shut down within a 5-second window
- The Java SDK contains zero `System.exit()` calls — the SIGTERM is external

This is a **tsuite/meshctl orchestration issue**, not a Java A2A consumer bug.
Likely root cause: meshctl's `terminateChildProcessGroup` in
`src/core/cli/start_execution.go:825-846` signalling a sibling agent's
process group via group-ID collision or `IsRunning()` mistake.

The Python equivalent (`uc25 tc07`) passes via timing — Python agents start
faster + Python's bridge progresses sooner, so test assertions complete before
the SIGTERM wave hits. Java's bridge ramps slower through the first
`tasks/send` round-trip + tc07's 15-section job (~90s natural runtime) exposes
the timing window.

## How to re-enable

Once #920 is resolved (meshctl SIGTERM source pinned and fixed):

1. Rename this directory back to `tc07_consumer_death_surfaces_failure/`
2. Re-run uc27 — should pass 8/8

The test YAML inside this directory is preserved AS-IS — no changes needed
once meshctl is fixed.

## See also

- Issue: https://github.com/dhyansraj/mcp-mesh/issues/920
- Sibling Python test (passing): `tests/integration/suites/uc25_a2a_consumer_python/tc07_consumer_death_surfaces_failure/`
