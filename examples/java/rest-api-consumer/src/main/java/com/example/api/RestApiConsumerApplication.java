package com.example.api;

import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshInject;
import io.mcpmesh.spring.web.MeshRoute;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Example: Spring Boot REST API consuming mesh capabilities without @MeshAgent.
 *
 * <p>This app has no @MeshAgent annotation — it uses @MeshRoute to declare
 * dependencies on mesh capabilities, and the framework automatically starts
 * in consumer-only mode (agent_type="api"). No meshctl start needed.
 *
 * <h2>Running</h2>
 * <pre>
 * # 1. Start the registry
 * meshctl start --registry-only -d
 *
 * # 2. Start a greeter agent (provides 'greeting' capability)
 * meshctl start examples/java/basic-tool-agent -d
 *
 * # 3. Start this REST API (no meshctl needed — just run the app)
 * cd examples/java/rest-api-consumer
 * mvn spring-boot:run
 *
 * # 4. Call the endpoint
 * curl http://localhost:8080/api/greet?name=World
 * </pre>
 */
@SpringBootApplication
public class RestApiConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(RestApiConsumerApplication.class, args);
    }
}

record Employee(
    int id,
    String firstName,
    String lastName,
    String department,
    double salary
) {}

record DepartmentStats(
    String department,
    int employeeCount,
    double averageSalary
) {}

record TeamMember(String name, String department, double salary) {}

record TeamAnalysis(int teamSize, double totalSalary, double averageSalary, String topDepartment) {}

record Team(String teamName, String department, List<Employee> members, double totalBudget) {}

record Organization(String name, List<Team> teams, int totalHeadcount, double totalBudget) {}

@RestController
@RequestMapping("/api")
class ApiController {

    private static final Logger log = LoggerFactory.getLogger(ApiController.class);

    /**
     * Greet a user via a mesh agent.
     *
     * <p>The @MeshRoute annotation declares a dependency on the "greeting" capability.
     * At request time, the framework resolves the dependency and injects it as a
     * McpMeshTool parameter (matched by parameter name).
     */
    @GetMapping("/greet")
    @MeshRoute(dependencies = @MeshDependency(capability = "greeting"))
    public ResponseEntity<Map<String, Object>> greet(
            @RequestParam(defaultValue = "World") String name,
            McpMeshTool<Map<String, Object>> greeting) {

        log.info("Greeting {} via mesh agent", name);
        Map<String, Object> result = greeting.call(Map.of("name", name));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-agent");
        response.put("result", result);
        response.put("timestamp", LocalDateTime.now().toString());
        return ResponseEntity.ok(response);
    }

    /**
     * Greet with graceful fallback when the mesh agent is unavailable.
     */
    @GetMapping("/greet-fallback")
    @MeshRoute(
        dependencies = @MeshDependency(capability = "greeting"),
        failOnMissingDependency = false
    )
    public ResponseEntity<Map<String, Object>> greetWithFallback(
            @RequestParam(defaultValue = "World") String name,
            McpMeshTool<Map<String, Object>> greeting) {

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("timestamp", LocalDateTime.now().toString());

        if (greeting != null && greeting.isAvailable()) {
            Map<String, Object> result = greeting.call(Map.of("name", name));
            response.put("source", "mesh-agent");
            response.put("result", result);
        } else {
            response.put("source", "local-fallback");
            response.put("result", Map.of("message", "Hello, " + name + "! (from fallback)"));
        }
        return ResponseEntity.ok(response);
    }

    /**
     * Get an employee by ID via a mesh agent, with typed deserialization.
     *
     * <p>The McpMeshTool&lt;Employee&gt; generic type ensures the response from
     * the remote agent is deserialized directly into an Employee record.
     */
    @GetMapping("/employee")
    @MeshRoute(dependencies = @MeshDependency(capability = "get_employee"))
    public ResponseEntity<Map<String, Object>> getEmployee(
            @RequestParam int id,
            @MeshInject("get_employee") McpMeshTool<Employee> employeeTool) {

        log.info("Getting employee {} via mesh agent (typed)", id);
        Employee employee = employeeTool.call(Map.of("id", id));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-agent-typed");
        response.put("result", employee);
        response.put("type", employee.getClass().getSimpleName());
        response.put("timestamp", LocalDateTime.now().toString());
        return ResponseEntity.ok(response);
    }

