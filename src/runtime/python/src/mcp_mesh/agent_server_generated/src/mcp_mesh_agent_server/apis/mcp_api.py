# coding: utf-8

import importlib
import pkgutil
from typing import Dict, List  # noqa: F401

from fastapi import (  # noqa: F401
    APIRouter,
    Body,
    Cookie,
    Depends,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    Security,
    status,
)
from pydantic import Field
from typing_extensions import Annotated

import mcp_mesh_agent_server.impl
from mcp_mesh_agent_server.apis.mcp_api_base import BaseMcpApi
from mcp_mesh_agent_server.models.extra_models import TokenModel  # noqa: F401
from mcp_mesh_agent_server.models.mcp_error_response import McpErrorResponse
from mcp_mesh_agent_server.models.mcp_request import McpRequest
from mcp_mesh_agent_server.models.mcp_response import McpResponse

router = APIRouter()

ns_pkg = mcp_mesh_agent_server.impl
for _, name, _ in pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + "."):
    importlib.import_module(name)


@router.post(
    "/mcp",
    responses={
        200: {"model": McpResponse, "description": "MCP response"},
        400: {"model": McpErrorResponse, "description": "Invalid MCP request"},
    },
    tags=["mcp"],
    summary="MCP protocol handler",
    response_model_by_alias=True,
)
async def handle_mcp_message(
    mcp_request: Annotated[
        McpRequest, Field(description="MCP JSON-RPC message")
    ] = Body(None, description="MCP JSON-RPC message"),
) -> McpResponse:
    """HTTP transport endpoint for MCP protocol messages.  🤖 AI CRITICAL CONTRACT: - This endpoint handles MCP JSON-RPC protocol over HTTP - Request/response format must match MCP specification - Used for agent communication in HTTP transport mode"""
    if not BaseMcpApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseMcpApi.subclasses[0]().handle_mcp_message(mcp_request)
