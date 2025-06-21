# coding: utf-8

from fastapi.testclient import TestClient
from pydantic import StrictStr  # noqa: F401


def test_get_agent_metrics(client: TestClient):
    """Test case for get_agent_metrics

    Agent metrics
    """

    headers = {}
    # uncomment below to make a request
    # response = client.request(
    #    "GET",
    #    "/metrics",
    #    headers=headers,
    # )

    # uncomment below to assert the status code of the HTTP response
    # assert response.status_code == 200
