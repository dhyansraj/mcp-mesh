#!/usr/bin/env python3
"""
Unit tests for Dynamic Class Generation functionality.

Tests the comprehensive proxy generation capabilities including:
- Type-preserving proxy creation
- Runtime type validation
- Method signature preservation
- IDE autocomplete support
- Contract validation
"""

import asyncio
import inspect
from dataclasses import dataclass
from typing import Optional, Union
from unittest.mock import Mock, patch

import pytest
from mcp_mesh import MethodMetadata, ServiceContract
from mcp_mesh.runtime.shared.registry_client import RegistryClient
from mcp_mesh.runtime.shared.service_proxy import MeshServiceProxy

# Test imports
from mcp_mesh.runtime.tools.proxy_factory import (
    DynamicProxyGenerator,
    EnhancedProxyFactory,
    TypeValidator,
    create_service_proxy,
    resolve_service_endpoint,
    round_trip_type_test,
    validate_proxy_compatibility,
)


# Test service classes
class SimpleService:
    """Simple service for testing basic functionality."""

    def get_value(self, key: str) -> str:
        """Get a value by key."""
        return f"value_for_{key}"

    def set_value(self, key: str, value: str) -> bool:
        """Set a value for a key."""
        return True

    async def async_operation(self, data: str) -> dict[str, str]:
        """Async operation for testing."""
        return {"result": data, "status": "completed"}


class ComplexService:
    """Service with complex type signatures."""

    def process_data(
        self,
        primary: dict[str, list[int]],
        secondary: list[str] | None = None,
        config: dict[str, str | int | bool] | None = None,
    ) -> dict[str, any]:
        """Complex method with optional parameters and union types."""
        return {
            "primary_keys": list(primary.keys()),
            "secondary_provided": secondary is not None,
            "config_provided": config is not None,
        }

    def union_params(self, value: str | int | list[str]) -> str:
        """Method with union parameter types."""
        return str(value)

    def optional_return(self, include_data: bool) -> dict[str, str] | None:
        """Method with optional return type."""
        if include_data:
            return {"data": "present"}
        return None


@dataclass
class TestDataClass:
    """Test dataclass for type validation."""

    name: str
    value: int
    tags: list[str]


class DataClassService:
    """Service using dataclass parameters."""

    def create_item(self, item: TestDataClass) -> TestDataClass:
        """Create an item using dataclass."""
        return item

    def list_items(self, filter_tags: list[str] | None = None) -> list[TestDataClass]:
        """List items with optional filtering."""
        items = [
            TestDataClass("item1", 100, ["tag1", "tag2"]),
            TestDataClass("item2", 200, ["tag2", "tag3"]),
        ]
        if filter_tags:
            items = [
                item for item in items if any(tag in item.tags for tag in filter_tags)
            ]
        return items


