# AgentInfo

## Properties

| Name             | Type          | Description | Notes      |
| ---------------- | ------------- | ----------- | ---------- |
| **id**           | **str**       |             |
| **name**         | **str**       |             |
| **status**       | **str**       |             |
| **endpoint**     | **str**       |             |
| **capabilities** | **List[str]** |             |
| **last_seen**    | **datetime**  |             | [optional] |
| **version**      | **str**       |             | [optional] |

## Example

```python
from mcp_mesh_registry_client.models.agent_info import AgentInfo

# TODO update the JSON string below
json = "{}"
# create an instance of AgentInfo from a JSON string
agent_info_instance = AgentInfo.from_json(json)
# print the JSON string representation of the object
print(AgentInfo.to_json())

# convert the object into a dict
agent_info_dict = agent_info_instance.to_dict()
# create an instance of AgentInfo from a dict
agent_info_from_dict = AgentInfo.from_dict(agent_info_dict)
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
