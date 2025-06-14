# MeshToolRegisterMetadata

Metadata for a single @mesh.tool decorated function

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**function_name** | **str** | Name of the decorated function | 
**capability** | **str** | Capability provided by this function | 
**version** | **str** | Function/capability version | [optional] [default to '1.0.0']
**tags** | **List[str]** | Tags for this capability | [optional] [default to []]
**dependencies** | [**List[StandardizedDependency]**](StandardizedDependency.md) | Dependencies required by this function | [optional] [default to []]
**description** | **str** | Function description | [optional] 

## Example

```python
from mcp_mesh_registry_client.models.mesh_tool_register_metadata import MeshToolRegisterMetadata

# TODO update the JSON string below
json = "{}"
# create an instance of MeshToolRegisterMetadata from a JSON string
mesh_tool_register_metadata_instance = MeshToolRegisterMetadata.from_json(json)
# print the JSON string representation of the object
print(MeshToolRegisterMetadata.to_json())

# convert the object into a dict
mesh_tool_register_metadata_dict = mesh_tool_register_metadata_instance.to_dict()
# create an instance of MeshToolRegisterMetadata from a dict
mesh_tool_register_metadata_from_dict = MeshToolRegisterMetadata.from_dict(mesh_tool_register_metadata_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


