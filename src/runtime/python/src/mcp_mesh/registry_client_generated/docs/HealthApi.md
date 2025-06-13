# mcp_mesh_registry_client.HealthApi

All URIs are relative to *http://localhost:8000*

Method | HTTP request | Description
------------- | ------------- | -------------
[**get_health**](HealthApi.md#get_health) | **GET** /health | Registry health check
[**get_root**](HealthApi.md#get_root) | **GET** / | Registry root information


# **get_health**
> HealthResponse get_health()

Registry health check

Returns registry health status and basic information.

🤖 AI NOTE: This endpoint should NEVER return errors unless the registry is truly broken.
Used by startup detection logic in CLI.


### Example


```python
import mcp_mesh_registry_client
from mcp_mesh_registry_client.models.health_response import HealthResponse
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
    api_instance = mcp_mesh_registry_client.HealthApi(api_client)

    try:
        # Registry health check
        api_response = api_instance.get_health()
        print("The response of HealthApi->get_health:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling HealthApi->get_health: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**HealthResponse**](HealthResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Registry is healthy |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **get_root**
> RootResponse get_root()

Registry root information

Returns basic registry information and available endpoints.

🤖 AI NOTE: Used for connectivity testing and endpoint discovery.


### Example


```python
import mcp_mesh_registry_client
from mcp_mesh_registry_client.models.root_response import RootResponse
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
    api_instance = mcp_mesh_registry_client.HealthApi(api_client)

    try:
        # Registry root information
        api_response = api_instance.get_root()
        print("The response of HealthApi->get_root:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling HealthApi->get_root: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**RootResponse**](RootResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Registry information |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