class TestTypeValidator:
    """Test the TypeValidator class."""

    def test_validate_basic_types(self):
        """Test validation of basic types."""
        # Valid cases
        assert TypeValidator.validate_type("hello", str, "test_param")
        assert TypeValidator.validate_type(42, int, "test_param")
        assert TypeValidator.validate_type(3.14, float, "test_param")
        assert TypeValidator.validate_type(True, bool, "test_param")
        assert TypeValidator.validate_type(None, type(None), "test_param")

        # Invalid cases
        with pytest.raises(TypeError):
            TypeValidator.validate_type("hello", int, "test_param")

        with pytest.raises(TypeError):
            TypeValidator.validate_type(42, str, "test_param")

    def test_validate_optional_types(self):
        """Test validation of Optional (Union with None) types."""
        optional_str = Optional[str]

        # Valid cases
        assert TypeValidator.validate_type("hello", optional_str, "test_param")
        assert TypeValidator.validate_type(None, optional_str, "test_param")

        # Invalid case
        with pytest.raises(TypeError):
            TypeValidator.validate_type(42, optional_str, "test_param")

    def test_validate_union_types(self):
        """Test validation of Union types."""
        union_type = Union[str, int, bool]

        # Valid cases
        assert TypeValidator.validate_type("hello", union_type, "test_param")
        assert TypeValidator.validate_type(42, union_type, "test_param")
        assert TypeValidator.validate_type(True, union_type, "test_param")

        # Invalid case
        with pytest.raises(TypeError):
            TypeValidator.validate_type(3.14, union_type, "test_param")

    def test_validate_list_types(self):
        """Test validation of List types."""
        list_str = list[str]

        # Valid cases
        assert TypeValidator.validate_type(["a", "b", "c"], list_str, "test_param")
        assert TypeValidator.validate_type([], list_str, "test_param")

        # Invalid cases
        with pytest.raises(TypeError):
            TypeValidator.validate_type("not_a_list", list_str, "test_param")

        with pytest.raises(TypeError):
            TypeValidator.validate_type([1, 2, 3], list_str, "test_param")

    def test_validate_dict_types(self):
        """Test validation of Dict types."""
        dict_str_int = dict[str, int]

        # Valid cases
        assert TypeValidator.validate_type({"a": 1, "b": 2}, dict_str_int, "test_param")
        assert TypeValidator.validate_type({}, dict_str_int, "test_param")

        # Invalid cases
        with pytest.raises(TypeError):
            TypeValidator.validate_type("not_a_dict", dict_str_int, "test_param")

        with pytest.raises(TypeError):
            TypeValidator.validate_type(
                {1: "wrong_key_type"}, dict_str_int, "test_param"
            )

        with pytest.raises(TypeError):
            TypeValidator.validate_type(
                {"a": "wrong_value_type"}, dict_str_int, "test_param"
            )

    def test_validate_method_args(self):
        """Test method argument validation."""
        signature = inspect.signature(ComplexService.process_data)
        metadata = MethodMetadata(
            method_name="process_data",
            signature=signature,
            type_hints={
                "primary": dict[str, list[int]],
                "secondary": Optional[list[str]],
                "config": Optional[dict[str, str | int | bool]],
            },
        )

        # Valid arguments
        args = ({"key1": [1, 2, 3]},)
        kwargs = {
            "secondary": ["a", "b"],
            "config": {"mode": "fast", "count": 10, "debug": True},
        }

        # Should not raise exception
        TypeValidator.validate_method_args(args, kwargs, metadata, "process_data")

        # Invalid arguments
        invalid_args = ("not_a_dict",)
        with pytest.raises(TypeError):
            TypeValidator.validate_method_args(
                invalid_args, {}, metadata, "process_data"
            )


class TestDynamicProxyGenerator:
    """Test the DynamicProxyGenerator class."""

    @pytest.fixture
    def mock_registry_client(self):
        """Create a mock registry client."""
        return Mock(spec=RegistryClient)

    @pytest.fixture
    def mock_base_proxy(self):
        """Create a mock base proxy."""
        proxy = Mock(spec=MeshServiceProxy)
        proxy.get_service_contract.return_value = ServiceContract(
            service_name="test_service",
            methods={
                "get_value": MethodMetadata(
                    method_name="get_value",
                    signature=inspect.signature(SimpleService.get_value),
                    type_hints={"key": str, "return": str},
                ),
                "set_value": MethodMetadata(
                    method_name="set_value",
                    signature=inspect.signature(SimpleService.set_value),
                    type_hints={"key": str, "value": str, "return": bool},
                ),
            },
        )
        return proxy

    @pytest.fixture
    def generator(self, mock_registry_client):
        """Create a DynamicProxyGenerator instance."""
        return DynamicProxyGenerator(mock_registry_client)

    def test_generate_proxy_class(self, generator, mock_base_proxy):
        """Test proxy class generation."""
        contract = mock_base_proxy.get_service_contract()

        proxy_class = generator.generate_proxy_class(
            SimpleService, contract, mock_base_proxy
        )

        # Check that the proxy class is created
        assert proxy_class is not None
        assert proxy_class.__name__ == "SimpleServiceProxy"

        # Check that methods are present
        assert hasattr(proxy_class, "get_value")
        assert hasattr(proxy_class, "set_value")

        # Check method signatures are preserved
        get_value_sig = inspect.signature(proxy_class.get_value)
        original_sig = inspect.signature(SimpleService.get_value)
        assert get_value_sig == original_sig

    def test_proxy_class_caching(self, generator, mock_base_proxy):
        """Test that proxy classes are cached."""
        contract = mock_base_proxy.get_service_contract()

        # Generate the same proxy class twice
        proxy_class1 = generator.generate_proxy_class(
            SimpleService, contract, mock_base_proxy
        )
        proxy_class2 = generator.generate_proxy_class(
            SimpleService, contract, mock_base_proxy
        )

        # Should be the same class object (cached)
        assert proxy_class1 is proxy_class2


