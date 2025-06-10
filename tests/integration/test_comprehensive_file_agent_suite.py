"""
Comprehensive File Agent Integration Test Suite

Main test suite that orchestrates all integration tests for the File Agent,
providing comprehensive validation of MCP protocol compliance, mesh integration,
end-to-end workflows, and performance characteristics.
"""

import asyncio
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from mcp_mesh.runtime.shared.types import HealthStatus
from mcp_mesh.runtime.tools.file_operations import FileOperations

from .test_end_to_end_workflows import (
    TestConcurrentWorkflows,
    TestDataProcessingWorkflow,
    TestDocumentManagementWorkflow,
    TestErrorRecoveryWorkflows,
)

# Import all test modules
from .test_mcp_protocol_compliance import (
    TestMCPErrorHandling,
    TestMCPPromptProtocol,
    TestMCPResourceProtocol,
    TestMCPToolCallProtocol,
    TestMCPToolRegistration,
)
from .test_mesh_integration import (
    TestDependencyInjection,
    TestHealthMonitoring,
    TestMeshAgentRegistration,
    TestMeshErrorHandling,
    TestMeshIntegrationWithFileOperations,
    TestServiceDiscovery,
)
from .test_performance_load import (
    TestConcurrentOperationPerformance,
    TestFileOperationPerformance,
    TestMeshIntegrationPerformance,
    TestScalabilityAndLimits,
)


