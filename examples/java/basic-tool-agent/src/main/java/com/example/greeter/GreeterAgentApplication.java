package com.example.greeter;

import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

/**
 * Basic MCP Mesh agent example with a simple greeting tool.
 *
 * <p>This demonstrates:
 * <ul>
 *   <li>@MeshAgent for agent configuration</li>
 *   <li>@MeshTool for capability registration</li>
 *   <li>@Param for tool parameter documentation</li>
 * </ul>
 *
 * <h2>Running</h2>
 * <pre>
 * # Start the registry
 * meshctl start --registry-only
 *
 * # Run this agent
 * mvn spring-boot:run
 *
 * # Or with environment overrides
 * MCP_MESH_HTTP_PORT=9001 mvn spring-boot:run
 *
 * # Test with meshctl
 * meshctl list                    # Should show "greeter" agent
 * meshctl list -t                 # Should show "greeting" tool
 * meshctl call greeting '{"name": "World"}'
 * </pre>
 */
@MeshAgent(
    name = "greeter",
    version = "1.0.0",
    description = "Simple greeting service",
    port = 9000
)
@SpringBootApplication
public class GreeterAgentApplication {

    private static final Logger log = LoggerFactory.getLogger(GreeterAgentApplication.class);

    public static void main(String[] args) {
        log.info("Starting Greeter Agent...");
        SpringApplication.run(GreeterAgentApplication.class, args);
    }

    /**
     * Greet a user by name.
     *
     * @param name The name to greet
     * @return A greeting message
     */
    @MeshTool(
        capability = "greeting",
        description = "Greet a user by name",
        tags = {"greeting", "utility", "java"}
    )
    public GreetingResponse greet(
        @Param(value = "name", description = "The name to greet") String name
    ) {
        log.info("Greeting: {}", name);

        String timestamp = LocalDateTime.now()
            .format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);

        String message = String.format("Hello, %s! Welcome to MCP Mesh.", name);

