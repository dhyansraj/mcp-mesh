"""
Media storage abstraction for MCP Mesh agents.

Provides a pluggable backend for storing and retrieving binary media
(images, audio, files) that can be referenced via resource_link content items.
"""

import asyncio
import logging
import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..shared.config_resolver import ValidationRule, get_config_value

logger = logging.getLogger(__name__)


class MediaStore(ABC):
    """Abstract base class for media storage backends."""

    @abstractmethod
    async def upload(self, data: bytes, filename: str, mime_type: str) -> str:
        """Upload media data and return a URI referencing the stored object.

        Args:
            data: Raw bytes of the media content.
            filename: Desired filename (used as key/suffix in the store).
            mime_type: MIME type of the content (e.g. "image/png").

        Returns:
            A URI string that can be used to retrieve the media later.
        """

    @abstractmethod
    async def fetch(self, uri: str) -> tuple[bytes, str]:
        """Fetch media by URI.

        Args:
            uri: The URI returned by a previous ``upload`` call.

        Returns:
            A tuple of (raw_bytes, mime_type).
        """

    @abstractmethod
    async def exists(self, uri: str) -> bool:
        """Check whether media exists at the given URI.

        Args:
            uri: The URI to check.

        Returns:
            True if the media exists, False otherwise.
        """


class LocalMediaStore(MediaStore):
    """File-system backed media store."""

    def __init__(self) -> None:
        base = get_config_value(
            "MCP_MESH_MEDIA_STORAGE_PATH",
            default="/tmp/mcp-mesh-media",
            rule=ValidationRule.STRING_RULE,
        )
        prefix = get_config_value(
            "MCP_MESH_MEDIA_STORAGE_PREFIX",
            default="media/",
            rule=ValidationRule.STRING_RULE,
        )
        self._base_path = Path(base)
        self._prefix = prefix

    def _validate_path(self, path: Path) -> None:
        """Raise ValueError if *path* escapes the base directory (path traversal)."""
        if not str(path.resolve()).startswith(str(self._base_path.resolve())):
            raise ValueError(f"Invalid filename (path traversal): {path}")

    async def upload(self, data: bytes, filename: str, mime_type: str) -> str:
        dest_dir = self._base_path / self._prefix
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        self._validate_path(dest)
        dest.write_bytes(data)
        logger.debug("Stored %d bytes to %s", len(data), dest)
        return f"file://{dest}"

    async def fetch(self, uri: str) -> tuple[bytes, str]:
        path = Path(uri.removeprefix("file://"))
        self._validate_path(path)
        if not path.exists():
            raise FileNotFoundError(f"Media not found: {uri}")
        data = path.read_bytes()
        guessed, _ = mimetypes.guess_type(path.name)
        mime_type = guessed or "application/octet-stream"
        return data, mime_type

    async def exists(self, uri: str) -> bool:
        path = Path(uri.removeprefix("file://"))
        self._validate_path(path)
        return path.exists()


class S3MediaStore(MediaStore):
    """S3-compatible media store (requires boto3 at runtime)."""

    def __init__(self) -> None:
        self._bucket: str = get_config_value(
            "MCP_MESH_MEDIA_STORAGE_BUCKET",
            default="mcp-mesh-media",
            rule=ValidationRule.STRING_RULE,
        )
        endpoint: str | None = get_config_value(
            "MCP_MESH_MEDIA_STORAGE_ENDPOINT",
            default=None,
            rule=ValidationRule.STRING_RULE,
        )
        self._prefix: str = get_config_value(
            "MCP_MESH_MEDIA_STORAGE_PREFIX",
            default="media/",
            rule=ValidationRule.STRING_RULE,
        )

        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for S3 media storage. "
                "Install it with: pip install boto3"
            ) from exc

        kwargs: dict = {}
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        self._client = boto3.client("s3", **kwargs)

    def _key(self, filename: str) -> str:
        return f"{self._prefix}{filename}"

    async def upload(self, data: bytes, filename: str, mime_type: str) -> str:
        key = self._key(filename)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=mime_type,
        )
        logger.debug("Uploaded %d bytes to s3://%s/%s", len(data), self._bucket, key)
        return f"s3://{self._bucket}/{key}"

    async def fetch(self, uri: str) -> tuple[bytes, str]:
        # Parse s3://bucket/key
        without_scheme = uri.removeprefix("s3://")
        bucket, _, key = without_scheme.partition("/")
        resp = await asyncio.to_thread(self._client.get_object, Bucket=bucket, Key=key)
        data = await asyncio.to_thread(resp["Body"].read)
        mime_type = resp.get("ContentType", "application/octet-stream")
        return data, mime_type

    async def exists(self, uri: str) -> bool:
        from botocore.exceptions import ClientError

        without_scheme = uri.removeprefix("s3://")
        bucket, _, key = without_scheme.partition("/")
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise


# ── singleton factory ──────────────────────────────────────────────

_instance: MediaStore | None = None


def get_media_store() -> MediaStore:
    """Return a cached MediaStore instance based on configuration.

    Reads ``MCP_MESH_MEDIA_STORAGE`` to choose the backend:
    - ``"local"`` (default) -> :class:`LocalMediaStore`
    - ``"s3"`` -> :class:`S3MediaStore`
    """
    global _instance
    if _instance is not None:
        return _instance

    backend = get_config_value(
        "MCP_MESH_MEDIA_STORAGE",
        default="local",
        rule=ValidationRule.STRING_RULE,
    )

    if backend == "s3":
        _instance = S3MediaStore()
    else:
        _instance = LocalMediaStore()

    logger.info("Initialized media store: %s", type(_instance).__name__)
    return _instance
