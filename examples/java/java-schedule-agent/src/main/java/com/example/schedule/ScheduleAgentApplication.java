package com.example.schedule;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;

/**
 * Schedule agent that returns java.time types directly in response records.
 *
 * <p>This agent reproduces the Jackson 2 JavaTimeModule bug in MeshMcpServerConfiguration.
 * The MCP SDK uses Jackson 2 (com.fasterxml.jackson) which does NOT support java.time
 * types by default. When @MeshTool methods return records containing LocalDate,
 * LocalDateTime, or LocalTime, the serialization fails with:
 *
 * <pre>
 * InvalidDefinitionException: Java 8 date/time type `java.time.LocalDate`
 * not supported by default: add Module "com.fasterxml.jackson.datatype:jackson-datatype-jsr310"
 * </pre>
 *
 * <h2>Running</h2>
 * <pre>
 * meshctl start --registry-only
 * mvn spring-boot:run
 * meshctl call get_schedule '{"date": "2025-03-15"}'
 * </pre>
 */
@MeshAgent(
    name = "schedule",
    version = "1.0.0",
    description = "Schedule service with java.time return types",
    port = 9050
)
@SpringBootApplication
public class ScheduleAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(ScheduleAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Schedule Agent...");
        SpringApplication.run(ScheduleAgentApplication.class, args);
    }

    /**
     * Get class schedule for a given date.
     * Returns a record with LocalDate and LocalTime fields — triggers Jackson 2 bug.
     */
    @MeshTool(
        capability = "get_schedule",
        description = "Get class schedule for a date",
        tags = {"schedule", "java"}
    )
    public DailySchedule getSchedule(
        @Param(value = "date", description = "Date in YYYY-MM-DD format") String date
    ) {
        log.info("getSchedule called for date: {}", date);
        LocalDate scheduleDate = LocalDate.parse(date);

        List<ClassSlot> classes = List.of(
            new ClassSlot("Yoga Basics", LocalTime.of(8, 0), LocalTime.of(9, 0), "Studio A", "Alice"),
            new ClassSlot("Pilates", LocalTime.of(9, 30), LocalTime.of(10, 30), "Studio B", "Bob"),
            new ClassSlot("Spin Class", LocalTime.of(11, 0), LocalTime.of(12, 0), "Gym Floor", "Carol")
        );

        return new DailySchedule(scheduleDate, classes, LocalDateTime.now());
    }

    /**
     * Get next available class.
     * Returns a record with LocalDateTime — triggers Jackson 2 bug.
     */
    @MeshTool(
        capability = "next_class",
        description = "Get the next available class",
        tags = {"schedule", "java"}
    )
    public ClassInfo nextClass() {
        log.info("nextClass called");
        return new ClassInfo(
            "Evening Yoga",
            LocalDate.now(),
            LocalTime.of(18, 0),
            LocalTime.of(19, 0),
            "Studio A",
            "Alice",
            12,
            20
        );
    }

    // =========================================================================
    // Data Types — use java.time types DIRECTLY (not as Strings)
    // =========================================================================

    public record ClassSlot(
        String className,
        LocalTime startTime,
        LocalTime endTime,
        String room,
        String instructor
    ) {}

    public record DailySchedule(
        LocalDate date,
        List<ClassSlot> classes,
        LocalDateTime generatedAt
    ) {}

    public record ClassInfo(
        String className,
        LocalDate date,
        LocalTime startTime,
        LocalTime endTime,
        String room,
        String instructor,
        int enrolled,
        int capacity
    ) {}
}
