"""
MCP Mesh Agent API

API contract for MCP Mesh Agent HTTP endpoints.  ⚠️  CRITICAL FOR AI DEVELOPERS: This OpenAPI specification defines the AGENT-SIDE CONTRACT for Python agent HTTP wrappers.  🤖 AI BEHAVIOR RULES: - NEVER modify this spec without explicit user approval - This is SEPARATE from the registry API contract - Only applies to Python agent HTTP wrapper endpoints - Used for agent-to-external and agent health monitoring  📋 Scope: - Agent health and readiness endpoints - Agent capability and tool discovery - Agent metrics and monitoring - MCP protocol HTTP transport

The version of the OpenAPI document: 1.0.0
Contact: dhyanraj@gmail.com
Generated by OpenAPI Generator (https://openapi-generator.tech)

Do not edit the class manually.
"""  # noqa: E501

from __future__ import annotations

import json
import pprint
import re  # noqa: F401
from typing import Any, ClassVar

from mcp_mesh_agent_server.models.tool_info import ToolInfo
from pydantic import BaseModel, Field

try:
    from typing import Self
except ImportError:
    from typing import Self


class AgentToolsList(BaseModel):
    """
    AgentToolsList
    """  # noqa: E501

    tools: dict[str, ToolInfo] = Field(description="Available tools mapping")
    __properties: ClassVar[list[str]] = ["tools"]

    model_config = {
        "populate_by_name": True,
        "validate_assignment": True,
        "protected_namespaces": (),
    }

    def to_str(self) -> str:
        """Returns the string representation of the model using alias"""
        return pprint.pformat(self.model_dump(by_alias=True))

    def to_json(self) -> str:
        """Returns the JSON representation of the model using alias"""
        # TODO: pydantic v2: use .model_dump_json(by_alias=True, exclude_unset=True) instead
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> Self:
        """Create an instance of AgentToolsList from a JSON string"""
        return cls.from_dict(json.loads(json_str))

    def to_dict(self) -> dict[str, Any]:
        """Return the dictionary representation of the model using alias.

        This has the following differences from calling pydantic's
        `self.model_dump(by_alias=True)`:

        * `None` is only added to the output dict for nullable fields that
          were set at model initialization. Other fields with value `None`
          are ignored.
        """
        _dict = self.model_dump(
            by_alias=True,
            exclude={},
            exclude_none=True,
        )
        # override the default output from pydantic by calling `to_dict()` of each value in tools (dict)
        _field_dict = {}
        if self.tools:
            for _key in self.tools:
                if self.tools[_key]:
                    _field_dict[_key] = self.tools[_key].to_dict()
            _dict["tools"] = _field_dict
        return _dict

    @classmethod
    def from_dict(cls, obj: dict) -> Self:
        """Create an instance of AgentToolsList from a dict"""
        if obj is None:
            return None

        if not isinstance(obj, dict):
            return cls.model_validate(obj)

        _obj = cls.model_validate(
            {
                "tools": (
                    dict(
                        (_k, ToolInfo.from_dict(_v))
                        for _k, _v in obj.get("tools").items()
                    )
                    if obj.get("tools") is not None
                    else None
                )
            }
        )
        return _obj
