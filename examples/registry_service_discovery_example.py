"""Registry Integration Service Discovery Example.

Demonstrates the complete Phase 2 implementation of Registry Integration
for Service Discovery with all required functionality:

1. Service endpoint resolution through registry client
2. Health-aware proxy creation excluding degraded services
3. discover_service_by_class functionality
4. select_best_service_instance with criteria matching
5. monitor_service_health with callback system
6. MCP compliance using official SDK patterns
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp_mesh.shared.registry_client import RegistryClient
from mcp_mesh.shared.service_discovery import (
    EnhancedServiceDiscovery,
    SelectionCriteria,
    ServiceDiscovery,
)
from mcp_mesh.shared.types import HealthStatusType
from mcp_mesh.tools.discovery_tools import DiscoveryTools

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Example service classes
class FileOperationsService:
    """Example file operations service."""

    async def read_file(self, path: str) -> str:
        """Read file content."""
        return f"Content of {path}"

    async def write_file(self, path: str, content: str) -> bool:
        """Write content to file."""
        return True

    async def list_files(self, directory: str) -> list[str]:
        """List files in directory."""
        return ["file1.txt", "file2.txt", "file3.txt"]


class CalculationService:
    """Example calculation service."""

    async def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        return a + b

    async def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b

    async def factorial(self, n: int) -> int:
        """Calculate factorial."""
        if n <= 1:
            return 1
        return n * await self.factorial(n - 1)


class DatabaseService:
    """Example database service."""

    async def query(self, sql: str) -> list[dict]:
        """Execute database query."""
        return [{"id": 1, "name": "test"}]

    async def insert(self, table: str, data: dict) -> int:
        """Insert data into table."""
        return 1


async def demonstrate_service_discovery():
    """Demonstrate service discovery functionality."""
    logger.info("=== Phase 2: Registry Integration for Service Discovery Demo ===")

    # Initialize registry client and service discovery
    registry_client = RegistryClient("http://localhost:8080")
    service_discovery = ServiceDiscovery(registry_client)
    enhanced_discovery = EnhancedServiceDiscovery(registry_client)

    try:
        # 1. Service Endpoint Resolution through Registry Client
        logger.info("\n1. Service Endpoint Resolution")
        logger.info("-" * 50)

        # Discover file operations services
        file_endpoints = await service_discovery.discover_service_by_class(
            FileOperationsService
        )
        logger.info(f"Found {len(file_endpoints)} healthy file service endpoints:")
        for endpoint in file_endpoints:
            logger.info(
                f"  - {endpoint.url} (status: {endpoint.status.value}, "
                f"version: {endpoint.service_version})"
            )

        # Discover calculation services
        calc_endpoints = await service_discovery.discover_service_by_class(
            CalculationService
        )
        logger.info(
            f"Found {len(calc_endpoints)} healthy calculation service endpoints:"
        )
        for endpoint in calc_endpoints:
            logger.info(f"  - {endpoint.url} (status: {endpoint.status.value})")

        # 2. Select Best Service Instance with Criteria Matching
        logger.info("\n2. Best Service Instance Selection")
        logger.info("-" * 50)

        # Define selection criteria
        criteria = SelectionCriteria(
            min_compatibility_score=0.7,
            max_response_time_ms=1000,
            min_success_rate=0.95,
            max_load=0.8,
        )

        # Select best file service
        best_file_endpoint = await service_discovery.select_best_service_instance(
            FileOperationsService, criteria
        )

        if best_file_endpoint:
            logger.info(f"Best file service endpoint: {best_file_endpoint.url}")
            logger.info(
                f"  Health score: {best_file_endpoint.metadata.get('health_score', 'N/A')}"
            )
            logger.info(
                f"  Response time: {best_file_endpoint.metadata.get('response_time_ms', 'N/A')}ms"
            )
            logger.info(
                f"  Success rate: {best_file_endpoint.metadata.get('success_rate', 'N/A')}"
            )
        else:
            logger.warning("No file service endpoint meets the criteria")

        # 3. Health Monitoring with Callback System
        logger.info("\n3. Health Monitoring System")
        logger.info("-" * 50)

        # Define health monitoring callback
        health_events = []

        def health_status_callback(endpoint_url: str, status: HealthStatusType):
            timestamp = datetime.now().strftime("%H:%M:%S")
            event = f"[{timestamp}] {endpoint_url} -> {status.value}"
            health_events.append(event)
            logger.info(f"Health status change: {event}")

        # Start monitoring file services
        file_monitor = await service_discovery.monitor_service_health(
            FileOperationsService, health_status_callback
        )

        logger.info("Started health monitoring for file services...")
        logger.info("Monitoring for 5 seconds...")

        # Let monitoring run for a few seconds
        await asyncio.sleep(5)

        # Check current health status
        current_status = file_monitor.get_current_status()
        logger.info(f"Current health status: {len(current_status)} endpoints monitored")
        for url, status in current_status.items():
            logger.info(f"  {url}: {status.value}")

        # Stop monitoring
        await file_monitor.stop_monitoring()
        logger.info("Stopped health monitoring")

        # 4. Health-Aware Proxy Creation (excluding degraded services)
        logger.info("\n4. Health-Aware Proxy Creation")
        logger.info("-" * 50)

        # Get only healthy endpoints
        healthy_endpoints = await enhanced_discovery.get_healthy_endpoints(
            FileOperationsService
        )
        logger.info(f"Healthy endpoints only: {len(healthy_endpoints)}")

        # Create proxy for healthy service
        proxy_criteria = SelectionCriteria(
            min_compatibility_score=0.8,
            max_response_time_ms=500,
            min_success_rate=0.98,
            max_load=0.6,
        )

        try:
            proxy = await enhanced_discovery.create_healthy_proxy(
                FileOperationsService, proxy_criteria
            )

            if proxy:
                logger.info("Successfully created healthy service proxy")
                logger.info(f"Proxy type: {type(proxy).__name__}")
            else:
                logger.warning("No healthy endpoint available for proxy creation")
        except Exception as e:
            logger.warning(f"Proxy creation not available: {e}")
            logger.info("This requires the full proxy factory implementation")

        # 5. MCP Compliance with Official SDK Patterns
        logger.info("\n5. MCP SDK Compliance")
        logger.info("-" * 50)

        # Initialize discovery tools with MCP compliance
        discovery_tools = DiscoveryTools(service_discovery)

        # Simulate MCP server registration
        class MockMCPServer:
            def __init__(self):
                self.tools = {}

            def tool(self):
                def decorator(func):
                    self.tools[func.__name__] = func
                    logger.info(f"Registered MCP tool: {func.__name__}")
                    return func

                return decorator

        mock_server = MockMCPServer()
        discovery_tools.register_tools(mock_server)

        logger.info(f"Registered {len(mock_server.tools)} MCP-compliant tools:")
        for tool_name in mock_server.tools.keys():
            logger.info(f"  - {tool_name}")

        # Demonstrate MCP tool usage
        if "discover_service_by_class" in mock_server.tools:
            logger.info("\nTesting MCP tool: discover_service_by_class")
            result = await mock_server.tools["discover_service_by_class"](
                "FileOperationsService"
            )
            logger.info("MCP tool result (JSON):")
            logger.info(result[:200] + "..." if len(result) > 200 else result)

        if "select_best_service_instance" in mock_server.tools:
            logger.info("\nTesting MCP tool: select_best_service_instance")
            result = await mock_server.tools["select_best_service_instance"](
                "FileOperationsService",
                min_compatibility_score=0.7,
                max_response_time_ms=1000,
            )
            logger.info("MCP tool result (JSON):")
            logger.info(result[:200] + "..." if len(result) > 200 else result)

        # 6. Complete Integration Workflow
        logger.info("\n6. Complete Integration Workflow")
        logger.info("-" * 50)

        logger.info("Executing complete service discovery workflow:")

        # Step 1: Discover all available services
        available_services = [
            FileOperationsService,
            CalculationService,
            DatabaseService,
        ]
        service_inventory = {}

        for service_class in available_services:
            endpoints = await service_discovery.discover_service_by_class(service_class)
            service_inventory[service_class.__name__] = len(endpoints)
            logger.info(
                f"  {service_class.__name__}: {len(endpoints)} healthy endpoints"
            )

        # Step 2: Select best instances for each service type
        best_services = {}
        for service_class in available_services:
            if service_inventory[service_class.__name__] > 0:
                best_endpoint = await service_discovery.select_best_service_instance(
                    service_class, criteria
                )
                if best_endpoint:
                    best_services[service_class.__name__] = best_endpoint.url
                    logger.info(f"  Best {service_class.__name__}: {best_endpoint.url}")

        # Step 3: Start monitoring all services
        monitors = []
        for service_class in available_services:
            if service_inventory[service_class.__name__] > 0:
                monitor = await service_discovery.monitor_service_health(
                    service_class, health_status_callback
                )
                monitors.append(monitor)

        logger.info(f"Started monitoring {len(monitors)} service types")

        # Brief monitoring period
        await asyncio.sleep(2)

        # Stop all monitors
        for monitor in monitors:
            await monitor.stop_monitoring()

        logger.info("Complete workflow executed successfully!")

        # Summary
        logger.info("\n=== Summary ===")
        logger.info("Phase 2 Registry Integration for Service Discovery completed:")
        logger.info("✓ Service endpoint resolution through registry client")
        logger.info("✓ Health-aware proxy creation excluding degraded services")
        logger.info("✓ discover_service_by_class implementation")
        logger.info("✓ select_best_service_instance with criteria matching")
        logger.info("✓ monitor_service_health with callback system")
        logger.info("✓ MCP compliance using official SDK patterns")
        logger.info(f"✓ Total health events captured: {len(health_events)}")
        logger.info(f"✓ Service types discovered: {len(service_inventory)}")
        logger.info(f"✓ Best services selected: {len(best_services)}")

    except Exception as e:
        logger.error(f"Error in service discovery demonstration: {e}")
        import traceback

        traceback.print_exc()

    finally:
        # Clean up
        await registry_client.close()


async def demonstrate_advanced_scenarios():
    """Demonstrate advanced service discovery scenarios."""
    logger.info("\n=== Advanced Scenarios ===")

    registry_client = RegistryClient("http://localhost:8080")
    service_discovery = ServiceDiscovery(registry_client)

    try:
        # Scenario 1: Fallback when primary service is unavailable
        logger.info("\n1. Service Fallback Scenario")
        logger.info("-" * 30)

        # Try to select with very strict criteria (likely to fail)
        strict_criteria = SelectionCriteria(
            min_compatibility_score=0.99,
            max_response_time_ms=10,
            min_success_rate=0.999,
            max_load=0.01,
        )

        primary_endpoint = await service_discovery.select_best_service_instance(
            FileOperationsService, strict_criteria
        )

        if not primary_endpoint:
            logger.info("Primary service unavailable, using fallback criteria")
            fallback_criteria = SelectionCriteria(
                min_compatibility_score=0.5,
                max_response_time_ms=5000,
                min_success_rate=0.8,
                max_load=0.9,
            )

            fallback_endpoint = await service_discovery.select_best_service_instance(
                FileOperationsService, fallback_criteria
            )

            if fallback_endpoint:
                logger.info(f"Fallback service selected: {fallback_endpoint.url}")
            else:
                logger.warning("No service available even with fallback criteria")

        # Scenario 2: Load balancing across multiple healthy instances
        logger.info("\n2. Load Balancing Scenario")
        logger.info("-" * 30)

        endpoints = await service_discovery.discover_service_by_class(
            CalculationService
        )
        if len(endpoints) > 1:
            logger.info(f"Multiple calculation services available: {len(endpoints)}")

            # Select different instances based on different criteria
            low_latency_criteria = SelectionCriteria(max_response_time_ms=50)
            high_reliability_criteria = SelectionCriteria(min_success_rate=0.99)
            low_load_criteria = SelectionCriteria(max_load=0.3)

            low_latency = await service_discovery.select_best_service_instance(
                CalculationService, low_latency_criteria
            )
            high_reliability = await service_discovery.select_best_service_instance(
                CalculationService, high_reliability_criteria
            )
            low_load = await service_discovery.select_best_service_instance(
                CalculationService, low_load_criteria
            )

            logger.info(
                f"Low latency choice: {low_latency.url if low_latency else 'None'}"
            )
            logger.info(
                f"High reliability choice: {high_reliability.url if high_reliability else 'None'}"
            )
            logger.info(f"Low load choice: {low_load.url if low_load else 'None'}")

        # Scenario 3: Health degradation detection
        logger.info("\n3. Health Degradation Detection")
        logger.info("-" * 30)

        degradation_events = []

        def degradation_callback(endpoint_url: str, status: HealthStatusType):
            if status in [HealthStatusType.DEGRADED, HealthStatusType.UNHEALTHY]:
                degradation_events.append((endpoint_url, status))
                logger.warning(
                    f"Service degradation detected: {endpoint_url} -> {status.value}"
                )

        monitor = await service_discovery.monitor_service_health(
            DatabaseService, degradation_callback
        )

        # Simulate monitoring period
        await asyncio.sleep(3)
        await monitor.stop_monitoring()

        if degradation_events:
            logger.warning(f"Detected {len(degradation_events)} degradation events")
        else:
            logger.info("No service degradation detected during monitoring period")

    except Exception as e:
        logger.error(f"Error in advanced scenarios: {e}")

    finally:
        await registry_client.close()


async def main():
    """Main demonstration function."""
    await demonstrate_service_discovery()
    await demonstrate_advanced_scenarios()


if __name__ == "__main__":
    asyncio.run(main())
