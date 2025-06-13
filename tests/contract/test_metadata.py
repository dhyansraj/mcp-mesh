"""
Test Metadata System for AI-Driven Development

This module provides decorators and utilities for embedding AI behavior guidance
directly into test code. This creates a "conversation" between current and future
AI developers about test intent and modification policies.

🤖 AI CRITICAL GUIDANCE:
This is the CORE of our AI-driven development pattern.
NEVER modify this system to make tests pass - it's designed to guide you!

The metadata decorators tell you:
- Whether a test should NEVER be modified (CORE_CONTRACT)
- When you can update tests (FLEXIBLE, EVOLVING)
- What to do when tests fail (fix code vs discuss with user)

USAGE PATTERN:
@test_metadata(
    requirement_type="CORE_CONTRACT",
    breaking_change_policy="NEVER_MODIFY",
    description="Validates core API contract - absolutely critical"
)
def test_critical_api_behavior():
    # Test that should never change
    pass
"""

import functools
import logging
import time
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

# Type for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


class RequirementType(Enum):
    """Classification of test requirements."""

    CORE_CONTRACT = "CORE_CONTRACT"  # API contracts, never change
    INTEGRATION_BEHAVIOR = "INTEGRATION_BEHAVIOR"  # System behavior, rarely change
    BUSINESS_LOGIC = "BUSINESS_LOGIC"  # Feature logic, may change
    TESTING_INFRASTRUCTURE = "TESTING_INFRASTRUCTURE"  # Test utilities, flexible
    PERFORMANCE = "PERFORMANCE"  # Performance benchmarks
    COMPATIBILITY = "COMPATIBILITY"  # Backward compatibility
    EVOLVING_FEATURE = "EVOLVING_FEATURE"  # New features under development


class BreakingChangePolicy(Enum):
    """Policy for handling test failures and modifications."""

    NEVER_MODIFY = "NEVER_MODIFY"  # Never change without user approval
    DISCUSS_WITH_USER = "DISCUSS_WITH_USER"  # Ask user before changing
    CAREFUL_ANALYSIS = "CAREFUL_ANALYSIS"  # Analyze carefully, may update
    FLEXIBLE = "FLEXIBLE"  # Can update with code changes
    EVOLVING = "EVOLVING"  # Expected to change frequently


class AIBehaviorGuide:
    """
    Guidance for AI behavior when tests fail.

    This class contains the "wisdom" that we want to pass to future AI sessions.
    """

    GUIDANCE_BY_REQUIREMENT = {
        RequirementType.CORE_CONTRACT: {
            "when_test_fails": [
                "🚨 STOP: This test validates a CORE API CONTRACT",
                "DO NOT modify this test to make it pass",
                "Your code likely broke the API contract",
                "Check: api/mcp-mesh-registry.openapi.yaml for the expected contract",
                "If you must change the API, discuss with user first",
            ],
            "when_to_modify": [
                "ONLY when user explicitly approves API changes",
                "ONLY when OpenAPI spec is updated with user approval",
                "NEVER to make failing tests pass",
            ],
        },
        RequirementType.INTEGRATION_BEHAVIOR: {
            "when_test_fails": [
                "This test validates system integration behavior",
                "Check if your changes broke expected system interactions",
                "Compare actual vs expected state carefully",
                "Look at tests/state/*.yaml for expected behavior",
            ],
            "when_to_modify": [
                "When user changes system requirements",
                "When integration patterns evolve with user approval",
                "After careful analysis of the failure",
            ],
        },
        RequirementType.BUSINESS_LOGIC: {
            "when_test_fails": [
                "This test validates business logic",
                "Check if your changes altered intended behavior",
                "Consider if the test reflects outdated requirements",
            ],
            "when_to_modify": [
                "When business requirements change",
                "When user clarifies different intended behavior",
                "After confirming the logic change is intentional",
            ],
        },
        RequirementType.TESTING_INFRASTRUCTURE: {
            "when_test_fails": [
                "This is a testing infrastructure component",
                "These can usually be updated to support new requirements",
                "But don't change just to hide real problems",
            ],
            "when_to_modify": [
                "When extending test capabilities",
                "When fixing test infrastructure bugs",
                "When adapting to new testing patterns",
            ],
        },
        RequirementType.EVOLVING_FEATURE: {
            "when_test_fails": [
                "This test is for an evolving feature",
                "Changes are expected as the feature develops",
                "But make sure the failure isn't a real bug",
            ],
            "when_to_modify": [
                "When feature requirements evolve",
                "When implementing new capabilities",
                "After confirming the change is intentional",
            ],
        },
    }

    POLICY_GUIDANCE = {
        BreakingChangePolicy.NEVER_MODIFY: {
            "action": "NEVER modify without explicit user approval",
            "escalation": "Discuss with user immediately if test fails",
        },
        BreakingChangePolicy.DISCUSS_WITH_USER: {
            "action": "Ask user before making any modifications",
            "escalation": "Explain why the test is failing and get guidance",
        },
        BreakingChangePolicy.CAREFUL_ANALYSIS: {
            "action": "Analyze the failure carefully before deciding",
            "escalation": "Document your analysis and reasoning",
        },
        BreakingChangePolicy.FLEXIBLE: {
            "action": "Can update if the change is clearly justified",
            "escalation": "Document why the change was necessary",
        },
        BreakingChangePolicy.EVOLVING: {
            "action": "Expected to change frequently during development",
            "escalation": "Update as needed but track significant changes",
        },
    }


