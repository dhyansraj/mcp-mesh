#!/usr/bin/env python3
"""
Local runner for the Python-side jobs of .github/workflows/ci.yml.

Runs the same commands, over the same paths, as the `lint-and-format`,
`python-test` and `scripts-test` jobs, so a green run here means those three
jobs will be green on the PR. Everything is invoked from the directory its CI
job uses, because both the ruff config and the pytest config are per-directory.

DELIBERATELY NOT COVERED — these have no meaningful local shortcut, so this
script does not pretend to run them:

  * go-test / rust-test / typescript-test / java-test / ui-test — each needs its
    own toolchain; run them from their own directories.
  * helm-charts / lockfile-integrity — need helm and a base-branch ref.
  * build-and-package — copies `_mcp_mesh`, `mesh`, README and LICENSE into
    packaging/pypi before building. That scribbles untracked files into the
    working tree, which is the wrong thing for a script people run mid-change.
  * security-scan — bandit, run below but ADVISORY only. CI runs it with
    `|| true` on push events only; it is not in `integration-status`'s `needs:`
    and does not gate a merge, so it does not gate this script either.

This file used to also shell out to `black --check`, `isort --check-only` and
`mypy src`. black and isort are no longer dev dependencies and the type-check
job no longer exists — linting and formatting are consolidated on ruff alone —
so those invocations could not pass and are gone.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Every CI job below sets its working directory to the Python runtime, and both
# the [tool.ruff] and [tool.pytest.ini_options] tables live in that directory's
# pyproject.toml. Running from anywhere else silently picks up different config.
PYTHON_RUNTIME = Path("src/runtime/python")

# The exact scope of the two `lint-and-format` ruff steps: every Python package
# under src/runtime/python, `mesh` (the public API shipped in the wheel)
# included. Keep in sync with .github/workflows/ci.yml.
LINT_PATHS = ["_mcp_mesh", "mesh", "tests"]


class CITestRunner:
    """Manages CI test execution with proper ordering and parallelization."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.results: dict[str, dict[str, Any]] = {}

    def run_command(
        self,
        cmd: list[str],
        description: str,
        timeout: int = 300,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        echo_on_failure: bool = True,
    ) -> tuple[bool, str, str]:
        """Run a command and return success status with output."""
        print(f"🔄 Running: {description}")
        start_time = time.time()

        run_env = None
        if env:
            import os

            run_env = {**os.environ, **env}

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root / cwd if cwd else self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=run_env,
            )

            duration = time.time() - start_time
            success = result.returncode == 0

            status = "✅" if success else "❌"
            print(f"{status} {description} ({duration:.2f}s)")

            if not success and echo_on_failure:
                # The output is the whole point of running this locally; a bare
                # ❌ sends people to the CI logs they were trying to avoid.
                sys.stdout.write(result.stdout)
                sys.stderr.write(result.stderr)

            return success, result.stdout, result.stderr

        except FileNotFoundError:
            print(f"💥 {description}: `{cmd[0]}` not found on PATH")
            return False, "", f"{cmd[0]} not installed"
        except subprocess.TimeoutExpired:
            print(f"⏰ {description} timed out after {timeout}s")
            return False, "", f"Command timed out after {timeout}s"
        except Exception as e:
            print(f"💥 {description} failed with exception: {e}")
            return False, "", str(e)

    def run_lint_checks(self) -> bool:
        """Replicate the `lint-and-format` job (ruff check + ruff format)."""
        print("\n🔍 Running Code Quality Checks...")

        # Sequential, not parallel: these are the only two checks left, they
        # take under a second each, and running them in order means `ruff check`
        # findings and `ruff format` findings do not interleave on the terminal.
        checks = [
            (["ruff", "check", *LINT_PATHS], "Ruff linting"),
            (["ruff", "format", "--check", *LINT_PATHS], "Ruff formatting check"),
        ]

        results = [
            self.run_command(cmd, desc, cwd=PYTHON_RUNTIME) for cmd, desc in checks
        ]

        all_passed = all(result[0] for result in results)
        self.results["lint"] = {"passed": all_passed, "details": results}
        return all_passed

    def run_security_scan(self) -> bool:
        """Run bandit. ADVISORY — the return value never gates the pipeline."""
        print("\n🔒 Running Security Scan (advisory)...")

        # bandit exits non-zero on ANY finding, and _mcp_mesh currently has
        # ~1400 of them, so the full report would bury every other result on the
        # terminal. Findings are summarised below and the report is one command
        # away; suppress the dump.
        success, stdout, stderr = self.run_command(
            ["bandit", "-r", "_mcp_mesh/", "-f", "txt"],
            "Bandit security scan",
            cwd=PYTHON_RUNTIME,
            echo_on_failure=False,
        )
        if not success:
            print(
                "   ℹ️  Findings are advisory and do not gate. Full report:\n"
                "      (cd src/runtime/python && bandit -r _mcp_mesh/ -f txt)"
            )

        self.results["security"] = {
            "passed": success,
            "advisory": True,
            "stdout": stdout,
            "stderr": stderr,
        }
        return success

    def run_python_unit_tests(self) -> bool:
        """Replicate the `python-test` job's unit run."""
        print("\n🧪 Running Python Unit Tests...")

        success, stdout, stderr = self.run_command(
            [
                "pytest",
                "tests/unit/",
                "_mcp_mesh/",
                "-v",
                "--cov=_mcp_mesh",
                "--cov-report=term-missing",
                # No --junit-xml, unlike CI: nothing local reads it, and
                # `test-results-*.xml` is not gitignored, so writing one leaves
                # an untracked file in the tree of whoever ran this.
            ],
            "Python unit tests",
            timeout=1800,
            cwd=PYTHON_RUNTIME,
            # Without this the mesh runtime auto-starts an HTTP server per
            # decorated test module. CI sets it for the same reason.
            env={"MCP_MESH_AUTO_RUN": "false"},
        )

        self.results["test_unit"] = {
            "passed": success,
            "stdout": stdout,
            "stderr": stderr,
        }
        return success

    def run_scripts_tests(self) -> bool:
        """Replicate the `scripts-test` job (both of its steps)."""
        print("\n🧰 Running Repo Script Tests...")

        pytest_ok, pytest_out, pytest_err = self.run_command(
            ["pytest", "scripts/", "-v"], "scripts/ tests"
        )

        # scripts/test_bump_version.py documents `python scripts/...` as a
        # supported entry point, and that __main__ runner collects by a
        # different rule than pytest does. CI runs both; so do we.
        direct_ok, direct_out, direct_err = self.run_command(
            [sys.executable, "scripts/test_bump_version.py"],
            "scripts/test_bump_version.py direct entry point",
        )

        success = pytest_ok and direct_ok
        self.results["test_scripts"] = {
            "passed": success,
            "stdout": pytest_out + direct_out,
            "stderr": pytest_err + direct_err,
        }
        return success

    def generate_report(self) -> bool:
        """Generate a comprehensive test report."""
        print("\n" + "=" * 80)
        print("🎯 CI TEST RESULTS SUMMARY")
        print("=" * 80)

        total_passed = 0
        total_gating = 0

        for test_name, result in self.results.items():
            if result.get("advisory"):
                # Never "FAILED": this check cannot fail the run, and labelling
                # it that way is exactly the overclaim this report should avoid.
                status = "✅ clean" if result["passed"] else "⚠️  findings"
                print(f"{test_name.ljust(20)}: {status} (advisory, not gating)")
                continue

            status = "✅ PASSED" if result["passed"] else "❌ FAILED"
            print(f"{test_name.ljust(20)}: {status}")

            if result["passed"]:
                total_passed += 1
            total_gating += 1

        print("=" * 80)
        print(f"Overall: {total_passed}/{total_gating} gating checks passed")

        if total_passed == total_gating:
            print("🎉 The Python-side CI jobs should pass.")
            print("   Still unchecked here: go, rust, typescript, java, ui,")
            print("   helm-charts, lockfile-integrity and build-and-package.")
            return True
        else:
            print("💥 Some CI checks failed. Please review and fix issues.")
            return False

    def run_full_ci_pipeline(self) -> bool:
        """Run the complete CI pipeline in proper order."""
        print("🚀 Starting Python CI Pipeline...")
        print(f"📁 Project root: {self.project_root}")

        # Phase 1: Static Analysis
        print("\n" + "=" * 60)
        print("📋 PHASE 1: Static Analysis")
        print("=" * 60)

        lint_ok = self.run_lint_checks()
        self.run_security_scan()  # advisory; result deliberately ignored

        if not lint_ok:
            print("❌ Lint/format failed. Stopping pipeline.")
            self.generate_report()
            return False

        # Phase 2: Python Unit Tests
        print("\n" + "=" * 60)
        print("🧪 PHASE 2: Python Unit Tests")
        print("=" * 60)

        self.run_python_unit_tests()

        # Phase 3: Repo Script Tests
        print("\n" + "=" * 60)
        print("🧰 PHASE 3: Repo Script Tests")
        print("=" * 60)

        self.run_scripts_tests()

        return self.generate_report()


def main():
    """Main entry point for the CI test runner."""
    project_root = Path(__file__).parent.parent

    # Deliberately does NOT install anything. It used to `pip install -r
    # requirements-dev.txt` and `pip install -e .` from the repo root, neither
    # of which exists (the Python manifest lives in src/runtime/python). A
    # checker that mutates the environment it is checking is also just a bad
    # idea. Report what is missing and let the caller decide.
    missing = [tool for tool in ("ruff", "pytest", "bandit") if not shutil.which(tool)]
    if missing:
        print(f"⚠️  Not on PATH: {', '.join(missing)}")
        print("   Install the dev extra first:")
        print("     pip install -e 'src/runtime/python[dev]'")
        print()

    runner = CITestRunner(project_root)
    success = runner.run_full_ci_pipeline()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
