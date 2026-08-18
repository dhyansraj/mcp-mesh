package io.mcpmesh.spring;

import io.mcpmesh.MeshHealth;
import io.mcpmesh.MeshHealthStatus;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@code degraded} as a health-check RETURN VALUE is deprecated (issue #1515).
 *
 * <p>The question a health check answers is binary: stay in dependency
 * resolution, or withdraw. {@code DEGRADED} and {@code HEALTHY} are the same
 * answer to it — both keep the heartbeat alive and both keep consumers routing
 * here — so the third word buys a 503 on an endpoint nothing probes and costs
 * the failure rate of a name that reads like withdrawal to everyone who picks
 * it when their upstream is down.
 *
 * <p>Two things are pinned here, and the second matters more than the first:
 *
 * <ol>
 *   <li>selecting {@code DEGRADED} warns, naming the CONSEQUENCE rather than
 *       the value;
 *   <li><b>behaviour is unchanged.</b> Remapping it to {@code UNHEALTHY} would
 *       fix the common intent and silently withdraw every agent whose author
 *       used the word correctly.
 * </ol>
 *
 * <p>The runtime's OWN degraded verdicts — a check that threw, one it could not
 * invoke, an unusable return type — must NOT warn: nothing the author can act
 * on happened.
 *
 * <p>Java is also the source-compatibility case. {@link MeshHealth#degraded}
 * is a public factory, so it carries {@code @Deprecated} and keeps working;
 * removal is no earlier than 4.0. The {@code @SuppressWarnings} below is the
 * point of this file, not an oversight — it must still COMPILE.
 */
@SuppressWarnings("deprecation")
class MeshHealthDegradedDeprecationTest {

    private LogCapture logs;

    @BeforeEach
    void setUp() {
        MeshHealthCheckRegistry.resetDegradedReturnWarning();
        logs = LogCapture.attach(MeshHealthCheckRegistry.class);
    }

    @AfterEach
    void tearDown() {
        logs.detach();
        MeshHealthCheckRegistry.resetDegradedReturnWarning();
    }

    private List<String> deprecationWarnings() {
        return logs.events.stream()
            .filter(e -> "WARN".equals(e.level()))
            .map(LogCapture.LogEvent::message)
            .filter(m -> m.contains("keep routing to it"))
            .toList();
    }

    // The consequence, not the value. An author who reads "degraded is
    // deprecated" learns nothing; one who reads "consumers will keep routing to
    // it" learns whether they meant it.
    @Test
    void selectingDegradedWarnsAndNamesTheConsequence() {
        MeshHealth health = MeshHealthCheckRegistry.coerce(MeshHealth.degraded("upstream slow"));

        assertEquals(MeshHealthStatus.DEGRADED, health.status());
        List<String> warnings = deprecationWarnings();
        assertEquals(1, warnings.size(), "expected exactly one deprecation warning");
        assertTrue(warnings.get(0).contains("stays in dependency resolution"), warnings.get(0));
        assertTrue(warnings.get(0).contains("consumers will keep routing to it"), warnings.get(0));
        assertTrue(warnings.get(0).contains("MeshHealth.unhealthy(...)"), warnings.get(0));
    }

    // Every route to a user-selected DEGRADED funnels through coerce, so all
    // three must warn — a guard on the factory alone would miss two of them.
    @Test
    void everyRouteToASelectedDegradedWarns() {
        MeshHealthCheckRegistry.coerce(MeshHealth.of("degraded", "via of()"));
        assertEquals(1, deprecationWarnings().size(), "MeshHealth.of(\"degraded\") is a selection");

        MeshHealthCheckRegistry.resetDegradedReturnWarning();
        logs.events.clear();
        MeshHealthCheckRegistry.coerce(
            MeshHealth.healthy().withStatus(MeshHealthStatus.DEGRADED));
        assertEquals(1, deprecationWarnings().size(), "withStatus(DEGRADED) is a selection");
    }

    // The whole point of warning rather than remapping: an author who used the
    // word correctly — impaired, still serving — keeps serving.
    @Test
    void behaviourIsUnchanged() {
        MeshHealth health = MeshHealthCheckRegistry.coerce(
            MeshHealth.degraded("cache cold").withCheck("cache_warm", false));

        assertEquals(MeshHealthStatus.DEGRADED, health.status(),
            "remapping degraded to unhealthy would withdraw every agent whose "
                + "author used the word correctly");
        assertNotEquals(MeshHealthStatus.UNHEALTHY, health.status());
        assertTrue(health.isServing(), "a degraded agent stays in dependency resolution");
        assertEquals(false, health.checks().get("cache_warm"));
        assertEquals(List.of("cache cold"), health.errors());
    }

    // A check re-runs every TTL; at the 15s default a per-tick warning is
    // ~5,760 identical lines a day from an agent doing what its author intended.
    @Test
    void warnsOncePerProcess() {
        for (int i = 0; i < 5; i++) {
            assertEquals(MeshHealthStatus.DEGRADED,
                MeshHealthCheckRegistry.coerce(MeshHealth.degraded("slow")).status());
        }
        assertEquals(1, deprecationWarnings().size());
    }

    // The indeterminate paths keep the internal state and say nothing: the
    // runtime assigned that verdict, so there is nothing for the author to fix.
    @Test
    void runtimeAssignedDegradedIsSilent() {
        assertEquals(MeshHealthStatus.DEGRADED,
            MeshHealthCheckRegistry.coerce("a string is not a verdict").status());
        assertEquals(MeshHealthStatus.DEGRADED,
            MeshHealthCheckRegistry.coerce(null).status());
        assertEquals(MeshHealthStatus.DEGRADED,
            MeshHealthCheckRegistry.coerce(42).status());

        assertEquals(List.of(), deprecationWarnings(),
            "the author did not choose these — the runtime assigned them because "
                + "it had no verdict it could trust");
    }

    // The one runtime-assigned DEGRADED that arrives on the MeshHealth branch,
    // and the only way to warn an author about an API they never called.
    // `MeshHealth.of(vendorStatus)` with an unreadable string is a REPORTING
    // fact, not a verdict the author chose; Python maps the same input to
    // UNKNOWN and TypeScript returns before its guard, so Java was the only
    // runtime that leaked here.
    @Test
    void anUnreadableStatusStringIsNotASelection() {
        MeshHealth health = MeshHealthCheckRegistry.coerce(MeshHealth.of("down"));

        assertEquals(MeshHealthStatus.DEGRADED, health.status());
        assertTrue(health.isUnreadableStatus());
        assertEquals(false, health.checks().get(MeshHealth.UNREADABLE_STATUS_CHECK),
            "the operator still learns on /health that the STATUS was the problem");
        assertTrue(health.errors().get(0).contains("down"), health.errors().toString());
        assertEquals(List.of(), deprecationWarnings(),
            "warning here tells an author to stop calling MeshHealth.degraded(), "
                + "which they did not call");
    }

    // fromWire maps null to DEGRADED, so a null status used to land on the
    // deprecation warning by the same route.
    @Test
    void aNullStatusStringIsNotASelectionEither() {
        MeshHealth health = MeshHealthCheckRegistry.coerce(MeshHealth.of(null));

        assertEquals(MeshHealthStatus.DEGRADED, health.status());
        assertTrue(health.isUnreadableStatus());
        assertEquals(List.of(), deprecationWarnings());
    }

    // The distinction is the status STRING, not the marker: a readable
    // "degraded" through the same factory is still a selection.
    @Test
    void aReadableDegradedThroughOfIsStillASelection() {
        MeshHealth health = MeshHealthCheckRegistry.coerce(MeshHealth.of(" DeGrAdEd "));

        assertEquals(MeshHealthStatus.DEGRADED, health.status());
        assertFalse(health.isUnreadableStatus());
        assertEquals(1, deprecationWarnings().size());
    }

    @Test
    void healthyAndUnhealthyAreSilent() {
        assertEquals(MeshHealthStatus.HEALTHY,
            MeshHealthCheckRegistry.coerce(MeshHealth.healthy()).status());
        assertEquals(MeshHealthStatus.HEALTHY,
            MeshHealthCheckRegistry.coerce(Boolean.TRUE).status());
        assertEquals(MeshHealthStatus.UNHEALTHY,
            MeshHealthCheckRegistry.coerce(MeshHealth.unhealthy("vendor down")).status());
        assertEquals(MeshHealthStatus.UNHEALTHY,
            MeshHealthCheckRegistry.coerce(Boolean.FALSE).status());

        assertEquals(List.of(), deprecationWarnings());
    }

    /** Minimal Logback appender recording level + message for a target logger. */
    static final class LogCapture {
        final java.util.List<LogEvent> events = new java.util.concurrent.CopyOnWriteArrayList<>();
        private final ch.qos.logback.classic.Logger target;
        private final ch.qos.logback.core.AppenderBase<ch.qos.logback.classic.spi.ILoggingEvent> appender;

        private LogCapture(ch.qos.logback.classic.Logger target) {
            this.target = target;
            this.appender = new ch.qos.logback.core.AppenderBase<>() {
                @Override
                protected void append(ch.qos.logback.classic.spi.ILoggingEvent event) {
                    events.add(new LogEvent(event.getLevel().toString(), event.getFormattedMessage()));
                }
            };
        }

        static LogCapture attach(Class<?> loggerClass) {
            ch.qos.logback.classic.Logger logger =
                (ch.qos.logback.classic.Logger) org.slf4j.LoggerFactory.getLogger(loggerClass);
            LogCapture capture = new LogCapture(logger);
            capture.appender.setContext(logger.getLoggerContext());
            capture.appender.start();
            logger.addAppender(capture.appender);
            return capture;
        }

        void detach() {
            target.detachAppender(appender);
            appender.stop();
        }

        record LogEvent(String level, String message) {}
    }
}
