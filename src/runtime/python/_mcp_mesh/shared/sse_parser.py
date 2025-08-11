"""Server-Sent Events (SSE) parsing utilities for MCP responses."""

import json
import logging
from typing import Any, Dict, Optional

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

        Handles multi-line JSON responses by accumulating all 'data:' lines
        before attempting to parse JSON.

        Args:
            response_text: Raw SSE response text
            context: Context string for error logging

        Returns:
            Parsed JSON data as dictionary

        Raises:
            RuntimeError: If SSE response cannot be parsed
        """
        logger.debug(f"🔧 SSEParser.parse_sse_response called from {context}")
        logger.debug(
            f"🔧 Response text length: {len(response_text)}, starts with 'event:': {response_text.startswith('event:')}"
        )
        logger.debug(f"🔧 Response preview: {repr(response_text[:100])}...")

        # Check if this is SSE format (can be malformed and not start with "event:")
        is_sse_format = (
            response_text.startswith("event:")
            or "event: message" in response_text
            or "data: " in response_text
        )

        if not is_sse_format:
            # Not an SSE response, try parsing as plain JSON
            logger.debug(f"🔧 {context}: Parsing as plain JSON (not SSE format)")
            logger.debug(
                f"🔧 {context}: Response preview: {repr(response_text[:200])}..."
            )
            try:
                result = json.loads(response_text)
                logger.debug(f"🔧 {context}: Plain JSON parsed successfully")
                return result
            except json.JSONDecodeError as e:
                logger.error(f"🔧 {context}: Plain JSON parse failed: {e}")
                logger.error(
                    f"🔧 {context}: Invalid response content (first 500 chars): {repr(response_text[:500])}"
                )
                raise RuntimeError(f"Invalid JSON response in {context}: {e}")

        # Parse SSE format: find first valid JSON in data lines
        logger.debug(f"🔧 {context}: Parsing SSE format - looking for first valid JSON")
        data_line_count = 0
        first_valid_json = None

        for line in response_text.split("\n"):
            if line.startswith("data:"):
                data_content = line[5:].strip()  # Remove 'data:' prefix and whitespace
                if data_content:
                    data_line_count += 1
                    try:
                        # Try to parse this line as JSON
                        parsed_json = json.loads(data_content)
                        if first_valid_json is None:
                            first_valid_json = parsed_json
                            logger.debug(f"🔧 {context}: Found first valid JSON in data line {data_line_count}")
                    except json.JSONDecodeError:
                        # Skip invalid JSON lines - this is expected behavior
                        logger.debug(f"🔧 {context}: Skipping invalid JSON in data line {data_line_count}: {data_content[:50]}...")
                        continue

        logger.debug(
            f"🔧 {context}: Processed {data_line_count} data lines"
        )

        # Return first valid JSON found
        if first_valid_json is None:
            logger.error(f"🔧 {context}: No valid JSON found in SSE response")
            raise RuntimeError(f"Could not parse SSE response from FastMCP")

        logger.debug(
            f"🔧 {context}: SSE parsing successful! Result type: {type(first_valid_json)}"
        )
        return first_valid_json

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
            return json.loads(chunk_data)
        except json.JSONDecodeError:
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
        self.logger.debug(
            f"🌊 SSEStreamProcessor.process_chunk called for {self.context}, chunk size: {len(chunk_bytes)}"
        )

        try:
            chunk_text = chunk_bytes.decode("utf-8")
            self.buffer += chunk_text
            self.logger.debug(
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

        self.logger.debug(
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
