# mcp_mesh_registry_client.AgentsApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**list_agents**](AgentsApi.md#list_agents) | **GET** /agents | List all registered agents
[**register_agent**](AgentsApi.md#register_agent) | **POST** /agents/register | Register agent with registry
[**send_heartbeat**](AgentsApi.md#send_heartbeat) | **POST** /heartbeat | Send agent heartbeat


# **list_agents**
> AgentsListResponse list_agents()

List all registered agents

Get list of all currently registered agents.

🤖 AI NOTE: Used by CLI list command and dependency resolution.


### Example


```python
import mcp_mesh_registry_client
from mcp_mesh_registry_client.models.agents_list_response import AgentsListResponse
from mcp_mesh_registry_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost:8000
# See configuration.py for a list of all supported configuration parameters.
configuration = mcp_mesh_registry_client.Configuration(
    host = "http://localhost:8000"
)


# Enter a context with an instance of the API client
with mcp_mesh_registry_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = mcp_mesh_registry_client.AgentsApi(api_client)

    try:
        # List all registered agents
        api_response = api_instance.list_agents()
        print("The response of AgentsApi->list_agents:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentsApi->list_agents: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**AgentsListResponse**](AgentsListResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | List of registered agents |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **register_agent**
> RegistrationResponse register_agent(agent_registration)

Register agent with registry

Register a new agent or update existing agent registration.

🤖 AI CRITICAL CONTRACT:
- Request format is FIXED - do not modify without user approval
- Both Go and Python must accept this exact format
- Response must include agent_id for heartbeat correlation
- Dependencies field enables dependency injection


### Example


```python
import mcp_mesh_registry_client
from mcp_mesh_registry_client.models.agent_registration import AgentRegistration
from mcp_mesh_registry_client.models.registration_response import RegistrationResponse
from mcp_mesh_registry_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost:8000
# See configuration.py for a list of all supported configuration parameters.
configuration = mcp_mesh_registry_client.Configuration(
    host = "http://localhost:8000"
)


# Enter a context with an instance of the API client
with mcp_mesh_registry_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = mcp_mesh_registry_client.AgentsApi(api_client)
    agent_registration = {"agent_id":"hello-world","metadata":{"name":"hello-world","agent_type":"mesh_agent","namespace":"default","endpoint":"stdio://hello-world","capabilities":["greeting","farewell"],"dependencies":[],"health_interval":30,"version":"1.0.0"},"timestamp":"2024-01-20T10:30:45Z"} # AgentRegistration | Agent registration data

    try:
        # Register agent with registry
        api_response = api_instance.register_agent(agent_registration)
        print("The response of AgentsApi->register_agent:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentsApi->register_agent: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_registration** | [**AgentRegistration**](AgentRegistration.md)| Agent registration data | 

### Return type

[**RegistrationResponse**](RegistrationResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Agent registered successfully |  -  |
**400** | Invalid registration data |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **send_heartbeat**
> HeartbeatResponse send_heartbeat(heartbeat_request)

Send agent heartbeat

Send periodic heartbeat to maintain agent registration and get dependency updates.

🤖 AI CRITICAL CONTRACT:
- Used by health monitoring system
- Response may include dependencies_resolved for dependency injection
- Python runtime depends on this exact response format


### Example


```python
import mcp_mesh_registry_client
from mcp_mesh_registry_client.models.heartbeat_request import HeartbeatRequest
from mcp_mesh_registry_client.models.heartbeat_response import HeartbeatResponse
from mcp_mesh_registry_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost:8000
# See configuration.py for a list of all supported configuration parameters.
configuration = mcp_mesh_registry_client.Configuration(
    host = "http://localhost:8000"
)


# Enter a context with an instance of the API client
with mcp_mesh_registry_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = mcp_mesh_registry_client.AgentsApi(api_client)
    heartbeat_request = {"agent_id":"hello-world","status":"healthy","metadata":{"capabilities":["greeting","farewell"],"timestamp":"2024-01-20T10:30:45Z","uptime_seconds":300,"version":"1.0.0"}} # HeartbeatRequest | Agent heartbeat data

    try:
        # Send agent heartbeat
        api_response = api_instance.send_heartbeat(heartbeat_request)
        print("The response of AgentsApi->send_heartbeat:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentsApi->send_heartbeat: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **heartbeat_request** | [**HeartbeatRequest**](HeartbeatRequest.md)| Agent heartbeat data | 

### Return type

[**HeartbeatResponse**](HeartbeatResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Heartbeat received successfully |  -  |
**400** | Invalid heartbeat data |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

