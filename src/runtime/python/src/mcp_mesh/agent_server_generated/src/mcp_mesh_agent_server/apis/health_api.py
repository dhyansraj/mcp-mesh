# coding: utf-8

import importlib
import pkgutil
from typing import Any, Dict, List  # noqa: F401

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
from pydantic import StrictStr

import mcp_mesh_agent_server.impl
from mcp_mesh_agent_server.apis.health_api_base import BaseHealthApi
from mcp_mesh_agent_server.models.agent_health_response import AgentHealthResponse
from mcp_mesh_agent_server.models.extra_models import TokenModel  # noqa: F401
from mcp_mesh_agent_server.models.readiness_response import ReadinessResponse

router = APIRouter()

ns_pkg = mcp_mesh_agent_server.impl
for _, name, _ in pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + "."):
    importlib.import_module(name)


@router.get(
    "/health",
    responses={
        200: {"model": AgentHealthResponse, "description": "Agent is healthy"},
        503: {"model": AgentHealthResponse, "description": "Agent is unhealthy"},
    },
    tags=["health"],
    summary="Agent health check",
    response_model_by_alias=True,
)
async def get_agent_health() -> AgentHealthResponse:
    """Returns agent health status and basic information.  🤖 AI NOTE: This is AGENT health, not registry health. Used by Kubernetes health checks and external monitoring."""
    if not BaseHealthApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseHealthApi.subclasses[0]().get_agent_health()


@router.get(
    "/livez",
    responses={
        200: {"model": str, "description": "Agent is alive"},
        503: {"description": "Agent is not alive"},
    },
    tags=["health"],
    summary="Agent liveness check",
    response_model_by_alias=True,
)
async def get_agent_liveness() -> str:
    """Returns agent liveness status for Kubernetes liveness probes.  🤖 AI NOTE: Kubernetes-specific liveness endpoint."""
    if not BaseHealthApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseHealthApi.subclasses[0]().get_agent_liveness()


@router.get(
    "/ready",
    responses={
        200: {"model": ReadinessResponse, "description": "Agent is ready"},
        503: {"description": "Agent is not ready"},
    },
    tags=["health"],
    summary="Agent readiness check",
    response_model_by_alias=True,
)
async def get_agent_readiness() -> ReadinessResponse:
    """Returns agent readiness status for Kubernetes readiness probes.  🤖 AI NOTE: Kubernetes-specific readiness endpoint."""
    if not BaseHealthApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseHealthApi.subclasses[0]().get_agent_readiness()
