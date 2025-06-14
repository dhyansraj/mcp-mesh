# DecoratorInfo

Information about a single @mesh_agent decorated function

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**function_name** | **str** | Name of the decorated function | 
**capability** | **str** | Capability provided by this function | 
**dependencies** | [**List[StandardizedDependency]**](StandardizedDependency.md) | Dependencies required by this function | [default to []]
**description** | **str** | Function description | [optional] 
**version** | **str** | Function/capability version | [optional] 
**tags** | **List[str]** | Tags for this capability | [optional] [default to []]

## Example

```python
from mcp_mesh_registry_client.models.decorator_info import DecoratorInfo

# TODO update the JSON string below
json = "{}"
# create an instance of DecoratorInfo from a JSON string
decorator_info_instance = DecoratorInfo.from_json(json)
# print the JSON string representation of the object
print(DecoratorInfo.to_json())

# convert the object into a dict
decorator_info_dict = decorator_info_instance.to_dict()
# create an instance of DecoratorInfo from a dict
decorator_info_from_dict = DecoratorInfo.from_dict(decorator_info_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


