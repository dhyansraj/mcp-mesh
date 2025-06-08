#!/usr/bin/env python3
"""
Comprehensive Service Proxy Example

Demonstrates the Dynamic Class Generation capabilities of MCP Mesh including:
1. Type-preserving proxy creation
2. Runtime type validation
3. Method signature preservation
4. IDE autocomplete support
5. Contract validation
"""

import asyncio
import logging
from dataclasses import dataclass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Example service classes with various method signatures
class DataProcessingService:
    """Example service with comprehensive method signatures."""

    def process_string(self, text: str, uppercase: bool = False) -> str:
        """Process a string with optional uppercase conversion."""
        result = text.strip()
        if uppercase:
            result = result.upper()
        return result

    def process_numbers(self, numbers: list[int]) -> dict[str, int]:
        """Process a list of numbers and return statistics."""
        if not numbers:
            return {"count": 0, "sum": 0, "avg": 0}

        return {
            "count": len(numbers),
            "sum": sum(numbers),
            "avg": sum(numbers) // len(numbers),
        }

    async def async_fetch_data(self, url: str, timeout: int = 30) -> dict[str, any]:
        """Async method to fetch data from a URL."""
        # Simulate async operation
        await asyncio.sleep(0.1)
        return {
            "url": url,
            "status": "success",
            "timeout": timeout,
            "data": f"Content from {url}",
        }

    def complex_operation(
        self,
        primary_data: dict[str, list[int]],
        secondary_data: list[str] | None = None,
        config: dict[str, any] | None = None,
    ) -> dict[str, any]:
        """Complex method with multiple optional parameters."""
        result = {
            "primary_keys": list(primary_data.keys()),
            "primary_total": sum(len(v) for v in primary_data.values()),
        }

        if secondary_data:
            result["secondary_count"] = len(secondary_data)

        if config:
            result["config_keys"] = list(config.keys())

        return result


@dataclass
class FileInfo:
    """Example dataclass for type validation."""

    name: str
    size: int
    path: str


class FileService:
    """Example file service with dataclass parameters."""

    def get_file_info(self, path: str) -> FileInfo:
        """Get file information."""
        return FileInfo(name=path.split("/")[-1], size=1024, path=path)

    def list_files(self, directory: str, pattern: str | None = None) -> list[FileInfo]:
        """List files in a directory."""
        files = [
            FileInfo(name="file1.txt", size=100, path=f"{directory}/file1.txt"),
            FileInfo(name="file2.py", size=200, path=f"{directory}/file2.py"),
        ]

        if pattern:
            files = [f for f in files if pattern in f.name]

        return files


