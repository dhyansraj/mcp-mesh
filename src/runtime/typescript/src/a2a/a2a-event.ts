/**
 * Parsed A2A v1.0 SSE event surface (issue #917).
 *
 * One event per `tasks/sendSubscribe` SSE frame after the JSON-RPC
 * envelope is decoded. Mirrors `mesh._a2a_consumer.A2AEvent` (Python)
 * and `io.mcpmesh.a2a.A2AEvent` (Java).
 */

export type A2AEventKind = "status" | "artifact";

export interface A2AEvent {
  /** "status" for TaskStatusUpdateEvent frames; "artifact" for TaskArtifactUpdateEvent frames. */
  kind: A2AEventKind;
  /** Lifecycle state (status frames only). */
  state?: string;
  /** Normalized progress in [0, 1] (status frames only, when present). */
  progress?: number;
  /** Status message text (status frames only, when present). */
  message?: string;
  /** Artifact text (artifact frames only). */
  artifactText?: string;
  /** True on the terminal status frame. */
  final: boolean;
  /** Full JSON-RPC envelope for advanced consumers. */
  raw: unknown;
}
