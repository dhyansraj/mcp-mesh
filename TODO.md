# MCP Mesh TODO List

## Completed Tasks

- [x] Investigate why decorators must be outside main() for mcp_mesh_runtime auto-import to work
  - **Finding**: Decorators must be applied at module level (when the module is imported) for the auto-enhancement mechanism to detect and process them

## Pending Tasks

### High Priority

- [ ] Document the requirement that @mesh_agent decorators must be applied at module level, not inside main()
  - This is critical for proper functionality and should be added to developer documentation

### Medium Priority

- [ ] Address multiple functions with same capability in hello_world.py

  - Currently hello_world.py has multiple functions providing "greeting" capability
  - Need to determine how this affects service discovery and proxy generation

- [ ] Decide on pattern for capability naming when multiple functions provide same capability

  - Options: versioning (greeting:v1, greeting:v2), namespacing (greeting.basic, greeting.enhanced), or other patterns

- [ ] Update hello_world.py to demonstrate clearer capability patterns

  - Consider using greeting_basic vs greeting_enhanced to show different capability names

- [ ] Document how registry handles multiple providers for same capability
  - First wins? Last wins? Selection criteria?
  - How does the proxy choose which provider to use?

## Notes

- The decorator placement issue was discovered when system_agent.py wasn't showing registration logs
- Moving decorators to a create_server() function (outside main) fixed the issue
- Both hello_world.py and system_agent.py now follow the same pattern
