# coding: utf-8

from typing import ClassVar, Dict, List, Tuple  # noqa: F401

from mcp_mesh_agent_server.models.agent_mesh_info import AgentMeshInfo
from mcp_mesh_agent_server.models.agent_tools_list import AgentToolsList


class BaseMeshApi:
    subclasses: ClassVar[Tuple] = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        BaseMeshApi.subclasses = BaseMeshApi.subclasses + (cls,)

    async def get_agent_mesh_info(
        self,
    ) -> AgentMeshInfo:
        """Returns agent capabilities, dependencies, and mesh integration info.  🤖 AI CRITICAL: This provides agent discovery information for mesh routing."""
        ...

    async def list_agent_tools(
        self,
    ) -> AgentToolsList:
        """Returns list of tools available from this agent.  🤖 AI NOTE: Used for tool discovery in mesh routing."""
        ...
