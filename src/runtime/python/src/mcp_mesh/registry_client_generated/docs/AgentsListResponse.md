# AgentsListResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agents** | [**List[AgentInfo]**](AgentInfo.md) | List of registered agents | 
**count** | **int** | Total number of agents | 
**timestamp** | **datetime** |  | 

## Example

```python
from mcp_mesh_registry_client.models.agents_list_response import AgentsListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentsListResponse from a JSON string
agents_list_response_instance = AgentsListResponse.from_json(json)
# print the JSON string representation of the object
print(AgentsListResponse.to_json())

# convert the object into a dict
agents_list_response_dict = agents_list_response_instance.to_dict()
# create an instance of AgentsListResponse from a dict
agents_list_response_from_dict = AgentsListResponse.from_dict(agents_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


