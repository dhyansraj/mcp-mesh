#!/usr/bin/env python3
"""
Comprehensive CI test runner that executes tests in proper order with parallelization.
This script replicates the CI/CD pipeline locally for development and debugging.
"""

import asyncio
import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class CITestRunner:
    """Manages CI test execution with proper ordering and parallelization."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.results: dict[str, dict[str, Any]] = {}

    def run_command(
        self, cmd: list[str], description: str, timeout: int = 300
    ) -> tuple[bool, str, str]:
        """Run a command and return success status with output."""
        print(f"🔄 Running: {description}")
        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            duration = time.time() - start_time
            success = result.returncode == 0

            status = "✅" if success else "❌"
            print(f"{status} {description} ({duration:.2f}s)")

            return success, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            print(f"⏰ {description} timed out after {timeout}s")
            return False, "", f"Command timed out after {timeout}s"
        except Exception as e:
            print(f"💥 {description} failed with exception: {e}")
            return False, "", str(e)

    def run_lint_checks(self) -> bool:
        """Run all linting and formatting checks in parallel."""
        print("\n🔍 Running Code Quality Checks...")

        checks = [
            (["ruff", "check", "src", "tests"], "Ruff linting"),
            (["ruff", "format", "--check", "src", "tests"], "Ruff formatting check"),
            (["black", "--check", "src", "tests"], "Black formatting check"),
            (["isort", "--check-only", "src", "tests"], "Import sorting check"),
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(self.run_command, cmd, desc) for cmd, desc in checks
            ]

            results = [
                future.result() for future in concurrent.futures.as_completed(futures)
            ]

        all_passed = all(result[0] for result in results)
        self.results["lint"] = {"passed": all_passed, "details": results}
        return all_passed

    def run_type_check(self) -> bool:
        """Run type checking with mypy."""
        print("\n🔍 Running Type Checking...")

        success, stdout, stderr = self.run_command(
            ["mypy", "src"], "MyPy type checking"
        )

        self.results["typecheck"] = {
            "passed": success,
            "stdout": stdout,
            "stderr": stderr,
        }
        return success

    def run_security_scan(self) -> bool:
        """Run security scanning with bandit."""
        print("\n🔒 Running Security Scan...")

        success, stdout, stderr = self.run_command(
            ["bandit", "-r", "src/", "-f", "txt"], "Bandit security scan"
        )

        self.results["security"] = {
            "passed": success,
            "stdout": stdout,
            "stderr": stderr,
        }
        return success

    def run_test_suite(self, test_type: str, parallel: bool = True) -> bool:
        """Run a specific test suite."""
        print(f"\n🧪 Running {test_type.title()} Tests...")

        cmd = ["pytest", f"tests/{test_type}/", "-v"]

        if parallel and test_type in ["unit", "integration"]:
            cmd.extend(["-n", "auto"])  # pytest-xdist for parallelization

        cmd.extend(
            [
                "--cov=mcp_mesh_sdk",
                "--cov-report=xml",
                "--cov-report=term-missing",
                f"--junit-xml=test-results-{test_type}.xml",
            ]
        )

        success, stdout, stderr = self.run_command(
            cmd, f"{test_type.title()} tests", timeout=600  # 10 minutes for test suites
        )

        self.results[f"test_{test_type}"] = {
            "passed": success,
            "stdout": stdout,
            "stderr": stderr,
        }
        return success

    def run_mcp_compliance_tests(self) -> bool:
        """Run MCP protocol compliance tests."""
        print("\n🔌 Running MCP Protocol Compliance Tests...")

        success, stdout, stderr = self.run_command(
            [
                "pytest",
                "tests/integration/test_mcp_protocol_compliance.py",
                "-v",
                "--junit-xml=mcp-compliance-results.xml",
                "-m",
                "not slow",
            ],
            "MCP compliance tests",
        )

        self.results["mcp_compliance"] = {
            "passed": success,
            "stdout": stdout,
            "stderr": stderr,
        }
        return success

    def run_performance_tests(self) -> bool:
        """Run performance and load tests."""
        print("\n⚡ Running Performance Tests...")

        success, stdout, stderr = self.run_command(
            [
                "pytest",
                "tests/integration/test_performance_load.py",
                "-v",
                "--junit-xml=performance-results.xml",
                "-m",
                "not slow",
            ],
            "Performance tests",
        )

        self.results["performance"] = {
            "passed": success,
            "stdout": stdout,
            "stderr": stderr,
        }
        return success

    def build_package(self) -> bool:
        """Build and verify the package."""
        print("\n📦 Building Package...")

        # Build the package
        build_success, build_stdout, build_stderr = self.run_command(
            ["python", "-m", "build"], "Package build"
        )

        if not build_success:
            self.results["build"] = {
                "passed": False,
                "stdout": build_stdout,
                "stderr": build_stderr,
            }
            return False

        # Verify the package
        verify_success, verify_stdout, verify_stderr = self.run_command(
            ["twine", "check", "dist/*"], "Package verification"
        )

        self.results["build"] = {
            "passed": verify_success,
            "build_stdout": build_stdout,
            "build_stderr": build_stderr,
            "verify_stdout": verify_stdout,
            "verify_stderr": verify_stderr,
        }
        return verify_success

    def generate_report(self) -> None:
        """Generate a comprehensive test report."""
        print("\n" + "=" * 80)
        print("🎯 CI TEST RESULTS SUMMARY")
        print("=" * 80)

        total_passed = 0
        total_tests = 0

        for test_name, result in self.results.items():
            status = "✅ PASSED" if result["passed"] else "❌ FAILED"
            print(f"{test_name.ljust(20)}: {status}")

            if result["passed"]:
                total_passed += 1
            total_tests += 1

        print("=" * 80)
        print(f"Overall: {total_passed}/{total_tests} checks passed")

        if total_passed == total_tests:
            print("🎉 All CI checks passed! Ready for production.")
            return True
        else:
            print("💥 Some CI checks failed. Please review and fix issues.")
            return False

    async def run_full_ci_pipeline(self) -> bool:
        """Run the complete CI pipeline in proper order."""
        print("🚀 Starting Full CI Pipeline...")
        print(f"📁 Project root: {self.project_root}")

        # Phase 1: Static Analysis (can run in parallel)
        print("\n" + "=" * 60)
        print("📋 PHASE 1: Static Analysis")
        print("=" * 60)

        static_tasks = [
            self.run_lint_checks(),
            self.run_type_check(),
            self.run_security_scan(),
        ]

        static_success = all(static_tasks)

        if not static_success:
            print("❌ Static analysis failed. Stopping pipeline.")
            self.generate_report()
            return False

        # Phase 2: Unit Tests
        print("\n" + "=" * 60)
        print("🧪 PHASE 2: Unit Tests")
        print("=" * 60)

        unit_success = self.run_test_suite("unit")

        if not unit_success:
            print("❌ Unit tests failed. Continuing with integration tests...")

        # Phase 3: Integration Tests (including MCP compliance)
        print("\n" + "=" * 60)
        print("🔗 PHASE 3: Integration Tests")
        print("=" * 60)

        self.run_test_suite("integration")
        self.run_mcp_compliance_tests()

        # Phase 4: E2E Tests and Performance
        print("\n" + "=" * 60)
        print("🌐 PHASE 4: E2E and Performance Tests")
        print("=" * 60)

        self.run_test_suite("e2e", parallel=False)
        self.run_performance_tests()

        # Phase 5: Build and Package
        print("\n" + "=" * 60)
        print("📦 PHASE 5: Build and Package")
        print("=" * 60)

        self.build_package()

        # Generate final report
        overall_success = self.generate_report()

        return overall_success


def main():
    """Main entry point for the CI test runner."""
    project_root = Path(__file__).parent.parent

    # Ensure we're in a virtual environment
    if not os.environ.get("VIRTUAL_ENV") and not sys.prefix != sys.base_prefix:
        print("⚠️  Warning: Not running in a virtual environment")
        print("   Consider running: python -m venv venv && source venv/bin/activate")

    # Install development dependencies
    print("📦 Installing development dependencies...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements-dev.txt"],
        cwd=project_root,
    )

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", "."], cwd=project_root
    )

    # Run the CI pipeline
    runner = CITestRunner(project_root)
    success = asyncio.run(runner.run_full_ci_pipeline())

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
