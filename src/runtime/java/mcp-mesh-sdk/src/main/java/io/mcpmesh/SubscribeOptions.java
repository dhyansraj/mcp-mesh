package io.mcpmesh;

import java.time.Duration;
import java.util.List;
import java.util.Objects;

/**
 * Options for {@link MeshJobs#subscribeEvents(String, SubscribeOptions)}.
 * Immutable; constructed via {@link #builder()} or
 * {@link #defaults()}. Mirrors Python's keyword args
 * ({@code types}, {@code after}, {@code long_poll_secs}) and
 * TypeScript's {@code SubscribeEventsOptions} object one-for-one.
 *
 * <p>All fields are optional — defaults match the Python / TS
 * siblings:
 * <ul>
 *   <li>{@code types} = {@code null} (yield events of all types)</li>
 *   <li>{@code after} = {@code 0} (from the beginning of the event log)</li>
 *   <li>{@code longPoll} = {@code Duration.ofSeconds(30)} (registry
 *       caps at 60s; pass {@link Duration#ZERO} for a single immediate
 *       read).</li>
 * </ul>
 */
public final class SubscribeOptions {

    private final List<String> types;
    private final long after;
    private final Duration longPoll;

    private SubscribeOptions(List<String> types, long after, Duration longPoll) {
        // Defensive copy + immutable wrap so callers can't mutate the
        // filter list after construction.
        this.types = types == null ? null : List.copyOf(types);
        this.after = after;
        this.longPoll = longPoll;
    }

    /**
     * Optional event-type filter applied server-side. Only events
     * whose {@code type} matches one of these is yielded. {@code null}
     * means "all types".
     */
    public List<String> types() {
        return types;
    }

    /**
     * Initial cursor (default {@code 0} ≡ from the beginning of the
     * event log). Pass a higher value to skip historical events.
     */
    public long after() {
        return after;
    }

    /**
     * Long-poll wait budget per registry call. Default
     * {@code Duration.ofSeconds(30)}; the registry caps at 60s.
     * {@link Duration#ZERO} bridges to a single immediate read.
     * The builder rejects negative values.
     */
    public Duration longPoll() {
        return longPoll;
    }

    /** Default options — matches Python / TS sibling defaults. */
    public static SubscribeOptions defaults() {
        return new Builder().build();
    }

    public static Builder builder() {
        return new Builder();
    }

    /** Fluent builder for {@link SubscribeOptions}. */
    public static final class Builder {
        private List<String> types = null;
        private long after = 0L;
        private Duration longPoll = Duration.ofSeconds(30);

        /**
         * Restrict subscription to the given event-type tags.
         * {@code null} (the default) yields events of all types.
         */
        public Builder types(List<String> types) {
            this.types = types;
            return this;
        }

        /**
         * Initial cursor (default {@code 0} ≡ from the beginning of
         * the event log). Pass a higher value to skip historical
         * events.
         *
         * @throws IllegalArgumentException if {@code after} is negative
         */
        public Builder after(long after) {
            if (after < 0) {
                throw new IllegalArgumentException(
                    "SubscribeOptions.after must be non-negative, got: " + after);
            }
            this.after = after;
            return this;
        }

        /**
         * Long-poll wait budget per registry call. Default 30s;
         * registry caps at 60s. {@link Duration#ZERO} bridges to a
         * single immediate read.
         *
         * @throws NullPointerException     if {@code longPoll} is null
         * @throws IllegalArgumentException if {@code longPoll} is negative
         */
        public Builder longPoll(Duration longPoll) {
            Objects.requireNonNull(longPoll, "longPoll must not be null");
            if (longPoll.isNegative()) {
                throw new IllegalArgumentException(
                    "SubscribeOptions.longPoll must be non-negative, got: " + longPoll);
            }
            this.longPoll = longPoll;
            return this;
        }

        public SubscribeOptions build() {
            return new SubscribeOptions(types, after, longPoll);
        }
    }
}
