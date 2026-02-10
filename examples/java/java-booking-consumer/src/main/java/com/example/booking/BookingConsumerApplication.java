package com.example.booking;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;

/**
 * Booking consumer agent that calls the schedule-agent's tools via McpMeshTool.
 *
 * <p>This agent reproduces the cascade error (Issue 2). When the schedule-agent fails
 * to serialize java.time types (Issue 1), the error response is a non-JSON string.
 * This consumer's McpHttpClient tries to deserialize that error as typed JSON,
 * triggering:
 *
 * <pre>
 * tools.jackson.core.exc.StreamReadException: Unrecognized token 'Error':
 * was expecting (JSON String, Number, Array, Object or token 'null', 'true' or 'false')
 * </pre>
 *
 * <h2>Running</h2>
 * <pre>
 * meshctl start --registry-only
 * # Start schedule-agent first (port 9050)
 * cd ../java-schedule-agent && mvn spring-boot:run &
 * # Then start this consumer (port 9051)
 * mvn spring-boot:run
 * meshctl call book_class '{"date": "2025-03-15", "className": "Yoga Basics"}'
 * </pre>
 */
@MeshAgent(
    name = "booking",
    version = "1.0.0",
    description = "Booking service that consumes schedule data",
    port = 9051
)
@SpringBootApplication
public class BookingConsumerApplication {

    private static final Logger log = LoggerFactory.getLogger(BookingConsumerApplication.class);

    public static void main(String[] args) {
        log.info("Starting Booking Consumer...");
        SpringApplication.run(BookingConsumerApplication.class, args);
    }

    /**
     * Book a class by looking up the schedule and confirming availability.
     * Calls schedule-agent's get_schedule tool — triggers cascade error.
     */
    @MeshTool(
        capability = "book_class",
        description = "Book a class from the schedule",
        tags = {"booking", "java"},
        dependencies = @Selector(capability = "get_schedule")
    )
    public BookingConfirmation bookClass(
        @Param(value = "date", description = "Date in YYYY-MM-DD format") String date,
        @Param(value = "className", description = "Name of the class to book") String className,
        McpMeshTool<DailySchedule> scheduleService
    ) {
        log.info("bookClass called: {} on {}", className, date);

        // This call triggers the cascade:
        // 1. schedule-agent tries to serialize DailySchedule with java.time types
        // 2. Jackson 2 fails with InvalidDefinitionException
        // 3. Error response comes back as non-JSON string
        // 4. McpHttpClient tries to deserialize it as DailySchedule
        // 5. Jackson 3 throws StreamReadException
        DailySchedule schedule = scheduleService.call("date", date);

        log.info("Received schedule for {}: {} classes", date, schedule.classes().size());

        return new BookingConfirmation(
            "BK-" + System.currentTimeMillis(),
            className,
            LocalDate.parse(date),
            "Confirmed",
            LocalDateTime.now()
        );
    }

    /**
     * Check schedule availability.
     * Calls schedule-agent's next_class tool — triggers cascade error.
     */
    @MeshTool(
        capability = "check_availability",
        description = "Check next available class",
        tags = {"booking", "java"},
        dependencies = @Selector(capability = "next_class")
    )
    public AvailabilityResponse checkAvailability(
        McpMeshTool<ClassInfo> scheduleService
    ) {
        log.info("checkAvailability called");

        ClassInfo nextClass = scheduleService.call();

        return new AvailabilityResponse(
            nextClass.className(),
            nextClass.date(),
            nextClass.startTime(),
            nextClass.capacity() - nextClass.enrolled(),
            "Available"
        );
    }

    // =========================================================================
    // Data Types — mirror schedule-agent's types for deserialization
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

    public record BookingConfirmation(
        String bookingId,
        String className,
        LocalDate date,
        String status,
        LocalDateTime confirmedAt
    ) {}

    public record AvailabilityResponse(
        String className,
        LocalDate date,
        LocalTime startTime,
        int spotsAvailable,
        String status
    ) {}
}
