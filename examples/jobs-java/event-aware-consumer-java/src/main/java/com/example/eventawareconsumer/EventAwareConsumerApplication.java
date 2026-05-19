package com.example.eventawareconsumer;

import io.mcpmesh.EventSubscription;
import io.mcpmesh.JobProxy;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshJobs;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Selector;
import io.mcpmesh.SubscribeOptions;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MeshJob Phase 2 — Java Consumer: drive an event-aware job (v2.2).
 *
 * <p>Demonstrates the three v2.2 event-channel surfaces from outside the
 * running handler:
 *
 * <pre>{@code
 * try (JobProxy proxy = submitter.submit(opts).get()) {
 *   // observer thread: walks EventSubscription, mirrors the stream
 *   // poster loop:    fires 3 'work' events + 1 'stop' via MeshJobs.postEvent
 *   Object result = proxy.await(30.0);
 * }
 * }</pre>
 *
 * <p>The subscriber and the poster run concurrently. Each has its own
 * cursor: the in-handler {@code recvEvent} cursor on the producer side is
 * independent from the observer's {@link EventSubscription} cursor —
 * both observe every {@code work} event the consumer posts.
 *
 * <p>Pair this consumer with {@code ../event-aware-provider-java}.
 * Run after the provider is up:
 *
 * <pre>
 * MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run
 * </pre>
 */
@MeshAgent(
    name = "event-aware-consumer-java",
    version = "1.0.0",
    description = "MeshJob v2.2 (Java) consumer — drives an event-aware job via postEvent + subscribeEvents",
    port = 9123
)
@SpringBootApplication
public class EventAwareConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(EventAwareConsumerApplication.class, args);
    }

    @MeshTool(
        capability = "drive_event_aware_task",
        description = "Submit an event-aware job, post 3 'work' events + 1 'stop', "
            + "mirror the stream via subscribeEvents, and return both halves.",
        dependencies = @Selector(capability = "event_aware_long_task")
    )
    public Map<String, Object> driveEventAwareTask(MeshJob eventAwareLongTask) throws Exception {
        if (!(eventAwareLongTask instanceof MeshJobSubmitter submitter)) {
            return Map.of("error", "event_aware_long_task submitter not injected");
        }

        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            new LinkedHashMap<>(), null, 60, null, null);

        try (JobProxy proxy = submitter.submit(opts).get()) {
            String jobId = proxy.jobId();

            // Brief wait so the producer claims the job + parks on
            // recvEvent before the first event lands.
            Thread.sleep(2000);

            // Synchronized list so the subscriber thread and the main
            // thread can both touch it safely.
            List<Map<String, Object>> observed =
                Collections.synchronizedList(new ArrayList<>());

            List<Object> postedSeqs = new ArrayList<>();
            String subscriberStatus;

            // Subscriber runs on a daemon thread. Java has no async/await —
            // try-with-resources on EventSubscription ensures the iterator
            // closes cleanly when we leave the block.
            try (EventSubscription subscription = MeshJobs.subscribeEvents(
                    jobId,
                    SubscribeOptions.builder()
                        .types(List.of("work"))
                        .longPoll(Duration.ofSeconds(5))
                        .build())) {
                Thread subscriber = new Thread(() -> {
                    while (subscription.hasNext()) {
                        Map<String, Object> event = subscription.next();
                        Map<String, Object> entry = new LinkedHashMap<>();
                        entry.put("seq", event.get("seq"));
                        entry.put("payload", event.get("payload"));
                        observed.add(entry);
                        if (observed.size() >= 3) {
                            return;
                        }
                    }
                }, "event-aware-subscriber");
                subscriber.setDaemon(true);
                subscriber.start();

                // Poster: fire 3 'work' events ~500ms apart, then 1 'stop'.
                for (int i = 1; i <= 3; i++) {
                    Thread.sleep(500);
                    Map<String, Object> receipt = MeshJobs.postEvent(
                        jobId, "work", Map.of("item", i));
                    postedSeqs.add(receipt.get("seq"));
                }
                MeshJobs.postEvent(jobId, "stop", Map.of());

                // Bound the subscriber wait. The try-with-resources close()
                // drops the iterator's "keep polling" flag on exit.
                // On timeout, the daemon subscriber thread is still blocked inside
                // proxy.listEvents()'s native FFI long-poll. EventSubscription.close()
                // (run by the surrounding try-with-resources) flips a volatile flag
                // that stops *future* long-polls but does NOT interrupt the in-flight
                // one — the thread will exit at its next poll boundary (up to
                // `longPoll` duration later). Daemon status keeps the JVM shutdown
                // path clean; the leak window is bounded by `longPoll`.
                subscriber.join(15_000L);
                subscriberStatus = subscriber.isAlive() ? "timeout" : "ok";
            }

            // proxy.close() at end of this try block takes the JobProxy write
            // lock; if the subscriber thread is still in flight (timeout branch
            // above), close blocks until its read-locked listEvents call drains.
            Object result = proxy.await(30.0);

            Map<String, Object> response = new LinkedHashMap<>();
            response.put("job_id", jobId);
            response.put("posted_seqs", postedSeqs);
            response.put("subscriber_status", subscriberStatus);
            response.put("observed_count", observed.size());
            response.put("observed_events", new ArrayList<>(observed));
            response.put("result", result);
            return response;
        }
    }
}
