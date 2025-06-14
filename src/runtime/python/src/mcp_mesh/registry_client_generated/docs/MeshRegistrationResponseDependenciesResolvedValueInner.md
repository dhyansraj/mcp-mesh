# MeshRegistrationResponseDependenciesResolvedValueInner


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | ID of the agent providing the dependency | 
**function_name** | **str** | Actual function name to call on provider | 
**endpoint** | **str** | Endpoint to connect to the provider | 
**capability** | **str** | Capability name for dependency matching | 
**status** | **str** | Current status of the dependency | 

## Example

```python
from mcp_mesh_registry_client.models.mesh_registration_response_dependencies_resolved_value_inner import MeshRegistrationResponseDependenciesResolvedValueInner

# TODO update the JSON string below
json = "{}"
# create an instance of MeshRegistrationResponseDependenciesResolvedValueInner from a JSON string
mesh_registration_response_dependencies_resolved_value_inner_instance = MeshRegistrationResponseDependenciesResolvedValueInner.from_json(json)
# print the JSON string representation of the object
print(MeshRegistrationResponseDependenciesResolvedValueInner.to_json())

# convert the object into a dict
mesh_registration_response_dependencies_resolved_value_inner_dict = mesh_registration_response_dependencies_resolved_value_inner_instance.to_dict()
# create an instance of MeshRegistrationResponseDependenciesResolvedValueInner from a dict
mesh_registration_response_dependencies_resolved_value_inner_from_dict = MeshRegistrationResponseDependenciesResolvedValueInner.from_dict(mesh_registration_response_dependencies_resolved_value_inner_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


