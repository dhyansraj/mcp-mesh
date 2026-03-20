/**
 * MediaStore abstraction for multimodal content storage.
 *
 * Provides pluggable storage backends (local filesystem, S3) for
 * binary media referenced by resource_link content items.
 */

import { resolveMediaConfig } from "../config.js";

/**
 * Storage backend for media blobs.
 */
export interface MediaStore {
  /** Upload data and return a URI for later retrieval. */
  upload(data: Buffer, filename: string, mimeType: string): Promise<string>;

  /** Fetch previously stored data by URI. */
  fetch(uri: string): Promise<{ data: Buffer; mimeType: string }>;

  /** Check whether a URI exists in the store. */
  exists(uri: string): Promise<boolean>;
}

/** Simple extension-to-MIME mapping for common types. */
const MIME_MAP: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".pdf": "application/pdf",
  ".json": "application/json",
  ".txt": "text/plain",
  ".html": "text/html",
  ".css": "text/css",
  ".csv": "text/csv",
};

/** Guess MIME type from a filename extension. Falls back to application/octet-stream. */
export function guessMimeType(filename: string): string {
  const ext = filename.slice(filename.lastIndexOf(".")).toLowerCase();
  return MIME_MAP[ext] ?? "application/octet-stream";
}

/**
 * Local filesystem media store.
 *
 * Stores files under a configurable base path and returns `file://` URIs.
 */
export class LocalMediaStore implements MediaStore {
  private readonly basePath: string;
  private readonly prefix: string;

  constructor(basePath?: string, prefix?: string) {
    const cfg = resolveMediaConfig();
    this.basePath = basePath ?? cfg.storagePath;
    this.prefix = prefix ?? cfg.storagePrefix;
  }

  private async validatePath(filePath: string): Promise<void> {
    const { resolve } = await import("node:path");
    const resolved = resolve(filePath);
    if (!resolved.startsWith(resolve(this.basePath))) {
      throw new Error(`Invalid filename (path traversal): ${filePath}`);
    }
  }

  async upload(data: Buffer, filename: string, _mimeType: string): Promise<string> {
    const { mkdir, writeFile } = await import("node:fs/promises");
    const { join } = await import("node:path");

    const dir = join(this.basePath, this.prefix);
    await mkdir(dir, { recursive: true });

    const filePath = join(dir, filename);
    await this.validatePath(filePath);
    await writeFile(filePath, data);

    return `file://${filePath}`;
  }

  async fetch(uri: string): Promise<{ data: Buffer; mimeType: string }> {
    const { readFile } = await import("node:fs/promises");

    const filePath = uri.startsWith("file://") ? uri.slice(7) : uri;
    await this.validatePath(filePath);
    const data = await readFile(filePath);
    const mimeType = guessMimeType(filePath);

    return { data: Buffer.from(data), mimeType };
  }

  async exists(uri: string): Promise<boolean> {
    const { access } = await import("node:fs/promises");

    const filePath = uri.startsWith("file://") ? uri.slice(7) : uri;
    try {
      await this.validatePath(filePath);
      await access(filePath);
      return true;
    } catch {
      return false;
    }
  }
}

/**
 * S3-compatible media store.
 *
 * Uses lazy imports for @aws-sdk/client-s3 so it is only required
 * when storage is configured as "s3".
 */
export class S3MediaStore implements MediaStore {
  private readonly bucket: string;
  private readonly endpoint: string | undefined;
  private readonly prefix: string;

  // Lazily initialised S3 client
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private _client: any = null;

  constructor(bucket?: string, endpoint?: string, prefix?: string) {
    const cfg = resolveMediaConfig();
    this.bucket = bucket ?? cfg.storageBucket ?? "mcp-mesh-media";
    this.endpoint = endpoint ?? cfg.storageEndpoint;
    this.prefix = prefix ?? cfg.storagePrefix;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private async getClient(): Promise<any> {
    if (this._client) return this._client;

    // Lazy import - @aws-sdk/client-s3 is NOT a required dependency.
    // Uses variable to prevent TypeScript from resolving the module at compile time.
    const s3ModuleName = "@aws-sdk/client-s3";
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const s3Module: any = await import(/* webpackIgnore: true */ s3ModuleName);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const opts: Record<string, any> = {};
    if (this.endpoint) {
      opts.endpoint = this.endpoint;
      opts.forcePathStyle = true;
    }
    this._client = new s3Module.S3Client(opts);
    return this._client;
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private async loadS3Module(): Promise<any> {
    const name = "@aws-sdk/client-s3";
    return import(/* webpackIgnore: true */ name);
  }

  async upload(data: Buffer, filename: string, mimeType: string): Promise<string> {
    const s3Module = await this.loadS3Module();
    const client = await this.getClient();

    const key = `${this.prefix}${filename}`;
    await client.send(
      new s3Module.PutObjectCommand({
        Bucket: this.bucket,
        Key: key,
        Body: data,
        ContentType: mimeType,
      })
    );

    return `s3://${this.bucket}/${key}`;
  }

  async fetch(uri: string): Promise<{ data: Buffer; mimeType: string }> {
    const s3Module = await this.loadS3Module();
    const client = await this.getClient();

    const { bucket, key } = this.parseUri(uri);
    const response = await client.send(
      new s3Module.GetObjectCommand({ Bucket: bucket, Key: key })
    );

    const body = await response.Body?.transformToByteArray();
    if (!body) throw new Error(`Empty body for ${uri}`);

    return {
      data: Buffer.from(body),
      mimeType: response.ContentType ?? guessMimeType(key),
    };
  }

  async exists(uri: string): Promise<boolean> {
    const s3Module = await this.loadS3Module();
    const client = await this.getClient();

    const { bucket, key } = this.parseUri(uri);
    try {
      await client.send(new s3Module.HeadObjectCommand({ Bucket: bucket, Key: key }));
      return true;
    } catch {
      return false;
    }
  }

  private parseUri(uri: string): { bucket: string; key: string } {
    if (uri.startsWith("s3://")) {
      const withoutScheme = uri.slice(5);
      const slashIdx = withoutScheme.indexOf("/");
      if (slashIdx === -1) {
        return { bucket: withoutScheme, key: "" };
      }
      return {
        bucket: withoutScheme.slice(0, slashIdx),
        key: withoutScheme.slice(slashIdx + 1),
      };
    }
    // Assume key-only, use configured bucket
    return { bucket: this.bucket, key: uri };
  }
}

// ---------------------------------------------------------------------------
// Singleton factory
// ---------------------------------------------------------------------------

let _instance: MediaStore | null = null;

/**
 * Get (or create) the singleton MediaStore based on configuration.
 *
 * Reads `media_storage` config key (env: `MCP_MESH_MEDIA_STORAGE`).
 * - `"local"` (default) -> LocalMediaStore
 * - `"s3"` -> S3MediaStore
 */
export function getMediaStore(): MediaStore {
  if (_instance) return _instance;

  const cfg = resolveMediaConfig();

  switch (cfg.storage) {
    case "s3":
      _instance = new S3MediaStore();
      break;
    default:
      _instance = new LocalMediaStore();
      break;
  }

  return _instance;
}

/**
 * Reset the singleton (mainly for testing).
 * @internal
 */
export function _resetMediaStore(): void {
  _instance = null;
}
