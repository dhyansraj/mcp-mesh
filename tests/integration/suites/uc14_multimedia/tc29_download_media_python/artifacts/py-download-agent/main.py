"""Test agent for download_media API."""

import json

import mesh
from fastmcp import FastMCP

app = FastMCP("Download Test Agent")

TEST_CONTENT = b"Hello Media Download Test - Python"
TEST_FILENAME = "test-download.txt"
TEST_MIME = "text/plain"


@app.tool()
@mesh.tool(
    capability="test_download_media",
    description="Upload then download media and verify",
)
async def test_download_media() -> str:
    # Upload
    uri = await mesh.upload_media(TEST_CONTENT, TEST_FILENAME, TEST_MIME)

    # Download
    data, mime_type = await mesh.download_media(uri)

    return json.dumps(
        {
            "uri": uri,
            "uploaded_size": len(TEST_CONTENT),
            "downloaded_size": len(data),
            "content_match": data == TEST_CONTENT,
            "mime_type": mime_type,
            "downloaded_text": data.decode("utf-8"),
        }
    )


@mesh.agent(
    name="py-download-agent",
    version="1.0.0",
    description="Agent for testing download_media API",
    http_port=0,
    enable_http=True,
    auto_run=True,
)
class Agent:
    pass