class TestEnhancedProxyFactory:
    """Test the EnhancedProxyFactory class."""

    @pytest.fixture
    def mock_registry_client(self):
        """Create a mock registry client."""
        return Mock(spec=RegistryClient)

    @pytest.fixture
    def factory(self, mock_registry_client):
        """Create an EnhancedProxyFactory instance."""
        return EnhancedProxyFactory(mock_registry_client)

    @patch("mcp_mesh.tools.proxy_factory.MeshServiceProxy")
    def test_create_service_proxy(self, mock_mesh_proxy, factory):
        """Test service proxy creation."""
        # Setup mock base proxy
        mock_proxy_instance = Mock()
        mock_proxy_instance.get_service_contract.return_value = ServiceContract(
            service_name="simple_service",
            methods={
                "get_value": MethodMetadata(
                    method_name="get_value",
                    signature=inspect.signature(SimpleService.get_value),
                    type_hints={"key": str, "return": str},
                )
            },
        )
        mock_mesh_proxy.return_value = mock_proxy_instance

        # Create proxy
        proxy = factory.create_service_proxy(SimpleService)

        # Verify proxy is created
        assert proxy is not None
        assert hasattr(proxy, "get_value")

        # Verify MeshServiceProxy was called
        mock_mesh_proxy.assert_called_once()

    def test_resolve_service_endpoint(self, factory):
        """Test service endpoint resolution."""
        endpoint_info = factory.resolve_service_endpoint(SimpleService)

        assert endpoint_info is not None
        assert endpoint_info.service_name == "simpleservice"
        assert endpoint_info.url.startswith("mcp://")
        assert endpoint_info.protocol == "mcp"

    def test_resolve_custom_endpoint(self, factory):
        """Test resolution with custom endpoint configuration."""
        # Add custom endpoint to class
        SimpleService._proxy_endpoint = "mcp://custom-service:9090"

        try:
            endpoint_info = factory.resolve_service_endpoint(SimpleService)
            assert endpoint_info.url == "mcp://custom-service:9090"
        finally:
            # Clean up
            delattr(SimpleService, "_proxy_endpoint")

    def test_validate_proxy_compatibility(self, factory):
        """Test proxy compatibility validation."""
        # Create a mock proxy
        mock_proxy = Mock()
        mock_proxy.get_value = Mock()
        mock_proxy.set_value = Mock()

        # Set up method signatures
        mock_proxy.get_value.__signature__ = inspect.signature(SimpleService.get_value)
        mock_proxy.set_value.__signature__ = inspect.signature(SimpleService.set_value)

        # Create contract
        contract = ServiceContract(
            service_name="test_service",
            methods={
                "get_value": MethodMetadata(
                    method_name="get_value",
                    signature=inspect.signature(SimpleService.get_value),
                ),
                "set_value": MethodMetadata(
                    method_name="set_value",
                    signature=inspect.signature(SimpleService.set_value),
                ),
            },
        )

        # Should be compatible
        assert factory.validate_proxy_compatibility(mock_proxy, contract)

        # Test incompatible proxy (missing method)
        mock_proxy_incomplete = Mock()
        mock_proxy_incomplete.get_value = Mock()
        mock_proxy_incomplete.get_value.__signature__ = inspect.signature(
            SimpleService.get_value
        )
        # missing set_value

        assert not factory.validate_proxy_compatibility(mock_proxy_incomplete, contract)