async def demonstrate_proxy_functionality():
    """Demonstrate comprehensive proxy functionality."""

    logger.info("=== MCP Mesh Dynamic Class Generation Demo ===")

    # Import proxy factory (this would be the user's code)
    from mcp_mesh_runtime.tools.proxy_factory import (
        create_service_proxy,
        resolve_service_endpoint,
        round_trip_type_test,
        validate_proxy_compatibility,
    )

    try:
        # 1. Test round-trip type preservation
        logger.info("1. Testing round-trip type preservation...")

        type_test_passed = round_trip_type_test(DataProcessingService)
        logger.info(
            f"DataProcessingService type test: {'PASSED' if type_test_passed else 'FAILED'}"
        )

        type_test_passed = round_trip_type_test(FileService)
        logger.info(
            f"FileService type test: {'PASSED' if type_test_passed else 'FAILED'}"
        )

        # 2. Create service proxies
        logger.info("\n2. Creating service proxies...")

        # Create proxies with full type preservation
        data_proxy = create_service_proxy(DataProcessingService)
        file_proxy = create_service_proxy(FileService)

        logger.info(
            f"Created proxy for DataProcessingService: {type(data_proxy).__name__}"
        )
        logger.info(f"Created proxy for FileService: {type(file_proxy).__name__}")

        # 3. Test method signatures are preserved
        logger.info("\n3. Testing method signature preservation...")

        import inspect

        # Check that proxy methods have identical signatures
        original_method = DataProcessingService.process_string
        proxy_method = data_proxy.process_string

        original_sig = inspect.signature(original_method)
        proxy_sig = inspect.signature(proxy_method)

        logger.info(f"Original signature: {original_sig}")
        logger.info(f"Proxy signature: {proxy_sig}")
        logger.info(f"Signatures match: {original_sig == proxy_sig}")

        # 4. Test runtime type validation
        logger.info("\n4. Testing runtime type validation...")

        try:
            # This should work - correct types
            result = data_proxy.process_string("hello world", uppercase=True)
            logger.info(f"Valid call result: {result}")
        except Exception as e:
            logger.error(f"Unexpected error on valid call: {e}")

        try:
            # This should fail - wrong type
            result = data_proxy.process_string(
                123, uppercase=True
            )  # int instead of str
            logger.error("Type validation failed - this should not happen!")
        except TypeError as e:
            logger.info(f"Type validation caught error (expected): {e}")
        except Exception as e:
            logger.error(f"Unexpected error type: {e}")

        # 5. Test complex type validation
        logger.info("\n5. Testing complex type validation...")

        try:
            # Valid complex call
            complex_data = {"group1": [1, 2, 3], "group2": [4, 5, 6]}
            result = data_proxy.complex_operation(
                primary_data=complex_data,
                secondary_data=["a", "b", "c"],
                config={"mode": "fast", "debug": True},
            )
            logger.info(f"Complex operation result: {result}")
        except Exception as e:
            logger.error(f"Error in complex operation: {e}")

        # 6. Test async method handling
        logger.info("\n6. Testing async method handling...")

        try:
            # Test async method
            async_result = await data_proxy.async_fetch_data(
                "https://example.com", timeout=10
            )
            logger.info(f"Async method result: {async_result}")
        except Exception as e:
            logger.error(f"Error in async method: {e}")

        # 7. Test endpoint resolution
        logger.info("\n7. Testing endpoint resolution...")

        endpoint_info = resolve_service_endpoint(DataProcessingService)
        logger.info(f"Resolved endpoint: {endpoint_info.url}")
        logger.info(f"Service name: {endpoint_info.service_name}")
        logger.info(f"Protocol: {endpoint_info.protocol}")

        # 8. Test contract validation
        logger.info("\n8. Testing contract validation...")

        # Get the service contract from the proxy
        if hasattr(data_proxy, "_base_proxy"):
            base_proxy = data_proxy._base_proxy
            contract = base_proxy.get_service_contract()

            if contract:
                is_compatible = validate_proxy_compatibility(data_proxy, contract)
                logger.info(f"Proxy contract compatibility: {is_compatible}")

                logger.info(f"Contract methods: {list(contract.methods.keys())}")
                logger.info(f"Contract capabilities: {contract.capabilities}")

        # 9. Test dataclass support
        logger.info("\n9. Testing dataclass parameter support...")

        try:
            file_info = file_proxy.get_file_info("/home/user/document.txt")
            logger.info(f"File info result: {file_info}")
            logger.info(f"File info type: {type(file_info)}")

            file_list = file_proxy.list_files("/home/user", pattern=".txt")
            logger.info(f"File list result: {file_list}")
        except Exception as e:
            logger.error(f"Error in dataclass methods: {e}")

        logger.info("\n=== Demo completed successfully! ===")

    except Exception as e:
        logger.error(f"Demo failed with error: {e}")
        raise


def demonstrate_ide_support():
    """Demonstrate IDE support and type checking capabilities."""

    logger.info("\n=== IDE Support Demonstration ===")

    from mcp_mesh_runtime.tools.proxy_factory import create_service_proxy

    # Create proxy
    service_proxy = create_service_proxy(DataProcessingService)

    # The following should show full IDE autocomplete and type checking:

    # IDE should autocomplete method names
    # service_proxy.process_string
    # service_proxy.process_numbers
    # service_proxy.async_fetch_data
    # service_proxy.complex_operation

    # IDE should show correct parameter types and return types
    result: str = service_proxy.process_string("test", uppercase=True)

    # IDE should catch type mismatches at development time
    # result: int = service_proxy.process_string("test")  # Should show type error

    logger.info("IDE support features verified (check your IDE for autocomplete)")


if __name__ == "__main__":
    # Run the comprehensive demonstration
    asyncio.run(demonstrate_proxy_functionality())

    # Demonstrate IDE support
    demonstrate_ide_support()
