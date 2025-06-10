"""Advanced Discovery MCP Tools.

Provides MCP-compliant tools for agent discovery including query_agents,
get_best_agent, and check_compatibility.
"""

import json
import logging

from mcp.server import Server

from mcp_mesh import (
    CapabilityQuery,
    QueryOperator,
    Requirements,
)

from ..shared.service_discovery import ServiceDiscoveryService


class DiscoveryTools:
    """MCP tools for advanced agent discovery."""

    def __init__(self, service_discovery: ServiceDiscoveryService | None = None):
        self.logger = logging.getLogger("discovery_tools")
        self.service_discovery = service_discovery or ServiceDiscoveryService()

    def register_tools(self, app: Server) -> None:
        """Register all discovery tools with the MCP server."""

        @app.tool()
        async def query_agents(
            query: str,
            operator: str = "contains",
            field: str = "capabilities",
            matching_strategy: str = "semantic",
            max_results: int = 10,
        ) -> str:
            """
            Query agents based on capability requirements with advanced matching.

            Args:
                query: The query value (capability name, pattern, etc.)
                operator: Query operator (contains, matches, equals, and, or, not)
                field: Field to query on (capabilities, name, description, tags)
                matching_strategy: Matching strategy (exact, partial, semantic, fuzzy, hierarchical)
                max_results: Maximum number of results to return

            Returns:
                JSON string containing list of matching agents with compatibility scores
            """
            try:
                # Build capability query
                capability_query = CapabilityQuery(
                    operator=QueryOperator(operator),
                    field=field,
                    value=query,
                    matching_strategy=matching_strategy,
                    weight=1.0,
                )

                # Execute query
                matches = await self.service_discovery.query_agents(capability_query)

                # Limit results
                matches = matches[:max_results]

                # Convert to JSON-serializable format
                results = []
                for match in matches:
                    results.append(
                        {
                            "agent_id": match.agent_info.agent_id,
                            "agent_name": match.agent_info.agent_metadata.name,
                            "version": match.agent_info.agent_metadata.version,
                            "description": match.agent_info.agent_metadata.description,
                            "capabilities": [
                                cap.name
                                for cap in match.agent_info.agent_metadata.capabilities
                            ],
                            "tags": match.agent_info.agent_metadata.tags,
                            "endpoint": match.agent_info.agent_metadata.endpoint,
                            "status": match.agent_info.status,
                            "health_score": match.agent_info.health_score,
                            "availability": match.agent_info.availability,
                            "response_time_ms": match.agent_info.response_time_ms,
                            "success_rate": match.agent_info.success_rate,
                            "compatibility_score": {
                                "overall": match.compatibility_score.overall_score,
                                "capability": match.compatibility_score.capability_score,
                                "performance": match.compatibility_score.performance_score,
                                "security": match.compatibility_score.security_score,
                                "availability": match.compatibility_score.availability_score,
                            },
                            "rank": match.rank,
                            "match_confidence": match.match_confidence,
                            "matching_reason": match.matching_reason,
                            "matching_capabilities": match.compatibility_score.matching_capabilities,
                            "missing_capabilities": match.compatibility_score.missing_capabilities,
                        }
                    )

                self.logger.info(f"Query returned {len(results)} agents for: {query}")
                return json.dumps(results, indent=2)

            except Exception as e:
                self.logger.error(f"Error in query_agents: {e}")
                return json.dumps([{"error": f"Query failed: {str(e)}"}], indent=2)

        @app.tool()
        async def get_best_agent(
            required_capabilities: list[str],
            preferred_capabilities: list[str] | None = None,
            performance_requirements: dict[str, float] | None = None,
            security_requirements: dict[str, str] | None = None,
            exclude_agents: list[str] | None = None,
            max_latency_ms: float | None = None,
            min_availability: float | None = None,
            compatibility_threshold: float = 0.7,
        ) -> str:
            """
            Get the best matching agent for given requirements.

            Args:
                required_capabilities: List of required capabilities
                preferred_capabilities: List of preferred capabilities (optional)
                performance_requirements: Performance requirements (optional)
                security_requirements: Security requirements (optional)
                exclude_agents: List of agent IDs to exclude (optional)
                max_latency_ms: Maximum acceptable latency in milliseconds (optional)
                min_availability: Minimum availability requirement (0.0-1.0) (optional)
                compatibility_threshold: Minimum compatibility score (0.0-1.0)

            Returns:
                JSON string containing best matching agent information or error
            """
            try:
                # Build requirements
                requirements = Requirements(
                    required_capabilities=required_capabilities,
                    preferred_capabilities=preferred_capabilities or [],
                    performance_requirements=performance_requirements or {},
                    security_requirements=security_requirements or {},
                    exclude_agents=exclude_agents or [],
                    max_latency_ms=max_latency_ms,
                    min_availability=min_availability,
                    compatibility_threshold=compatibility_threshold,
                )

                # Find best agent
                best_agent = await self.service_discovery.get_best_agent(requirements)

                if not best_agent:
                    self.logger.info("No suitable agent found for requirements")
                    return json.dumps(
                        {"error": "No suitable agent found for requirements"}, indent=2
                    )

                # Convert to JSON-serializable format
                result = {
                    "agent_id": best_agent.agent_id,
                    "agent_name": best_agent.agent_metadata.name,
                    "version": best_agent.agent_metadata.version,
                    "description": best_agent.agent_metadata.description,
                    "capabilities": [
                        cap.name for cap in best_agent.agent_metadata.capabilities
                    ],
                    "tags": best_agent.agent_metadata.tags,
                    "endpoint": best_agent.agent_metadata.endpoint,
                    "status": best_agent.status,
                    "health_score": best_agent.health_score,
                    "availability": best_agent.availability,
                    "current_load": best_agent.current_load,
                    "response_time_ms": best_agent.response_time_ms,
                    "success_rate": best_agent.success_rate,
                    "last_updated": best_agent.last_updated.isoformat(),
                    "performance_profile": best_agent.agent_metadata.performance_profile,
                    "resource_usage": best_agent.agent_metadata.resource_usage,
                }

                self.logger.info(f"Best agent found: {best_agent.agent_id}")
                return json.dumps(result, indent=2)

            except Exception as e:
                self.logger.error(f"Error in get_best_agent: {e}")
                return json.dumps(
                    {"error": f"Best agent search failed: {str(e)}"}, indent=2
                )

        @app.tool()
        async def check_compatibility(
            agent_id: str,
            required_capabilities: list[str],
            preferred_capabilities: list[str] | None = None,
            performance_requirements: dict[str, float] | None = None,
            security_requirements: dict[str, str] | None = None,
            max_latency_ms: float | None = None,
            min_availability: float | None = None,
        ) -> str:
            """
            Check compatibility between an agent and requirements.

            Args:
                agent_id: ID of the agent to check
                required_capabilities: List of required capabilities
                preferred_capabilities: List of preferred capabilities (optional)
                performance_requirements: Performance requirements (optional)
                security_requirements: Security requirements (optional)
                max_latency_ms: Maximum acceptable latency in milliseconds (optional)
                min_availability: Minimum availability requirement (0.0-1.0) (optional)

            Returns:
                JSON string containing detailed compatibility assessment with scores and recommendations
            """
            try:
                # Build requirements
                requirements = Requirements(
                    required_capabilities=required_capabilities,
                    preferred_capabilities=preferred_capabilities or [],
                    performance_requirements=performance_requirements or {},
                    security_requirements=security_requirements or {},
                    max_latency_ms=max_latency_ms,
                    min_availability=min_availability,
                    compatibility_threshold=0.0,  # Don't filter, just assess
                )

                # Check compatibility
                compatibility = await self.service_discovery.check_compatibility(
                    agent_id, requirements
                )

                # Convert to JSON-serializable format
                result = {
                    "agent_id": compatibility.agent_id,
                    "overall_score": compatibility.overall_score,
                    "capability_score": compatibility.capability_score,
                    "performance_score": compatibility.performance_score,
                    "security_score": compatibility.security_score,
                    "availability_score": compatibility.availability_score,
                    "is_compatible": compatibility.is_compatible(),
                    "detailed_breakdown": compatibility.detailed_breakdown,
                    "missing_capabilities": compatibility.missing_capabilities,
                    "matching_capabilities": compatibility.matching_capabilities,
                    "recommendations": compatibility.recommendations,
                    "computed_at": compatibility.computed_at.isoformat(),
                }

                self.logger.info(
                    f"Compatibility check for {agent_id}: {compatibility.overall_score:.3f}"
                )
                return json.dumps(result, indent=2)

            except Exception as e:
                self.logger.error(f"Error in check_compatibility: {e}")
                return json.dumps(
                    {
                        "agent_id": agent_id,
                        "overall_score": 0.0,
                        "is_compatible": False,
                        "error": f"Compatibility check failed: {str(e)}",
                    },
                    indent=2,
                )

        @app.tool()
        async def list_agent_capabilities(
            agent_id: str | None = None, include_metadata: bool = False
        ) -> str:
            """
            List capabilities for a specific agent or all agents.

            Args:
                agent_id: Specific agent ID to query (optional, lists all if None)
                include_metadata: Whether to include detailed capability metadata

            Returns:
                JSON string containing dictionary mapping agent IDs to their capabilities
            """
            try:
                if agent_id:
                    # Get specific agent
                    agent = await self.service_discovery._get_agent_by_id(agent_id)
                    if not agent:
                        return json.dumps(
                            {"error": f"Agent {agent_id} not found"}, indent=2
                        )

                    agents = [agent]
                else:
                    # Get all agents
                    agents = await self.service_discovery._get_all_agents()

                result = {}
                for agent in agents:
                    capabilities_data = []
                    for cap in agent.agent_metadata.capabilities:
                        if include_metadata:
                            capabilities_data.append(
                                {
                                    "name": cap.name,
                                    "version": cap.version,
                                    "description": cap.description,
                                    "tags": cap.tags,
                                    "performance_metrics": cap.performance_metrics,
                                    "security_level": cap.security_level,
                                    "resource_requirements": cap.resource_requirements,
                                }
                            )
                        else:
                            capabilities_data.append(cap.name)

                    result[agent.agent_id] = {
                        "agent_name": agent.agent_metadata.name,
                        "capabilities": capabilities_data,
                        "status": agent.status,
                        "health_score": agent.health_score,
                        "availability": agent.availability,
                    }

                self.logger.info(f"Listed capabilities for {len(result)} agents")
                return json.dumps(result, indent=2)

            except Exception as e:
                self.logger.error(f"Error in list_agent_capabilities: {e}")
                return json.dumps(
                    {"error": f"Capability listing failed: {str(e)}"}, indent=2
                )

        @app.tool()
        async def get_capability_hierarchy() -> str:
            """
            Get the capability hierarchy showing inheritance relationships.

            Returns:
                JSON string containing capability hierarchy structure with inheritance mappings
            """
            try:
                # Get all agents to build comprehensive hierarchy
                agents = await self.service_discovery._get_all_agents()

                # Collect all capabilities
                all_capabilities = []
                for agent in agents:
                    all_capabilities.extend(agent.agent_metadata.capabilities)

                # Build hierarchy
                hierarchy = self.service_discovery.capability_matcher.build_capability_hierarchy(
                    all_capabilities
                )

                # Convert to JSON-serializable format
                result = {
                    "root_capabilities": [
                        {
                            "name": cap.name,
                            "version": cap.version,
                            "description": cap.description,
                            "parent_capabilities": cap.parent_capabilities,
                            "tags": cap.tags,
                        }
                        for cap in hierarchy.root_capabilities
                    ],
                    "inheritance_map": hierarchy.inheritance_map,
                    "total_capabilities": len(all_capabilities),
                    "total_agents": len(agents),
                }

                self.logger.info("Retrieved capability hierarchy")
                return json.dumps(result, indent=2)

            except Exception as e:
                self.logger.error(f"Error in get_capability_hierarchy: {e}")
                return json.dumps(
                    {"error": f"Hierarchy retrieval failed: {str(e)}"}, indent=2
                )

        # Registry Integration for Service Discovery - Phase 2 MCP Tools

        @app.tool()
        async def discover_service_by_class(
            service_class_name: str, include_degraded: bool = False
        ) -> str:
            """
            Discover service endpoints by class name through registry integration.

            Args:
                service_class_name: Name of the service class to discover
                include_degraded: Whether to include degraded services

            Returns:
                JSON string containing list of service endpoints
            """
            try:
                # Create a mock service class for discovery
                class MockServiceClass:
                    pass

                MockServiceClass.__name__ = service_class_name

                # Discover services
                if include_degraded:
                    # Use base discovery that includes all endpoints
                    agents = await self.service_discovery._get_all_agents()
                    endpoints = []
                    for agent in agents:
                        if self.service_discovery._agent_provides_service(
                            agent, MockServiceClass
                        ):
                            endpoint_info = (
                                self.service_discovery._agent_to_endpoint_info(
                                    agent, service_class_name.lower()
                                )
                            )
                            if endpoint_info:
                                endpoints.append(endpoint_info)
                else:
                    # Use registry integration method that filters healthy endpoints
                    endpoints = await self.service_discovery.discover_service_by_class(
                        MockServiceClass
                    )

                # Convert to JSON-serializable format
                results = []
                for endpoint in endpoints:
                    results.append(
                        {
                            "url": endpoint.url,
                            "service_name": endpoint.service_name,
                            "service_version": endpoint.service_version,
                            "protocol": endpoint.protocol,
                            "status": endpoint.status.value,
                            "metadata": endpoint.metadata,
                            "last_updated": endpoint.last_updated.isoformat(),
                        }
                    )

                self.logger.info(
                    f"Discovered {len(results)} endpoints for {service_class_name}"
                )
                return json.dumps(results, indent=2)

            except Exception as e:
                self.logger.error(f"Error in discover_service_by_class: {e}")
                return json.dumps(
                    [{"error": f"Service discovery failed: {str(e)}"}], indent=2
                )

        @app.tool()
        async def select_best_service_instance(
            service_class_name: str,
            min_compatibility_score: float = 0.7,
            max_response_time_ms: int | None = None,
            min_success_rate: float | None = None,
            max_load: float | None = None,
            exclude_agents: list[str] | None = None,
        ) -> str:
            """
            Select the best service instance based on criteria through registry integration.

            Args:
                service_class_name: Name of the service class
                min_compatibility_score: Minimum compatibility score (0.0-1.0)
                max_response_time_ms: Maximum response time in milliseconds
                min_success_rate: Minimum success rate (0.0-1.0)
                max_load: Maximum load (0.0-1.0)
                exclude_agents: List of agent IDs to exclude

            Returns:
                JSON string containing best service endpoint or error
            """
            try:
                # Create mock service class and selection criteria
                class MockServiceClass:
                    pass

                MockServiceClass.__name__ = service_class_name

                # Import SelectionCriteria from service discovery
                from ..shared.service_discovery import SelectionCriteria

                criteria = SelectionCriteria(
                    min_compatibility_score=min_compatibility_score,
                    max_response_time_ms=max_response_time_ms,
                    min_success_rate=min_success_rate,
                    max_load=max_load,
                    exclude_agents=exclude_agents or [],
                )

                # Select best instance
                best_endpoint = (
                    await self.service_discovery.select_best_service_instance(
                        MockServiceClass, criteria
                    )
                )

                if not best_endpoint:
                    return json.dumps(
                        {
                            "error": f"No suitable endpoint found for {service_class_name}"
                        },
                        indent=2,
                    )

                # Convert to JSON-serializable format
                result = {
                    "url": best_endpoint.url,
                    "service_name": best_endpoint.service_name,
                    "service_version": best_endpoint.service_version,
                    "protocol": best_endpoint.protocol,
                    "status": best_endpoint.status.value,
                    "metadata": best_endpoint.metadata,
                    "last_updated": best_endpoint.last_updated.isoformat(),
                    "selection_reason": "Best match based on criteria",
                }

                self.logger.info(
                    f"Selected best endpoint for {service_class_name}: {best_endpoint.url}"
                )
                return json.dumps(result, indent=2)

            except Exception as e:
                self.logger.error(f"Error in select_best_service_instance: {e}")
                return json.dumps(
                    {"error": f"Service selection failed: {str(e)}"}, indent=2
                )

        @app.tool()
        async def monitor_service_health_status(service_class_name: str) -> str:
            """
            Get current health monitoring status for a service class.
            Note: This returns current status. Use monitor_service_health in Python for callback monitoring.

            Args:
                service_class_name: Name of the service class to check

            Returns:
                JSON string containing current health status of all service instances
            """
            try:
                # Create mock service class
                class MockServiceClass:
                    pass

                MockServiceClass.__name__ = service_class_name

                # Get all endpoints for the service
                endpoints = await self.service_discovery.discover_service_by_class(
                    MockServiceClass
                )

                # Check health status for each endpoint
                health_statuses = {}
                for endpoint in endpoints:
                    agent = await self.service_discovery._get_agent_by_endpoint(
                        endpoint
                    )
                    if agent:
                        health_statuses[endpoint.url] = {
                            "status": endpoint.status.value,
                            "health_score": agent.health_score,
                            "availability": agent.availability,
                            "current_load": agent.current_load,
                            "response_time_ms": agent.response_time_ms,
                            "success_rate": agent.success_rate,
                            "last_updated": agent.last_updated.isoformat(),
                        }
                    else:
                        health_statuses[endpoint.url] = {
                            "status": endpoint.status.value,
                            "error": "Agent information not available",
                        }

                result = {
                    "service_class": service_class_name,
                    "total_endpoints": len(endpoints),
                    "healthy_endpoints": len(
                        [e for e in endpoints if e.status.value == "healthy"]
                    ),
                    "endpoint_health": health_statuses,
                    "check_timestamp": "timestamp",
                }

                self.logger.info(
                    f"Health status check for {service_class_name}: {len(endpoints)} endpoints"
                )
                return json.dumps(result, indent=2)

            except Exception as e:
                self.logger.error(f"Error in monitor_service_health_status: {e}")
                return json.dumps(
                    {"error": f"Health status check failed: {str(e)}"}, indent=2
                )

        @app.tool()
        async def create_healthy_service_proxy(
            service_class_name: str,
            min_compatibility_score: float = 0.7,
            max_response_time_ms: int = 5000,
            min_success_rate: float = 0.9,
            max_load: float = 0.8,
        ) -> str:
            """
            Create a proxy for a healthy service instance through registry integration.

            Args:
                service_class_name: Name of the service class
                min_compatibility_score: Minimum compatibility score
                max_response_time_ms: Maximum response time
                min_success_rate: Minimum success rate
                max_load: Maximum load

            Returns:
                JSON string containing proxy creation result and endpoint information
            """
            try:
                # Create mock service class
                class MockServiceClass:
                    pass

                MockServiceClass.__name__ = service_class_name

                # Import SelectionCriteria from service discovery
                from ..shared.service_discovery import SelectionCriteria

                criteria = SelectionCriteria(
                    min_compatibility_score=min_compatibility_score,
                    max_response_time_ms=max_response_time_ms,
                    min_success_rate=min_success_rate,
                    max_load=max_load,
                )

                # Check if enhanced service discovery is available
                if hasattr(self.service_discovery, "create_healthy_proxy"):
                    proxy = await self.service_discovery.create_healthy_proxy(
                        MockServiceClass, criteria
                    )
                    if proxy:
                        result = {
                            "success": True,
                            "service_class": service_class_name,
                            "proxy_created": True,
                            "proxy_type": type(proxy).__name__,
                            "message": f"Healthy proxy created for {service_class_name}",
                        }
                    else:
                        result = {
                            "success": False,
                            "service_class": service_class_name,
                            "proxy_created": False,
                            "error": "No healthy endpoint available for proxy creation",
                        }
                else:
                    # Fallback: just return endpoint information
                    endpoint = (
                        await self.service_discovery.select_best_service_instance(
                            MockServiceClass, criteria
                        )
                    )
                    if endpoint:
                        result = {
                            "success": True,
                            "service_class": service_class_name,
                            "proxy_created": False,
                            "selected_endpoint": {
                                "url": endpoint.url,
                                "status": endpoint.status.value,
                                "metadata": endpoint.metadata,
                            },
                            "message": "Endpoint selected, proxy can be created using the endpoint URL",
                        }
                    else:
                        result = {
                            "success": False,
                            "service_class": service_class_name,
                            "error": "No suitable healthy endpoint found",
                        }

                self.logger.info(
                    f"Proxy creation attempt for {service_class_name}: {result['success']}"
                )
                return json.dumps(result, indent=2)

            except Exception as e:
                self.logger.error(f"Error in create_healthy_service_proxy: {e}")
                return json.dumps(
                    {
                        "success": False,
                        "service_class": service_class_name,
                        "error": f"Proxy creation failed: {str(e)}",
                    },
                    indent=2,
                )


def register_discovery_tools(
    app: Server, service_discovery: ServiceDiscoveryService | None = None
) -> None:
    """
    Register discovery tools with an MCP server.

    Args:
        app: MCP server instance
        service_discovery: Service discovery instance (optional)
    """
    discovery_tools = DiscoveryTools(service_discovery)
    discovery_tools.register_tools(app)
