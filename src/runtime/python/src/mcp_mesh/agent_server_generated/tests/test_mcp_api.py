# coding: utf-8

from fastapi.testclient import TestClient
from pydantic import Field  # noqa: F401
from typing_extensions import Annotated  # noqa: F401

from mcp_mesh_agent_server.models.mcp_error_response import (  # noqa: F401
    McpErrorResponse,
)
from mcp_mesh_agent_server.models.mcp_request import McpRequest  # noqa: F401
from mcp_mesh_agent_server.models.mcp_response import McpResponse  # noqa: F401


def test_handle_mcp_message(client: TestClient):
    """Test case for handle_mcp_message

    MCP protocol handler
    """
    mcp_request = {"method": "tools/list", "id": 1, "jsonrpc": "2.0", "params": {}}

    headers = {}
    # uncomment below to make a request
    # response = client.request(
    #    "POST",
    #    "/mcp",
    #    headers=headers,
    #    json=mcp_request,
    # )

    # uncomment below to assert the status code of the HTTP response
    # assert response.status_code == 200
