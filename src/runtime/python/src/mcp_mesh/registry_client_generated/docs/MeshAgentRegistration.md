# MeshAgentRegistration

Agent registration request with flattened structure. Used by both /agents/register and /heartbeat endpoints. Based on @mesh.tool decorator processing - always has at least one tool. 

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Unique identifier for the agent | 
**agent_type** | **str** | Type of agent (always mcp_agent for mesh tools) | [optional] [default to 'mcp_agent']
**name** | **str** | Human-readable agent name (defaults to agent_id) | [optional] 
**version** | **str** | Agent version | [optional] [default to '1.0.0']
**http_host** | **str** | HTTP host for agent endpoint | [optional] [default to '0.0.0.0']
**http_port** | **int** | HTTP port for agent endpoint (0 for stdio) | [optional] [default to 0]
**timestamp** | **datetime** | Registration/heartbeat timestamp | [optional] 
**namespace** | **str** | Agent namespace for organization | [optional] [default to 'default']
**tools** | [**List[MeshToolRegistration]**](MeshToolRegistration.md) | Array of tools provided by this agent (@mesh.tool functions) | 

## Example

```python
from mcp_mesh_registry_client.models.mesh_agent_registration import MeshAgentRegistration

# TODO update the JSON string below
json = "{}"
# create an instance of MeshAgentRegistration from a JSON string
mesh_agent_registration_instance = MeshAgentRegistration.from_json(json)
# print the JSON string representation of the object
print(MeshAgentRegistration.to_json())

# convert the object into a dict
mesh_agent_registration_dict = mesh_agent_registration_instance.to_dict()
# create an instance of MeshAgentRegistration from a dict
mesh_agent_registration_from_dict = MeshAgentRegistration.from_dict(mesh_agent_registration_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


