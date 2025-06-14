# AgentRegistrationMetadata

Agent metadata (legacy format or new mesh format)

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Agent name | 
**agent_type** | **str** | Type of agent (always mcp_agent for mesh tools) | 
**namespace** | **str** | Agent namespace | [default to 'default']
**endpoint** | **str** | Agent endpoint URL | 
**capabilities** | **List[str]** | List of capabilities provided by agent (0 or more) | [optional] 
**dependencies** | [**List[AgentMetadataDependenciesInner]**](AgentMetadataDependenciesInner.md) | List of agent dependencies (0 or more) - supports both simple strings and rich objects | [optional] [default to []]
**health_interval** | **int** | Health check interval in seconds | [optional] [default to 30]
**timeout_threshold** | **int** | Timeout threshold in seconds | [optional] [default to 60]
**eviction_threshold** | **int** | Eviction threshold in seconds | [optional] [default to 120]
**version** | **str** | Agent version | [optional] [default to '1.0.0']
**description** | **str** | Agent description | [optional] 
**tags** | **List[str]** | Agent tags for categorization | [optional] [default to []]
**security_context** | **str** | Security context for agent | [optional] 
**tools** | [**List[MeshToolRegisterMetadata]**](MeshToolRegisterMetadata.md) | Array of tools provided by this agent | 

## Example

```python
from mcp_mesh_registry_client.models.agent_registration_metadata import AgentRegistrationMetadata

# TODO update the JSON string below
json = "{}"
# create an instance of AgentRegistrationMetadata from a JSON string
agent_registration_metadata_instance = AgentRegistrationMetadata.from_json(json)
# print the JSON string representation of the object
print(AgentRegistrationMetadata.to_json())

# convert the object into a dict
agent_registration_metadata_dict = agent_registration_metadata_instance.to_dict()
# create an instance of AgentRegistrationMetadata from a dict
agent_registration_metadata_from_dict = AgentRegistrationMetadata.from_dict(agent_registration_metadata_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


