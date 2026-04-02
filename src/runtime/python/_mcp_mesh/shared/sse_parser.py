"""Server-Sent Events (SSE) parsing utilities for MCP responses."""

import logging
from typing import Any, Optional

import mcp_mesh_core

from .json_fast import loads as json_loads

logger = logging.getLogger(__name__)


class SSEParser:
    """Utility class for parsing Server-Sent Events responses from FastMCP servers.

    Handles the common issue where large JSON responses get split across multiple
    SSE 'data:' lines, which would cause JSON parsing failures if processed line-by-line.
    """

    @staticmethod
    def parse_sse_response(
        response_text: str, context: str = "unknown"
    ) -> dict[str, Any]:
        """
        Parse SSE response text and extract JSON data.

        Delegates to Rust core for parsing. Handles both plain JSON and
        SSE-formatted responses with multi-line data.

        Args:
            response_text: Raw SSE response text
            context: Context string for error logging

        Returns:
            Parsed JSON data as dictionary

        Raises:
            RuntimeError: If SSE response cannot be parsed
        """
        try:
            # Use Rust for SSE detection + extraction, orjson for final parse.
            # Benchmarks show orjson is faster than Rust->PyDict FFI boundary
            # because building Python dicts from Rust is expensive.
            result_json = mcp_mesh_core.parse_sse_response_py(response_text)
            return json_loads(result_json)
        except Exception as e:
            raise RuntimeError(f"Could not parse SSE response from {context}: {e}")

    @staticmethod
    def parse_streaming_sse_chunk(chunk_data: str) -> Optional[dict[str, Any]]:
        """
        Parse a single streaming SSE chunk.

        Used for processing individual chunks in streaming responses.

        Args:
            chunk_data: Single data line content (without 'data:' prefix)

        Returns:
            Parsed JSON if valid and complete, None if should be skipped
        """
        if not chunk_data.strip():
            return None

        # Quick validation for complete JSON structures
        chunk_data = chunk_data.strip()

        # Must be complete JSON structures
        if (
            (chunk_data.startswith("{") and not chunk_data.endswith("}"))
            or (chunk_data.startswith("[") and not chunk_data.endswith("]"))
            or (chunk_data.startswith('"') and not chunk_data.endswith('"'))
        ):
            # Incomplete JSON structure - should be accumulated elsewhere
            return None

        try:
            return json_loads(chunk_data)
        except (ValueError, TypeError):
            # Invalid JSON - skip this chunk
            return None


class SSEStreamProcessor:
    """Processor for streaming SSE responses with proper buffering."""

    def __init__(self, context: str = "streaming"):
        self.context = context
        self.buffer = ""
        self.logger = logger.getChild(f"sse_stream.{context}")

    def process_chunk(self, chunk_bytes: bytes) -> list[dict[str, Any]]:
        """
        Process a chunk of bytes and return any complete JSON objects found.

        Args:
            chunk_bytes: Raw bytes from streaming response

        Returns:
            List of complete JSON objects found in this chunk
        """
        self.logger.trace(
            f"🌊 SSEStreamProcessor.process_chunk called for {self.context}, chunk size: {len(chunk_bytes)}"
        )

        try:
            chunk_text = chunk_bytes.decode("utf-8")
            self.buffer += chunk_text
            self.logger.trace(
                f"🌊 {self.context}: Buffer size after chunk: {len(self.buffer)}"
            )
        except UnicodeDecodeError:
            self.logger.warning(
                f"🌊 {self.context}: Skipping chunk with unicode decode error"
            )
            return []

        results = []
        events_processed = 0

        # Process complete SSE events (end with \n\n)
        while True:
            event_end = self.buffer.find("\n\n")
            if event_end == -1:
                break  # No complete event yet

            event_block = self.buffer[:event_end]
            self.buffer = self.buffer[event_end + 2 :]  # Remove processed event
            events_processed += 1

            # Extract data from SSE event
            for line in event_block.split("\n"):
                if line.startswith("data: "):
                    data_str = line[6:].strip()  # Remove "data: " prefix
                    if data_str:
                        parsed = SSEParser.parse_streaming_sse_chunk(data_str)
                        if parsed:
                            results.append(parsed)

        self.logger.trace(
            f"🌊 {self.context}: Processed {events_processed} complete SSE events, yielding {len(results)} JSON objects"
        )
        return results

    def finalize(self) -> list[dict[str, Any]]:
        """
        Process any remaining data in buffer.

        Returns:
            List of any final JSON objects found
        """
        results = []

        if self.buffer.strip():
            for line in self.buffer.split("\n"):
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str:
                        parsed = SSEParser.parse_streaming_sse_chunk(data_str)
                        if parsed:
                            results.append(parsed)

        self.buffer = ""  # Clear buffer
        return results
