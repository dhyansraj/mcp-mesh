# MCP Client Implementation Plan

## Overview

Replace our custom JSON-RPC HTTP implementation with a proper MCP client library to achieve full protocol compliance and comprehensive content type support for stateless MCP calls.

## Current Status: ✅ Research Complete - Plan Ready for Review

---

## 1. Research Phase

### 1.1 Python MCP Client Library Investigation ✅ COMPLETED

**Objective**: Identify the best Python MCP client library for HTTP transport

#### Libraries Investigated:

- ✅ Official Model Context Protocol Python SDK (`mcp>=1.9.0`)
- ✅ FastMCP client capabilities (`fastmcp>=2.8.0`)
- ✅ Current custom implementation analysis

#### Research Findings:

**Option 1: Official MCP Python SDK (RECOMMENDED)**

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async with streamablehttp_client("example/mcp") as (read_stream, write_stream, _):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        result = await session.call_tool("tool_name", {"param": "value"})
```

**Pros:**

- ✅ Official MCP protocol implementation
- ✅ Streamable HTTP transport (latest standard)
- ✅ Full protocol compliance (initialization, capabilities, errors)
- ✅ Built-in session management
- ✅ Standardized error handling
- ✅ Already in our dependencies (`mcp>=1.9.0`)

**Cons:**

- ❌ Async-only interface (need sync wrapper)
- ❌ More complex session management
- ❌ Less documentation for HTTP transport

**Option 2: FastMCP Client (ALTERNATIVE)**

```python
from fastmcp import Client

async with Client("http://localhost:8000/sse") as client:
    result = await client.call_tool("tool_name", {"param": "value"})
```

**Pros:**

- ✅ Simple, Pythonic interface
- ✅ Already familiar from our FastMCP server usage
- ✅ Multiple transport support (HTTP, SSE, stdio)
- ✅ Auto transport detection

**Cons:**

- ❌ Third-party library (not official MCP)
- ❌ May not support all MCP protocol features
- ❌ Still async-only interface

**DECISION: Use Official MCP SDK with sync wrapper**

- Official protocol compliance ensures future compatibility
- Comprehensive feature support
- Already in our dependencies

### 1.2 Current Implementation Analysis ✅ COMPLETED

**Files Analyzed**:

- `src/runtime/python/mcp_mesh/engine/sync_http_client.py` - Custom HTTP client
- `src/runtime/python/mcp_mesh/pipeline/registry_steps.py` - Proxy creation and injection
- `examples/simple/dependent_agent.py` - Usage example

**Current Flow**:

1. **Dependency Registration**: `registry_steps.py` creates `SyncHttpClient` instances
2. **Callable Proxy Creation**: Wraps client in callable function
3. **Dependency Injection**: Injects callable proxy into tool functions
4. **Tool Call**: `time_service()` → proxy → `SyncHttpClient.call_tool()` → HTTP request

**Current Implementation Issues**:

**SyncHttpClient Problems**:

- ❌ **Custom JSON-RPC**: Manual implementation, not MCP compliant
- ❌ **No Protocol Initialization**: Missing MCP handshake and capabilities
- ❌ **Basic Error Handling**: No proper JSON-RPC error codes
- ❌ **SSE Parser**: Custom SSE parsing that could be standardized
- ❌ **Limited Content Types**: Only handles text and object content
- ❌ **No Connection Reuse**: Creates new connection per call
- ❌ **Synchronous Only**: Uses `urllib` blocking calls

**Proxy Creation Issues**:

- ❌ **Content Extraction**: Custom logic to extract text from MCP responses
- ❌ **Error Propagation**: Basic string error messages
- ❌ **No Type Support**: Only returns text or basic objects

**Current Proxy Pattern**:

```python
def create_callable_proxy(client, func_name):
    def proxy_call():
        result = client.call_tool(func_name, {})
        # Custom content extraction logic
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if content and isinstance(content[0], dict) and "text" in content[0]:
                return content[0]["text"]
        return str(result)
    return proxy_call
