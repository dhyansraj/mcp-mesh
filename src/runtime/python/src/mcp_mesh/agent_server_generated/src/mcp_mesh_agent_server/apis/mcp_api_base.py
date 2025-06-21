# coding: utf-8

from typing import ClassVar, Dict, List, Tuple  # noqa: F401

from pydantic import Field
from typing_extensions import Annotated

from mcp_mesh_agent_server.models.mcp_error_response import McpErrorResponse
from mcp_mesh_agent_server.models.mcp_request import McpRequest
from mcp_mesh_agent_server.models.mcp_response import McpResponse


class BaseMcpApi:
    subclasses: ClassVar[Tuple] = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        BaseMcpApi.subclasses = BaseMcpApi.subclasses + (cls,)

    async def handle_mcp_message(
        self,
        mcp_request: Annotated[McpRequest, Field(description="MCP JSON-RPC message")],
    ) -> McpResponse:
        """HTTP transport endpoint for MCP protocol messages.  🤖 AI CRITICAL CONTRACT: - This endpoint handles MCP JSON-RPC protocol over HTTP - Request/response format must match MCP specification - Used for agent communication in HTTP transport mode"""
        ...
