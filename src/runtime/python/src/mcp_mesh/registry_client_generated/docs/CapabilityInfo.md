# CapabilityInfo


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Capability name | 
**version** | **str** | Capability version | [default to '1.0.0']
**function_name** | **str** | Name of the function that provides this capability | 
**tags** | **List[str]** | Tags associated with this capability | [optional] [default to []]
**description** | **str** | Human-readable description of the capability | [optional] 

## Example

```python
from mcp_mesh_registry_client.models.capability_info import CapabilityInfo

# TODO update the JSON string below
json = "{}"
# create an instance of CapabilityInfo from a JSON string
capability_info_instance = CapabilityInfo.from_json(json)
# print the JSON string representation of the object
print(CapabilityInfo.to_json())

# convert the object into a dict
capability_info_dict = capability_info_instance.to_dict()
# create an instance of CapabilityInfo from a dict
capability_info_from_dict = CapabilityInfo.from_dict(capability_info_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


