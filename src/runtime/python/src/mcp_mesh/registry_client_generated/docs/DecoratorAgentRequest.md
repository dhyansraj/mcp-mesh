# DecoratorAgentRequest

Unified request schema for both /agents/register and /heartbeat endpoints. Supports decorator-based agent registration with per-function dependencies. 

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Unique identifier for the agent | 
**timestamp** | **datetime** | Request timestamp | 
**metadata** | [**DecoratorAgentMetadata**](DecoratorAgentMetadata.md) |  | 

## Example

```python
from mcp_mesh_registry_client.models.decorator_agent_request import DecoratorAgentRequest

# TODO update the JSON string below
json = "{}"
# create an instance of DecoratorAgentRequest from a JSON string
decorator_agent_request_instance = DecoratorAgentRequest.from_json(json)
# print the JSON string representation of the object
print(DecoratorAgentRequest.to_json())

# convert the object into a dict
decorator_agent_request_dict = decorator_agent_request_instance.to_dict()
# create an instance of DecoratorAgentRequest from a dict
decorator_agent_request_from_dict = DecoratorAgentRequest.from_dict(decorator_agent_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


