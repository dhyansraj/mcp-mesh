# AgentMetadataDependenciesInnerOneOf

Rich dependency with tags and metadata

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**capability** | **str** | Required capability name | 
**tags** | **List[str]** | Optional tags for smart matching | [optional] 
**version** | **str** | Optional version constraint | [optional] 
**namespace** | **str** | Optional namespace filter | [optional] [default to 'default']

## Example

```python
from mcp_mesh_registry_client.models.agent_metadata_dependencies_inner_one_of import AgentMetadataDependenciesInnerOneOf

# TODO update the JSON string below
json = "{}"
# create an instance of AgentMetadataDependenciesInnerOneOf from a JSON string
agent_metadata_dependencies_inner_one_of_instance = AgentMetadataDependenciesInnerOneOf.from_json(json)
# print the JSON string representation of the object
print(AgentMetadataDependenciesInnerOneOf.to_json())

# convert the object into a dict
agent_metadata_dependencies_inner_one_of_dict = agent_metadata_dependencies_inner_one_of_instance.to_dict()
# create an instance of AgentMetadataDependenciesInnerOneOf from a dict
agent_metadata_dependencies_inner_one_of_from_dict = AgentMetadataDependenciesInnerOneOf.from_dict(agent_metadata_dependencies_inner_one_of_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


