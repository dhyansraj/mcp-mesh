"""
State Validator for MCP Mesh Integration Tests

This module validates actual system state against expected state files.
Designed to provide clear feedback to AI developers about test failures.

🤖 AI BEHAVIOR GUIDANCE:
- This validator tells you WHY tests fail
- Read the validation messages carefully
- Don't modify this validator to make tests pass
- Use validation output to understand what needs fixing
"""

import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

import aiohttp
import yaml


class ValidationError(Exception):
    """Raised when state validation fails."""

    pass


class StateValidator:
    """
    Validates actual system state against expected state definitions.

    🤖 AI USAGE PATTERN:

    # Good usage:
    validator = StateValidator("tests/state/integration-full-system.yaml")
    if not validator.validate_full_system():
        print("System state doesn't match expectations")
        print(validator.get_detailed_report())
        # Fix your code, not the validator

    # Bad usage:
    # Don't do this - fix the underlying issue instead
    validator.ignore_failing_checks = True  # NO!
    """

    def __init__(self, state_file_path: str):
        self.state_file_path = Path(state_file_path)
        self.logger = logging.getLogger(__name__)
        self.validation_results: list[dict[str, Any]] = []
        self.actual_state: dict[str, Any] = {}
        self.expected_state: dict[str, Any] = {}

        # Load expected state
        self._load_expected_state()

    def _load_expected_state(self) -> None:
        """Load expected state from YAML file."""
        try:
            with open(self.state_file_path) as f:
                data = yaml.safe_load(f)
                self.expected_state = data.get("expected_state", {})
                self.meta = data.get("meta", {})
                self.validation_rules = data.get("validation", {})
        except Exception as e:
            raise ValidationError(
                f"Failed to load state file {self.state_file_path}: {e}"
            )

    async def validate_full_system(self) -> bool:
        """
        Validate the complete system state.

        Returns:
            True if all validations pass, False otherwise
        """
        self.validation_results.clear()

        try:
            # Gather actual state
            await self._gather_actual_state()

            # Run all validations
            await self._validate_registry_state()
            await self._validate_agent_states()
            await self._validate_dependencies()
            await self._validate_api_responses()

            # Check if all critical validations passed
            critical_failures = [
                r
                for r in self.validation_results
                if r.get("level") == "critical" and not r.get("passed")
            ]

            return len(critical_failures) == 0

        except Exception as e:
            self._add_result(
                "system",
                "validation_error",
                False,
                "critical",
                f"Validation process failed: {e}",
            )
            return False

    async def _gather_actual_state(self) -> None:
        """Gather current system state."""
        self.actual_state = {
            "registry": await self._get_registry_state(),
            "agents": await self._get_agents_state(),
            "cli": await self._get_cli_state(),
            "timestamp": time.time(),
        }

    async def _get_registry_state(self) -> dict[str, Any]:
        """Get current registry state."""
        expected_registry = self.expected_state.get("registry", {})
        host = expected_registry.get("host", "localhost")
        port = expected_registry.get("port", 8000)
        base_url = f"http://{host}:{port}"

        try:
            async with aiohttp.ClientSession() as session:
                # Test health endpoint
                health_response = None
                try:
                    async with session.get(
                        f"{base_url}/health", timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        health_response = {
                            "status_code": resp.status,
                            "data": await resp.json() if resp.status == 200 else None,
                        }
                except Exception as e:
                    health_response = {"error": str(e)}

                # Test root endpoint
                root_response = None
                try:
                    async with session.get(
                        f"{base_url}/", timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        root_response = {
                            "status_code": resp.status,
                            "data": await resp.json() if resp.status == 200 else None,
                        }
                except Exception as e:
                    root_response = {"error": str(e)}

                # Test agents list endpoint
                agents_response = None
                try:
                    async with session.get(
                        f"{base_url}/agents", timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        agents_response = {
                            "status_code": resp.status,
                            "data": await resp.json() if resp.status == 200 else None,
                        }
                except Exception as e:
                    agents_response = {"error": str(e)}

                return {
                    "reachable": True,
                    "host": host,
                    "port": port,
                    "base_url": base_url,
                    "health": health_response,
                    "root": root_response,
                    "agents_list": agents_response,
                }

        except Exception as e:
            return {
                "reachable": False,
                "host": host,
                "port": port,
                "base_url": base_url,
                "error": str(e),
            }

    async def _get_agents_state(self) -> dict[str, Any]:
        """Get current agent states."""
        # This would typically involve checking agent processes,
        # their registration status, and heartbeat status
        # For now, we'll get this from the registry's agent list

        registry_state = self.actual_state.get("registry", {})
        agents_response = registry_state.get("agents_list", {})

        if agents_response.get("status_code") == 200:
            agents_data = agents_response.get("data", {})
            agents_list = agents_data.get("agents", [])

            # Convert list to dict keyed by agent id
            agents_dict = {}
            for agent in agents_list:
                agent_id = agent.get("id", agent.get("name", "unknown"))
                agents_dict[agent_id] = agent

            return {
                "count": len(agents_list),
                "agents": agents_dict,
                "raw_response": agents_data,
            }
        else:
            return {
                "count": 0,
                "agents": {},
                "error": agents_response.get("error", "Failed to get agents list"),
            }

    async def _get_cli_state(self) -> dict[str, Any]:
        """Get CLI command states."""
        # Test key CLI commands
        cli_results = {}

        # Test registry status via CLI
        try:
            result = subprocess.run(
                ["./bin/mcp-mesh-dev", "status"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd="/media/psf/Home/workspace/github/mcp-mesh",
            )
            cli_results["status"] = {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except Exception as e:
            cli_results["status"] = {"error": str(e)}

        # Test list command
        try:
            result = subprocess.run(
                ["./bin/mcp-mesh-dev", "list"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd="/media/psf/Home/workspace/github/mcp-mesh",
            )
            cli_results["list"] = {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except Exception as e:
            cli_results["list"] = {"error": str(e)}

        return cli_results

    async def _validate_registry_state(self) -> None:
        """Validate registry state against expectations."""
        expected = self.expected_state.get("registry", {})
        actual = self.actual_state.get("registry", {})

        # Check if registry is reachable
        if not actual.get("reachable", False):
            self._add_result(
                "registry",
                "reachable",
                False,
                "critical",
                f"Registry not reachable at {actual.get('base_url', 'unknown')}. "
                f"Error: {actual.get('error', 'Unknown error')}",
            )
            return

        self._add_result(
            "registry",
            "reachable",
            True,
            "critical",
            f"Registry reachable at {actual.get('base_url')}",
        )

        # Check health endpoint
        health = actual.get("health", {})
        if health.get("status_code") == 200:
            self._add_result(
                "registry",
                "health_endpoint",
                True,
                "critical",
                "Health endpoint responding correctly",
            )

            # Validate health response structure
            health_data = health.get("data", {})
            expected_fields = [
                "status",
                "version",
                "uptime_seconds",
                "timestamp",
                "service",
            ]
            for field in expected_fields:
                if field in health_data:
                    self._add_result(
                        "registry",
                        f"health_{field}",
                        True,
                        "important",
                        f"Health response contains {field}: {health_data[field]}",
                    )
                else:
                    self._add_result(
                        "registry",
                        f"health_{field}",
                        False,
                        "important",
                        f"Health response missing required field: {field}",
                    )
        else:
            self._add_result(
                "registry",
                "health_endpoint",
                False,
                "critical",
                f"Health endpoint failed: {health.get('status_code', 'No response')}",
            )

        # Check expected endpoints
        root = actual.get("root", {})
        if root.get("status_code") == 200:
            root_data = root.get("data", {})
            actual_endpoints = root_data.get("endpoints", [])
            expected_endpoints = expected.get("endpoints", [])

            for endpoint in expected_endpoints:
                if endpoint in actual_endpoints:
                    self._add_result(
                        "registry",
                        f"endpoint_{endpoint}",
                        True,
                        "important",
                        f"Registry exposes expected endpoint: {endpoint}",
                    )
                else:
                    self._add_result(
                        "registry",
                        f"endpoint_{endpoint}",
                        False,
                        "important",
                        f"Registry missing expected endpoint: {endpoint}",
                    )

        # Check agent count
        expected_count = expected.get("expected_agent_count", 0)
        actual_count = self.actual_state.get("agents", {}).get("count", 0)

        if actual_count == expected_count:
            self._add_result(
                "registry",
                "agent_count",
                True,
                "important",
                f"Registry has expected number of agents: {actual_count}",
            )
        else:
            self._add_result(
                "registry",
                "agent_count",
                False,
                "important",
                f"Agent count mismatch: expected {expected_count}, got {actual_count}",
            )

    async def _validate_agent_states(self) -> None:
        """Validate individual agent states."""
        expected_agents = self.expected_state.get("agents", {})
        actual_agents = self.actual_state.get("agents", {}).get("agents", {})

        for agent_id, expected_config in expected_agents.items():
            if agent_id in actual_agents:
                actual_config = actual_agents[agent_id]
                self._validate_single_agent(agent_id, expected_config, actual_config)
            else:
                self._add_result(
                    "agents",
                    f"{agent_id}_present",
                    False,
                    "critical",
                    f"Expected agent {agent_id} not found in registry",
                )

    def _validate_single_agent(
        self, agent_id: str, expected: dict, actual: dict
    ) -> None:
        """Validate a single agent's state."""
        # Check status
        expected_status = expected.get("status", "healthy")
        actual_status = actual.get("status", "unknown")

        if actual_status == expected_status:
            self._add_result(
                "agents",
                f"{agent_id}_status",
                True,
                "critical",
                f"Agent {agent_id} has expected status: {actual_status}",
            )
        else:
            self._add_result(
                "agents",
                f"{agent_id}_status",
                False,
                "critical",
                f"Agent {agent_id} status mismatch: expected {expected_status}, got {actual_status}",
            )

        # Check capabilities
        expected_capabilities = set(expected.get("capabilities", []))
        actual_capabilities = set(actual.get("capabilities", []))

        if expected_capabilities.issubset(actual_capabilities):
            self._add_result(
                "agents",
                f"{agent_id}_capabilities",
                True,
                "important",
                f"Agent {agent_id} has expected capabilities: {list(expected_capabilities)}",
            )
        else:
            missing = expected_capabilities - actual_capabilities
            self._add_result(
                "agents",
                f"{agent_id}_capabilities",
                False,
                "important",
                f"Agent {agent_id} missing capabilities: {list(missing)}",
            )

        # Check endpoint type
        expected_endpoint_type = expected.get("endpoint_type", "stdio")
        actual_endpoint = actual.get("endpoint", "")

        if expected_endpoint_type == "stdio" and actual_endpoint.startswith("stdio://"):
            self._add_result(
                "agents",
                f"{agent_id}_endpoint_type",
                True,
                "optional",
                f"Agent {agent_id} has expected stdio endpoint",
            )
        elif expected_endpoint_type == "http" and (
            actual_endpoint.startswith("http://")
            or actual_endpoint.startswith("https://")
        ):
            self._add_result(
                "agents",
                f"{agent_id}_endpoint_type",
                True,
                "optional",
                f"Agent {agent_id} has expected HTTP endpoint",
            )
        else:
            self._add_result(
                "agents",
                f"{agent_id}_endpoint_type",
                False,
                "optional",
                f"Agent {agent_id} endpoint type mismatch: expected {expected_endpoint_type}, got endpoint {actual_endpoint}",
            )

    async def _validate_dependencies(self) -> None:
        """Validate dependency resolution."""
        expected_deps = self.expected_state.get("dependencies_resolved", {})

        # For now, we'll check if agents with dependencies are registered
        # Full dependency validation would require checking heartbeat responses
        for dependent_agent, dependencies in expected_deps.items():
            actual_agents = self.actual_state.get("agents", {}).get("agents", {})

            if dependent_agent in actual_agents:
                agent_deps = actual_agents[dependent_agent].get("dependencies", [])

                for dep_name in dependencies.keys():
                    if dep_name in [a.get("id", "") for a in actual_agents.values()]:
                        self._add_result(
                            "dependencies",
                            f"{dependent_agent}_{dep_name}",
                            True,
                            "important",
                            f"Dependency {dep_name} available for {dependent_agent}",
                        )
                    else:
                        self._add_result(
                            "dependencies",
                            f"{dependent_agent}_{dep_name}",
                            False,
                            "important",
                            f"Dependency {dep_name} not available for {dependent_agent}",
                        )

    async def _validate_api_responses(self) -> None:
        """Validate API response formats against OpenAPI spec."""
        # This could validate response schemas against the OpenAPI spec
        # For now, we'll do basic structure validation

        registry_state = self.actual_state.get("registry", {})
        health = registry_state.get("health", {})

        if health.get("status_code") == 200:
            health_data = health.get("data", {})
            required_fields = [
                "status",
                "version",
                "uptime_seconds",
                "timestamp",
                "service",
            ]

            all_present = all(field in health_data for field in required_fields)
            if all_present:
                self._add_result(
                    "api",
                    "health_schema",
                    True,
                    "critical",
                    "Health endpoint returns valid schema",
                )
            else:
                missing = [f for f in required_fields if f not in health_data]
                self._add_result(
                    "api",
                    "health_schema",
                    False,
                    "critical",
                    f"Health endpoint missing fields: {missing}",
                )

    def _add_result(
        self, category: str, check: str, passed: bool, level: str, message: str
    ) -> None:
        """Add a validation result."""
        self.validation_results.append(
            {
                "category": category,
                "check": check,
                "passed": passed,
                "level": level,  # critical, important, optional
                "message": message,
                "timestamp": time.time(),
            }
        )

    def get_detailed_report(self) -> str:
        """
        Get a detailed validation report.

        🤖 AI DEBUGGING GUIDE:
        - Read this report carefully when tests fail
        - Critical failures need immediate attention
        - Important failures may indicate API changes
        - Optional failures are nice-to-have features
        """
        lines = []
        lines.append("=" * 60)
        lines.append("MCP MESH SYSTEM STATE VALIDATION REPORT")
        lines.append("=" * 60)

        # Add AI guidance
        lines.append("\n🤖 AI DEVELOPER GUIDANCE:")
        guidance = self.meta.get("guidance_for_ai", "No specific guidance available")
        for line in guidance.strip().split("\n"):
            lines.append(f"   {line.strip()}")

        lines.append(f"\nTest Type: {self.meta.get('test_type', 'Unknown')}")
        lines.append(
            f"Breaking Change Policy: {self.meta.get('breaking_change_policy', 'Unknown')}"
        )

        # Summary
        total = len(self.validation_results)
        passed = len([r for r in self.validation_results if r["passed"]])
        failed = total - passed

        critical_failed = len(
            [
                r
                for r in self.validation_results
                if not r["passed"] and r["level"] == "critical"
            ]
        )

        lines.append(f"\nSUMMARY: {passed}/{total} checks passed")
        if critical_failed > 0:
            lines.append(f"❌ CRITICAL FAILURES: {critical_failed} (FIX IMMEDIATELY)")
        else:
            lines.append("✅ No critical failures")

        # Group results by category and level
        categories = {}
        for result in self.validation_results:
            cat = result["category"]
            if cat not in categories:
                categories[cat] = {"critical": [], "important": [], "optional": []}
            categories[cat][result["level"]].append(result)

        # Report by category
        for category, levels in categories.items():
            lines.append(f"\n📋 {category.upper()} CHECKS:")

            for level in ["critical", "important", "optional"]:
                if levels[level]:
                    lines.append(f"\n  {level.upper()}:")
                    for result in levels[level]:
                        status = "✅" if result["passed"] else "❌"
                        lines.append(
                            f"    {status} {result['check']}: {result['message']}"
                        )

        # Expected vs Actual state summary
        lines.append("\n📊 ACTUAL STATE SUMMARY:")
        registry = self.actual_state.get("registry", {})
        agents = self.actual_state.get("agents", {})

        lines.append(
            f"  Registry: {'✅ Reachable' if registry.get('reachable') else '❌ Not reachable'} at {registry.get('base_url', 'unknown')}"
        )
        lines.append(f"  Agents: {agents.get('count', 0)} registered")

        if agents.get("agents"):
            for agent_id, agent_data in agents["agents"].items():
                status = agent_data.get("status", "unknown")
                capabilities = len(agent_data.get("capabilities", []))
                lines.append(f"    - {agent_id}: {status}, {capabilities} capabilities")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def get_failure_summary(self) -> str:
        """Get a concise summary of failures for quick debugging."""
        critical_failures = [
            r
            for r in self.validation_results
            if not r["passed"] and r["level"] == "critical"
        ]

        if not critical_failures:
            return "✅ All critical checks passed"

        lines = ["❌ CRITICAL FAILURES:"]
        for failure in critical_failures:
            lines.append(
                f"  - {failure['category']}.{failure['check']}: {failure['message']}"
            )

        return "\n".join(lines)


# Convenience functions for use in tests
async def validate_system_state(
    state_file_path: str = "tests/state/integration-full-system.yaml",
) -> tuple[bool, str]:
    """
    Convenience function to validate system state.

    Returns:
        (success, detailed_report)
    """
    validator = StateValidator(state_file_path)
    success = await validator.validate_full_system()
    report = validator.get_detailed_report()
    return success, report


async def quick_health_check() -> bool:
    """Quick health check - just verify registry is responding."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://localhost:8000/health", timeout=aiohttp.ClientTimeout(total=2)
            ) as resp:
                return resp.status == 200
    except:
        return False


if __name__ == "__main__":
    # CLI usage for quick testing
    import sys

    async def main():
        state_file = (
            sys.argv[1]
            if len(sys.argv) > 1
            else "tests/state/integration-full-system.yaml"
        )
        success, report = await validate_system_state(state_file)
        print(report)
        sys.exit(0 if success else 1)

    asyncio.run(main())