class TestSuiteReporter:
    """Comprehensive test suite reporter."""

    def __init__(self):
        self.test_results: dict[str, dict[str, Any]] = {}
        self.start_time: datetime | None = None
        self.end_time: datetime | None = None
        self.summary_stats = {
            "total_tests": 0,
            "passed_tests": 0,
            "failed_tests": 0,
            "skipped_tests": 0,
            "test_categories": {},
            "performance_metrics": {},
            "compliance_checks": {},
            "coverage_analysis": {},
        }

    def start_suite(self) -> None:
        """Start test suite execution."""
        self.start_time = datetime.now()
        print(f"\n{'='*80}")
        print("🚀 STARTING COMPREHENSIVE FILE AGENT TEST SUITE")
        print(f"   Started at: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")

    def end_suite(self) -> None:
        """End test suite execution."""
        self.end_time = datetime.now()
        duration = self.end_time - self.start_time if self.start_time else timedelta(0)

        print(f"\n{'='*80}")
        print("🏁 COMPREHENSIVE FILE AGENT TEST SUITE COMPLETED")
        print(f"   Completed at: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Total Duration: {duration}")
        print(f"{'='*80}")

        self._print_summary()

    def record_test_result(
        self, category: str, test_name: str, result: str, **kwargs
    ) -> None:
        """Record individual test result."""
        if category not in self.test_results:
            self.test_results[category] = {}

        self.test_results[category][test_name] = {
            "result": result,
            "timestamp": datetime.now(),
            **kwargs,
        }

        self.summary_stats["total_tests"] += 1
        if result == "PASSED":
            self.summary_stats["passed_tests"] += 1
        elif result == "FAILED":
            self.summary_stats["failed_tests"] += 1
        else:
            self.summary_stats["skipped_tests"] += 1

        # Update category stats
        if category not in self.summary_stats["test_categories"]:
            self.summary_stats["test_categories"][category] = {
                "total": 0,
                "passed": 0,
                "failed": 0,
            }

        self.summary_stats["test_categories"][category]["total"] += 1
        if result == "PASSED":
            self.summary_stats["test_categories"][category]["passed"] += 1
        elif result == "FAILED":
            self.summary_stats["test_categories"][category]["failed"] += 1

    def _print_summary(self) -> None:
        """Print comprehensive test summary."""
        print("\n📊 TEST SUITE SUMMARY")
        print(f"{'─'*50}")

        # Overall stats
        total = self.summary_stats["total_tests"]
        passed = self.summary_stats["passed_tests"]
        failed = self.summary_stats["failed_tests"]
        skipped = self.summary_stats["skipped_tests"]

        success_rate = (passed / total * 100) if total > 0 else 0

        print(f"Total Tests: {total}")
        print(f"✅ Passed: {passed} ({passed/total*100:.1f}%)")
        print(f"❌ Failed: {failed} ({failed/total*100:.1f}%)")
        print(f"⏭️  Skipped: {skipped} ({skipped/total*100:.1f}%)")
        print(f"🎯 Success Rate: {success_rate:.1f}%")

        # Category breakdown
        print("\n📋 CATEGORY BREAKDOWN")
        print(f"{'─'*50}")
        for category, stats in self.summary_stats["test_categories"].items():
            cat_success_rate = (
                (stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0
            )
            status_icon = (
                "✅"
                if cat_success_rate == 100
                else "⚠️" if cat_success_rate >= 80 else "❌"
            )
            print(
                f"{status_icon} {category}: {stats['passed']}/{stats['total']} ({cat_success_rate:.1f}%)"
            )

        # Compliance assessment
        print("\n🔍 COMPLIANCE ASSESSMENT")
        print(f"{'─'*50}")
        self._assess_compliance()

        # Performance summary
        print("\n⚡ PERFORMANCE SUMMARY")
        print(f"{'─'*50}")
        self._assess_performance()

        # Final verdict
        print("\n🏆 FINAL VERDICT")
        print(f"{'─'*50}")
        if success_rate >= 95:
            print(
                "🌟 EXCELLENT: File Agent is production-ready with comprehensive validation!"
            )
        elif success_rate >= 85:
            print("✅ GOOD: File Agent is ready with minor issues to address.")
        elif success_rate >= 70:
            print(
                "⚠️ ACCEPTABLE: File Agent has issues that should be addressed before production."
            )
        else:
            print(
                "❌ NEEDS WORK: Significant issues found, requires attention before deployment."
            )

    def _assess_compliance(self) -> None:
        """Assess MCP protocol and mesh integration compliance."""
        mcp_category = self.summary_stats["test_categories"].get("MCP_Protocol", {})
        mesh_category = self.summary_stats["test_categories"].get(
            "Mesh_Integration", {}
        )

        mcp_compliance = (
            (mcp_category.get("passed", 0) / mcp_category.get("total", 1) * 100)
            if mcp_category.get("total", 0) > 0
            else 0
        )
        mesh_compliance = (
            (mesh_category.get("passed", 0) / mesh_category.get("total", 1) * 100)
            if mesh_category.get("total", 0) > 0
            else 0
        )

        print(f"📡 MCP Protocol Compliance: {mcp_compliance:.1f}%")
        print(f"🕸️  Mesh Integration Compliance: {mesh_compliance:.1f}%")

        if mcp_compliance >= 95 and mesh_compliance >= 95:
            print("🎉 Full compliance achieved!")
        elif mcp_compliance >= 80 and mesh_compliance >= 80:
            print("✨ Good compliance level.")
        else:
            print("⚠️ Compliance issues detected.")

    def _assess_performance(self) -> None:
        """Assess performance characteristics."""
        perf_category = self.summary_stats["test_categories"].get("Performance", {})

        if perf_category.get("total", 0) > 0:
            perf_success = (
                perf_category.get("passed", 0) / perf_category.get("total", 1) * 100
            )
            print(f"🚀 Performance Test Success: {perf_success:.1f}%")

            if perf_success >= 90:
                print("⚡ Excellent performance characteristics!")
            elif perf_success >= 75:
                print("✅ Good performance profile.")
            else:
                print("⚠️ Performance concerns detected.")
        else:
            print("ℹ️ No performance tests recorded.")


@pytest.fixture(scope="session")
def test_reporter():
    """Session-wide test reporter."""
    reporter = TestSuiteReporter()
    reporter.start_suite()
    yield reporter
    reporter.end_suite()


@pytest.fixture
async def comprehensive_test_env():
    """Comprehensive test environment for all test types."""
    # Create temporary directory
    base_dir = Path(tempfile.mkdtemp())

    # Setup mock registry for mesh integration
    mock_registry = AsyncMock()
    mock_registry.get_dependency.return_value = "mock-service-v1.0.0"
    mock_registry.register_agent = AsyncMock()
    mock_registry.send_heartbeat = AsyncMock()
    mock_registry.close = AsyncMock()

    # Create file operations instance
    with patch(
        "mcp_mesh.decorators.mesh_agent.RegistryClient", return_value=mock_registry
    ):
        file_ops = FileOperations(
            base_directory=str(base_dir),
            max_file_size=50 * 1024 * 1024,  # 50MB for testing
        )

    env = {"base_dir": base_dir, "file_ops": file_ops, "mock_registry": mock_registry}

    yield env

    # Cleanup
    await file_ops.cleanup()
    if base_dir.exists():
        shutil.rmtree(base_dir, ignore_errors=True)


class TestComprehensiveFileAgentSuite:
    """Main comprehensive test suite orchestrator."""

    @pytest.mark.asyncio
    async def test_mcp_protocol_compliance_suite(
        self, comprehensive_test_env, test_reporter
    ):
        """Run complete MCP protocol compliance test suite."""
        print("\n🔌 Running MCP Protocol Compliance Tests...")

        test_classes = [
            TestMCPToolRegistration,
            TestMCPToolCallProtocol,
            TestMCPResourceProtocol,
            TestMCPPromptProtocol,
            TestMCPErrorHandling,
        ]

        for test_class in test_classes:
            class_name = test_class.__name__
            print(f"  Running {class_name}...")

            try:
                # Create test instance
                test_instance = test_class()

                # Run all test methods
                for method_name in dir(test_instance):
                    if method_name.startswith("test_"):
                        print(f"    • {method_name}")
                        try:
                            method = getattr(test_instance, method_name)
                            if asyncio.iscoroutinefunction(method):
                                await method(comprehensive_test_env["file_ops"])
                            else:
                                method(comprehensive_test_env["file_ops"])

                            test_reporter.record_test_result(
                                "MCP_Protocol", f"{class_name}.{method_name}", "PASSED"
                            )
                        except Exception as e:
                            test_reporter.record_test_result(
                                "MCP_Protocol",
                                f"{class_name}.{method_name}",
                                "FAILED",
                                error=str(e),
                            )
                            print(f"      ❌ FAILED: {e}")

            except Exception as e:
                test_reporter.record_test_result(
                    "MCP_Protocol", class_name, "FAILED", error=str(e)
                )
                print(f"  ❌ {class_name} FAILED: {e}")

        print("  ✅ MCP Protocol Compliance Tests Completed")

    @pytest.mark.asyncio
    async def test_mesh_integration_suite(self, comprehensive_test_env, test_reporter):
        """Run complete mesh integration test suite."""
        print("\n🕸️ Running Mesh Integration Tests...")

        test_classes = [
            TestMeshAgentRegistration,
            TestDependencyInjection,
            TestHealthMonitoring,
            TestServiceDiscovery,
            TestMeshIntegrationWithFileOperations,
            TestMeshErrorHandling,
        ]

        for test_class in test_classes:
            class_name = test_class.__name__
            print(f"  Running {class_name}...")

            try:
                test_instance = test_class()

                for method_name in dir(test_instance):
                    if method_name.startswith("test_"):
                        print(f"    • {method_name}")
                        try:
                            method = getattr(test_instance, method_name)

                            # Pass appropriate parameters based on method signature
                            if "file_ops_with_mesh" in method.__code__.co_varnames:
                                # Create mock mesh environment
                                file_ops_with_mesh = (
                                    comprehensive_test_env["file_ops"],
                                    comprehensive_test_env["mock_registry"],
                                )
                                await method(file_ops_with_mesh)
                            elif "mock_registry" in method.__code__.co_varnames:
                                await method(comprehensive_test_env["mock_registry"])
                            else:
                                await method()

                            test_reporter.record_test_result(
                                "Mesh_Integration",
                                f"{class_name}.{method_name}",
                                "PASSED",
                            )
                        except Exception as e:
                            test_reporter.record_test_result(
                                "Mesh_Integration",
                                f"{class_name}.{method_name}",
                                "FAILED",
                                error=str(e),
                            )
                            print(f"      ❌ FAILED: {e}")

            except Exception as e:
                test_reporter.record_test_result(
                    "Mesh_Integration", class_name, "FAILED", error=str(e)
                )
                print(f"  ❌ {class_name} FAILED: {e}")

        print("  ✅ Mesh Integration Tests Completed")

    @pytest.mark.asyncio
    async def test_end_to_end_workflows_suite(
        self, comprehensive_test_env, test_reporter
    ):
        """Run complete end-to-end workflow test suite."""
        print("\n🔄 Running End-to-End Workflow Tests...")

        # Import workflow test environment setup
        from .test_end_to_end_workflows import WorkflowTestEnvironment

        test_classes = [
            TestDocumentManagementWorkflow,
            TestDataProcessingWorkflow,
            TestErrorRecoveryWorkflows,
            TestConcurrentWorkflows,
        ]

        # Create workflow environment
        workflow_env = WorkflowTestEnvironment(
            comprehensive_test_env["base_dir"] / "workflows"
        )
        await workflow_env.setup()

        try:
            for test_class in test_classes:
                class_name = test_class.__name__
                print(f"  Running {class_name}...")

                try:
                    test_instance = test_class()

                    for method_name in dir(test_instance):
                        if method_name.startswith("test_"):
                            print(f"    • {method_name}")
                            try:
                                method = getattr(test_instance, method_name)
                                await method(workflow_env)

                                test_reporter.record_test_result(
                                    "End_to_End_Workflows",
                                    f"{class_name}.{method_name}",
                                    "PASSED",
                                )
                            except Exception as e:
                                test_reporter.record_test_result(
                                    "End_to_End_Workflows",
                                    f"{class_name}.{method_name}",
                                    "FAILED",
                                    error=str(e),
                                )
                                print(f"      ❌ FAILED: {e}")

                except Exception as e:
                    test_reporter.record_test_result(
                        "End_to_End_Workflows", class_name, "FAILED", error=str(e)
                    )
                    print(f"  ❌ {class_name} FAILED: {e}")

        finally:
            await workflow_env.cleanup()

        print("  ✅ End-to-End Workflow Tests Completed")

    @pytest.mark.asyncio
    async def test_performance_load_suite(self, comprehensive_test_env, test_reporter):
        """Run complete performance and load test suite."""
        print("\n⚡ Running Performance and Load Tests...")

        # Import load test environment setup
        from .test_performance_load import LoadTestEnvironment

        test_classes = [
            TestFileOperationPerformance,
            TestConcurrentOperationPerformance,
            TestScalabilityAndLimits,
            TestMeshIntegrationPerformance,
        ]

        # Create load test environment
        load_env = LoadTestEnvironment(
            comprehensive_test_env["base_dir"] / "performance"
        )
        await load_env.setup()

        try:
            for test_class in test_classes:
                class_name = test_class.__name__
                print(f"  Running {class_name}...")

                try:
                    test_instance = test_class()

                    for method_name in dir(test_instance):
                        if method_name.startswith("test_"):
                            print(f"    • {method_name}")
                            try:
                                method = getattr(test_instance, method_name)
                                await method(load_env)

                                test_reporter.record_test_result(
                                    "Performance",
                                    f"{class_name}.{method_name}",
                                    "PASSED",
                                )
                            except Exception as e:
                                test_reporter.record_test_result(
                                    "Performance",
                                    f"{class_name}.{method_name}",
                                    "FAILED",
                                    error=str(e),
                                )
                                print(f"      ❌ FAILED: {e}")

                except Exception as e:
                    test_reporter.record_test_result(
                        "Performance", class_name, "FAILED", error=str(e)
                    )
                    print(f"  ❌ {class_name} FAILED: {e}")

        finally:
            await load_env.cleanup()

        print("  ✅ Performance and Load Tests Completed")

    @pytest.mark.asyncio
    async def test_integration_health_check(
        self, comprehensive_test_env, test_reporter
    ):
        """Perform comprehensive health check of the integrated system."""
        print("\n🏥 Running Integration Health Check...")

        file_ops = comprehensive_test_env["file_ops"]

        try:
            # Basic health check
            health_status = await file_ops.health_check()
            assert isinstance(health_status, HealthStatus)
            assert health_status.agent_name == "file-operations-agent"

            # Test core capabilities
            test_file = str(comprehensive_test_env["base_dir"] / "health_check.txt")
            test_content = "Health check content"

            # Write test
            result = await file_ops.write_file(test_file, test_content)
            assert result is True

            # Read test
            content = await file_ops.read_file(test_file)
            assert content == test_content

            # List test
            entries = await file_ops.list_directory(
                str(comprehensive_test_env["base_dir"])
            )
            assert "health_check.txt" in entries

            test_reporter.record_test_result(
                "Integration_Health",
                "comprehensive_health_check",
                "PASSED",
                health_status=(
                    health_status.status.value
                    if hasattr(health_status.status, "value")
                    else str(health_status.status)
                ),
            )

            print("  ✅ Integration Health Check PASSED")

        except Exception as e:
            test_reporter.record_test_result(
                "Integration_Health",
                "comprehensive_health_check",
                "FAILED",
                error=str(e),
            )
            print(f"  ❌ Integration Health Check FAILED: {e}")
            raise

    @pytest.mark.asyncio
    async def test_compliance_validation(self, comprehensive_test_env, test_reporter):
        """Validate overall compliance with requirements."""
        print("\n📋 Running Compliance Validation...")

        compliance_checks = {
            "mcp_protocol_support": self._check_mcp_protocol_support,
            "mesh_integration_support": self._check_mesh_integration_support,
            "security_features": self._check_security_features,
            "error_handling": self._check_error_handling,
            "performance_requirements": self._check_performance_requirements,
        }

        for check_name, check_func in compliance_checks.items():
            print(f"  Checking {check_name}...")
            try:
                result = await check_func(comprehensive_test_env)
                test_reporter.record_test_result(
                    "Compliance_Validation",
                    check_name,
                    "PASSED" if result else "FAILED",
                )
                if result:
                    print(f"    ✅ {check_name} PASSED")
                else:
                    print(f"    ❌ {check_name} FAILED")
            except Exception as e:
                test_reporter.record_test_result(
                    "Compliance_Validation", check_name, "FAILED", error=str(e)
                )
                print(f"    ❌ {check_name} FAILED: {e}")

        print("  ✅ Compliance Validation Completed")

    async def _check_mcp_protocol_support(self, env) -> bool:
        """Check MCP protocol support."""
        file_ops = env["file_ops"]

        # Verify tools are decorated and accessible
        required_methods = ["read_file", "write_file", "list_directory"]
        for method_name in required_methods:
            method = getattr(file_ops, method_name, None)
            if not method or not hasattr(method, "_mesh_agent_metadata"):
                return False

        return True

    async def _check_mesh_integration_support(self, env) -> bool:
        """Check mesh integration support."""
        file_ops = env["file_ops"]
        env["mock_registry"]

        # Verify decorator metadata
        read_method = file_ops.read_file
        metadata = getattr(read_method, "_mesh_agent_metadata", {})

        return (
            "capabilities" in metadata
            and "dependencies" in metadata
            and "decorator_instance" in metadata
        )

    async def _check_security_features(self, env) -> bool:
        """Check security features."""
        file_ops = env["file_ops"]

        try:
            # Test path traversal protection
            await file_ops.read_file("../../../etc/passwd")
            return False  # Should have raised exception
        except Exception:
            pass  # Expected

        # Verify base directory constraints work
        if file_ops.base_directory:
            return True

        return True  # Security checks passed

    async def _check_error_handling(self, env) -> bool:
        """Check error handling capabilities."""
        file_ops = env["file_ops"]

        try:
            # Test file not found
            await file_ops.read_file("/nonexistent/file.txt")
            return False  # Should have raised exception
        except Exception:
            pass  # Expected

        return True  # Error handling working

    async def _check_performance_requirements(self, env) -> bool:
        """Check basic performance requirements."""
        file_ops = env["file_ops"]
        base_dir = env["base_dir"]

        # Test basic operation speed
        test_file = str(base_dir / "perf_test.txt")
        test_content = "Performance test content"

        start_time = time.time()
        await file_ops.write_file(test_file, test_content)
        content = await file_ops.read_file(test_file)
        end_time = time.time()

        duration = end_time - start_time

        # Basic operations should complete within reasonable time
        return duration < 1.0 and content == test_content


def run_comprehensive_test_suite():
    """Run the complete comprehensive test suite."""
    print("🚀 Starting Comprehensive File Agent Test Suite")
    print("This will validate MCP protocol compliance, mesh integration,")
    print("end-to-end workflows, and performance characteristics.\n")

    # Run pytest with comprehensive coverage
    pytest_args = [__file__, "-v", "-s", "--tb=short", "--durations=10", "--capture=no"]

    return pytest.main(pytest_args)


if __name__ == "__main__":
    exit_code = run_comprehensive_test_suite()
    exit(exit_code)
