# DecoratorAgentMetadata

Agent metadata containing all decorator information

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Human-readable agent name | 
**agent_type** | **str** | Type of agent (standardized to mcp_agent) | 
**namespace** | **str** | Agent namespace for organization | [default to 'default']
**endpoint** | **str** | Agent endpoint URL (http://, https://, or stdio://) | 
**version** | **str** | Agent version | [optional] [default to '1.0.0']
**decorators** | [**List[DecoratorInfo]**](DecoratorInfo.md) | Array of all @mesh_agent decorators from the agent script | 

## Example

```python
from mcp_mesh_registry_client.models.decorator_agent_metadata import DecoratorAgentMetadata

# TODO update the JSON string below
json = "{}"
# create an instance of DecoratorAgentMetadata from a JSON string
decorator_agent_metadata_instance = DecoratorAgentMetadata.from_json(json)
# print the JSON string representation of the object
print(DecoratorAgentMetadata.to_json())

# convert the object into a dict
decorator_agent_metadata_dict = decorator_agent_metadata_instance.to_dict()
# create an instance of DecoratorAgentMetadata from a dict
decorator_agent_metadata_from_dict = DecoratorAgentMetadata.from_dict(decorator_agent_metadata_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


