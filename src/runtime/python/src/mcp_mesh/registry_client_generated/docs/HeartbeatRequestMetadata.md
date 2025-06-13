# HeartbeatRequestMetadata

Agent metadata and health information

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**capabilities** | **List[str]** |  | 
**timestamp** | **datetime** |  | 
**checks** | **Dict[str, object]** | Health check results | [optional] 
**errors** | **List[str]** | Any error messages | [optional] 
**uptime_seconds** | **int** |  | [optional] 
**version** | **str** |  | [optional] 

## Example

```python
from mcp_mesh_registry_client.models.heartbeat_request_metadata import HeartbeatRequestMetadata

# TODO update the JSON string below
json = "{}"
# create an instance of HeartbeatRequestMetadata from a JSON string
heartbeat_request_metadata_instance = HeartbeatRequestMetadata.from_json(json)
# print the JSON string representation of the object
print(HeartbeatRequestMetadata.to_json())

# convert the object into a dict
heartbeat_request_metadata_dict = heartbeat_request_metadata_instance.to_dict()
# create an instance of HeartbeatRequestMetadata from a dict
heartbeat_request_metadata_from_dict = HeartbeatRequestMetadata.from_dict(heartbeat_request_metadata_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