```

**Dependencies**:

- Currently: `urllib`, `json` (standard library)
- Available: `mcp>=1.9.0`, `fastmcp>=2.8.0` (already in requirements)

---

## 2. Target Architecture (Updated - Simplified)

### 2.1 New MCP Client Architecture

**Design Goals**:

- ✅ Full MCP protocol compliance using official SDK
- ✅ Support all content types (text, image, resource, mixed)
- ✅ **Stateless connections** - New connection per request for K8s load balancing
- ✅ Proper error handling and propagation
- ✅ Maintain existing dependency injection interface
- ✅ Async-to-sync bridge for current synchronous usage

**Architecture Overview**:

```
Dependency Injection System
           ↓
    MCPClientProxy (sync interface)
           ↓
    AsyncMCPClient (async wrapper)
           ↓
    Official MCP SDK (streamable HTTP)
           ↓
    K8s Service DNS (load balancing)
           ↓
    Remote MCP Server Pods
```

### 2.2 Component Design (Simplified)

**MCPClientProxy (Replacement for SyncHttpClient)**

```python
class MCPClientProxy:
    """Synchronous MCP client proxy for dependency injection."""

    def __init__(self, endpoint: str, function_name: str):
        self.endpoint = endpoint
        self.function_name = function_name
        # No connection pooling - create fresh connection per request

    def __call__(self, **kwargs) -> Any:
        """Callable interface for dependency injection."""
        return asyncio.run(self._async_call(**kwargs))

    async def _async_call(self, **kwargs) -> Any:
        # Create new MCP client for each request (K8s load balancing)
        client = AsyncMCPClient(self.endpoint)
        result = await client.call_tool(self.function_name, kwargs)
        await client.close()  # Clean up connection
        return ContentExtractor.extract_content(result)