class TestMetadata:
    """Stores metadata about a test."""

    def __init__(
        self,
        requirement_type: RequirementType,
        breaking_change_policy: BreakingChangePolicy,
        description: str,
        related_files: list[str] = None,
        api_contract_reference: str = None,
        last_updated: str = None,
        created_by: str = None,
        tags: list[str] = None,
        expected_behavior: str = None,
        failure_analysis_notes: str = None,
    ):
        self.requirement_type = requirement_type
        self.breaking_change_policy = breaking_change_policy
        self.description = description
        self.related_files = related_files or []
        self.api_contract_reference = api_contract_reference
        self.last_updated = last_updated or datetime.now().isoformat()
        self.created_by = created_by or "AI_DEVELOPER"
        self.tags = tags or []
        self.expected_behavior = expected_behavior
        self.failure_analysis_notes = failure_analysis_notes

        # Generate guidance
        self.ai_guidance = self._generate_ai_guidance()

    def _generate_ai_guidance(self) -> dict[str, Any]:
        """Generate AI guidance based on metadata."""
        requirement_guidance = AIBehaviorGuide.GUIDANCE_BY_REQUIREMENT.get(
            self.requirement_type, {}
        )
        policy_guidance = AIBehaviorGuide.POLICY_GUIDANCE.get(
            self.breaking_change_policy, {}
        )

        return {
            "requirement_type": self.requirement_type.value,
            "breaking_change_policy": self.breaking_change_policy.value,
            "when_test_fails": requirement_guidance.get("when_test_fails", []),
            "when_to_modify": requirement_guidance.get("when_to_modify", []),
            "policy_action": policy_guidance.get("action", ""),
            "escalation": policy_guidance.get("escalation", ""),
            "api_contract_reference": self.api_contract_reference,
            "related_files": self.related_files,
        }

    def get_failure_guidance(self) -> str:
        """Get formatted guidance for when this test fails."""
        lines = []
        lines.append("🤖 TEST FAILURE GUIDANCE:")
        lines.append("=" * 50)
        lines.append(f"Test Type: {self.requirement_type.value}")
        lines.append(f"Change Policy: {self.breaking_change_policy.value}")
        lines.append(f"Description: {self.description}")
        lines.append("")

        lines.append("WHEN THIS TEST FAILS:")
        for guidance in self.ai_guidance["when_test_fails"]:
            lines.append(f"  • {guidance}")
        lines.append("")

        lines.append("WHEN TO MODIFY THIS TEST:")
        for guidance in self.ai_guidance["when_to_modify"]:
            lines.append(f"  • {guidance}")
        lines.append("")

        lines.append(f"POLICY: {self.ai_guidance['policy_action']}")
        if self.ai_guidance["escalation"]:
            lines.append(f"ESCALATION: {self.ai_guidance['escalation']}")

        if self.api_contract_reference:
            lines.append(f"API CONTRACT: {self.api_contract_reference}")

        if self.related_files:
            lines.append(f"RELATED FILES: {', '.join(self.related_files)}")

        if self.expected_behavior:
            lines.append("")
            lines.append("EXPECTED BEHAVIOR:")
            lines.append(f"  {self.expected_behavior}")

        lines.append("=" * 50)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "requirement_type": self.requirement_type.value,
            "breaking_change_policy": self.breaking_change_policy.value,
            "description": self.description,
            "related_files": self.related_files,
            "api_contract_reference": self.api_contract_reference,
            "last_updated": self.last_updated,
            "created_by": self.created_by,
            "tags": self.tags,
            "expected_behavior": self.expected_behavior,
            "failure_analysis_notes": self.failure_analysis_notes,
            "ai_guidance": self.ai_guidance,
        }


