# coding: utf-8

from typing import Any, ClassVar, Dict, List, Tuple  # noqa: F401

from pydantic import StrictStr

from mcp_mesh_agent_server.models.agent_health_response import AgentHealthResponse
from mcp_mesh_agent_server.models.readiness_response import ReadinessResponse


class BaseHealthApi:
    subclasses: ClassVar[Tuple] = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        BaseHealthApi.subclasses = BaseHealthApi.subclasses + (cls,)

    async def get_agent_health(
        self,
    ) -> AgentHealthResponse:
        """Returns agent health status and basic information.  🤖 AI NOTE: This is AGENT health, not registry health. Used by Kubernetes health checks and external monitoring."""
        ...

    async def get_agent_liveness(
        self,
    ) -> str:
        """Returns agent liveness status for Kubernetes liveness probes.  🤖 AI NOTE: Kubernetes-specific liveness endpoint."""
        ...

    async def get_agent_readiness(
        self,
    ) -> ReadinessResponse:
        """Returns agent readiness status for Kubernetes readiness probes.  🤖 AI NOTE: Kubernetes-specific readiness endpoint."""
        ...