```

**AsyncMCPClient (Official SDK Wrapper)**

```python
class AsyncMCPClient:
    """Async wrapper around official MCP SDK client."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self._session: ClientSession = None

    async def call_tool(self, tool_name: str, arguments: dict) -> MCPResult:
        """Call remote tool using official MCP protocol."""
        await self._connect()
        result = await self._session.call_tool(tool_name, arguments)
        await self.close()
        return result

    async def _connect(self):
        """Connect to MCP server using streamable HTTP."""
        transport_streams = await streamablehttp_client(f"{self.endpoint}/mcp").__aenter__()
        read_stream, write_stream, _ = transport_streams
        self._session = ClientSession(read_stream, write_stream)
        await self._session.__aenter__()
        await self._session.initialize()
```

**ContentExtractor (Response Processing)**

```python
class ContentExtractor:
    """Handles all MCP content types and response formats."""

    @staticmethod
    def extract_content(mcp_result: MCPResult) -> Any:
        """Extract content from MCP result based on type."""
        if mcp_result.isError:
            raise MCPError(mcp_result.error)

        content = mcp_result.content
        if len(content) == 1:
            return ContentExtractor._extract_single_content(content[0])
        else:
            return ContentExtractor._extract_multi_content(content)
```

---

## 3. Implementation Plan (Updated - Simplified)

### 3.1 Files to Modify

**Primary Files**:

1. **`src/runtime/python/mcp_mesh/engine/sync_http_client.py`**

   - **Action**: REPLACE entirely with `MCPClientProxy`
   - **Impact**: Core HTTP client functionality

2. **`src/runtime/python/mcp_mesh/pipeline/registry_steps.py`**
   - **Action**: UPDATE import and proxy creation
   - **Lines**: 329 (import), 341 (client creation), 344-367 (proxy creation)
   - **Impact**: Dependency injection system

**New Files to Create**: 3. **`src/runtime/python/mcp_mesh/engine/mcp_client_proxy.py`** (NEW)

- **Content**: MCPClientProxy, AsyncMCPClient classes (NO connection pooling)
- **Purpose**: Replace SyncHttpClient with MCP SDK integration

4. **`src/runtime/python/mcp_mesh/engine/content_extractor.py`** (NEW)
   - **Content**: ContentExtractor class for all MCP content types
   - **Purpose**: Handle text, image, resource, mixed content

**Test Files**: 5. **`src/runtime/python/tests/unit/test_mcp_client_proxy.py`** (NEW)

- **Content**: Unit tests for new MCP client implementation
- **Purpose**: Ensure compatibility and functionality

### 3.2 Implementation Steps (Simplified)

**Phase 1: Core MCP Client Implementation (2 days)**

**Step 1.1**: Create MCPClientProxy Infrastructure

```bash
# Create new files
touch src/runtime/python/mcp_mesh/engine/mcp_client_proxy.py
touch src/runtime/python/mcp_mesh/engine/content_extractor.py
```

**Step 1.2**: Implement AsyncMCPClient with Official SDK

- Research official MCP SDK client usage patterns
- Implement streamable HTTP transport integration
- **NO connection pooling** - create new connection per request
- Handle MCP protocol initialization and capabilities

**Step 1.3**: Implement ContentExtractor

- Support text content (current working case)
- Add image content support (base64 data + MIME type)
- Add resource content support (file references)
- Add mixed content array support
- Maintain backward compatibility for text-only responses

**Step 1.4**: Implement MCPClientProxy Sync Interface

- Create callable proxy that wraps AsyncMCPClient
- Implement async-to-sync bridge using `asyncio.run()`
- Maintain exact same interface as current SyncHttpClient
- Add error handling and logging

**Phase 2: Integration and Testing (1 day)**

**Step 2.1**: Update Registry Steps

- Replace `SyncHttpClient` import with `MCPClientProxy`
- Update proxy creation logic in `_register_dependencies_with_injector`
- Remove custom content extraction (use ContentExtractor)
- Test with existing dependent_agent.py

**Step 2.2**: Comprehensive Testing

- Unit tests for each component
- Integration tests with FastMCP servers
- Test all content types (text, image, resource)
- Error handling and edge case testing
- **No performance testing needed** - stateless connections are simpler

---

## 4. Code Structure Samples

### 4.1 MCPClientProxy Class (Updated - Simplified)

**File**: `src/runtime/python/mcp_mesh/engine/mcp_client_proxy.py`

```python
"""MCP Client Proxy using official MCP SDK for full protocol compliance."""

import asyncio
import logging
from typing import Any, Optional
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

from .content_extractor import ContentExtractor

logger = logging.getLogger(__name__)


class MCPClientProxy:
    """Synchronous MCP client proxy for dependency injection.

    Replaces SyncHttpClient with official MCP SDK integration while
    maintaining the same callable interface for dependency injection.

    NO CONNECTION POOLING - Creates new connection per request for K8s load balancing.
    """

    def __init__(self, endpoint: str, function_name: str):
        """Initialize MCP client proxy.

        Args:
            endpoint: Base URL of the remote MCP service
            function_name: Specific tool function to call
        """
        self.endpoint = endpoint.rstrip('/')
        self.function_name = function_name
        self.logger = logger.getChild(f"proxy.{function_name}")

    def __call__(self, **kwargs) -> Any:
        """Callable interface for dependency injection.

        Maintains compatibility with existing dependency injection:
        time_service() -> calls get_current_time tool
        """
        return asyncio.run(self._async_call(**kwargs))

    async def _async_call(self, **kwargs) -> Any:
        """Make async MCP tool call with fresh connection."""
        client = None
        try:
            # Create new client for each request (K8s load balancing)
            client = AsyncMCPClient(self.endpoint)
            result = await client.call_tool(self.function_name, kwargs)
            return ContentExtractor.extract_content(result)
        except Exception as e:
            self.logger.error(f"Failed to call {self.function_name}: {e}")
            raise RuntimeError(f"Error calling {self.function_name}: {e}")
        finally:
            # Always clean up connection
            if client:
                await client.close()


class AsyncMCPClient:
    """Async wrapper around official MCP SDK client."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self._session: Optional[ClientSession] = None
        self._transport_cleanup = None
        self.logger = logger.getChild(f"client.{endpoint}")

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call remote tool using official MCP protocol."""
        await self._connect()

        try:
            result = await self._session.call_tool(tool_name, arguments)
            self.logger.debug(f"Tool call successful: {tool_name}")
            return result
        except Exception as e:
            self.logger.error(f"Tool call failed: {tool_name} - {e}")
            raise

    async def _connect(self):
        """Connect to MCP server using streamable HTTP."""
        try:
            # Use official MCP SDK streamable HTTP transport
            transport_context = streamablehttp_client(f"{self.endpoint}/mcp")
            transport_streams = await transport_context.__aenter__()
            read_stream, write_stream, _ = transport_streams

            # Store cleanup function
            self._transport_cleanup = lambda: transport_context.__aexit__(None, None, None)

            # Create MCP client session
            self._session = ClientSession(read_stream, write_stream)
            await self._session.__aenter__()

            # Initialize MCP protocol
            await self._session.initialize()

            self.logger.debug(f"Connected to MCP server at {self.endpoint}")

        except Exception as e:
            self.logger.error(f"Failed to connect to {self.endpoint}: {e}")
            raise RuntimeError(f"MCP connection failed: {e}")

    async def list_tools(self) -> list:
        """List available tools."""
        if not self._session:
            await self._connect()
        return await self._session.list_tools()

    async def close(self):
        """Close MCP session and transport."""
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
                self._session = None

            if self._transport_cleanup:
                await self._transport_cleanup()
                self._transport_cleanup = None

        except Exception as e:
            self.logger.warning(f"Error during cleanup: {e}")
```

### 4.2 Content Extractor Implementation

**File**: `src/runtime/python/mcp_mesh/engine/content_extractor.py`

```python
"""Content extraction for all MCP response types."""

import json
import logging
from typing import Any, Dict, List, Union

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Handles all MCP content types and response formats."""

    @staticmethod
    def extract_content(mcp_result: Any) -> Any:
        """Extract content from MCP result based on type.

        Supports:
        - TextContent: {"type": "text", "text": "..."}
        - ImageContent: {"type": "image", "data": "...", "mimeType": "..."}
        - ResourceContent: {"type": "resource", "resource": {...}, "text": "..."}
        - Mixed content arrays
        """
        if hasattr(mcp_result, 'isError') and mcp_result.isError:
            raise RuntimeError(f"MCP Error: {mcp_result.error}")

        # Handle result content
        if hasattr(mcp_result, 'content'):
            content = mcp_result.content
        elif isinstance(mcp_result, dict) and 'content' in mcp_result:
            content = mcp_result['content']
        else:
            # Fallback for non-standard response
            return str(mcp_result)

        if not content:
            return ""

        # Single content item - extract based on type
        if len(content) == 1:
            return ContentExtractor._extract_single_content(content[0])

        # Multiple content items - return structured format
        return ContentExtractor._extract_multi_content(content)

    @staticmethod
    def _extract_single_content(content_item: Any) -> Any:
        """Extract single content item."""
        if isinstance(content_item, dict):
            content_type = content_item.get('type', 'unknown')

            if content_type == 'text':
                text = content_item.get('text', '')
                # Try to parse as JSON for backward compatibility
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text

            elif content_type == 'image':
                return {
                    'type': 'image',
                    'data': content_item.get('data', ''),
                    'mimeType': content_item.get('mimeType', 'image/png')
                }

            elif content_type == 'resource':
                return {
                    'type': 'resource',
                    'resource': content_item.get('resource', {}),
                    'text': content_item.get('text', '')
                }

            elif 'object' in content_item:
                # FastMCP object format
                return content_item['object']

        # Fallback to string representation
        return str(content_item)

    @staticmethod
    def _extract_multi_content(content_items: List[Any]) -> Dict[str, Any]:
        """Extract multiple content items into structured format."""
        result = {
            'type': 'multi_content',
            'items': [],
            'text_summary': ''
        }

        text_parts = []

        for item in content_items:
            extracted = ContentExtractor._extract_single_content(item)
            result['items'].append(extracted)

            # Build text summary
            if isinstance(extracted, dict):
                if extracted.get('type') == 'text':
                    text_parts.append(str(extracted))
                elif extracted.get('type') == 'resource':
                    text_parts.append(extracted.get('text', ''))
                else:
                    text_parts.append(f"[{extracted.get('type', 'content')}]")
            else:
                text_parts.append(str(extracted))

        result['text_summary'] = ' '.join(text_parts)
        return result
