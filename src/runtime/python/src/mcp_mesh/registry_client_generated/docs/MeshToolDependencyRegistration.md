# MeshToolDependencyRegistration

Dependency specification for a tool function

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**capability** | **str** | Required capability name | 
**tags** | **List[str]** | Tags for smart matching | [optional] [default to []]
**version** | **str** | Version constraint | [optional] 
**namespace** | **str** | Namespace filter | [optional] [default to 'default']

## Example

```python
from mcp_mesh_registry_client.models.mesh_tool_dependency_registration import MeshToolDependencyRegistration

# TODO update the JSON string below
json = "{}"
# create an instance of MeshToolDependencyRegistration from a JSON string
mesh_tool_dependency_registration_instance = MeshToolDependencyRegistration.from_json(json)
# print the JSON string representation of the object
print(MeshToolDependencyRegistration.to_json())

# convert the object into a dict
mesh_tool_dependency_registration_dict = mesh_tool_dependency_registration_instance.to_dict()
# create an instance of MeshToolDependencyRegistration from a dict
mesh_tool_dependency_registration_from_dict = MeshToolDependencyRegistration.from_dict(mesh_tool_dependency_registration_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


