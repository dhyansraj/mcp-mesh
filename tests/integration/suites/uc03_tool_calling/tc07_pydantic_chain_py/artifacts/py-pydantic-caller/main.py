#!/usr/bin/env python3
"""Caller agent - sends Pydantic model arguments to provider."""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Pydantic Caller")


class TaskRequest(BaseModel):
    task: str = "greet"
    name: str = "World"
    count: int = 1


class TaskResponse(BaseModel):
    result: str = ""
    service: str = ""


@app.tool()
@mesh.tool(
    capability="run_task",
    description="Send a Pydantic model to the provider",
    dependencies=["execute_task"],
)
async def run_task(
    request: TaskRequest,
    execute_task: mesh.McpMeshTool = None,
) -> TaskResponse:
    if execute_task is None:
        return TaskResponse(result="degraded", service="caller")
    return await execute_task(request=request)


@mesh.agent(
    name="pydantic-caller",
    version="1.0.0",
    description="Caller that sends Pydantic model arguments",
    http_port=0,
    enable_http=True,
    auto_run=True,
)
class CallerAgent:
    pass
