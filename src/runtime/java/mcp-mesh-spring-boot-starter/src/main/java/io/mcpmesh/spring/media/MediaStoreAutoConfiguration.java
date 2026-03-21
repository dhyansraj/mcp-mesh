package io.mcpmesh.spring.media;

import io.mcpmesh.spring.MeshProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Auto-configuration for {@link MediaStore} beans.
 *
 * <p>Selects the implementation based on {@code mesh.media.storage}:
 * <ul>
 *   <li>{@code local} (default) — stores files on local filesystem</li>
 *   <li>{@code s3} — stores files in an AWS S3 bucket (requires {@code software.amazon.awssdk:s3} on classpath)</li>
 * </ul>
 */
@Configuration
@ConditionalOnProperty(name = "mesh.media.storage", matchIfMissing = true)
public class MediaStoreAutoConfiguration {

    private static final Logger log = LoggerFactory.getLogger(MediaStoreAutoConfiguration.class);

    @Bean
    @ConditionalOnProperty(name = "mesh.media.storage", havingValue = "local", matchIfMissing = true)
    public MediaStore localMediaStore(MeshProperties properties) {
        MeshProperties.Media media = properties.getMedia();
        log.info("Configuring local MediaStore: path={}, prefix={}",
            media.getStoragePath(), media.getStoragePrefix());
        return new LocalMediaStore(media.getStoragePath(), media.getStoragePrefix());
    }

    @Bean
    @ConditionalOnProperty(name = "mesh.media.storage", havingValue = "s3")
    @ConditionalOnMissingClass("software.amazon.awssdk.services.s3.S3Client")
    public MediaStore s3MediaStoreMissingSdk() {
        throw new IllegalStateException(
            "mesh.media.storage=s3 but software.amazon.awssdk:s3 is not on the classpath. " +
            "Add the S3 SDK dependency or set mesh.media.storage=local.");
    }

    @Bean
    @ConditionalOnProperty(name = "mesh.media.storage", havingValue = "s3")
    @ConditionalOnClass(name = "software.amazon.awssdk.services.s3.S3Client")
    public MediaStore s3MediaStore(MeshProperties properties) {
        MeshProperties.Media media = properties.getMedia();
        log.info("Configuring S3 MediaStore: bucket={}, prefix={}, endpoint={}",
            media.getStorageBucket(), media.getStoragePrefix(), media.getStorageEndpoint());
        return new S3MediaStore(
            media.getStorageBucket(),
            media.getStorageEndpoint(),
            media.getStoragePrefix()
        );
    }
}
