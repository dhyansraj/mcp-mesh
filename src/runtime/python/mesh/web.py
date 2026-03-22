"""Web framework media utilities for mesh agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import UploadFile

from _mcp_mesh.media import get_media_store


class MediaUpload:
    """Result of saving an upload to MediaStore."""

    __slots__ = ("uri", "name", "mime_type", "size")

    def __init__(self, uri: str, name: str, mime_type: str, size: int):
        self.uri = uri
        self.name = name
        self.mime_type = mime_type
        self.size = size


async def save_upload(
    upload: "UploadFile",
    filename: str | None = None,
    mime_type: str | None = None,
) -> str:
    """Save a FastAPI UploadFile to MediaStore and return the URI.

    Args:
        upload: FastAPI UploadFile object.
        filename: Override filename (defaults to upload.filename).
        mime_type: Override MIME type (defaults to upload.content_type).

    Returns:
        Media URI (e.g., "file:///tmp/mcp-mesh-media/media/photo.jpg").
    """
    data = await upload.read()
    fname = filename or upload.filename or "upload"
    mtype = mime_type or upload.content_type or "application/octet-stream"
    store = get_media_store()
    return await store.upload(data, fname, mtype)


async def save_upload_result(
    upload: "UploadFile",
    filename: str | None = None,
    mime_type: str | None = None,
) -> MediaUpload:
    """Save a FastAPI UploadFile and return a MediaUpload with metadata."""
    data = await upload.read()
    fname = filename or upload.filename or "upload"
    mtype = mime_type or upload.content_type or "application/octet-stream"
    store = get_media_store()
    uri = await store.upload(data, fname, mtype)
    return MediaUpload(uri=uri, name=fname, mime_type=mtype, size=len(data))
