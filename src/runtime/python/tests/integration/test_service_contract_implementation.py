"""Integration tests for ServiceContract storage and retrieval operations.

Tests the complete implementation of Phase 1: Registry Schema Enhancement requirements
including storage, retrieval, validation, and performance requirements.
"""

import asyncio
import inspect
import time
from datetime import UTC, datetime

import pytest
from mcp_mesh_runtime.method_metadata import MethodMetadata, MethodType, ServiceContract

from src.mcp_mesh.server.database import DatabaseConfig, RegistryDatabase
from src.mcp_mesh.tools.contract_tools import ContractTools


class TestServiceContractImplementation:
    """Test the complete ServiceContract implementation."""

    @pytest.fixture
    async def database(self, tmp_path):
        """Create a test database."""
        db_path = tmp_path / "test_registry.db"
        config = DatabaseConfig(database_path=str(db_path))
        database = RegistryDatabase(config)
        await database.initialize()
        yield database
        await database.close()

    @pytest.fixture
    async def contract_tools(self, database):
        """Create ContractTools instance."""
        return ContractTools(database)

    @pytest.fixture
    def sample_method_metadata(self):
        """Create sample method metadata for testing."""

        def sample_method(name: str, age: int = 25) -> str:
            """Sample method for testing."""
            return f"Hello {name}, age {age}"

        signature = inspect.signature(sample_method)

        metadata = MethodMetadata(
            method_name="sample_method",
            signature=signature,
            capabilities=["greeting", "user_interaction"],
            return_type=str,
            method_type=MethodType.FUNCTION,
            is_async=False,
            docstring="Sample method for testing.",
            service_version="1.0.0",
            stability_level="stable",
            expected_complexity="O(1)",
            timeout_hint=30,
        )

        return metadata

    @pytest.fixture
    def sample_service_contract(self, sample_method_metadata):
        """Create sample service contract for testing."""
        contract = ServiceContract(
            service_name="test_service",
            service_version="1.0.0",
            description="Test service contract",
            contract_version="1.0.0",
            compatibility_level="strict",
        )
        contract.add_method(sample_method_metadata)
        return contract

    @pytest.mark.asyncio
    async def test_store_service_contract_performance(
        self, contract_tools, sample_method_metadata
    ):
        """Test store_service_contract meets <100ms performance requirement."""

        class TestClass:
            pass

        # Warm up
        await contract_tools.store_service_contract(TestClass, sample_method_metadata)

        # Measure performance
        start_time = time.time()
        result = await contract_tools.store_service_contract(
            TestClass, sample_method_metadata
        )
        duration_ms = (time.time() - start_time) * 1000

        assert result.success, f"Storage failed: {result.error}"
        assert (
            duration_ms < 100
        ), f"Storage took {duration_ms:.2f}ms, exceeds 100ms requirement"
        assert result.contract_id is not None, "Contract ID should be returned"

    @pytest.mark.asyncio
    async def test_get_service_contract_performance(
        self, contract_tools, sample_method_metadata
    ):
        """Test get_service_contract meets <100ms performance requirement."""

        class TestClass:
            pass

        # Store a contract first
        store_result = await contract_tools.store_service_contract(
            TestClass, sample_method_metadata
        )
        assert store_result.success

        # Measure retrieval performance
        start_time = time.time()
        contract = await contract_tools.get_service_contract(TestClass)
        duration_ms = (time.time() - start_time) * 1000

        assert contract is not None, "Contract should be retrieved"
        assert (
            duration_ms < 100
        ), f"Retrieval took {duration_ms:.2f}ms, exceeds 100ms requirement"
        assert contract.service_name == "testclass"
        assert len(contract.methods) > 0

    @pytest.mark.asyncio
    async def test_validate_contract_compatibility_performance(
        self, contract_tools, sample_service_contract
    ):
        """Test validate_contract_compatibility meets <100ms performance requirement."""
        # Measure validation performance
        start_time = time.time()
        result = await contract_tools.validate_contract_compatibility(
            sample_service_contract
        )
        duration_ms = (time.time() - start_time) * 1000

        assert (
            duration_ms < 100
        ), f"Validation took {duration_ms:.2f}ms, exceeds 100ms requirement"
        assert result.is_valid, f"Contract should be valid, issues: {result.issues}"
        assert (
            result.compatibility_score > 0.8
        ), f"Score too low: {result.compatibility_score}"

    @pytest.mark.asyncio
    async def test_contract_storage_and_retrieval_integration(
        self, contract_tools, sample_method_metadata
    ):
        """Test complete storage and retrieval workflow."""

        class TestService:
            def test_method(self, data: str) -> dict:
                return {"processed": data}

        # Store the contract
        store_result = await contract_tools.store_service_contract(
            TestService, sample_method_metadata
        )
        assert store_result.success, f"Storage failed: {store_result.error}"
        assert store_result.contract_id is not None

        # Retrieve the contract
        retrieved_contract = await contract_tools.get_service_contract(TestService)
        assert retrieved_contract is not None
        assert retrieved_contract.service_name == "testservice"
        assert sample_method_metadata.method_name in retrieved_contract.methods

        # Validate the retrieved contract
        validation_result = await contract_tools.validate_contract_compatibility(
            retrieved_contract
        )
        assert (
            validation_result.is_valid
        ), f"Retrieved contract invalid: {validation_result.issues}"

    @pytest.mark.asyncio
    async def test_contract_validation_with_issues(self, contract_tools):
        """Test contract validation identifies issues correctly."""
        # Create a contract with issues
        invalid_contract = ServiceContract(
            service_name="",  # Invalid: empty name
            service_version="1.0.0",
            description="Test contract with issues",
        )
        # No methods added - this should be flagged

        validation_result = await contract_tools.validate_contract_compatibility(
            invalid_contract
        )

        assert not validation_result.is_valid, "Contract with issues should be invalid"
        assert len(validation_result.issues) > 0, "Should identify validation issues"
        assert any("name" in issue.lower() for issue in validation_result.issues)
        assert any("method" in issue.lower() for issue in validation_result.issues)
        assert (
            validation_result.compatibility_score < 0.5
        ), "Score should reflect issues"

    @pytest.mark.asyncio
    async def test_find_contracts_by_capability(
        self, contract_tools, sample_method_metadata
    ):
        """Test finding contracts by capability."""

        class CapabilityService:
            pass

        # Store contract with specific capabilities
        store_result = await contract_tools.store_service_contract(
            CapabilityService, sample_method_metadata
        )
        assert store_result.success

        # Find contracts by capability
        contracts = await contract_tools.find_contracts_by_capability("greeting")
        assert len(contracts) > 0, "Should find contracts with greeting capability"

        # Verify the contract is in results
        found_names = [c.get("method_name") for c in contracts]
        assert "sample_method" in found_names

    @pytest.mark.asyncio
    async def test_contract_compatibility_info(
        self, contract_tools, sample_method_metadata
    ):
        """Test getting contract compatibility information."""

        class VersionService:
            pass

        # Store contract
        store_result = await contract_tools.store_service_contract(
            VersionService, sample_method_metadata
        )
        assert store_result.success

        # Get compatibility info
        info = await contract_tools.get_contract_compatibility_info("versionservice")
        assert len(info) > 0, "Should find compatibility information"

        # Verify information structure
        for item in info:
            assert "service_name" in item
            assert "service_version" in item
            assert "compatibility_level" in item

    @pytest.mark.asyncio
    async def test_multiple_method_contract(self, contract_tools):
        """Test storing and retrieving contracts with multiple methods."""

        class MultiMethodService:
            pass

        # Create multiple method metadata
        def method1(x: int) -> int:
            return x * 2

        def method2(name: str) -> str:
            return f"Hello {name}"

        metadata1 = MethodMetadata(
            method_name="method1",
            signature=inspect.signature(method1),
            capability="math",
            return_type=int,
        )

        metadata2 = MethodMetadata(
            method_name="method2",
            signature=inspect.signature(method2),
            capability="greeting",
            return_type=str,
        )

        # Store both methods
        result1 = await contract_tools.store_service_contract(
            MultiMethodService, metadata1
        )
        result2 = await contract_tools.store_service_contract(
            MultiMethodService, metadata2
        )

        assert result1.success and result2.success

        # Retrieve contract
        contract = await contract_tools.get_service_contract(MultiMethodService)
        assert contract is not None
        assert len(contract.methods) == 2
        assert "method1" in contract.methods
        assert "method2" in contract.methods
        assert set(contract.capabilities) == {"math", "greeting"}

    @pytest.mark.asyncio
    async def test_performance_metrics(self, contract_tools):
        """Test performance metrics functionality."""
        metrics = await contract_tools.get_performance_metrics()

        assert "database_stats" in metrics
        assert "contract_metrics" in metrics
        assert "timestamp" in metrics

        # Verify timestamp is recent
        timestamp = datetime.fromisoformat(metrics["timestamp"].replace("Z", "+00:00"))
        now = datetime.now(UTC)
        time_diff = abs((now - timestamp).total_seconds())
        assert time_diff < 60, "Timestamp should be recent"

    @pytest.mark.asyncio
    async def test_transaction_management(self, contract_tools, sample_method_metadata):
        """Test transaction management and error handling."""

        class TransactionService:
            pass

        # Create invalid metadata to trigger transaction rollback
        invalid_metadata = MethodMetadata(
            method_name="",  # Invalid empty name
            signature=inspect.signature(lambda: None),
        )

        # This should fail and rollback
        result = await contract_tools.store_service_contract(
            TransactionService, invalid_metadata
        )
        assert not result.success, "Invalid metadata should fail"

        # Verify no partial data was stored
        contract = await contract_tools.get_service_contract(TransactionService)
        assert contract is None, "No contract should exist after failed transaction"

        # Now store valid metadata
        valid_result = await contract_tools.store_service_contract(
            TransactionService, sample_method_metadata
        )
        assert valid_result.success, "Valid metadata should succeed"

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, contract_tools, sample_method_metadata):
        """Test concurrent contract operations."""

        class ConcurrentService:
            pass

        # Run multiple concurrent storage operations
        tasks = []
        for i in range(5):
            metadata = MethodMetadata(
                method_name=f"method_{i}",
                signature=inspect.signature(lambda x=i: x),
                capabilities=[f"capability_{i}"],
            )
            task = contract_tools.store_service_contract(ConcurrentService, metadata)
            tasks.append(task)

        # Wait for all operations to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify all operations succeeded
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                pytest.fail(f"Task {i} failed with exception: {result}")
            assert result.success, f"Task {i} failed: {result.error}"

        # Verify final contract has all methods
        final_contract = await contract_tools.get_service_contract(ConcurrentService)
        assert final_contract is not None
        assert len(final_contract.methods) == 5

    @pytest.mark.asyncio
    async def test_signature_consistency_validation(self, contract_tools):
        """Test signature consistency validation across methods."""
        # Create contract with inconsistent signatures for same capability
        contract = ServiceContract(
            service_name="inconsistent_service",
            service_version="1.0.0",
        )

        # Method 1: requires 'name' parameter
        def method1(name: str) -> str:
            return name

        metadata1 = MethodMetadata(
            method_name="method1",
            signature=inspect.signature(method1),
            capability="user_operation",
        )

        # Method 2: requires 'user_id' parameter (inconsistent)
        def method2(user_id: int) -> str:
            return str(user_id)

        metadata2 = MethodMetadata(
            method_name="method2",
            signature=inspect.signature(method2),
            capability="user_operation",
        )

        contract.add_method(metadata1)
        contract.add_method(metadata2)

        # Validation should detect inconsistency
        validation_result = await contract_tools.validate_contract_compatibility(
            contract
        )

        # Should identify parameter inconsistency
        assert (
            not validation_result.is_valid
            or validation_result.compatibility_score < 0.8
        )
        inconsistency_found = any(
            "parameter" in issue.lower() and "different" in issue.lower()
            for issue in validation_result.issues
        )
        assert (
            inconsistency_found
        ), f"Should detect parameter inconsistency, issues: {validation_result.issues}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
