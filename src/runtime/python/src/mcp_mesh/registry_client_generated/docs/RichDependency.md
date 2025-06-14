# RichDependency

Rich dependency format with full metadata for internal processing

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**capability** | **str** | Required capability name | 
**tags** | **List[str]** | Tags for smart matching | [default to []]
**version** | **str** | Version constraint | [default to '1.0.0']
**namespace** | **str** | Namespace filter | [default to 'default']

## Example

```python
from mcp_mesh_registry_client.models.rich_dependency import RichDependency

# TODO update the JSON string below
json = "{}"
# create an instance of RichDependency from a JSON string
rich_dependency_instance = RichDependency.from_json(json)
# print the JSON string representation of the object
print(RichDependency.to_json())

# convert the object into a dict
rich_dependency_dict = rich_dependency_instance.to_dict()
# create an instance of RichDependency from a dict
rich_dependency_from_dict = RichDependency.from_dict(rich_dependency_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


