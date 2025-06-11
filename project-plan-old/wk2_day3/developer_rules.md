# MCP Mesh Development Rules

## Core Development Principles

### Rule 1: No Reinventing Wheels - Use MCP SDK As-Is
- **First Priority**: Always check if functionality exists in the official MCP SDK
- **Use Native Features**: Leverage MCP SDK's built-in capabilities (protocol, transport, decorators)
- **Avoid Duplication**: Don't create custom implementations of existing MCP SDK features
- **Example**: Use `@app.tool()` decorator from MCP SDK, not custom tool registration

### Rule 2: Complement MCP SDK - Fill Genuine Gaps
- **Only When Necessary**: Add functionality ONLY when MCP SDK lacks essential capabilities
- **Identify Real Gaps**: Ensure the missing functionality is genuinely needed
- **Work Alongside**: Complement, don't replace MCP SDK features
- **Package Separation**: Extract non-runtime parts to `mcp-mesh-types` package
- **Example**: File operations (MCP SDK has none), security validation (MCP SDK lacks)

### Rule 3: Enhance MCP SDK - Add Value Layer
- **Last Resort**: Only after confirming Rules 1 and 2 don't apply
- **Preserve Compatibility**: Enhancements must maintain full MCP SDK compatibility
- **Dual Integration**: Use alongside MCP SDK features, not instead of them
- **Package Separation**: Extract interfaces to `mcp-mesh-types`, implementations to `mcp-mesh`
- **Example**: Mesh integration via `@mesh_agent` + `@app.tool()` dual decorators

## Package Architecture Requirements

### When Implementing Rules 2 & 3: Dual-Package Strategy

**📦 `mcp-mesh-types` Package (Non-Runtime Components)**
- **Abstract Base Classes**: Interface definitions and contracts
- **Exception Classes**: Error types and hierarchies  
- **Decorator Stubs**: No-op decorators that preserve metadata
- **Type Definitions**: Protocols, TypedDicts, Enums
- **Zero Dependencies**: Except `mcp` for MCP SDK compatibility
- **No Implementations**: Only interfaces and stubs

**📦 `mcp-mesh` Package (Full Runtime Implementation)**
- **Concrete Implementations**: Full feature implementations
- **Runtime Logic**: Service mesh functionality, networking, monitoring
- **Enhanced Decorators**: Active mesh integration decorators
- **Dependencies**: All required runtime libraries
- **Depends on**: `mcp-mesh-types` package

### Extraction Guidelines

When complementing or enhancing MCP SDK:

1. **Extract to `mcp-mesh-types`**:
   ```python
   # Abstract classes
   class FileOperations(ABC):
       @abstractmethod
       async def read_file(self, path: str) -> str: ...
   
   # Exception classes
   class FileOperationError(Exception): ...
   class SecurityValidationError(FileOperationError): ...
   
   # No-op decorators
   def mesh_agent(**kwargs):
       def decorator(func):
           func._mesh_config = kwargs
           return func
       return decorator
   ```

2. **Implement in `mcp-mesh`**:
   ```python
   # Concrete implementations
   class EnhancedFileOperations(FileOperations):
       async def read_file(self, path: str) -> str:
           # Full implementation with mesh features
           await self._validate_security(path)
           return await super().read_file(path)
   
   # Active decorators with runtime logic
   def mesh_agent(**kwargs):
       # Full mesh integration implementation
       pass
   ```

## Implementation Guidelines

### MCP SDK Compliance Requirements
- **Always use `@app.tool()` or `@server.tool()` for MCP protocol compliance**
- **Never bypass MCP SDK's protocol handling**
- **All examples must work in vanilla MCP environments**
- **Import from `mcp-mesh-types` (interfaces) not `mcp-mesh` (implementation) in examples**

### Sample Code Requirements

**✅ Correct Sample Imports**:
```python
# All samples MUST import from mcp-mesh-types
from mcp_mesh_types.decorators import mesh_agent
from mcp_mesh_types.tools.file_operations import FileOperations
from mcp_mesh_types.exceptions import FileOperationError
```

**❌ Forbidden Sample Imports**:
```python
# NEVER import from mcp-mesh in samples
from mcp_mesh.decorators import mesh_agent  # ❌ FORBIDDEN
from mcp_mesh.tools import FileOperations   # ❌ FORBIDDEN
from mcp_mesh import *                      # ❌ FORBIDDEN
```

**🎯 Sample Code Rules**:
- **Zero references to `mcp-mesh` package in any sample code**
- **All imports must be from `mcp-mesh-types` only**
- **Samples must work with just `pip install mcp mcp-mesh-types`**
- **No runtime dependencies on full mesh implementation**

### Architecture Patterns
- **Dual-Decorator Pattern**: `@app.tool()` + `@mesh_agent()` for enhanced functionality
- **Dual-Package Strategy**: Core interfaces (`mcp-mesh-types`) + full implementation (`mcp-mesh`)
- **Progressive Enhancement**: Basic functionality with types package, advanced with full package
- **Graceful Degradation**: Mesh features work as no-ops when infrastructure unavailable

