"""Public media helpers for mesh agents."""

from mcp.types import ResourceLink

from _mcp_mesh.media import get_media_store


async def upload_media(data: bytes, filename: str, mime_type: str) -> str:
    """Upload media and return a URI."""
    store = get_media_store()
    return await store.upload(data, filename, mime_type)


def media_result(
    uri: str,
    name: str,
    mime_type: str,
    description: str = None,
    size: int = None,
) -> ResourceLink:
    """Create a resource_link content item for tool results.

    Returns an MCP ResourceLink that FastMCP will send as a proper
    resource_link content type in the MCP protocol.
    """
    kwargs = {
        "type": "resource_link",
        "uri": uri,
        "name": name,
        "mimeType": mime_type,
    }
    if description is not None:
        kwargs["description"] = description
    if size is not None:
        kwargs["size"] = size
    return ResourceLink(**kwargs)
