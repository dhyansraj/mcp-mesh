# StandardizedDependency

Standardized dependency format (always object, never string)

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**capability** | **str** | Required capability name | 
**tags** | **List[str]** | Tags for smart matching | [optional] [default to []]
**version** | **str** | Version constraint | [optional] 
**namespace** | **str** | Namespace filter | [optional] [default to 'default']

## Example

```python
from mcp_mesh_registry_client.models.standardized_dependency import StandardizedDependency

# TODO update the JSON string below
json = "{}"
# create an instance of StandardizedDependency from a JSON string
standardized_dependency_instance = StandardizedDependency.from_json(json)
# print the JSON string representation of the object
print(StandardizedDependency.to_json())

# convert the object into a dict
standardized_dependency_dict = standardized_dependency_instance.to_dict()
# create an instance of StandardizedDependency from a dict
standardized_dependency_from_dict = StandardizedDependency.from_dict(standardized_dependency_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


