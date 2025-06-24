"""
Registry Lifecycle Manager

Implements registry-level lifecycle management for agents.
Focuses on registration events, not server start/stop operations.
"""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from mcp_mesh import (
    AgentInfo,
    DeregistrationResult,
    DrainResult,
    LifecycleConfiguration,
    LifecycleEvent,
    LifecycleEventData,
    LifecycleProtocol,
    LifecycleStatus,
    RegistrationResult,
)


class LifecycleManager(LifecycleProtocol):
    """
    Registry lifecycle manager handling agent registration/deregistration events.

    This class manages the lifecycle of agents within the registry, handling
    registration, deregistration, and drain operations with proper state transitions.
    """

    def __init__(
        self, registry_storage: Any, config: LifecycleConfiguration | None = None
    ):
        self.storage = registry_storage
        self.config = config or LifecycleConfiguration()
        self.config.__post_init__()  # Initialize default transitions

        # Track agent lifecycle states
        self._agent_lifecycle_states: dict[str, LifecycleStatus] = {}
        self._event_subscribers: list[Any] = []

        # Track ongoing operations
        self._draining_agents: dict[str, datetime] = {}
        self._deregistering_agents: dict[str, datetime] = {}

    async def register_agent(self, agent_info: AgentInfo) -> RegistrationResult:
        """Register an agent with the registry."""
        try:
            # Set initial lifecycle status
            agent_info.lifecycle_status = LifecycleStatus.REGISTERING
            self._agent_lifecycle_states[agent_info.id] = LifecycleStatus.REGISTERING

            # Emit registration started event
            await self._emit_lifecycle_event(
                LifecycleEvent.REGISTRATION_STARTED,
                agent_info.id,
                agent_info.name,
                agent_info.namespace,
                message=f"Starting registration for agent {agent_info.name}",
            )

            # Convert AgentInfo to AgentRegistration format for storage
            registration_data = {
                "id": agent_info.id,
                "name": agent_info.name,
                "namespace": agent_info.namespace,
                "endpoint": agent_info.endpoint,
                "capabilities": [
                    {
                        "name": cap,
                        "version": "1.0.0",
                        "description": f"Capability {cap}",
                    }
                    for cap in agent_info.capabilities
                ],
                "dependencies": agent_info.dependencies,
                "health_interval": agent_info.health_interval,
                "security_context": agent_info.security_context,
                "labels": agent_info.labels,
                "annotations": agent_info.annotations,
                "config": agent_info.metadata,
            }

            # Import AgentRegistration here to avoid circular imports
            from ..server.models import AgentRegistration

            registration = AgentRegistration(**registration_data)

            # Register with storage
            registered_agent = await self.storage.register_agent(registration)

            # Update lifecycle status to active
            agent_info.lifecycle_status = LifecycleStatus.ACTIVE
            self._agent_lifecycle_states[agent_info.id] = LifecycleStatus.ACTIVE

            # Emit registration completed event
            await self._emit_lifecycle_event(
                LifecycleEvent.REGISTRATION_COMPLETED,
                agent_info.id,
                agent_info.name,
                agent_info.namespace,
                message=f"Successfully registered agent {agent_info.name}",
                old_status=LifecycleStatus.REGISTERING,
                new_status=LifecycleStatus.ACTIVE,
            )

            return RegistrationResult(
                success=True,
                agent_id=registered_agent.id,
                resource_version=registered_agent.resource_version,
                message=f"Agent {agent_info.name} registered successfully",
                lifecycle_status=LifecycleStatus.ACTIVE,
                registered_at=registered_agent.created_at,
            )

        except Exception as e:
            # Update lifecycle status to failed
            self._agent_lifecycle_states[agent_info.id] = LifecycleStatus.FAILED

            # Emit registration failed event
            await self._emit_lifecycle_event(
                LifecycleEvent.REGISTRATION_FAILED,
                agent_info.id,
                agent_info.name,
                agent_info.namespace,
                message=f"Failed to register agent {agent_info.name}: {str(e)}",
                old_status=LifecycleStatus.REGISTERING,
                new_status=LifecycleStatus.FAILED,
            )

            return RegistrationResult(
                success=False,
                agent_id=agent_info.id,
                resource_version="",
                message=f"Registration failed: {str(e)}",
                lifecycle_status=LifecycleStatus.FAILED,
                errors=[str(e)],
            )

    async def deregister_agent(
        self, agent_id: str, graceful: bool = True
    ) -> DeregistrationResult:
        """Deregister an agent from the registry."""
        try:
            # Get agent information
            agent = await self.storage.get_agent(agent_id)
            if not agent:
                return DeregistrationResult(
                    success=False,
                    agent_id=agent_id,
                    message=f"Agent {agent_id} not found",
                    graceful=graceful,
                    errors=[f"Agent {agent_id} not found"],
                )

            # Check current lifecycle status
            current_status = self._agent_lifecycle_states.get(
                agent_id, LifecycleStatus.ACTIVE
            )

            # If graceful and agent is active, drain first
            if graceful and current_status == LifecycleStatus.ACTIVE:
                drain_result = await self.drain_agent(agent_id)
                if not drain_result.success:
                    return DeregistrationResult(
                        success=False,
                        agent_id=agent_id,
                        message=f"Failed to drain agent before deregistration: {drain_result.message}",
                        graceful=graceful,
                        errors=drain_result.errors,
                    )

            # Update lifecycle status to deregistering
            self._agent_lifecycle_states[agent_id] = LifecycleStatus.DEREGISTERING
            self._deregistering_agents[agent_id] = datetime.now(UTC)

            # Emit deregistration started event
            await self._emit_lifecycle_event(
                LifecycleEvent.DEREGISTRATION_STARTED,
                agent_id,
                agent.name,
                agent.namespace,
                message=f"Starting deregistration for agent {agent.name}",
                old_status=current_status,
                new_status=LifecycleStatus.DEREGISTERING,
            )

            # Remove from storage
            success = await self.storage.unregister_agent(agent_id)

            if success:
                # Update lifecycle status to removed
                self._agent_lifecycle_states[agent_id] = LifecycleStatus.REMOVED
                self._deregistering_agents.pop(agent_id, None)

                # Emit deregistration completed event
                await self._emit_lifecycle_event(
                    LifecycleEvent.DEREGISTRATION_COMPLETED,
                    agent_id,
                    agent.name,
                    agent.namespace,
                    message=f"Successfully deregistered agent {agent.name}",
                    old_status=LifecycleStatus.DEREGISTERING,
                    new_status=LifecycleStatus.REMOVED,
                )

                return DeregistrationResult(
                    success=True,
                    agent_id=agent_id,
                    message=f"Agent {agent.name} deregistered successfully",
                    graceful=graceful,
                    cleanup_completed=True,
                )
            else:
                # Revert status on failure
                self._agent_lifecycle_states[agent_id] = current_status
                self._deregistering_agents.pop(agent_id, None)

                return DeregistrationResult(
                    success=False,
                    agent_id=agent_id,
                    message=f"Failed to remove agent {agent_id} from storage",
                    graceful=graceful,
                    errors=["Storage operation failed"],
                )

        except Exception as e:
            # Clean up tracking on error
            self._deregistering_agents.pop(agent_id, None)

            return DeregistrationResult(
                success=False,
                agent_id=agent_id,
                message=f"Deregistration failed: {str(e)}",
                graceful=graceful,
                errors=[str(e)],
            )

    async def drain_agent(self, agent_id: str) -> DrainResult:
        """Drain agent by removing from selection pool gracefully."""
        try:
            # Get agent information
            agent = await self.storage.get_agent(agent_id)
            if not agent:
                return DrainResult(
                    success=False,
                    agent_id=agent_id,
                    message=f"Agent {agent_id} not found",
                    errors=[f"Agent {agent_id} not found"],
                )

            # Check current lifecycle status
            current_status = self._agent_lifecycle_states.get(
                agent_id, LifecycleStatus.ACTIVE
            )

            if current_status != LifecycleStatus.ACTIVE:
                return DrainResult(
                    success=False,
                    agent_id=agent_id,
                    message=f"Agent {agent_id} is not in ACTIVE state (current: {current_status})",
                    errors=[f"Invalid state for drain operation: {current_status}"],
                )

            # Update lifecycle status to draining
            self._agent_lifecycle_states[agent_id] = LifecycleStatus.DRAINING
            self._draining_agents[agent_id] = datetime.now(UTC)

            # Emit drain started event
            await self._emit_lifecycle_event(
                LifecycleEvent.DRAIN_STARTED,
                agent_id,
                agent.name,
                agent.namespace,
                message=f"Starting drain for agent {agent.name}",
                old_status=LifecycleStatus.ACTIVE,
                new_status=LifecycleStatus.DRAINING,
            )

            # Mark agent as degraded in storage to remove from selection pool
            # but keep it registered for graceful shutdown
            agent.status = "degraded"
            agent.updated_at = datetime.now(UTC)
            agent.resource_version = str(int(time.time() * 1000))

            await self.storage.register_agent(agent)  # Update status

            # Simulate drain process (in real implementation, this would
            # wait for active connections to complete)
            drain_timeout = self.config.default_drain_timeout
            await asyncio.sleep(1)  # Simulate drain time

            # Complete drain
            drain_completed_at = datetime.now(UTC)
            self._draining_agents.pop(agent_id, None)

            # Emit drain completed event
            await self._emit_lifecycle_event(
                LifecycleEvent.DRAIN_COMPLETED,
                agent_id,
                agent.name,
                agent.namespace,
                message=f"Successfully drained agent {agent.name}",
                old_status=LifecycleStatus.DRAINING,
                new_status=LifecycleStatus.DRAINING,  # Still draining until deregistered
            )

            return DrainResult(
                success=True,
                agent_id=agent_id,
                message=f"Agent {agent.name} drained successfully",
                connections_terminated=0,  # Would be actual count in real implementation
                pending_requests=0,
                drain_completed_at=drain_completed_at,
                drain_timeout_seconds=drain_timeout,
            )

        except Exception as e:
            # Clean up tracking on error
            self._draining_agents.pop(agent_id, None)

            return DrainResult(
                success=False,
                agent_id=agent_id,
                message=f"Drain failed: {str(e)}",
                errors=[str(e)],
            )

    async def get_agent_lifecycle_status(self, agent_id: str) -> LifecycleStatus | None:
        """Get current lifecycle status of an agent."""
        return self._agent_lifecycle_states.get(agent_id)

    async def list_agents_by_lifecycle_status(
        self, status: LifecycleStatus
    ) -> list[str]:
        """List agents by lifecycle status."""
        return [
            agent_id
            for agent_id, agent_status in self._agent_lifecycle_states.items()
            if agent_status == status
        ]

    async def _emit_lifecycle_event(
        self,
        event_type: LifecycleEvent,
        agent_id: str,
        agent_name: str,
        namespace: str,
        message: str,
        old_status: LifecycleStatus | None = None,
        new_status: LifecycleStatus | None = None,
    ) -> None:
        """Emit a lifecycle event to all subscribers."""
        event_data = LifecycleEventData(
            event_type=event_type,
            agent_id=agent_id,
            agent_name=agent_name,
            namespace=namespace,
            message=message,
            old_status=old_status,
            new_status=new_status,
        )

        # Send to all subscribers
        for subscriber in self._event_subscribers[
            :
        ]:  # Copy to avoid modification during iteration
            try:
                if hasattr(subscriber, "put"):
                    await subscriber.put(event_data.dict())
                elif callable(subscriber):
                    await subscriber(event_data.dict())
            except Exception:
                # Remove failed subscribers
                self._event_subscribers.remove(subscriber)

    def subscribe_to_lifecycle_events(self, subscriber: Any) -> None:
        """Subscribe to lifecycle events."""
        self._event_subscribers.append(subscriber)

    def unsubscribe_from_lifecycle_events(self, subscriber: Any) -> None:
        """Unsubscribe from lifecycle events."""
        if subscriber in self._event_subscribers:
            self._event_subscribers.remove(subscriber)

    async def health_status_changed(
        self, agent_id: str, old_status: str, new_status: str
    ) -> None:
        """Handle health status changes and trigger lifecycle transitions if needed."""
        agent = await self.storage.get_agent(agent_id)
        if not agent:
            return

        # Get current lifecycle status
        lifecycle_status = self._agent_lifecycle_states.get(
            agent_id, LifecycleStatus.ACTIVE
        )

        # Emit health status change event
        await self._emit_lifecycle_event(
            LifecycleEvent.HEALTH_STATUS_CHANGED,
            agent_id,
            agent.name,
            agent.namespace,
            message=f"Health status changed from {old_status} to {new_status}",
            metadata={"old_health_status": old_status, "new_health_status": new_status},
        )

        # Trigger lifecycle transitions based on health status
        if new_status == "expired" and lifecycle_status == LifecycleStatus.ACTIVE:
            # Auto-drain expired agents
            await self.drain_agent(agent_id)

    async def cleanup_stale_operations(self) -> None:
        """Clean up stale lifecycle operations."""
        current_time = datetime.now(UTC)

        # Clean up stale draining operations
        stale_draining = []
        for agent_id, start_time in self._draining_agents.items():
            if (
                current_time - start_time
            ).total_seconds() > self.config.default_drain_timeout:
                stale_draining.append(agent_id)

        for agent_id in stale_draining:
            self._draining_agents.pop(agent_id, None)
            self._agent_lifecycle_states[agent_id] = LifecycleStatus.FAILED

            agent = await self.storage.get_agent(agent_id)
            if agent:
                await self._emit_lifecycle_event(
                    LifecycleEvent.DRAIN_COMPLETED,
                    agent_id,
                    agent.name,
                    agent.namespace,
                    message=f"Drain operation timed out for agent {agent.name}",
                    metadata={"timeout": True},
                )

        # Clean up stale deregistering operations
        stale_deregistering = []
        for agent_id, start_time in self._deregistering_agents.items():
            if (
                current_time - start_time
            ).total_seconds() > self.config.default_deregistration_timeout:
                stale_deregistering.append(agent_id)

        for agent_id in stale_deregistering:
            self._deregistering_agents.pop(agent_id, None)
            self._agent_lifecycle_states[agent_id] = LifecycleStatus.FAILED
