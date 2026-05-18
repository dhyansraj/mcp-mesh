package io.mcpmesh;

import io.mcpmesh.core.MeshException;

/**
 * The targeted job does not exist (or has been swept) in the registry.
 *
 * <p>Translated from the Rust core's {@code JobError::Backend(BackendError::NotFound)}
 * error path (HTTP 404 from {@code GET}/{@code POST /jobs/{id}/events}).
 *
 * <p>Mirrors:
 * <ul>
 *   <li>Python {@code mesh.jobs.JobNotFoundError}</li>
 *   <li>TypeScript {@code JobNotFoundError}</li>
 * </ul>
 *
 * <p>Extends {@link MeshException} so existing {@code catch (MeshException ...)}
 * handlers continue to catch this; callers that want to branch on
 * job-not-found vs. transport failure should catch this subclass
 * specifically.
 */
public final class JobNotFoundException extends MeshException {

    public JobNotFoundException(String message) {
        super(message);
    }

    public JobNotFoundException(String message, Throwable cause) {
        super(message, cause);
    }
}
