# HeartbeatRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** | Agent identifier from registration | 
**status** | **str** | Current agent health status | 
**metadata** | [**HeartbeatRequestMetadata**](HeartbeatRequestMetadata.md) |  | 

## Example

```python
from mcp_mesh_registry_client.models.heartbeat_request import HeartbeatRequest

# TODO update the JSON string below
json = "{}"
# create an instance of HeartbeatRequest from a JSON string
heartbeat_request_instance = HeartbeatRequest.from_json(json)
# print the JSON string representation of the object
print(HeartbeatRequest.to_json())

# convert the object into a dict
heartbeat_request_dict = heartbeat_request_instance.to_dict()
# create an instance of HeartbeatRequest from a dict
heartbeat_request_from_dict = HeartbeatRequest.from_dict(heartbeat_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


