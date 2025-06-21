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

import mcp_mesh_agent_server.impl
from mcp_mesh_agent_server.apis.mesh_api_base import BaseMeshApi
from mcp_mesh_agent_server.models.agent_mesh_info import AgentMeshInfo
from mcp_mesh_agent_server.models.agent_tools_list import AgentToolsList
from mcp_mesh_agent_server.models.extra_models import TokenModel  # noqa: F401

router = APIRouter()

ns_pkg = mcp_mesh_agent_server.impl
for _, name, _ in pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + "."):
    importlib.import_module(name)


@router.get(
    "/mesh/info",
    responses={
        200: {"model": AgentMeshInfo, "description": "Agent mesh information"},
    },
    tags=["mesh"],
    summary="Agent mesh information",
    response_model_by_alias=True,
)
async def get_agent_mesh_info() -> AgentMeshInfo:
    """Returns agent capabilities, dependencies, and mesh integration info.  🤖 AI CRITICAL: This provides agent discovery information for mesh routing."""
    if not BaseMeshApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseMeshApi.subclasses[0]().get_agent_mesh_info()


@router.get(
    "/mesh/tools",
    responses={
        200: {"model": AgentToolsList, "description": "Agent tools list"},
    },
    tags=["mesh"],
    summary="List agent tools",
    response_model_by_alias=True,
)
async def list_agent_tools() -> AgentToolsList:
    """Returns list of tools available from this agent.  🤖 AI NOTE: Used for tool discovery in mesh routing."""
    if not BaseMeshApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseMeshApi.subclasses[0]().list_agent_tools()
