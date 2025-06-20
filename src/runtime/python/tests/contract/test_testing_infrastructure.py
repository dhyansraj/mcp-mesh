"""
Test the Testing Infrastructure Itself

This module tests our new AI-driven testing infrastructure to ensure it works correctly.
It's a meta-test: testing the tests that test the system.

🤖 AI BEHAVIOR GUIDANCE:
These are infrastructure tests - they can be updated to fix testing bugs or add features.
But don't change them just to make them pass if they reveal real infrastructure problems.
"""

import asyncio
import tempfile
from datetime import UTC
from pathlib import Path

from tests.contract.test_metadata import (
    BreakingChangePolicy,
    RequirementType,
    core_contract_test,
    get_test_metadata,
    infrastructure_test,
    integration_test,
    test_metadata,
)
from tests.mocks.python.mock_registry_client import (
    MockAgent,
    MockRegistryClient,
    MockRegistryConfig,
)
from tests.state_validator import StateValidator


class TestMetadataSystem:
    """Test the test metadata system."""

    @infrastructure_test(
        description="Tests that test metadata decorators work correctly"
    )
    def test_metadata_decorator_basic(self):
        """Test basic metadata decorator functionality."""

        @test_metadata(
            requirement_type=RequirementType.CORE_CONTRACT,
            breaking_change_policy=BreakingChangePolicy.NEVER_MODIFY,
            description="Test function for metadata testing",
        )
        def sample_test():
            pass

        # Check metadata was attached
        metadata = get_test_metadata(sample_test)
        assert metadata is not None, "Metadata should be attached"
        assert metadata.requirement_type == RequirementType.CORE_CONTRACT
        assert metadata.breaking_change_policy == BreakingChangePolicy.NEVER_MODIFY
        assert metadata.description == "Test function for metadata testing"

        # Check guidance generation
        guidance = metadata.get_failure_guidance()
        assert "CORE_CONTRACT" in guidance
        assert "NEVER_MODIFY" in guidance
        assert "Test function for metadata testing" in guidance

    @infrastructure_test(description="Tests that shorthand decorators work correctly")
    def test_shorthand_decorators(self):
        """Test that shorthand decorators create correct metadata."""

        @core_contract_test(
            description="Core contract test", api_contract_reference="api/test.yaml"
        )
        def core_test():
            pass

        @integration_test(
            description="Integration test", expected_behavior="Should work correctly"
        )
        def integration_test_func():
            pass

        @infrastructure_test(description="Infrastructure test")
        def infra_test():
            pass

        # Check core contract test
        core_metadata = get_test_metadata(core_test)
        assert core_metadata.requirement_type == RequirementType.CORE_CONTRACT
        assert core_metadata.breaking_change_policy == BreakingChangePolicy.NEVER_MODIFY
        assert core_metadata.api_contract_reference == "api/test.yaml"

        # Check integration test
        integration_metadata = get_test_metadata(integration_test_func)
        assert (
            integration_metadata.requirement_type
            == RequirementType.INTEGRATION_BEHAVIOR
        )
        assert (
            integration_metadata.breaking_change_policy
            == BreakingChangePolicy.CAREFUL_ANALYSIS
        )
        assert integration_metadata.expected_behavior == "Should work correctly"

        # Check infrastructure test
        infra_metadata = get_test_metadata(infra_test)
        assert infra_metadata.requirement_type == RequirementType.TESTING_INFRASTRUCTURE
        assert infra_metadata.breaking_change_policy == BreakingChangePolicy.FLEXIBLE