class TestFactoryFunctions:
    """Test the module-level factory functions."""

    @patch("mcp_mesh.tools.proxy_factory.get_proxy_factory")
    def test_create_service_proxy(self, mock_get_factory):
        """Test the create_service_proxy function."""
        mock_factory = Mock()
        mock_factory.create_service_proxy.return_value = Mock()
        mock_get_factory.return_value = mock_factory

        proxy = create_service_proxy(SimpleService)

        assert proxy is not None
        mock_factory.create_service_proxy.assert_called_once_with(SimpleService)

    @patch("mcp_mesh.tools.proxy_factory.get_proxy_factory")
    def test_resolve_service_endpoint(self, mock_get_factory):
        """Test the resolve_service_endpoint function."""
        mock_factory = Mock()
        mock_endpoint = Mock()
        mock_factory.resolve_service_endpoint.return_value = mock_endpoint
        mock_get_factory.return_value = mock_factory

        endpoint = resolve_service_endpoint(SimpleService)

        assert endpoint is mock_endpoint
        mock_factory.resolve_service_endpoint.assert_called_once_with(SimpleService)

    @patch("mcp_mesh.tools.proxy_factory.get_proxy_factory")
    def test_validate_proxy_compatibility(self, mock_get_factory):
        """Test the validate_proxy_compatibility function."""
        mock_factory = Mock()
        mock_factory.validate_proxy_compatibility.return_value = True
        mock_get_factory.return_value = mock_factory

        mock_proxy = Mock()
        mock_contract = Mock()

        result = validate_proxy_compatibility(mock_proxy, mock_contract)

        assert result is True
        mock_factory.validate_proxy_compatibility.assert_called_once_with(
            mock_proxy, mock_contract
        )


class TestRoundTripTypeTesting:
    """Test the round-trip type preservation functionality."""

    @patch("mcp_mesh.tools.proxy_factory.create_service_proxy")
    @patch("mcp_mesh.tools.proxy_factory.get_type_hints")
    def test_round_trip_type_test_success(self, mock_get_type_hints, mock_create_proxy):
        """Test successful round-trip type preservation."""
        # Setup mock proxy with same type hints as original
        mock_proxy = Mock()
        mock_proxy_type = Mock()
        mock_proxy_type.__annotations__ = {"param": str, "return": str}
        type(mock_proxy).return_value = mock_proxy_type
        mock_create_proxy.return_value = mock_proxy

        # Mock type hints to return same for both original and proxy
        original_hints = {"param": str, "return": str}
        mock_get_type_hints.return_value = original_hints

        # Mock method signatures
        with patch("inspect.signature") as mock_signature:
            mock_sig = Mock()
            mock_signature.return_value = mock_sig

            result = round_trip_type_test(SimpleService)

            assert result is True

    @patch("mcp_mesh.tools.proxy_factory.create_service_proxy")
    @patch("mcp_mesh.tools.proxy_factory.get_type_hints")
    def test_round_trip_type_test_failure(self, mock_get_type_hints, mock_create_proxy):
        """Test round-trip type preservation failure."""
        # Setup mock proxy with different type hints
        mock_proxy = Mock()
        mock_create_proxy.return_value = mock_proxy

        # Mock different type hints for original vs proxy
        def side_effect(cls_or_type):
            if cls_or_type == SimpleService:
                return {"param": str, "return": str}
            else:  # proxy type
                return {"param": int, "return": str}  # Different!

        mock_get_type_hints.side_effect = side_effect

        result = round_trip_type_test(SimpleService)

        assert result is False


class TestIntegrationScenarios:
    """Integration tests for complex scenarios."""

    @pytest.mark.asyncio
    async def test_async_method_proxy(self):
        """Test proxy creation for services with async methods."""
        # This would be an integration test that actually creates proxies
        # For now, just test that the structure supports async methods

        # Verify async method is detected correctly
        metadata = MethodMetadata(
            method_name="async_operation",
            signature=inspect.signature(SimpleService.async_operation),
            is_async=True,
        )

        assert metadata.is_async is True
        assert asyncio.iscoroutinefunction(SimpleService.async_operation)

    def test_complex_type_signatures(self):
        """Test handling of complex type signatures."""
        # Test method with complex signature
        signature = inspect.signature(ComplexService.process_data)

        # Verify signature has correct parameters
        params = list(signature.parameters.keys())
        assert "primary" in params
        assert "secondary" in params
        assert "config" in params

        # Test parameter annotations
        primary_param = signature.parameters["primary"]
        assert primary_param.annotation is not inspect.Parameter.empty

    def test_dataclass_support(self):
        """Test support for dataclass parameters and return types."""
        # Create test dataclass instance
        test_item = TestDataClass("test", 42, ["tag1", "tag2"])

        # Verify dataclass structure
        assert test_item.name == "test"
        assert test_item.value == 42
        assert test_item.tags == ["tag1", "tag2"]

        # Test method signature with dataclass
        signature = inspect.signature(DataClassService.create_item)
        item_param = signature.parameters["item"]
        assert item_param.annotation == TestDataClass


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])
