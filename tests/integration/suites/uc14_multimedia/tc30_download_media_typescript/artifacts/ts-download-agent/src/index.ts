#!/usr/bin/env npx tsx
/**
 * Test agent for downloadMedia API.
 *
 * Uploads test data via uploadMedia, downloads it back via downloadMedia,
 * and returns the comparison result.
 */

import { FastMCP, mesh, uploadMedia, downloadMedia } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Download Test Agent", version: "1.0.0" });

const TEST_CONTENT = Buffer.from("Hello Media Download Test - TypeScript");
const TEST_FILENAME = "test-download.txt";
const TEST_MIME = "text/plain";

const agent = mesh(server, {
  name: "ts-download-agent",
  httpPort: 0,
  description: "Agent for testing downloadMedia API",
});

agent.addTool({
  name: "test_download_media",
  capability: "test_download_media",
  description: "Upload then download media and verify",
  parameters: z.object({}),
  execute: async () => {
    // Upload
    const uri = await uploadMedia(TEST_CONTENT, TEST_FILENAME, TEST_MIME);

    // Download
    const { data, mimeType } = await downloadMedia(uri);

    return JSON.stringify({
      uri,
      uploaded_size: TEST_CONTENT.length,
      downloaded_size: data.length,
      content_match: Buffer.compare(data, TEST_CONTENT) === 0,
      mime_type: mimeType,
      downloaded_text: data.toString("utf-8"),
    });
  },
});

console.log("ts-download-agent defined. Waiting for auto-start...");
