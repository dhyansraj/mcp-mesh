"""Unit tests for MediaStore abstraction."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestS3MediaStoreFailFast:
    """Issue #846: S3MediaStore must fail-fast on misconfiguration at startup
    (not at first LLM call).

    The constructor is the validation surface — when MCP_MESH_MEDIA_STORAGE=s3
    is set explicitly, missing boto3, missing bucket, or (opt-in) bad creds
    must raise immediately rather than silently producing a broken store.
    """

    def setup_method(self):
        media_store_mod._instance = None

    def teardown_method(self):
        media_store_mod._instance = None

    def _config(self, **overrides):
        """Build a config_value side_effect with sensible s3 defaults."""
        base = {
            "MCP_MESH_MEDIA_STORAGE": "s3",
            "MCP_MESH_MEDIA_STORAGE_BUCKET": "test-bucket",
            "MCP_MESH_MEDIA_STORAGE_ENDPOINT": None,
            "MCP_MESH_MEDIA_STORAGE_PREFIX": "media/",
            "MCP_MESH_MEDIA_STORAGE_VALIDATE": "false",
        }
        base.update(overrides)
        return lambda env_var, default=None, rule=None: base.get(env_var, default)

    def test_missing_bucket_raises_value_error(self):
        """Issue #846 #1: bucket must be explicit — no silent default."""
        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=self._config(MCP_MESH_MEDIA_STORAGE_BUCKET=None),
        ):
            with pytest.raises(ValueError, match="MCP_MESH_MEDIA_STORAGE_BUCKET"):
                get_media_store()

    def test_missing_boto3_raises_at_construction(self):
        """Issue #846 #2: boto3 ImportError must surface at startup, not lazily."""
        # Simulate boto3 not being importable.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=self._config(),
        ), patch.object(builtins, "__import__", side_effect=fake_import):
            with pytest.raises(ImportError, match="boto3 is required"):
                get_media_store()

    def test_valid_config_with_mocked_boto3_succeeds(self):
        """Working path: boto3 present, bucket set, validate off -> store ready."""
        fake_boto3 = MagicMock()
        fake_client = MagicMock()
        fake_boto3.client.return_value = fake_client

        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=self._config(),
        ), patch.dict(sys.modules, {"boto3": fake_boto3}):
            store = get_media_store()
            assert type(store).__name__ == "S3MediaStore"
            # head_bucket must NOT have been called (validate=false default)
            fake_client.head_bucket.assert_not_called()

    def test_validate_enabled_calls_head_bucket(self):
        """Opt-in probe: head_bucket runs when MCP_MESH_MEDIA_STORAGE_VALIDATE=true."""
        fake_boto3 = MagicMock()
        fake_client = MagicMock()
        fake_boto3.client.return_value = fake_client
        botocore_pkg, botoexc = self._fake_botocore_exceptions()

        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=self._config(MCP_MESH_MEDIA_STORAGE_VALIDATE="true"),
        ), patch.dict(
            sys.modules,
            {"boto3": fake_boto3, "botocore": botocore_pkg, "botocore.exceptions": botoexc},
        ):
            store = get_media_store()
            assert type(store).__name__ == "S3MediaStore"
            fake_client.head_bucket.assert_called_once_with(Bucket="test-bucket")

    def _fake_botocore_exceptions(self):
        """Build a fake botocore.exceptions module shim with the two error types
        the probe handler imports. Lets these tests run without botocore installed."""
        import types

        mod = types.ModuleType("botocore.exceptions")

        class NoCredentialsError(Exception):
            def __init__(self):
                super().__init__("Unable to locate credentials")

        class ClientError(Exception):
            def __init__(self, error_response, operation_name):
                super().__init__(str(error_response))
                self.response = error_response
                self.operation_name = operation_name

        mod.NoCredentialsError = NoCredentialsError
        mod.ClientError = ClientError
        parent = types.ModuleType("botocore")
        parent.exceptions = mod
        return parent, mod

    def test_validate_no_credentials_raises_runtime_error(self):
        """Probe surfaces NoCredentialsError as a clear RuntimeError naming the env vars."""
        fake_boto3 = MagicMock()
        fake_client = MagicMock()
        fake_boto3.client.return_value = fake_client
        botocore_pkg, botoexc = self._fake_botocore_exceptions()
        fake_client.head_bucket.side_effect = botoexc.NoCredentialsError()

        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=self._config(MCP_MESH_MEDIA_STORAGE_VALIDATE="true"),
        ), patch.dict(
            sys.modules,
            {"boto3": fake_boto3, "botocore": botocore_pkg, "botocore.exceptions": botoexc},
        ):
            with pytest.raises(RuntimeError, match="AWS credentials not found"):
                get_media_store()

    def test_validate_client_error_raises_runtime_error_with_code(self):
        """Probe surfaces a ClientError (e.g. NoSuchBucket) with the error code."""
        fake_boto3 = MagicMock()
        fake_client = MagicMock()
        fake_boto3.client.return_value = fake_client
        botocore_pkg, botoexc = self._fake_botocore_exceptions()
        fake_client.head_bucket.side_effect = botoexc.ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "nope"}}, "HeadBucket"
        )

        with patch(
            "_mcp_mesh.media.media_store.get_config_value",
            side_effect=self._config(MCP_MESH_MEDIA_STORAGE_VALIDATE="true"),
        ), patch.dict(
            sys.modules,
            {"boto3": fake_boto3, "botocore": botocore_pkg, "botocore.exceptions": botoexc},
        ):
            with pytest.raises(RuntimeError, match="NoSuchBucket"):
                get_media_store()
