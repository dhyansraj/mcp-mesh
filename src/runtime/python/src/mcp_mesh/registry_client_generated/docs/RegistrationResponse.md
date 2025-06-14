# RegistrationResponse


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
from mcp_mesh_registry_client.models.registration_response import RegistrationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RegistrationResponse from a JSON string
registration_response_instance = RegistrationResponse.from_json(json)
# print the JSON string representation of the object
print(RegistrationResponse.to_json())

# convert the object into a dict
registration_response_dict = registration_response_instance.to_dict()
# create an instance of RegistrationResponse from a dict
registration_response_from_dict = RegistrationResponse.from_dict(registration_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


