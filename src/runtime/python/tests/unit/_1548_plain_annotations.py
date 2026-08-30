"""Control module for issue #1548 — the SAME declarations, WITHOUT PEP 563.

Deliberately has no ``from __future__ import annotations``. PEP 563 is a
per-module compile flag that stringifies **every** annotation in the module
where it appears, including annotations on functions defined inside test
methods, so the "without the future import" half of the parity contract cannot
live in the same file as the "with" half. It lives here.

Nothing in this module is decorated: importing it must not touch the shared
``DecoratorRegistry``. The decorated parity cases are built inside the tests
(both worlds) where the registry fixture can isolate them.
"""

from typing import Optional

from pydantic import BaseModel

import mesh
from mesh.types import McpMeshAgent, McpMeshTool, MeshJob, MeshLlmAgent


class Reply(BaseModel):
    """Structured LLM response used by the return-annotation parity test."""

    text: str


def tool_dep(x: str, dep: McpMeshTool = None) -> str:
    return x


def agent_dep(x: str, dep: McpMeshAgent = None) -> str:
    return x


def llm_param(x: str, llm: MeshLlmAgent = None) -> str:
    return x


def job_param(x: str, job: MeshJob = None) -> str:
    return x


def qualified(
    x: str,
    dep: mesh.McpMeshTool = None,
    job: mesh.MeshJob = None,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    return x


def optional_forms(
    a: Optional[McpMeshTool] = None,  # noqa: UP045 - both spellings on purpose
    b: MeshJob | None = None,
    c: MeshLlmAgent | None = None,
) -> str:
    return "x"


def structured(x: str, llm: MeshLlmAgent = None) -> Reply:
    return Reply(text=x)