    /**
     * Get department statistics via a mesh agent, with typed deserialization.
     *
     * <p>Demonstrates McpMeshTool&lt;DepartmentStats&gt; returning a different
     * typed record from a different capability on the same remote agent.
     */
    @GetMapping("/department-stats")
    @MeshRoute(dependencies = @MeshDependency(capability = "employee_count"))
    public ResponseEntity<Map<String, Object>> getDepartmentStats(
            @RequestParam String department,
            @MeshInject("employee_count") McpMeshTool<DepartmentStats> statsTool) {

        log.info("Getting department stats for {} via mesh agent (typed)", department);
        DepartmentStats stats = statsTool.call(Map.of("department", department));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-agent-typed");
        response.put("result", stats);
        response.put("type", stats.getClass().getSimpleName());
        response.put("timestamp", LocalDateTime.now().toString());
        return ResponseEntity.ok(response);
    }

    /**
     * Analyze a team via a mesh agent, passing a list of team members.
     */
    @PostMapping("/analyze-team")
    @MeshRoute(dependencies = @MeshDependency(capability = "analyze_team"))
    public ResponseEntity<Map<String, Object>> analyzeTeam(
            @RequestBody List<TeamMember> members,
            @MeshInject("analyze_team") McpMeshTool<TeamAnalysis> analyzeTeamTool) {

        if (analyzeTeamTool == null || !analyzeTeamTool.isAvailable()) {
            return ResponseEntity.status(503)
                    .body(Map.of("error", "analyze_team capability not available"));
        }

        TeamAnalysis result = analyzeTeamTool.call(Map.of("members", members));
        return ResponseEntity.ok(Map.of(
                "source", "mesh",
                "analysis", result
        ));
    }

    /**
     * List employees via mesh, returning a List of typed records.
     * Tests McpMeshTool&lt;List&lt;Employee&gt;&gt; via @MeshRoute (#562).
     * This verifies the ParameterizedType is correctly resolved through
     * the MeshRouteHandlerInterceptor → McpMeshToolProxy → McpHttpClient path.
     */
    @GetMapping("/team-roster")
    @MeshRoute(dependencies = @MeshDependency(capability = "list_employees"))
    public ResponseEntity<Map<String, Object>> getTeamRoster(
            @RequestParam(required = false) String department,
            @MeshInject("list_employees") McpMeshTool<List<Employee>> employeeListTool) {

        log.info("Getting team roster for department: {} via mesh agent (typed list)", department);

        List<Employee> employees;
        if (department != null && !department.isEmpty()) {
            employees = employeeListTool.call(Map.of("department", department));
        } else {
            employees = employeeListTool.call(Map.of());
        }

        double totalSalary = employees.stream().mapToDouble(Employee::salary).sum();
        String firstEmployee = employees.isEmpty() ? "none" : employees.get(0).firstName();

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-agent-typed-list");
        response.put("department", department != null ? department : "all");
        response.put("count", employees.size());
        response.put("totalSalary", totalSalary);
        response.put("firstEmployeeName", firstEmployee);
        response.put("type", employees.isEmpty() ? "empty" : employees.get(0).getClass().getSimpleName());
        response.put("timestamp", LocalDateTime.now().toString());
        return ResponseEntity.ok(response);
    }

    /**
     * Get organization structure with deeply nested types via mesh.
     * Tests McpMeshTool&lt;Organization&gt; where Organization contains
     * List&lt;Team&gt; and each Team contains List&lt;Employee&gt;.
     */
    @GetMapping("/organization")
    @MeshRoute(dependencies = @MeshDependency(capability = "get_organization"))
    public ResponseEntity<Map<String, Object>> getOrganization(
            @MeshInject("get_organization") McpMeshTool<Organization> orgTool) {

        log.info("Getting organization structure via mesh agent (nested types)");
        Organization org = orgTool.call(Map.of());

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("source", "mesh-agent-typed-nested");
        response.put("result", org);
        response.put("type", org.getClass().getSimpleName());
        response.put("teamCount", org.teams().size());
        response.put("totalHeadcount", org.totalHeadcount());
        response.put("timestamp", LocalDateTime.now().toString());
        return ResponseEntity.ok(response);
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        return ResponseEntity.ok(Map.of(
            "status", "healthy",
            "timestamp", LocalDateTime.now().toString()
        ));
    }
}