        return new GreetingResponse(message, timestamp, "greeter-java");
    }

    /**
     * Get agent information.
     *
     * @return Agent metadata
     */
    @MeshTool(
        capability = "agent_info",
        description = "Get information about this agent",
        tags = {"info", "metadata", "java"}
    )
    public AgentInfo getInfo() {
        return new AgentInfo(
            "greeter",
            "1.0.0",
            "Java " + System.getProperty("java.version"),
            System.getProperty("os.name")
        );
    }

    /**
     * Add two numbers using the remote calculator service.
     * Demonstrates cross-agent tool calls (Java -> TypeScript).
     *
     * <p>The {@code McpMeshTool<Integer>} type parameter tells the SDK to
     * automatically deserialize the calculator's response as an Integer,
     * eliminating manual type-checking code.
     *
     * <p>Uses {@code callWith(record)} for clean parameter passing.
     *
     * @param a First number
     * @param b Second number
     * @param calculator Injected calculator tool from mesh (typed as Integer)
     * @return Calculation result with metadata
     */
    @MeshTool(
        capability = "add_via_mesh",
        description = "Add two numbers using the remote calculator service (cross-agent call)",
        tags = {"math", "cross-agent", "java"},
        dependencies = @Selector(capability = "add")
    )
    public CalculationResult addViaMesh(
        @Param(value = "a", description = "First number") int a,
        @Param(value = "b", description = "Second number") int b,
        McpMeshTool<Integer> calculator
    ) {
        log.info("addViaMesh called: {} + {} via {}", a, b, calculator.getCapability());

        // Call with a record - field names become MCP parameter names
        Integer sum = calculator.call(new AddParams(a, b));

        log.info("Remote calculator response: {}", sum);

        return new CalculationResult(
            a,
            b,
            "+",
            sum,
            "greeter-java → calculator-typescript",
            calculator.getEndpoint()
        );
    }

    /** Parameters for the add tool. */
    record AddParams(int a, int b) {}

    /**
     * Greet an employee by ID using the remote employee service.
     * Demonstrates cross-agent calls with complex types (McpMeshTool&lt;Employee&gt;).
     *
     * <p>The {@code McpMeshTool<Employee>} type parameter tells the SDK to
     * automatically deserialize the employee service's JSON response into
     * an Employee record - no manual parsing needed.
     *
     * @param employeeId The employee ID to look up and greet
     * @param employeeService Injected employee service tool (typed as Employee)
     * @return Personalized greeting for the employee
     */
    @MeshTool(
        capability = "greet_employee",
        description = "Greet an employee by their ID (fetches from employee service)",
        tags = {"greeting", "employee", "cross-agent", "java"},
        dependencies = @Selector(capability = "get_employee")
    )
    public EmployeeGreeting greetEmployee(
        @Param(value = "employee_id", description = "The employee ID to greet") int employeeId,
        McpMeshTool<Employee> employeeService
    ) {
        log.info("greetEmployee called for ID: {} via {}", employeeId, employeeService.getCapability());

        // For simple params, use varargs: call("key", value, "key2", value2)
        Employee employee = employeeService.call("id", employeeId);

        log.info("Remote employee service response: {} {} ({})",
            employee.firstName(), employee.lastName(), employee.department());

        String timestamp = LocalDateTime.now()
            .format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);

        String message = String.format(
            "Hello, %s %s! Welcome from the %s department.",
            employee.firstName(),
            employee.lastName(),
            employee.department()
        );

        return new EmployeeGreeting(
            message,
            employee,
            timestamp,
            "greeter-java → employee-service-java",
            employeeService.getEndpoint()
        );
    }

    /**
     * Send a team roster for analysis via the remote employee service.
     * Demonstrates cross-agent calls with List of complex types.
     *
     * <p>This reproduces issue #548 from the consumer side: the {@code members}
     * parameter arrives as {@code List<LinkedHashMap>} instead of
     * {@code List<TeamMember>}, and the provider side throws a
     * {@code ClassCastException} when accessing record fields.
     *
     * @param members List of team members to analyze
     * @param analyzeTeamTool Injected analyze_team tool from mesh
     * @return Analysis of the team roster
     */
    @MeshTool(
        capability = "analyze_my_team",
        description = "Send a team roster for analysis via mesh",
        dependencies = @Selector(capability = "analyze_team")
    )
    public TeamAnalysis analyzeMyTeam(
        @Param(value = "members", description = "List of team members")
        List<TeamMember> members,
        McpMeshTool<TeamAnalysis> analyzeTeamTool
    ) {
        log.info("analyzeMyTeam called with {} members via {}", members.size(), analyzeTeamTool.getCapability());

        TeamAnalysis analysis = analyzeTeamTool.call("members", members);

        log.info("Remote analyze_team response: teamSize={}, avgSalary={}",
            analysis.teamSize(), analysis.averageSalary());

        return analysis;
    }

    /**
     * List employees by department via mesh and return a summary roster.
     * Tests McpMeshTool&lt;List&lt;Employee&gt;&gt; generic type deserialization (#562):
     * The proxy must correctly resolve the ParameterizedType to deserialize
     * the response as List&lt;Employee&gt; instead of List&lt;LinkedHashMap&gt;.
     *
     * @param department Department to list (optional, null for all)
     * @param employeeList Injected list_employees tool typed as List&lt;Employee&gt;
     * @return TeamRoster with summary statistics
     */
    @MeshTool(
        capability = "list_team_members",
        description = "List employees by department via mesh and return a roster summary",
        tags = {"roster", "cross-agent", "java"},
        dependencies = @Selector(capability = "list_employees")
    )
    public TeamRoster listTeamMembers(
        @Param(value = "department", description = "Department to list (optional)", required = false) String department,
        McpMeshTool<List<Employee>> employeeList
    ) {
        log.info("listTeamMembers called for department: {} via {}", department, employeeList.getCapability());

        List<Employee> employees = (department != null && !department.isEmpty())
            ? employeeList.call("department", department)
            : employeeList.call();

        log.info("Got {} employees from remote service", employees.size());

        double totalSalary = employees.stream().mapToDouble(Employee::salary).sum();
        String firstEmployee = employees.isEmpty() ? "none" : employees.get(0).firstName();

        return new TeamRoster(
            department != null ? department : "all",
            employees.size(),
            totalSalary,
            firstEmployee
        );
    }

    // =========================================================================
    // Data Types
    // =========================================================================

    /**
     * Calculation result record.
     */
    public record CalculationResult(
        int operandA,
        int operandB,
        String operation,
        int result,
        String callPath,
        String remoteEndpoint
    ) {}

    /**
     * Greeting response record.
     */
    public record GreetingResponse(
        String message,
        String timestamp,
        String source
    ) {}

    /**
     * Agent information record.
     */
    public record AgentInfo(
        String name,
        String version,
        String runtime,
        String platform
    ) {}

    /**
     * Employee record - matches the structure from employee-service.
     * The SDK will deserialize the remote JSON response into this record.
     */
    public record Employee(
        int id,
        String firstName,
        String lastName,
        String department,
        double salary
    ) {}

    /**
     * Team member record - mirrors the structure in employee-service.
     */
    public record TeamMember(String name, String department, double salary) {}

    /**
     * Team analysis result record - mirrors the response from employee-service.
     */
    public record TeamAnalysis(int teamSize, double totalSalary, double averageSalary, String topDepartment) {}

    /**
     * Employee greeting response with full employee data.
     */
    public record EmployeeGreeting(
        String message,
        Employee employee,
        String timestamp,
        String callPath,
        String remoteEndpoint
    ) {}

    /**
     * Team roster summary — returned by listTeamMembers.
     * Tests McpMeshTool<List<Employee>> deserialization (#562).
     */
    public record TeamRoster(String department, int count, double totalSalary, String firstEmployeeName) {}
}