def test_metadata(
    requirement_type: RequirementType | str,
    breaking_change_policy: BreakingChangePolicy | str = None,
    description: str = "",
    related_files: list[str] = None,
    api_contract_reference: str = None,
    expected_behavior: str = None,
    **kwargs,
) -> Callable[[F], F]:
    """
    Decorator to add AI behavior metadata to tests.

    🤖 AI CRITICAL PATTERN:
    This decorator embeds guidance directly into test functions.
    When tests fail, check function._test_metadata.get_failure_guidance()

    Usage:
    @test_metadata(
        requirement_type=RequirementType.CORE_CONTRACT,
        breaking_change_policy=BreakingChangePolicy.NEVER_MODIFY,
        description="Validates agent registration API contract",
        api_contract_reference="api/mcp-mesh-registry.openapi.yaml#/paths/~1agents~1register"
    )
    def test_agent_registration_contract():
        # Test code here
        pass
    """

    def decorator(func: F) -> F:
        # Convert string enums if necessary
        req_type = (
            requirement_type
            if isinstance(requirement_type, RequirementType)
            else RequirementType(requirement_type)
        )
        policy = (
            breaking_change_policy
            if isinstance(breaking_change_policy, BreakingChangePolicy)
            else BreakingChangePolicy(breaking_change_policy or "DISCUSS_WITH_USER")
        )

        # Create metadata
        metadata = TestMetadata(
            requirement_type=req_type,
            breaking_change_policy=policy,
            description=description,
            related_files=related_files,
            api_contract_reference=api_contract_reference,
            expected_behavior=expected_behavior,
            **kwargs,
        )

        # Attach metadata to function
        func._test_metadata = metadata

        # Create wrapper that provides guidance on failure
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Add guidance to exception
                guidance = metadata.get_failure_guidance()

                # Log guidance
                logger = logging.getLogger(func.__module__)
                logger.error(f"Test failure in {func.__name__}:")
                logger.error(guidance)

                # Re-raise with enhanced message
                enhanced_msg = f"{str(e)}\n\n{guidance}"
                e.args = (enhanced_msg,) + e.args[1:]
                raise

        return wrapper

    return decorator


def get_test_metadata(func: Callable) -> TestMetadata | None:
    """Get metadata from a test function."""
    return getattr(func, "_test_metadata", None)


def core_contract_test(
    description: str, api_contract_reference: str = None, **kwargs
) -> Callable[[F], F]:
    """
    Shorthand decorator for core contract tests.

    🤖 AI PATTERN: Use this for tests that should NEVER change without user approval.
    These typically validate API contracts, data formats, or critical behaviors.
    """
    return test_metadata(
        requirement_type=RequirementType.CORE_CONTRACT,
        breaking_change_policy=BreakingChangePolicy.NEVER_MODIFY,
        description=description,
        api_contract_reference=api_contract_reference,
        **kwargs,
    )


def integration_test(
    description: str, expected_behavior: str = None, **kwargs
) -> Callable[[F], F]:
    """
    Shorthand decorator for integration tests.

    🤖 AI PATTERN: Use this for tests that validate system interactions.
    These can be updated when system behavior changes, but require careful analysis.
    """
    return test_metadata(
        requirement_type=RequirementType.INTEGRATION_BEHAVIOR,
        breaking_change_policy=BreakingChangePolicy.CAREFUL_ANALYSIS,
        description=description,
        expected_behavior=expected_behavior,
        **kwargs,
    )


def evolving_feature_test(description: str, **kwargs) -> Callable[[F], F]:
    """
    Shorthand decorator for evolving feature tests.

    🤖 AI PATTERN: Use this for tests of features under active development.
    These are expected to change frequently as requirements evolve.
    """
    return test_metadata(
        requirement_type=RequirementType.EVOLVING_FEATURE,
        breaking_change_policy=BreakingChangePolicy.EVOLVING,
        description=description,
        **kwargs,
    )


def infrastructure_test(description: str, **kwargs) -> Callable[[F], F]:
    """
    Shorthand decorator for testing infrastructure.

    🤖 AI PATTERN: Use this for mocks, utilities, and test helpers.
    These are flexible and can be updated to support new testing needs.
    """
    return test_metadata(
        requirement_type=RequirementType.TESTING_INFRASTRUCTURE,
        breaking_change_policy=BreakingChangePolicy.FLEXIBLE,
        description=description,
        **kwargs,
    )


