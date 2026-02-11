package com.example.employee;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * Employee Service MCP Mesh agent.
 *
 * <p>Provides employee data services that return complex types (Employee records).
 * This demonstrates how McpMeshTool&lt;Employee&gt; can be used by other agents
 * for type-safe cross-agent calls.
 *
 * <h2>Running</h2>
 * <pre>
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this agent
 * mvn spring-boot:run -Dspring-boot.run.jvmArguments="-Djava.library.path=/path/to/native/lib"
 *
 * # Test
 * meshctl call getEmployee '{"id": 1}'
 * meshctl call listEmployees '{"department": "Engineering"}'
 * </pre>
 */
@MeshAgent(
    name = "employee-service",
    version = "1.0.0",
    description = "Employee data services",
    port = 9003
)
@SpringBootApplication
public class EmployeeServiceApplication {

    private static final Logger log = LoggerFactory.getLogger(EmployeeServiceApplication.class);

    // In-memory employee database
    private final Map<Integer, Employee> employees = new ConcurrentHashMap<>();

    public EmployeeServiceApplication() {
        // Seed with sample data
        employees.put(1, new Employee(1, "Alice", "Smith", "Engineering", 120000.0));
        employees.put(2, new Employee(2, "Bob", "Johnson", "Engineering", 115000.0));
        employees.put(3, new Employee(3, "Carol", "Williams", "Product", 130000.0));
        employees.put(4, new Employee(4, "David", "Brown", "Sales", 95000.0));
        employees.put(5, new Employee(5, "Eve", "Davis", "Engineering", 125000.0));
    }

    public static void main(String[] args) {
        log.info("Starting Employee Service Agent...");
        SpringApplication.run(EmployeeServiceApplication.class, args);
    }

    /**
     * Get an employee by ID.
     *
     * @param id The employee ID
     * @return The employee record
     */
    @MeshTool(
        capability = "get_employee",
        description = "Get an employee by their ID",
        tags = {"employee", "data", "tools", "java"}
    )
    public Employee getEmployee(
        @Param(value = "id", description = "The employee ID") int id
    ) {
        log.info("Getting employee with ID: {}", id);

        Employee employee = employees.get(id);
        if (employee == null) {
            throw new IllegalArgumentException("Employee not found: " + id);
        }

        return employee;
    }

    /**
     * List employees by department.
     *
     * @param department The department name (optional, null for all)
     * @return List of employees
     */
    @MeshTool(
        capability = "list_employees",
        description = "List employees, optionally filtered by department",
        tags = {"employee", "data", "tools", "java"}
    )
    public List<Employee> listEmployees(
        @Param(value = "department", description = "Department to filter by (optional)", required = false)
        String department
    ) {
        log.info("Listing employees for department: {}", department);

        if (department == null || department.isEmpty()) {
            return List.copyOf(employees.values());
        }

        return employees.values().stream()
            .filter(e -> e.department().equalsIgnoreCase(department))
            .toList();
    }

    /**
     * Get employee count by department.
     *
     * @param department The department name
     * @return Count of employees
     */
    @MeshTool(
        capability = "employee_count",
        description = "Get the count of employees in a department",
        tags = {"employee", "stats", "java"}
    )
    public DepartmentStats getEmployeeCount(
        @Param(value = "department", description = "Department name") String department
    ) {
        log.info("Getting employee count for department: {}", department);

        long count = employees.values().stream()
            .filter(e -> e.department().equalsIgnoreCase(department))
            .count();

        double avgSalary = employees.values().stream()
            .filter(e -> e.department().equalsIgnoreCase(department))
            .mapToDouble(Employee::salary)
            .average()
            .orElse(0.0);

        return new DepartmentStats(department, (int) count, avgSalary);
    }

    /**
     * Analyze a team of members and return statistics.
     * NOTE: This method is intentionally added to reproduce issue #548 —
     * List<Record> @Param types deserialize as List<LinkedHashMap> due to type erasure.
     * At runtime, calling TeamMember::salary on a LinkedHashMap will throw ClassCastException.
     *
     * @param members List of team members to analyze
     * @return Team analysis statistics
     */
    @MeshTool(
        capability = "analyze_team",
        description = "Analyze a team of members and return statistics",
        tags = {"employee", "analysis"}
    )
    public TeamAnalysis analyzeTeam(
        @Param(value = "members", description = "List of team members to analyze")
        List<TeamMember> members
    ) {
        log.info("Analyzing team with {} members", members.size());

        double totalSalary = members.stream()
            .mapToDouble(TeamMember::salary)
            .sum();

        String topDepartment = members.stream()
            .collect(Collectors.groupingBy(TeamMember::department, Collectors.counting()))
            .entrySet().stream()
            .max(Map.Entry.comparingByValue())
            .map(Map.Entry::getKey)
            .orElse("unknown");

        return new TeamAnalysis(
            members.size(),
            totalSalary,
            members.isEmpty() ? 0.0 : totalSalary / members.size(),
            topDepartment
        );
    }

    // =========================================================================
    // Data Types
    // =========================================================================

    /**
     * Employee record with all relevant fields.
     */
    public record Employee(
        int id,
        String firstName,
        String lastName,
        String department,
        double salary
    ) {}

    /**
     * Department statistics.
     */
    public record DepartmentStats(
        String department,
        int employeeCount,
        double averageSalary
    ) {}

    /**
     * A team member for team analysis input.
     */
    public record TeamMember(String name, String department, double salary) {}

    /**
     * Team analysis result.
     */
    public record TeamAnalysis(int teamSize, double totalSalary, double averageSalary, String topDepartment) {}
}
