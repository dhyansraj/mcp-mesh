# MeshRegistrationResponse

Response for both registration and heartbeat requests

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | **str** |  | 
**timestamp** | **datetime** |  | 
**message** | **str** |  | 
**agent_id** | **str** | Confirmed agent ID | 
**dependencies_resolved** | **Dict[str, List[MeshRegistrationResponseDependenciesResolvedValueInner]]** | Function name to array of resolved dependencies mapping. 🤖 AI NOTE: This enables immediate dependency injection setup.  | [optional] 

## Example

```python
from mcp_mesh_registry_client.models.mesh_registration_response import MeshRegistrationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of MeshRegistrationResponse from a JSON string
mesh_registration_response_instance = MeshRegistrationResponse.from_json(json)
# print the JSON string representation of the object
print(MeshRegistrationResponse.to_json())

# convert the object into a dict
mesh_registration_response_dict = mesh_registration_response_instance.to_dict()
# create an instance of MeshRegistrationResponse from a dict
mesh_registration_response_from_dict = MeshRegistrationResponse.from_dict(mesh_registration_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


