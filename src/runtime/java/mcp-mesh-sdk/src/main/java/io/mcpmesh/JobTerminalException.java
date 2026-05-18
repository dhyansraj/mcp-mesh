package io.mcpmesh;

import io.mcpmesh.core.MeshException;

/**
 * The targeted job is in a terminal state (completed / failed /
 * cancelled) and no longer accepts events.
 *
 * <p>Translated from the Rust {@code JobError::JobTerminal} variant —
 * {@code POST /jobs/{id}/events} returns HTTP 409 once the row is
 * terminal, and the Rust layer maps that to {@code JobTerminal}.
 *
 * <p>Mirrors:
 * <ul>
 *   <li>Python {@code mesh.jobs.JobTerminalError}</li>
 *   <li>TypeScript {@code JobTerminalError}</li>
 * </ul>
 *
 * <p>Extends {@link MeshException} so existing {@code catch (MeshException ...)}
 * handlers continue to catch this; callers that want to branch on
 * terminal-state vs. unknown-job vs. transport failure should catch
 * this subclass specifically.
 */
public final class JobTerminalException extends MeshException {

    public JobTerminalException(String message) {
        super(message);
    }

    public JobTerminalException(String message, Throwable cause) {
        super(message, cause);
    }
}