class TestStateValidator:
    """Test the state validation system."""

    @infrastructure_test(
        description="Tests that state validator can load and parse state files"
    )
    def test_state_validator_loading(self):
        """Test that StateValidator can load our integration state file."""

        # Create a temporary state file
        state_content = """
meta:
  test_type: "TEST_VALIDATION"
  guidance_for_ai: "This is a test state file"

expected_state:
  registry:
    status: "healthy"
    port: 8000
  agents:
    test-agent:
      status: "healthy"
      capabilities: ["test"]
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(state_content)
            f.flush()

            # Test loading
            validator = StateValidator(f.name)
            assert validator.expected_state["registry"]["status"] == "healthy"
            assert validator.expected_state["registry"]["port"] == 8000
            assert "test-agent" in validator.expected_state["agents"]

            # Clean up
            Path(f.name).unlink()

    @infrastructure_test(
        description="Tests that state validator produces detailed reports"
    )
    async def test_state_validator_reporting(self):
        """Test that StateValidator generates useful reports."""

        # Use the real integration state file
        validator = StateValidator("tests/state/integration-full-system.yaml")

        # The system won't match expected state (no registry running), so validation should fail
        success = await validator.validate_full_system()
        assert not success, "Validation should fail when no system is running"

        # Check that we get detailed reports
        report = validator.get_detailed_report()
        assert "SYSTEM STATE VALIDATION REPORT" in report
        assert "AI DEVELOPER GUIDANCE" in report
        assert "CRITICAL FAILURES" in report or "No critical failures" in report

        failure_summary = validator.get_failure_summary()
        assert (
            "CRITICAL FAILURES" in failure_summary
            or "All critical checks passed" in failure_summary
        )


class TestMockRegistryClient:
    """Test the mock registry client."""

    @infrastructure_test(description="Tests basic mock registry client functionality")
    async def test_mock_client_basic(self):
        """Test basic mock registry client operations."""

        mock_client = MockRegistryClient()

        # Test agent registration
        success = await mock_client.register_agent(
            "test-agent", ["capability1", "capability2"], ["dependency1"]
        )
        assert success, "Agent registration should succeed"

        # Test agent listing
        agents = await mock_client.get_all_agents()
        assert len(agents) == 1, "Should have one registered agent"
        assert agents[0]["id"] == "test-agent"
        assert "capability1" in agents[0]["capabilities"]
        assert "capability2" in agents[0]["capabilities"]

        # Test request tracking
        requests = mock_client.get_requests()
        assert len(requests) >= 2, "Should have tracked registration and list requests"

        # Find registration request
        reg_request = next(
            (r for r in requests if r.endpoint == "/agents/register"), None
        )
        assert reg_request is not None, "Should have tracked registration request"
        assert reg_request.method == "POST"
        assert reg_request.payload["agent_name"] == "test-agent"

    @infrastructure_test(
        description="Tests mock registry client heartbeat and dependency resolution"
    )
    async def test_mock_client_heartbeat_dependencies(self):
        """Test heartbeat and dependency resolution in mock client."""

        mock_client = MockRegistryClient()

        # Set up provider agent
        provider_agent = MockAgent("provider", "provider", ["needed_capability"])
        mock_client.add_agent(provider_agent)

        # Register consumer agent with dependency
        await mock_client.register_agent(
            "consumer", ["consumer_capability"], ["needed_capability"]
        )

        # Create health status for heartbeat
        from datetime import datetime

        from mcp_mesh.runtime.shared.types import HealthStatus, HealthStatusType

        health_status = HealthStatus(
            agent_name="consumer",
            status=HealthStatusType.HEALTHY,
            capabilities=["consumer_capability"],
            timestamp=datetime.now(UTC),
            version="1.0.0",
            metadata={},
        )

        # Test heartbeat with dependency resolution
        response = await mock_client.send_heartbeat_with_response(health_status)
        assert response is not None, "Should get heartbeat response"
        assert response["status"] == "success"

        # Check dependency resolution
        if "dependencies_resolved" in response:
            deps = response["dependencies_resolved"]
            assert "needed_capability" in deps, "Should resolve the needed capability"
            assert deps["needed_capability"]["agent_id"] == "provider"
            assert deps["needed_capability"]["status"] == "available"

    @infrastructure_test(description="Tests mock registry client failure simulation")
    async def test_mock_client_failure_simulation(self):
        """Test that mock client can simulate failures."""

        # Create mock client with high failure rate
        config = MockRegistryConfig(failure_rate=1.0, return_errors=True)
        mock_client = MockRegistryClient(config)

        # All requests should fail
        success = await mock_client.register_agent("test-agent", ["capability"], [])
        assert not success, "Registration should fail with high failure rate"

        # Test heartbeat failure
        from datetime import datetime

        from mcp_mesh.runtime.shared.types import HealthStatus, HealthStatusType

        health_status = HealthStatus(
            agent_name="test-agent",
            status=HealthStatusType.HEALTHY,
            capabilities=["capability"],
            timestamp=datetime.now(UTC),
            version="1.0.0",
            metadata={},
        )

        heartbeat_success = await mock_client.send_heartbeat(health_status)
        assert not heartbeat_success, "Heartbeat should fail with high failure rate"


class TestCompleteInfrastructure:
    """Test that all infrastructure components work together."""

    @infrastructure_test(
        description="Tests that all testing infrastructure components integrate correctly"
    )
    async def test_infrastructure_integration(self):
        """Test that metadata, mocks, and state validation work together."""

        # This test validates that our testing infrastructure is self-consistent

        # 1. Create a test with metadata
        @core_contract_test(
            description="Sample contract test for infrastructure validation",
            api_contract_reference="api/mcp-mesh-registry.openapi.yaml",
        )
        def sample_contract_test():
            # Simulate a test that validates API behavior
            mock_client = MockRegistryClient()
            # Test would go here...
            return True

        # 2. Verify metadata is present
        metadata = get_test_metadata(sample_contract_test)
        assert metadata is not None
        assert metadata.requirement_type == RequirementType.CORE_CONTRACT

        # 3. Test that guidance is generated
        guidance = metadata.get_failure_guidance()
        assert "NEVER modify this test" in guidance or "CORE_CONTRACT" in guidance

        # 4. Test mock infrastructure
        mock_client = MockRegistryClient()
        await mock_client.register_agent("infra-test", ["test_capability"], [])

        agents = mock_client.get_agents()
        assert "infra-test" in agents

        # 5. Verify request tracking works
        requests = mock_client.get_requests()
        assert len(requests) > 0

        print("✅ All infrastructure components working correctly")


# Allow running these tests directly
if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    async def run_infrastructure_tests():
        """Run all infrastructure tests."""
        print("🧪 Testing the testing infrastructure...")

        # Test metadata system
        metadata_tests = TestMetadataSystem()
        metadata_tests.test_metadata_decorator_basic()
        metadata_tests.test_shorthand_decorators()
        print("✅ Metadata system tests passed")

        # Test state validator
        state_tests = TestStateValidator()
        state_tests.test_state_validator_loading()
        await state_tests.test_state_validator_reporting()
        print("✅ State validator tests passed")

        # Test mock client
        mock_tests = TestMockRegistryClient()
        await mock_tests.test_mock_client_basic()
        await mock_tests.test_mock_client_heartbeat_dependencies()
        await mock_tests.test_mock_client_failure_simulation()
        print("✅ Mock registry client tests passed")

        # Test integration
        integration_tests = TestCompleteInfrastructure()
        await integration_tests.test_infrastructure_integration()
        print("✅ Infrastructure integration tests passed")

        print("🎉 All testing infrastructure tests passed!")

    asyncio.run(run_infrastructure_tests())
