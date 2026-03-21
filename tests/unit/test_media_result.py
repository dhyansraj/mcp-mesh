"""Unit tests for MediaResult class and web upload utilities."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add the Python runtime source to the path so imports work outside tox
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "src" / "runtime" / "python")
)

from mesh.media import MediaResult
from mesh.web import MediaUpload, save_upload, save_upload_result


def _make_mock_store(tmp_path):
    """Create a mock MediaStore whose upload() writes to tmp_path and returns a URI."""
    store = AsyncMock()

    async def _upload(data: bytes, filename: str, mime_type: str) -> str:
        dest = tmp_path / "media" / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return f"file://{dest}"

    store.upload = AsyncMock(side_effect=_upload)
    return store


class TestMediaResult:
    @pytest.mark.asyncio
    async def test_uploads_and_returns_resource_link(self, tmp_path):
        """MediaResult uploads bytes and returns ResourceLink."""
        mock_store = _make_mock_store(tmp_path)
        with patch("mesh.media.get_media_store", return_value=mock_store):
            result = await MediaResult(
                data=b"PNG data here",
                filename="test.png",
                mime_type="image/png",
                name="Test Image",
                description="A test image",
            )
        assert result.type == "resource_link"
        assert result.name == "Test Image"
        assert result.mimeType == "image/png"
        assert result.description == "A test image"

    @pytest.mark.asyncio
    async def test_defaults_name_to_filename(self, tmp_path):
        """MediaResult defaults name to filename when name is not provided."""
        mock_store = _make_mock_store(tmp_path)
        with patch("mesh.media.get_media_store", return_value=mock_store):
            result = await MediaResult(
                data=b"data",
                filename="photo.jpg",
                mime_type="image/jpeg",
            )
        assert result.name == "photo.jpg"

    @pytest.mark.asyncio
    async def test_size_matches_data(self, tmp_path):
        """MediaResult sets size to len(data)."""
        data = b"0123456789"
        mock_store = _make_mock_store(tmp_path)
        with patch("mesh.media.get_media_store", return_value=mock_store):
            result = await MediaResult(
                data=data,
                filename="numbers.bin",
                mime_type="application/octet-stream",
            )
        assert result.size == len(data)

    @pytest.mark.asyncio
    async def test_uri_is_set(self, tmp_path):
        """MediaResult sets the uri from the store."""
        mock_store = _make_mock_store(tmp_path)
        with patch("mesh.media.get_media_store", return_value=mock_store):
            result = await MediaResult(
                data=b"content",
                filename="doc.pdf",
                mime_type="application/pdf",
                name="Document",
            )
        assert "doc.pdf" in str(result.uri)

    @pytest.mark.asyncio
    async def test_calls_store_upload(self, tmp_path):
        """MediaResult invokes store.upload with correct arguments."""
        mock_store = _make_mock_store(tmp_path)
        with patch("mesh.media.get_media_store", return_value=mock_store):
            await MediaResult(
                data=b"abc",
                filename="file.txt",
                mime_type="text/plain",
            )
        mock_store.upload.assert_awaited_once_with(b"abc", "file.txt", "text/plain")


def _make_upload_file(data: bytes, filename: str, content_type: str):
    """Create a mock FastAPI UploadFile."""
    upload = AsyncMock()
    upload.read = AsyncMock(return_value=data)
    upload.filename = filename
    upload.content_type = content_type
    return upload


class TestSaveUpload:
    @pytest.mark.asyncio
    async def test_returns_uri(self, tmp_path):
        """save_upload stores file and returns URI."""
        mock_store = _make_mock_store(tmp_path)
        upload = _make_upload_file(b"image data", "photo.jpg", "image/jpeg")
        with patch("mesh.web.get_media_store", return_value=mock_store):
            uri = await save_upload(upload)
        assert uri.startswith("file://")
        assert "photo.jpg" in uri

    @pytest.mark.asyncio
    async def test_override_filename(self, tmp_path):
        """save_upload uses overridden filename."""
        mock_store = _make_mock_store(tmp_path)
        upload = _make_upload_file(b"data", "original.txt", "text/plain")
        with patch("mesh.web.get_media_store", return_value=mock_store):
            uri = await save_upload(upload, filename="renamed.txt")
        assert "renamed.txt" in uri
        mock_store.upload.assert_awaited_once_with(b"data", "renamed.txt", "text/plain")

    @pytest.mark.asyncio
    async def test_override_mime_type(self, tmp_path):
        """save_upload uses overridden mime_type."""
        mock_store = _make_mock_store(tmp_path)
        upload = _make_upload_file(b"data", "file.bin", "application/octet-stream")
        with patch("mesh.web.get_media_store", return_value=mock_store):
            await save_upload(upload, mime_type="custom/type")
        mock_store.upload.assert_awaited_once_with(b"data", "file.bin", "custom/type")

    @pytest.mark.asyncio
    async def test_defaults_for_missing_upload_metadata(self, tmp_path):
        """save_upload uses defaults when upload has no filename or content_type."""
        mock_store = _make_mock_store(tmp_path)
        upload = AsyncMock()
        upload.read = AsyncMock(return_value=b"blob")
        upload.filename = None
        upload.content_type = None
        with patch("mesh.web.get_media_store", return_value=mock_store):
            await save_upload(upload)
        mock_store.upload.assert_awaited_once_with(
            b"blob", "upload", "application/octet-stream"
        )


class TestSaveUploadResult:
    @pytest.mark.asyncio
    async def test_returns_media_upload_with_metadata(self, tmp_path):
        """save_upload_result returns a MediaUpload with correct fields."""
        mock_store = _make_mock_store(tmp_path)
        upload = _make_upload_file(b"file content", "report.pdf", "application/pdf")
        with patch("mesh.web.get_media_store", return_value=mock_store):
            result = await save_upload_result(upload)
        assert isinstance(result, MediaUpload)
        assert result.name == "report.pdf"
        assert result.mime_type == "application/pdf"
        assert result.size == len(b"file content")
        assert "report.pdf" in result.uri

    @pytest.mark.asyncio
    async def test_override_filename_and_mime(self, tmp_path):
        """save_upload_result respects filename and mime_type overrides."""
        mock_store = _make_mock_store(tmp_path)
        upload = _make_upload_file(b"x", "a.txt", "text/plain")
        with patch("mesh.web.get_media_store", return_value=mock_store):
            result = await save_upload_result(
                upload, filename="b.csv", mime_type="text/csv"
            )
        assert result.name == "b.csv"
        assert result.mime_type == "text/csv"
