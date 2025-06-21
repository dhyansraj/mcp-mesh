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
from pydantic import StrictStr

import mcp_mesh_agent_server.impl
from mcp_mesh_agent_server.apis.monitoring_api_base import BaseMonitoringApi
from mcp_mesh_agent_server.models.extra_models import TokenModel  # noqa: F401

router = APIRouter()

ns_pkg = mcp_mesh_agent_server.impl
for _, name, _ in pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + "."):
    importlib.import_module(name)


@router.get(
    "/metrics",
    responses={
        200: {"model": str, "description": "Prometheus metrics"},
    },
    tags=["monitoring"],
    summary="Agent metrics",
    response_model_by_alias=True,
)
async def get_agent_metrics() -> str:
    """Returns Prometheus metrics for agent monitoring.  🤖 AI NOTE: Standard Prometheus metrics endpoint."""
    if not BaseMonitoringApi.subclasses:
        raise HTTPException(status_code=500, detail="Not implemented")
    return await BaseMonitoringApi.subclasses[0]().get_agent_metrics()
