#!/usr/bin/env python3
"""Provider agent - receives Pydantic model arguments and responds."""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Pydantic Provider")


class TaskRequest(BaseModel):
    task: str = "greet"
    name: str = "World"
    count: int = 1


class TaskResponse(BaseModel):
    result: str = ""
    service: str = ""


@app.tool()
@mesh.tool(
    capability="execute_task",
    description="Execute a task from Pydantic model arguments",
)
async def execute_task(
    request: TaskRequest,
) -> TaskResponse:
    if request.task == "greet":
        greeting = f"Hello {request.name}!" * request.count
        return TaskResponse(result=greeting, service="provider")
    return TaskResponse(result=f"unknown task: {request.task}", service="provider")


@mesh.agent(
    name="pydantic-provider",
    version="1.0.0",
    description="Provider that receives Pydantic model arguments",
    http_port=0,
    enable_http=True,
    auto_run=True,
)
class ProviderAgent:
    pass
