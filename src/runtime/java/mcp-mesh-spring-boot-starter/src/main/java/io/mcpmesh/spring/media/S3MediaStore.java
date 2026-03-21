package io.mcpmesh.spring.media;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import software.amazon.awssdk.core.ResponseBytes;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3ClientBuilder;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.HeadObjectRequest;
import software.amazon.awssdk.services.s3.model.NoSuchKeyException;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

import java.net.URI;

/**
 * AWS S3 implementation of {@link MediaStore}.
 *
 * <p>Requires {@code software.amazon.awssdk:s3} on the classpath (optional dependency).
 * URIs use the {@code s3://} scheme.
 *
 * <p>The S3 client is lazily initialized on first use to avoid startup cost
 * when the store is configured but not immediately needed.
 */
public class S3MediaStore implements MediaStore {

    private static final Logger log = LoggerFactory.getLogger(S3MediaStore.class);

    private final String bucket;
    private final String endpoint;
    private final String prefix;

    private volatile S3Client s3Client;

    /**
     * @param bucket   S3 bucket name
     * @param endpoint Custom S3 endpoint (nullable; uses default AWS endpoint if null)
     * @param prefix   Key prefix prepended to filenames (e.g., "media/")
     */
    public S3MediaStore(String bucket, String endpoint, String prefix) {
        this.bucket = bucket;
        this.endpoint = endpoint;
        this.prefix = prefix != null ? prefix : "";
    }

    @Override
    public String upload(byte[] data, String filename, String mimeType) {
        try {
            String key = prefix + filename;
            PutObjectRequest request = PutObjectRequest.builder()
                .bucket(bucket)
                .key(key)
                .contentType(mimeType)
                .build();
            getClient().putObject(request, RequestBody.fromBytes(data));
            log.debug("Stored media in S3: s3://{}/{} ({}, {} bytes)", bucket, key, mimeType, data.length);
            return "s3://" + bucket + "/" + key;
        } catch (Exception e) {
            throw new MediaStoreException("Failed to upload media to S3: " + filename + " (" + e.getClass().getSimpleName() + ": " + e.getMessage() + ")", e);
        }
    }

    @Override
    public MediaFetchResult fetch(String uri) {
        try {
            String key = toKey(uri);
            GetObjectRequest request = GetObjectRequest.builder()
                .bucket(bucket)
                .key(key)
                .build();
            ResponseBytes<GetObjectResponse> response = getClient().getObjectAsBytes(request);
            String mimeType = response.response().contentType();
            if (mimeType == null) {
                mimeType = "application/octet-stream";
            }
            return new MediaFetchResult(response.asByteArray(), mimeType);
        } catch (NoSuchKeyException e) {
            throw new MediaStoreException("Media not found in S3: " + uri);
        } catch (MediaStoreException e) {
            throw e;
        } catch (Exception e) {
            throw new MediaStoreException("Failed to fetch media from S3: " + uri, e);
        }
    }

    @Override
    public boolean exists(String uri) {
        try {
            String key = toKey(uri);
            HeadObjectRequest request = HeadObjectRequest.builder()
                .bucket(bucket)
                .key(key)
                .build();
            getClient().headObject(request);
            return true;
        } catch (NoSuchKeyException e) {
            return false;
        } catch (Exception e) {
            throw new MediaStoreException("Failed to check existence in S3: " + uri, e);
        }
    }

    private S3Client getClient() {
        if (s3Client == null) {
            synchronized (this) {
                if (s3Client == null) {
                    S3ClientBuilder builder = S3Client.builder();
                    if (endpoint != null && !endpoint.isBlank()) {
                        builder.endpointOverride(URI.create(endpoint))
                               .forcePathStyle(true);
                    }
                    s3Client = builder.build();
                    log.info("Initialized S3 client for bucket '{}'{}", bucket,
                        endpoint != null ? " (endpoint: " + endpoint + ")" : "");
                }
            }
        }
        return s3Client;
    }

    private String toKey(String uri) {
        if (uri.startsWith("s3://")) {
            // s3://bucket/key -> extract key after bucket/
            String withoutScheme = uri.substring(5);
            int slashIdx = withoutScheme.indexOf('/');
            if (slashIdx >= 0) {
                return withoutScheme.substring(slashIdx + 1);
            }
        }
        return uri;
    }
}
