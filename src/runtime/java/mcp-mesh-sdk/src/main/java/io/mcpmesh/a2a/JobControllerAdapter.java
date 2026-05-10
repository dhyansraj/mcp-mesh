package io.mcpmesh.a2a;

import io.mcpmesh.JobController;

/**
 * Internal seam over the two {@link JobController} methods that
 * {@link A2AJob#bridge} and {@link A2AStream#bridge} need to call.
 *
 * <p>{@link JobController} is {@code final} (intentional — the
 * production class wraps a native handle and any subclass would risk
 * use-after-free). This package-private interface lets the unit tests
 * supply an in-memory adapter without instantiating a real native
 * handle, while the production path uses {@link #wrap} which
 * trivially delegates.
 */
interface JobControllerAdapter {

    void updateProgress(double progress, String message);

    boolean isCancelled();

    /**
     * Wrap a real {@link JobController} as an adapter — the only
     * adapter ever constructed by production code paths.
     */
    static JobControllerAdapter wrap(JobController controller) {
        if (controller == null) {
            throw new NullPointerException(
                "JobControllerAdapter.wrap: controller must be non-null");
        }
        return new JobControllerAdapter() {
            @Override
            public void updateProgress(double progress, String message) {
                controller.updateProgress(progress, message);
            }

            @Override
            public boolean isCancelled() {
                return controller.isCancelled();
            }
        };
    }
}
