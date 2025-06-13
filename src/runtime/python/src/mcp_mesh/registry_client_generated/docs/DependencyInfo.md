# DependencyInfo


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | ID of the agent providing the dependency | 
**endpoint** | **str** | Endpoint to connect to the provider | 
**status** | **str** | Current status of the dependency | 
**capabilities** | **List[str]** | Capabilities provided by this dependency | [optional] 
**version** | **str** | Version of the provider agent | [optional] 
**metadata** | **Dict[str, object]** | Additional metadata about the provider | [optional] 

## Example

```python
from mcp_mesh_registry_client.models.dependency_info import DependencyInfo

# TODO update the JSON string below
json = "{}"
# create an instance of DependencyInfo from a JSON string
dependency_info_instance = DependencyInfo.from_json(json)
# print the JSON string representation of the object
print(DependencyInfo.to_json())

# convert the object into a dict
dependency_info_dict = dependency_info_instance.to_dict()
# create an instance of DependencyInfo from a dict
dependency_info_from_dict = DependencyInfo.from_dict(dependency_info_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


