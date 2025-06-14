# MeshAgentRegisterMetadata

Agent registration metadata for @mesh.tool based agents

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_type** | **str** | Type of agent (always mcp_agent for mesh tools) | 
**name** | **str** | Agent name | 
**version** | **str** | Agent version | [optional] [default to '1.0.0']
**namespace** | **str** | Agent namespace | [optional] [default to 'default']
**endpoint** | **str** | Agent endpoint URL | [optional] 
**tools** | [**List[MeshToolRegisterMetadata]**](MeshToolRegisterMetadata.md) | Array of tools provided by this agent | 

## Example

```python
from mcp_mesh_registry_client.models.mesh_agent_register_metadata import MeshAgentRegisterMetadata

# TODO update the JSON string below
json = "{}"
# create an instance of MeshAgentRegisterMetadata from a JSON string
mesh_agent_register_metadata_instance = MeshAgentRegisterMetadata.from_json(json)
# print the JSON string representation of the object
print(MeshAgentRegisterMetadata.to_json())

# convert the object into a dict
mesh_agent_register_metadata_dict = mesh_agent_register_metadata_instance.to_dict()
# create an instance of MeshAgentRegisterMetadata from a dict
mesh_agent_register_metadata_from_dict = MeshAgentRegisterMetadata.from_dict(mesh_agent_register_metadata_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