### Code Quality Standards
- **MCP Protocol First**: Ensure MCP compliance before adding mesh features
- **Zero Breaking Changes**: Mesh enhancements must not break MCP compatibility
- **Community Ready**: All examples must demonstrate proper MCP SDK usage patterns
- **Industry Standards**: Follow Python packaging conventions (types suffix for interfaces)

## Decision Flow

When adding functionality, follow this decision tree:

1. **Does MCP SDK provide this?** → Use MCP SDK (Rule 1)
2. **Is this missing from MCP SDK but essential?** → Complement MCP SDK (Rule 2)
   - Extract interfaces/errors to `mcp-mesh-types`
   - Implement functionality in `mcp-mesh`
3. **Do we need to enhance existing MCP functionality?** → Enhance MCP SDK (Rule 3)
   - Extract decorator stubs to `mcp-mesh-types`
   - Implement enhanced decorators in `mcp-mesh`

## Examples

### ✅ Correct Implementation

**File Structure:**
```
mcp-mesh-types/
├── decorators.py     # No-op @mesh_agent stub
├── exceptions.py     # FileOperationError, SecurityValidationError
└── tools/
    └── file_operations.py  # Abstract FileOperations class

mcp-mesh/
├── decorators.py     # Full @mesh_agent implementation
└── tools/
    └── file_operations.py  # Concrete FileOperations with mesh features
```

**Sample Code:**
```python
from mcp.server.fastmcp import FastMCP
from mcp_mesh_types.decorators import mesh_agent  # ✅ From types package
from mcp_mesh_types.tools.file_operations import FileOperations  # ✅ From types package

app = FastMCP("file-agent")

@app.tool()           # Rule 1: Use MCP SDK as-is
@mesh_agent()         # Rule 3: Enhance with mesh features (from types)
async def read_file(path: str) -> str:
    # Rule 2: Add missing file operations with security
    file_ops = FileOperations()  # Uses types package interface
    return await file_ops.read_file(path)
```

### ❌ Incorrect Implementation

**Wrong Package Usage:**
```python
# Don't import from implementation package in samples
from mcp_mesh.tools import FileOperations        # ❌ Violates sample rules
from mcp_mesh.decorators import mesh_agent       # ❌ Breaks vanilla MCP

# Don't create custom tool registration when MCP SDK provides it
@custom_tool_decorator()  # ❌ Violates Rule 1
async def read_file(path: str) -> str:
    return open(path).read()
```

**Wrong Package Structure:**
```python
# Don't put implementations in types package
# mcp-mesh-types/decorators.py
def mesh_agent(**kwargs):
    # ❌ Full implementation in types package
    await setup_mesh_infrastructure()  # Runtime logic doesn't belong here
```

## Validation Checklist

Before implementing any feature:
- [ ] Checked if MCP SDK already provides this functionality
- [ ] Confirmed the gap is genuine and essential
- [ ] Designed to work alongside, not replace MCP SDK
- [ ] Maintains full MCP protocol compliance
- [ ] **Extracted interfaces/stubs to `mcp-mesh-types` package**
- [ ] **Implemented runtime logic in `mcp-mesh` package only**
- [ ] **All samples import from `mcp-mesh-types` only**
- [ ] **No references to `mcp-mesh` in any sample code**
- [ ] Works in vanilla MCP environment with types package
- [ ] Examples demonstrate proper MCP SDK patterns
- [ ] Follows dual-package architecture (types vs implementation)

## Community and Open Source Readiness

### MCP SDK Integration
- **Show MCP First**: All examples must demonstrate MCP SDK compliance first
- **Mesh as Enhancement**: Present mesh features as optional enhancements
- **Clear Upgrade Path**: Users can start with MCP SDK and add mesh gradually
- **No Confusion**: Community should never think we bypass official MCP SDK

### Package Strategy
- **`mcp-mesh-types`**: Lightweight interfaces for vanilla MCP compatibility
- **`mcp-mesh`**: Full implementation with advanced mesh features
- **Progressive Installation**: Start with types, upgrade to full package when ready
- **Zero Import Errors**: Examples work without runtime dependencies on full package
- **Sample Isolation**: All samples use types package only, never full implementation

### Sample Code Standards
- **Vanilla MCP Compatible**: Every sample works with `pip install mcp mcp-mesh-types`
- **No Implementation Dependencies**: Samples never import from `mcp-mesh` package
- **Clear Documentation**: Show both vanilla and enhanced usage scenarios
- **Progressive Enhancement**: Demonstrate how features activate when full package installed

---

*These rules ensure we build a complementary ecosystem around MCP SDK rather than competing with or replacing it, while maintaining clean package separation and vanilla MCP compatibility in all examples.*