# Test discovery and reporting utilities


def analyze_test_file(file_path: str) -> dict[str, Any]:
    """Analyze a test file and extract metadata from all tests."""
    import ast

    with open(file_path) as f:
        content = f.read()

    tree = ast.parse(content)
    test_info = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            # Look for test_metadata decorator
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "test_metadata"
                ):

                    # Extract decorator arguments
                    metadata_info = {
                        "function_name": node.name,
                        "line_number": node.lineno,
                        "decorator_args": {},
                    }

                    # Parse decorator arguments
                    for keyword in decorator.keywords:
                        if isinstance(keyword.value, ast.Constant):
                            metadata_info["decorator_args"][
                                keyword.arg
                            ] = keyword.value.value

                    test_info.append(metadata_info)

    return {
        "file_path": file_path,
        "tests": test_info,
        "total_tests": len(test_info),
        "analysis_timestamp": datetime.now().isoformat(),
    }


def generate_test_metadata_report(test_directory: str = "tests/") -> dict[str, Any]:
    """Generate a comprehensive report of all test metadata."""
    import glob
    import os

    report = {
        "generated_at": datetime.now().isoformat(),
        "files_analyzed": [],
        "summary": {
            "total_files": 0,
            "total_tests": 0,
            "by_requirement_type": {},
            "by_change_policy": {},
        },
    }

    # Find all test files
    test_files = glob.glob(os.path.join(test_directory, "**/test_*.py"), recursive=True)

    for test_file in test_files:
        try:
            file_analysis = analyze_test_file(test_file)
            report["files_analyzed"].append(file_analysis)
            report["summary"]["total_files"] += 1
            report["summary"]["total_tests"] += file_analysis["total_tests"]
        except Exception:
            # Skip files that can't be analyzed
            continue

    return report


# Context manager for test execution with enhanced error reporting


class TestExecutionContext:
    """Context manager that provides enhanced error reporting for metadata-decorated tests."""

    def __init__(self, test_func: Callable):
        self.test_func = test_func
        self.metadata = get_test_metadata(test_func)
        self.start_time = None
        self.logger = logging.getLogger(test_func.__module__)

    def __enter__(self):
        self.start_time = time.time()
        if self.metadata:
            self.logger.info(
                f"Executing {self.metadata.requirement_type.value} test: {self.test_func.__name__}"
            )
            self.logger.debug(f"Description: {self.metadata.description}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time

        if exc_type is None:
            # Test passed
            if self.metadata:
                self.logger.info(
                    f"✅ Test passed: {self.test_func.__name__} ({duration:.2f}s)"
                )
        else:
            # Test failed
            if self.metadata:
                self.logger.error(
                    f"❌ Test failed: {self.test_func.__name__} ({duration:.2f}s)"
                )
                self.logger.error(self.metadata.get_failure_guidance())

        # Don't suppress exceptions
        return False


def run_with_metadata_context(test_func: Callable):
    """Run a test function with metadata context for enhanced error reporting."""
    with TestExecutionContext(test_func):
        return test_func()


# 🤖 AI USAGE EXAMPLES:
#
# CORE CONTRACT TEST (NEVER MODIFY):
# @core_contract_test(
#     description="Validates agent registration API returns correct response format",
#     api_contract_reference="api/mcp-mesh-registry.openapi.yaml#/components/schemas/RegistrationResponse"
# )
# def test_agent_registration_response_format():
#     # This test should NEVER be modified without user approval
#     pass
#
# INTEGRATION TEST (CAREFUL ANALYSIS):
# @integration_test(
#     description="Validates full agent registration and heartbeat flow",
#     expected_behavior="Agent registers successfully and maintains heartbeat"
# )
# def test_full_agent_lifecycle():
#     # This test can be updated when system behavior changes, but needs analysis
#     pass
#
# EVOLVING FEATURE TEST (EXPECTED TO CHANGE):
# @evolving_feature_test(
#     description="Tests new multi-tool agent registration feature"
# )
# def test_multi_tool_registration():
#     # This test is expected to change as the feature develops
#     pass
#
# INFRASTRUCTURE TEST (FLEXIBLE):
# @infrastructure_test(
#     description="Tests mock registry client functionality"
# )
# def test_mock_registry_client():
#     # This test can be updated to support new testing needs
#     pass
