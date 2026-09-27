//! Subprocess isolation for tests that mutate process-global state (issue #1618).
//!
//! # Why this exists
//!
//! A handful of tests in this crate exercise code whose inputs and state are
//! *process*-global, not parameters:
//!
//! * the environment — `REDIS_URL`, `MCP_MESH_DISTRIBUTED_TRACING_ENABLED`,
//!   `MCP_MESH_TRACE_STREAM_MAXLEN` are read by [`crate::config`] on every
//!   `init_trace_publisher`;
//! * the trace publisher singleton — a `OnceLock` that latches the first value
//!   permanently and, by construction, can never be reset;
//! * the re-probe atomics — `REPROBE_RUNNING` / `REPROBE_COOLDOWN_MS`.
//!
//! Run two such tests concurrently and they read each other's writes: one
//! test's span lands in another's fake Redis, one test's `init` shows up as an
//! extra connection in another's count. The failures are real cross-talk, not
//! timing noise, and the observed failure set varied run to run (issue #1618).
//!
//! # Why not a global test mutex
//!
//! Serialising around the singleton preserves the singleton. The next test
//! author writes the next env-mutating test, forgets the lock, and the class of
//! bug returns — exactly how #1618 survived long enough to be found on an
//! unrelated branch. A lock also cannot make `std::env::set_var` sound: it is
//! not thread-safe against *readers*, and every other test in the binary is a
//! potential concurrent reader.
//!
//! # What this does instead
//!
//! Re-exec the test binary for one single test, in a child process of its own.
//! The child gets a private environment and a private copy of every `static`,
//! so there is nothing to serialise against. This is the shape already used by
//! `schema_normalize::tests::node_budget_env_is_wired_up`, generalised so the
//! isolation reason and the 0-tests-matched footgun are handled in one place.
//!
//! # Usage
//!
//! ```ignore
//! #[tokio::test]
//! async fn publisher_reuses_connection_across_publishes() {
//!     if crate::test_isolation::isolate("tracing_publish::tests::publisher_reuses_connection_across_publishes") {
//!         return;
//!     }
//!     // ... body runs only in the child, alone in its own process ...
//! }
//! ```
//!
//! # Cost
//!
//! One `fork`/`exec` of the already-built test binary per isolated test (~6 of
//! them), and the children run concurrently with each other and with the rest
//! of the suite. That is far cheaper than `--test-threads=1` across ~570 tests,
//! which is what this replaces.

/// Set on the child so it runs the test body instead of re-exec'ing again.
const CHILD_MARKER: &str = "MCP_MESH_TEST_ISOLATED_CHILD";

/// Re-exec `test_path` in a dedicated child process unless we already are that
/// child.
///
/// Returns `true` if the caller is the *parent* and must return immediately —
/// the body has already been run (and asserted on) in the child. Returns
/// `false` if the caller IS the isolated child and should run the body.
///
/// The child is started with a scrubbed environment: every `MCP_MESH_*` var
/// and `REDIS_URL` are removed before exec. Without that the child would
/// inherit whatever a *concurrently running* sibling test happened to have set
/// at fork time — reintroducing, through the back door, the cross-talk this
/// function exists to remove. It also makes a developer's exported `MCP_MESH_*`
/// vars stop changing local test results.
///
/// Panics (failing the parent test) if the child fails, **or if the child did
/// not run exactly one test**. The second check matters: `--exact` with a stale
/// or misspelled `test_path` matches nothing, and libtest exits 0 having run
/// nothing — a silently vacuous test. Renaming an isolated test without
/// updating its path is therefore a loud failure, not a green no-op.
pub fn isolate(test_path: &str) -> bool {
    if std::env::var_os(CHILD_MARKER).is_some() {
        return false;
    }

    let exe = std::env::current_exe().expect("test binary path");
    let mut cmd = std::process::Command::new(&exe);
    cmd.args(["--exact", "--nocapture", "--test-threads=1", test_path])
        .env(CHILD_MARKER, "1");

    for (key, _) in std::env::vars_os() {
        let name = key.to_string_lossy();
        if name.starts_with("MCP_MESH_") || name == "REDIS_URL" {
            cmd.env_remove(&key);
        }
    }
    // Re-assert the marker: the scrub loop above would otherwise strip it.
    cmd.env(CHILD_MARKER, "1");

    let output = cmd.output().expect("re-exec the test binary");
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    assert!(
        output.status.success(),
        "isolated child for {} failed ({})\n--- child stdout ---\n{}\n--- child stderr ---\n{}",
        test_path,
        output.status,
        stdout,
        stderr
    );
    assert!(
        stdout.contains("1 passed"),
        "isolated child for {} did not run exactly one test — the path is probably stale \
         (a test was renamed without updating its isolate() argument), and libtest exits 0 \
         when --exact matches nothing\n--- child stdout ---\n{}\n--- child stderr ---\n{}",
        test_path,
        stdout,
        stderr
    );

    true
}

#[cfg(test)]
mod tests {
    /// The guard that turns a stale `test_path` from a vacuous pass into a
    /// failure must itself be exercised — otherwise it is one more thing that
    /// is only *believed* to work. Isolating a path that matches no test must
    /// panic on the "did not run exactly one test" assertion.
    #[test]
    #[should_panic(expected = "did not run exactly one test")]
    fn isolate_rejects_a_path_that_matches_nothing() {
        super::isolate("test_isolation::tests::no_such_test_exists_anywhere");
    }
}
