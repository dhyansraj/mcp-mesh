"""Unit tests for MediaStore abstraction."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add the Python runtime source to the path so imports work outside tox
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "src" / "runtime" / "python")
)

import _mcp_mesh.media.media_store as media_store_mod
from _mcp_mesh.media.media_store import LocalMediaStore, get_media_store


class TestLocalMediaStoreUploadFetch:
    """Test upload/fetch round-trip with LocalMediaStore."""

    @pytest.fixture()
    def store(self, tmp_path):
        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=lambda env_var, default=None, rule=None: {
                "MCP_MESH_MEDIA_STORAGE_PATH": str(tmp_path),
                "MCP_MESH_MEDIA_STORAGE_PREFIX": "media/",
            }.get(env_var, default),
        ):
            return LocalMediaStore()

    @pytest.mark.asyncio
    async def test_upload_creates_file(self, store, tmp_path):
        uri = await store.upload(b"hello world", "test.txt", "text/plain")
        assert uri.startswith("file://")
        path = Path(uri.removeprefix("file://"))
        assert path.exists()
        assert path.read_bytes() == b"hello world"

    @pytest.mark.asyncio
    async def test_round_trip(self, store):
        data = b"\x89PNG\r\n\x1a\n fake png data"
        uri = await store.upload(data, "image.png", "image/png")
        fetched_data, mime = await store.fetch(uri)
        assert fetched_data == data
        assert mime == "image/png"

    @pytest.mark.asyncio
    async def test_round_trip_unknown_extension(self, store):
        data = b"binary blob"
        uri = await store.upload(data, "data.xyz123", "application/octet-stream")
        fetched_data, mime = await store.fetch(uri)
        assert fetched_data == data
        # Unknown extension -> fallback mime type
        assert mime == "application/octet-stream"


class TestLocalMediaStoreExists:
    """Test exists() behavior."""

    @pytest.fixture()
    def store(self, tmp_path):
        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=lambda env_var, default=None, rule=None: {
                "MCP_MESH_MEDIA_STORAGE_PATH": str(tmp_path),
                "MCP_MESH_MEDIA_STORAGE_PREFIX": "media/",
            }.get(env_var, default),
        ):
            return LocalMediaStore()

    @pytest.mark.asyncio
    async def test_exists_false_before_upload(self, store, tmp_path):
        assert await store.exists(f"file://{tmp_path}/media/nonexistent.txt") is False

    @pytest.mark.asyncio
    async def test_exists_true_after_upload(self, store):
        uri = await store.upload(b"data", "check.bin", "application/octet-stream")
        assert await store.exists(uri) is True

    @pytest.mark.asyncio
    async def test_fetch_missing_raises(self, store, tmp_path):
        with pytest.raises(FileNotFoundError):
            await store.fetch(f"file://{tmp_path}/media/nope.bin")


class TestGetMediaStore:
    """Test the singleton factory."""

    def setup_method(self):
        # Reset singleton between tests
        media_store_mod._instance = None

    def teardown_method(self):
        media_store_mod._instance = None

    def test_default_returns_local(self, tmp_path):
        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=lambda env_var, default=None, rule=None: {
                "MCP_MESH_MEDIA_STORAGE": "local",
                "MCP_MESH_MEDIA_STORAGE_PATH": str(tmp_path),
                "MCP_MESH_MEDIA_STORAGE_PREFIX": "media/",
            }.get(env_var, default),
        ):
            store = get_media_store()
            assert isinstance(store, LocalMediaStore)

    def test_singleton_returns_same_instance(self, tmp_path):
        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=lambda env_var, default=None, rule=None: {
                "MCP_MESH_MEDIA_STORAGE": "local",
                "MCP_MESH_MEDIA_STORAGE_PATH": str(tmp_path),
                "MCP_MESH_MEDIA_STORAGE_PREFIX": "media/",
            }.get(env_var, default),
        ):
            store1 = get_media_store()
            store2 = get_media_store()
            assert store1 is store2