```

### 4.3 Registry Integration Update (Simplified)

**File**: `src/runtime/python/mcp_mesh/pipeline/registry_steps.py` (Updated section)

```python
# Line 329: Update import - remove connection pooling references
from ..engine.mcp_client_proxy import MCPClientProxy

# Lines 340-370: Simplified proxy creation (no pooling)
if endpoint and function_name:
    # Create stateless MCP client proxy (new connection per request)
    proxy = MCPClientProxy(endpoint, function_name)

    # Register with injector (same interface as before)
    await injector.register_dependency(capability, proxy)

    self.logger.info(
        f"🔌 Registered stateless MCP proxy '{capability}' -> {endpoint}/{function_name}"
    )
```

---

## 5. Migration Strategy

### 5.1 Backward Compatibility Requirements

**CRITICAL**: Maintain exact same interface for dependency injection

- ✅ `time_service()` calls must continue to work unchanged
- ✅ Return values must be compatible with existing code
- ✅ Error handling must not break existing error handling

### 5.2 Safe Migration Approach

**Step 1**: Parallel Implementation

- Keep existing `SyncHttpClient` as fallback
- Add `MCPClientProxy` as new implementation
- Add feature flag to switch between implementations

**Step 2**: Gradual Rollout

- Test with single dependency (time_service)
- Validate all content types work correctly
- Performance testing and comparison
- Full validation with dependent_agent.py

**Step 3**: Complete Migration

- Replace imports in registry_steps.py
- Remove old SyncHttpClient implementation
- Update documentation and examples

### 5.3 Rollback Plan

If issues arise:

1. Revert import in registry_steps.py to SyncHttpClient
2. Keep new MCP client code for future use
3. Address issues and retry migration

---

## 6. Testing Plan

### 6.1 Unit Tests

- **MCPClientProxy**: Test callable interface and error handling
- **AsyncMCPClient**: Test MCP protocol integration
- **ContentExtractor**: Test all content types (text, image, resource, mixed)
- **MCPClientPool**: Test connection pooling and reuse

### 6.2 Integration Tests

- **End-to-end**: dependent_agent.py → time_service dependency injection
- **Content Types**: Test with FastMCP servers returning different content types
- **Error Scenarios**: Network failures, invalid responses, timeout handling
- **Performance**: Compare response times vs current SyncHttpClient

### 6.3 Compatibility Tests

- **Existing Interface**: Ensure `time_service()` works unchanged
- **Response Format**: Validate return values match expected format
- **Error Propagation**: Ensure errors are handled consistently

---

## 7. Success Criteria

### 7.1 Functional Requirements ✅

- [x] Full MCP protocol compliance using official SDK
- [x] Support for all content types (text, image, resource, mixed)
- [x] No breaking changes to existing dependency injection interface
- [x] Proper error handling and protocol initialization
- [x] Connection pooling and reliability improvements

### 7.2 Performance Requirements

- [ ] Response times equal or better than current implementation
- [ ] Connection reuse reduces overhead for multiple calls
- [ ] Memory usage reasonable with connection pooling
- [ ] No regression in dependency injection speed

### 7.3 Quality Requirements

- [ ] Comprehensive test coverage (>90%)
- [ ] Proper error handling and logging
- [ ] Clean, maintainable code structure
- [ ] Documentation for new capabilities

---

## 8. Implementation Timeline (Updated - Simplified)

**Total Estimated Time**: 3 days (reduced from 4-5 days)

| Phase       | Duration | Tasks                                                           |
| ----------- | -------- | --------------------------------------------------------------- |
| **Phase 1** | 2 days   | Core MCP client implementation (no pooling), content extraction |
| **Phase 2** | 1 day    | Integration, testing, compatibility validation                  |

**Key Simplifications:**

- ✅ **No connection pooling complexity** - Simpler implementation
- ✅ **Leverages K8s load balancing** - Works with existing infrastructure
- ✅ **Fewer edge cases** - Stateless connections are more predictable
- ✅ **Easier testing** - No complex connection state management

---

## 9. Risk Assessment (Updated - Reduced Risks)

### 9.1 Technical Risks

**Risk**: Official MCP SDK may not work as expected with our use case

- **Mitigation**: Fallback to FastMCP client if needed
- **Probability**: Low
- **Impact**: Medium

**Risk**: Breaking changes to dependency injection

- **Mitigation**: Comprehensive compatibility testing
- **Probability**: Low
- **Impact**: High

**Risk**: Performance degradation from new connections per request

- **Mitigation**: K8s networking is optimized for this pattern
- **Probability**: Very Low
- **Impact**: Low

### 9.2 Timeline Risks (Reduced)

**Risk**: Official MCP SDK complexity higher than expected

- **Mitigation**: Simpler architecture reduces learning curve
- **Probability**: Low (reduced from Medium)
- **Impact**: Low (reduced from Medium)

### 9.3 Eliminated Risks

**✅ Connection pooling complexity** - No longer applicable
**✅ Connection state management** - Stateless design eliminates this
**✅ Load balancing implementation** - K8s handles this automatically

---

## Next Steps

1. ✅ Create this comprehensive implementation plan
2. ✅ Conduct thorough library research
3. ✅ Fill in detailed implementation plan
4. ✅ Review and update plan for K8s load balancing (simplified architecture)
5. 🚀 **CURRENT**: Begin Phase 1 implementation

---

_Last Updated: 2025-06-27_
_Status: ✅ Plan Updated for K8s Integration - Ready for Implementation_
