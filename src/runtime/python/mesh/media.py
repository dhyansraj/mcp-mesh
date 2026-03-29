"""Public media helpers for mesh agents."""

from __future__ import annotations

from mcp.types import ResourceLink

from _mcp_mesh.media import get_media_store


async def upload_media(data: bytes, filename: str, mime_type: str) -> str:
    """Upload media and return a URI."""
    store = get_media_store()
    return await store.upload(data, filename, mime_type)


async def download_media(uri: str) -> tuple[bytes, str]:
    """Download media by URI.

    Args:
        uri: Media URI (e.g., "file:///..." or "s3://...").

    Returns:
        A tuple of (raw_bytes, mime_type).
    """
    store = get_media_store()
    return await store.fetch(uri)


def media_result(
    uri: str,
    name: str,
    mime_type: str,
    description: str | None = None,
    size: int | None = None,
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


class MediaResult:
    """Convenience class: upload bytes and return a ResourceLink in one step.

    Usage::

        return await mesh.MediaResult(
            data=png_bytes,
            filename="chart.png",
            mime_type="image/png",
            name="Sales Chart",
            description="Quarterly revenue chart",
        )
    """

    def __init__(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
        name: str | None = None,
        description: str | None = None,
    ):
        self.data = data
        self.filename = filename
        self.mime_type = mime_type
        self.name = name or filename
        self.description = description

    def __await__(self):
        return self._upload().__await__()

    async def _upload(self) -> ResourceLink:
        uri = await upload_media(self.data, self.filename, self.mime_type)
        return media_result(
            uri=uri,
            name=self.name,
            mime_type=self.mime_type,
            description=self.description,
            size=len(self.data),
        )
